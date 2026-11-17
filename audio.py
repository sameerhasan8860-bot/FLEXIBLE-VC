import math
import numpy as np


# ─── defaults ─────────────────────────────────────────────────────────────────
DEFAULT_EFFECTS = {
    "db":          0.0,
    "gain":        1.0,
    "bass":        0.0,
    "treble":      0.0,
    "echo":        0.0,
    "distortion":  0.0,
    "level":       0.0,
    "presence":    0.0,
    "air":         0.0,
    "loudmax":     0.0,
    "stereowide":  0.0,
    "bitcrush":    0.0,
}

_LIMITS = {
    "db":          (-120.0,  96.0),
    "gain":        (0.0,    512.0),
    "bass":        (-48.0,   48.0),
    "treble":      (-48.0,   48.0),
    "echo":        (0.0,    100.0),
    "distortion":  (0.0,    100.0),
    "presence":    (-48.0,   48.0),
    "air":         (-48.0,   48.0),
    "loudmax":     (0.0,    100.0),
    "stereowide":  (0.0,    100.0),
    "bitcrush":    (0.0,    100.0),
}


class AudioProcessor:
    """
    Unlimited PCM-16 stereo effects engine — 48 kHz stereo.
    .level = pure voice loudness only (gain + clarity chain).
    Individual knobs (bass, echo, distortion …) stay separate.
    """

    def __init__(self, settings=None, sample_rate: int = 48000, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels    = channels
        self.settings    = {**DEFAULT_EFFECTS, **(settings or {})}

        self.low_state  = np.zeros(channels, dtype=np.float64)
        self.mid_state  = np.zeros(channels, dtype=np.float64)
        self.air_state  = np.zeros(channels, dtype=np.float64)

        echo_len = int(sample_rate * 0.30) * channels
        self.echo_buffer = np.zeros(echo_len, dtype=np.float64)
        self.echo_pos    = 0

        la_len = int(sample_rate * 0.005) * channels
        self.la_buffer   = np.zeros(la_len, dtype=np.float64)
        self.la_pos      = 0
        self.gain_smooth = 1.0

        # ── level-chain state ───────────────────────────────────────────
        # De-esser (sibilance smoother so voice stays clear, not harsh)
        self.de_ess_state = np.zeros(channels, dtype=np.float64)
        # Soft-knee limiter envelope (prevents fata-hua sound)
        self.lim_env      = np.zeros(channels, dtype=np.float64)

    # ──────────────────────────────────────────────────────────────────────────
    def update(self, name: str, value: float) -> float:

        if name == "level":
            if not math.isfinite(value) or value < 0:
                raise ValueError("Level must be a finite non-negative number.")
            if value == 0:
                self.settings["level"] = 0.0
                return 0.0

            # Pure loudness mapping — ONLY gain + loudmax + presence/air.
            # No bass, treble, echo, distortion, stereowide, bitcrush.
            # Logarithmic so every step feels equally louder to the ear.
            # Unlimited — user can go as high as they want.
            t = math.log1p(value) / math.log1p(1000.0)   # 0→0, 1000→1, beyond 1

            self.settings.update({
                "level":    value,
                # linear gain — primary loudness knob
                "gain":     1.0 + (value * 0.5),          # level 1000 → 501× gain
                # dB boost on top — doubles perceived punch
                "db":       t * 60.0,                      # 0 → +60 dB at level 1000
                # presence: voice cut-through (kadak, saaf)
                "presence": t * 36.0,                      # 0 → +36 dB
                # air: high-end clarity (saaf aawaz)
                "air":      t * 24.0,                      # 0 → +24 dB
                # loudmax: brick-wall limiter so it stays LOUD not DISTORTED
                "loudmax":  min(99.0, t * 110.0),          # saturates at 99
                # individual knobs untouched
                "bass":        self.settings["bass"],
                "treble":      self.settings["treble"],
                "echo":        self.settings["echo"],
                "distortion":  self.settings["distortion"],
                "stereowide":  self.settings["stereowide"],
                "bitcrush":    self.settings["bitcrush"],
            })
            return value

        if name not in _LIMITS or not math.isfinite(value):
            raise ValueError(f"Unknown or non-finite parameter: {name!r}")

        low, high = _LIMITS[name]
        if value == 0:
            actual = DEFAULT_EFFECTS[name]
            if name == "echo":
                self.echo_buffer.fill(0); self.echo_pos = 0
        else:
            actual = max(low, min(high, float(value)))

        self.settings[name] = actual
        self.settings["level"] = 0.0
        return actual

    def reset(self):
        self.settings = dict(DEFAULT_EFFECTS)
        self.echo_buffer.fill(0); self.echo_pos = 0
        self.low_state.fill(0); self.mid_state.fill(0); self.air_state.fill(0)
        self.la_buffer.fill(0); self.la_pos = 0; self.gain_smooth = 1.0
        self.de_ess_state.fill(0); self.lim_env.fill(0)

    # ──────────────────────────────────────────────────────────────────────────
    def process(self, pcm: bytes) -> bytes:
        if not pcm:
            return pcm

        raw    = np.frombuffer(pcm, dtype=np.int16)
        usable = len(raw) - (len(raw) % self.channels)
        if usable <= 0:
            return pcm

        s  = raw[:usable].astype(np.float64).reshape(-1, self.channels)
        s /= 32768.0

        # ── 1. Four-band EQ (bass / mid / presence / air) ───────────────
        alpha_lo  = 0.12
        alpha_mid = 0.55
        alpha_air = 0.82

        low = np.empty_like(s)
        mid = np.empty_like(s)
        air = np.empty_like(s)

        st_lo  = self.low_state.copy()
        st_mid = self.mid_state.copy()
        st_air = self.air_state.copy()

        for i, row in enumerate(s):
            st_lo  += alpha_lo  * (row - st_lo)
            st_mid += alpha_mid * (row - st_mid)
            st_air += alpha_air * (row - st_air)
            low[i]  = st_lo
            mid[i]  = st_mid - st_lo
            air[i]  = st_air - st_mid

        self.low_state = st_lo
        self.mid_state = st_mid
        self.air_state = st_air

        highs = s - st_air

        bass_g  = 10.0 ** (self.settings["bass"]     / 20.0)
        treble_g = 10.0 ** (self.settings["treble"]  / 20.0)
        pres_g  = 10.0 ** (self.settings["presence"] / 20.0)
        air_g   = 10.0 ** (self.settings["air"]      / 20.0)

        s = low * bass_g + mid * treble_g + air[:len(mid)] * pres_g + highs * air_g

        # ── 2. De-esser — sibilance control so loud voice stays CLEAR ───
        # Damps only the 6–12 kHz band when it spikes (no fatna).
        alpha_ess = 0.90
        pres_level = self.settings["presence"] + self.settings["air"]
        if pres_level > 12.0:
            thresh  = 0.35 - min(0.25, pres_level / 300.0)
            st_ess  = self.de_ess_state.copy()
            hi_band = np.empty_like(s)
            for i, row in enumerate(s):
                st_ess   += alpha_ess * (row - st_ess)
                hi_band[i] = row - st_ess
            self.de_ess_state = st_ess
            mask = np.abs(hi_band) > thresh
            hi_band[mask] *= (thresh / (np.abs(hi_band[mask]) + 1e-12))
            s = s - (np.abs(s - (s - hi_band)) * 0.4)

        # ── 3. Stereo widener ────────────────────────────────────────────
        sw = self.settings["stereowide"] / 100.0
        if sw > 0 and self.channels == 2:
            m  = (s[:, 0] + s[:, 1]) * 0.5
            sd = (s[:, 0] - s[:, 1]) * 0.5
            width = 1.0 + sw * 2.5
            s[:, 0] = m + sd * width
            s[:, 1] = m - sd * width

        # ── 4. Echo ──────────────────────────────────────────────────────
        echo = self.settings["echo"] / 100.0
        if echo > 0:
            flat    = s.reshape(-1)
            delayed = np.empty_like(flat)
            fb      = 0.5 + echo * 0.45
            for i, v in enumerate(flat):
                delayed[i]                      = self.echo_buffer[self.echo_pos]
                self.echo_buffer[self.echo_pos] = v + delayed[i] * fb
                self.echo_pos = (self.echo_pos + 1) % len(self.echo_buffer)
            s = (flat + delayed * echo * 0.9).reshape(-1, self.channels)

        # ── 5. Bit-crush ─────────────────────────────────────────────────
        bc = self.settings["bitcrush"] / 100.0
        if bc > 0:
            bits  = max(1.0, 16.0 * (1.0 - bc * 0.875))
            steps = 2.0 ** bits
            s     = np.round(s * steps) / steps

        # ── 6. Distortion ────────────────────────────────────────────────
        dist = self.settings["distortion"] / 100.0
        if dist > 0:
            drive = 1.0 + dist * 99.0
            denom = math.tanh(drive)
            s     = np.tanh(s * drive) / denom

        # ── 7. Master gain + dB ──────────────────────────────────────────
        multiplier = self.settings["gain"] * (10.0 ** (self.settings["db"] / 20.0))
        s *= multiplier

        # ── 8. Loudness maximizer (look-ahead brick-wall) ────────────────
        lm = self.settings["loudmax"] / 100.0
        if lm > 0:
            ceiling = 0.9999 + (1.0 - lm) * 0.0001
            flat    = s.reshape(-1)
            out     = np.empty_like(flat)
            att     = 0.001 + (1.0 - lm) * 0.099
            rel     = 0.9900 + lm * 0.009

            for i, v in enumerate(flat):
                lookahead_val               = self.la_buffer[self.la_pos]
                self.la_buffer[self.la_pos] = v
                self.la_pos = (self.la_pos + 1) % len(self.la_buffer)

                peak = abs(v)
                if peak > 1e-9:
                    needed = ceiling / peak
                    if needed < self.gain_smooth:
                        self.gain_smooth = self.gain_smooth * (1 - att) + needed * att
                    else:
                        self.gain_smooth = self.gain_smooth * rel + needed * (1 - rel)
                out[i] = lookahead_val * min(self.gain_smooth, 1.0 / (ceiling + 1e-12))

            s = out.reshape(-1, self.channels)

        # ── 9. Final hard clip ───────────────────────────────────────────
        s = np.clip(s, -0.9999999, 0.9999999)

        return (s.reshape(-1) * 32767.0).astype(np.int16).tobytes()
