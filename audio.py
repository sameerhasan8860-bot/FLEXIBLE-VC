import math
import numpy as np


# ─── UNLIMITED defaults ────────────────────────────────────────────────────────
DEFAULT_EFFECTS = {
    "db": 0.0,
    "gain": 1.0,
    "bass": 0.0,
    "treble": 0.0,
    "echo": 0.0,
    "distortion": 0.0,
    "level": 0.0,
    # new knobs
    "presence": 0.0,   # 2–8 kHz snarl / cut-through
    "air": 0.0,        # 8–16 kHz shimmer
    "loudmax": 0.0,    # integrated loudness maximizer 0-100
    "stereowide": 0.0, # stereo width expander 0-100
    "bitcrush": 0.0,   # bit depth crush for digital-scream texture 0-100
}

# No upper bound anywhere — the caller is free to push as hard as they want.
# PCM clipping is handled inside process() as a last-resort safety net only.
_LIMITS = {
    "db":          (-120.0,  96.0),   # up to +96 dB
    "gain":        (0.0,    512.0),   # up to 512× linear
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
    Unlimited PCM-16 stereo effects engine for 48 kHz frames.
    Designed to be as loud and aggressive as possible — no soft limits,
    no "safety" clamps except the final int16 hard clip.
    """

    def __init__(self, settings=None, sample_rate: int = 48000, channels: int = 2):
        self.sample_rate = sample_rate
        self.channels = channels
        self.settings = {**DEFAULT_EFFECTS, **(settings or {})}

        # filter states
        self.low_state     = np.zeros(channels, dtype=np.float64)
        self.mid_state     = np.zeros(channels, dtype=np.float64)
        self.air_state     = np.zeros(channels, dtype=np.float64)

        # echo / delay line  — 300 ms max
        echo_len = int(sample_rate * 0.30) * channels
        self.echo_buffer   = np.zeros(echo_len, dtype=np.float64)
        self.echo_pos      = 0

        # loudness maximizer state  (simple look-ahead brick-wall)
        la_len = int(sample_rate * 0.005) * channels   # 5 ms look-ahead
        self.la_buffer     = np.zeros(la_len, dtype=np.float64)
        self.la_pos        = 0
        self.gain_smooth   = 1.0   # attack/release envelope for maximizer

    # ──────────────────────────────────────────────────────────────────────
    # update()
    # ──────────────────────────────────────────────────────────────────────
    def update(self, name: str, value: float) -> float:
        if name == "level":
            if not math.isfinite(value) or value < 0:
                raise ValueError("Level must be a finite non-negative number.")
            if value == 0:
                self.settings["level"] = 0.0
                return 0.0

            # Aggressive exponential mapping — /level 1000 hits the ceiling
            # much harder than the original code.
            t = 1.0 - math.exp(-math.log1p(value) / 4.5)
            self.settings.update({
                "level":      value,
                "db":         6.0  + 90.0 * t,       # up to ~+96 dB
                "gain":       1.0  + 511.0 * t,       # up to 512×
                "bass":       6.0  + 42.0 * t,
                "treble":     4.0  + 44.0 * t,
                "presence":   6.0  + 42.0 * t,
                "air":        3.0  + 45.0 * t,
                "echo":       10.0 + 90.0 * t,
                "distortion": 10.0 + 90.0 * t,
                "loudmax":    40.0 + 60.0 * t,
                "stereowide": 20.0 + 80.0 * t,
                "bitcrush":   0.0  + 30.0 * t,
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
        self.settings["level"] = 0.0   # individual control overrides master profile
        return actual

    def reset(self):
        self.settings     = dict(DEFAULT_EFFECTS)
        self.echo_buffer.fill(0); self.echo_pos = 0
        self.low_state.fill(0); self.mid_state.fill(0); self.air_state.fill(0)
        self.la_buffer.fill(0); self.la_pos = 0; self.gain_smooth = 1.0

    # ──────────────────────────────────────────────────────────────────────
    # process()  — the hot path
    # ──────────────────────────────────────────────────────────────────────
    def process(self, pcm: bytes) -> bytes:
        if not pcm:
            return pcm

        raw    = np.frombuffer(pcm, dtype=np.int16)
        usable = len(raw) - (len(raw) % self.channels)
        if usable <= 0:
            return pcm

        s = raw[:usable].astype(np.float64).reshape(-1, self.channels)
        s /= 32768.0   # → [-1, 1]

        # ── 1. Four-band EQ ─────────────────────────────────────────────
        # sub-bass / bass split at ~200 Hz (alpha ≈ 0.12 @48k)
        alpha_lo = 0.12
        alpha_mid = 0.55     # ~4 kHz crossover for presence band
        alpha_air = 0.82     # ~8 kHz crossover for air band

        low  = np.empty_like(s)
        mid  = np.empty_like(s)
        air  = np.empty_like(s)

        st_lo  = self.low_state.copy()
        st_mid = self.mid_state.copy()
        st_air = self.air_state.copy()

        for i, row in enumerate(s):
            st_lo  += alpha_lo  * (row   - st_lo)
            st_mid += alpha_mid * (row   - st_mid)
            st_air += alpha_air * (row   - st_air)
            low[i]  = st_lo
            mid[i]  = st_mid - st_lo    # 200 Hz – 4 kHz
            air[i]  = st_air - st_mid   # 4 kHz – 8 kHz

        self.low_state  = st_lo
        self.mid_state  = st_mid
        self.air_state  = st_air

        highs = s - st_air              # >8 kHz

        bass_g    = 10.0 ** (self.settings["bass"]     / 20.0)
        treble_g  = 10.0 ** (self.settings["treble"]   / 20.0)
        pres_g    = 10.0 ** (self.settings["presence"] / 20.0)
        air_g     = 10.0 ** (self.settings["air"]      / 20.0)

        s = low * bass_g + mid * treble_g + air[: len(mid)] * pres_g + highs * air_g

        # ── 2. Stereo widener ───────────────────────────────────────────
        sw = self.settings["stereowide"] / 100.0
        if sw > 0 and self.channels == 2:
            m  = (s[:, 0] + s[:, 1]) * 0.5
            sd = (s[:, 0] - s[:, 1]) * 0.5
            width = 1.0 + sw * 2.5          # up to 3.5× side channel
            s[:, 0] = m + sd * width
            s[:, 1] = m - sd * width

        # ── 3. Echo ─────────────────────────────────────────────────────
        echo = self.settings["echo"] / 100.0
        if echo > 0:
            flat    = s.reshape(-1)
            delayed = np.empty_like(flat)
            fb      = 0.5 + echo * 0.45    # feedback up to 0.95 for wild smearing
            for i, v in enumerate(flat):
                delayed[i]              = self.echo_buffer[self.echo_pos]
                self.echo_buffer[self.echo_pos] = v + delayed[i] * fb
                self.echo_pos = (self.echo_pos + 1) % len(self.echo_buffer)
            s = (flat + delayed * echo * 0.9).reshape(-1, self.channels)

        # ── 4. Bit-crush (digital-scream texture) ───────────────────────
        bc = self.settings["bitcrush"] / 100.0
        if bc > 0:
            bits  = max(1.0, 16.0 * (1.0 - bc * 0.875))   # down to ~2 bits
            steps = 2.0 ** bits
            s     = np.round(s * steps) / steps

        # ── 5. Distortion (tanh soft-clip with extreme drive) ───────────
        dist = self.settings["distortion"] / 100.0
        if dist > 0:
            drive = 1.0 + dist * 99.0      # up to 100× drive
            denom = math.tanh(drive)
            s     = np.tanh(s * drive) / denom

        # ── 6. Master gain + dB boost ───────────────────────────────────
        multiplier = self.settings["gain"] * (10.0 ** (self.settings["db"] / 20.0))
        s *= multiplier

        # ── 7. Loudness maximizer (look-ahead brick-wall) ────────────────
        lm = self.settings["loudmax"] / 100.0
        if lm > 0:
            ceiling = 0.9999 + (1.0 - lm) * 0.0001   # approaches true 0 dBFS
            flat = s.reshape(-1)
            out  = np.empty_like(flat)
            att  = 0.001 + (1.0 - lm) * 0.099   # fast attack at high setting
            rel  = 0.9900 + lm * 0.009            # slow release

            for i, v in enumerate(flat):
                # write into look-ahead delay
                lookahead_val        = self.la_buffer[self.la_pos]
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

        # ── 8. Final hard clip at true 0 dBFS ───────────────────────────
        # Only clips; does NOT normalise — the user chose these settings.
        s = np.clip(s, -0.9999999, 0.9999999)

        output = (s.reshape(-1) * 32767.0).astype(np.int16)
        return output.tobytes()
