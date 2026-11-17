import logging
import numpy as np

from pytgcalls import PyTgCalls, filters
from pytgcalls.types import Device, Direction, ExternalMedia, MediaStream, RecordStream, StreamFrames
from pytgcalls.types.raw import AudioParameters
from audio import AudioProcessor

log = logging.getLogger("flexible_vc")

# 48 kHz / stereo — keep same params but mark highest bitrate pytgcalls allows
AUDIO = AudioParameters(bitrate=48000, channels=2)


class VoiceBridge:
    """
    One persistent PyTgCalls engine.

    Key upgrades vs stock:
    • DOMINANT mode — Kovak's processed signal is pushed at full amplitude
      regardless of how many other speakers are in the source VC.
    • NO gain-share normalisation on mix — others get divided down, host stays at peak.
    • Outgoing frame is processed AFTER mix so full effect chain hits target.
    • Priority-push: host signal is inserted twice in the frame sum so it
      always wins the mix even when multiple speakers are present.
    """

    def __init__(self, client, source_id: int, target_id: int, effects=None):
        self.client = client
        self.source_id = int(source_id)
        self.target_id = int(target_id)
        self.processor = AudioProcessor(effects)
        self.calls = PyTgCalls(client)
        self.engine_started = False
        self.connected = False

        # dominant-mode flag — when True, host track bypasses division
        self.dominant = True
        # host-boost multiplier applied to host track before merge
        self.host_boost = 4.0   # 4× = +12 dB advantage over other speakers

    def configure(self, source_id: int, target_id: int, effects=None):
        if self.connected:
            raise RuntimeError("Leave the current bridge before changing groups.")
        self.source_id = int(source_id)
        self.target_id = int(target_id)
        self.processor = AudioProcessor(effects)

    async def connect(self, source_auto_start=False, target_auto_start=False):
        if self.connected:
            return
        if not self.engine_started:
            await self.calls.start()
            self.calls.on_update(
                filters.stream_frame(Direction.INCOMING, Device.MICROPHONE)
            )(self._on_audio)
            self.engine_started = True

        from pytgcalls.types import GroupCallConfig
        source_config = GroupCallConfig(auto_start=source_auto_start)
        target_config = GroupCallConfig(auto_start=target_auto_start)
        self.connected = True
        try:
            await self.calls.play(
                self.source_id,
                MediaStream(ExternalMedia.AUDIO, AUDIO),
                config=source_config,
            )
            await self.calls.record(
                self.source_id,
                RecordStream(True, AUDIO),
            )
            await self.calls.play(
                self.target_id,
                MediaStream(ExternalMedia.AUDIO, AUDIO),
                config=target_config,
            )
        except Exception:
            await self.disconnect()
            raise

    async def _on_audio(self, _engine: PyTgCalls, update: StreamFrames):
        if not self.connected or int(update.chat_id) != self.source_id or not update.frames:
            return
        try:
            arrays = [
                np.frombuffer(frame.frame, dtype=np.int16).astype(np.int64)
                for frame in update.frames
                if frame.frame
            ]
            if not arrays:
                return

            frame_len = min(map(len, arrays))

            if self.dominant and len(arrays) >= 1:
                # ── DOMINANT MIX ────────────────────────────────────────
                # Frame 0 = assumed host (first speaker = bot's own track
                # reflected back; works because bot is source VC participant).
                # Boost host track, then add others at reduced weight so they
                # don't wash out the host signal.
                host   = arrays[0][:frame_len].astype(np.float64)
                others = arrays[1:]

                mixed = host * self.host_boost
                if others:
                    bkg = np.zeros(frame_len, dtype=np.float64)
                    for a in others:
                        bkg += a[:frame_len]
                    bkg /= len(others)
                    # Others at 30% weight → host is always dominant
                    mixed += bkg * 0.30
            else:
                # fallback: equal mix (stock behaviour)
                mixed = np.zeros(frame_len, dtype=np.float64)
                for a in arrays:
                    mixed += a[:frame_len]
                mixed /= max(len(arrays), 1)

            # Clip to int16 range before passing to effect chain
            pcm = np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()

            # Full effect chain (gain, EQ, distortion, maximizer…)
            processed = self.processor.process(pcm)

            await self.calls.send_frame(
                self.target_id,
                Device.MICROPHONE,
                processed,
            )
        except Exception:
            log.exception("Audio frame relay failed for source %s", self.source_id)

    # ── public helpers ──────────────────────────────────────────────────────
    def set_effect(self, name: str, value: float) -> float:
        return self.processor.update(name, value)

    def set_host_boost(self, multiplier: float) -> float:
        """Adjust how dominant the host is over other speakers (default 4.0)."""
        self.host_boost = max(1.0, float(multiplier))
        return self.host_boost

    def set_dominant(self, enabled: bool):
        self.dominant = bool(enabled)

    async def disconnect(self):
        if not self.connected:
            return
        self.connected = False
        for chat_id in (self.source_id, self.target_id):
            try:
                await self.calls.leave_call(chat_id)
            except Exception:
                log.debug("Call %s was already disconnected", chat_id, exc_info=True)
