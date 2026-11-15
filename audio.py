import math
import numpy as np


DEFAULT_EFFECTS = {
    "db": 0.0,
    "gain": 1.0,
    "bass": 0.0,
    "treble": 0.0,
    "echo": 0.0,
    "distortion": 0.0,
}


class AudioProcessor:
    """Low-latency PCM16 stereo effects processor for 48 kHz frames."""

    def __init__(self, settings=None, sample_rate=48000, channels=2):
        self.settings = {**DEFAULT_EFFECTS, **(settings or {})}
        self.sample_rate = sample_rate
        self.channels = channels
        self.low_state = np.zeros(channels, dtype=np.float32)
        self.echo_buffer = np.zeros(int(sample_rate * 0.24) * channels, dtype=np.float32)
        self.echo_pos = 0

    def update(self, name: str, value: float) -> float:
        # Inputs are free-form numeric values. DSP safety limits prevent
        # overflow, runaway feedback and unusable audio.
        limits = {
            "db": (-60.0, 24.0),
            "gain": (0.0, 8.0),
            "bass": (-24.0, 24.0),
            "treble": (-24.0, 24.0),
            "echo": (0.0, 100.0),
            "distortion": (0.0, 100.0),
        }
        if name not in limits or not math.isfinite(value):
            raise ValueError("Unsupported or non-finite audio value.")
        low, high = limits[name]
        actual = max(low, min(high, float(value)))
        self.settings[name] = actual
        return actual

    def process(self, pcm: bytes) -> bytes:
        if not pcm:
            return pcm
        raw = np.frombuffer(pcm, dtype=np.int16)
        usable = len(raw) - (len(raw) % self.channels)
        if usable <= 0:
            return pcm
        samples = raw[:usable].astype(np.float32).reshape(-1, self.channels)
        samples /= 32768.0

        # One-pole low/high split; bass and treble are independently adjustable.
        low = np.empty_like(samples)
        alpha = 0.12
        state = self.low_state.copy()
        for index, row in enumerate(samples):
            state += alpha * (row - state)
            low[index] = state
        self.low_state = state
        high = samples - low
        bass = self.settings["bass"]
        treble = self.settings["treble"]
        samples = low * (10.0 ** (bass / 20.0)) + high * (10.0 ** (treble / 20.0))

        # Short feedback echo with a fixed 240 ms delay.
        echo = self.settings["echo"] / 100.0
        if echo > 0:
            flat = samples.reshape(-1)
            delayed = np.empty_like(flat)
            for i, value in enumerate(flat):
                delayed[i] = self.echo_buffer[self.echo_pos]
                self.echo_buffer[self.echo_pos] = value + delayed[i] * 0.35
                self.echo_pos = (self.echo_pos + 1) % len(self.echo_buffer)
            samples = (flat + delayed * echo * 0.55).reshape(-1, self.channels)

        # Soft saturation distortion.
        distortion = self.settings["distortion"] / 100.0
        if distortion > 0:
            drive = 1.0 + distortion * 18.0
            samples = np.tanh(samples * drive) / np.tanh(drive)

        multiplier = self.settings["gain"] * (10.0 ** (self.settings["db"] / 20.0))
        samples *= multiplier
        samples = np.clip(samples, -0.999, 0.999)
        output = (samples.reshape(-1) * 32767.0).astype(np.int16)
        return output.tobytes()
