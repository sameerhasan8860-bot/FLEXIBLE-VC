import logging
import numpy as np

from pytgcalls import PyTgCalls, filters
from pytgcalls.types import Device, Direction, ExternalMedia, MediaStream, RecordStream, StreamFrames
from pytgcalls.types.raw import AudioParameters
from audio import AudioProcessor

log = logging.getLogger("flexible_vc")
AUDIO = AudioParameters(bitrate=48000, channels=2)


class VoiceBridge:
    def __init__(self, client, source_id: int, target_id: int, effects=None):
        self.client = client
        self.source_id = int(source_id)
        self.target_id = int(target_id)
        self.processor = AudioProcessor(effects)
        self.calls = PyTgCalls(client)
        self.started = False

    async def connect(self, source_auto_start=False, target_auto_start=False):
        self.calls.start()
        self.started = True
        self.calls.on_update(
            filters.stream_frame(Direction.INCOMING, Device.MICROPHONE)
        )(self._on_audio)

        from pytgcalls.types import GroupCallConfig

        source_config = GroupCallConfig(auto_start=source_auto_start)
        target_config = GroupCallConfig(auto_start=target_auto_start)

        try:
            # The source call is joined as a listener and its incoming audio
            # is recorded as PCM frames. The target call exposes a microphone
            # input to receive the processed frames.
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
        if int(update.chat_id) != self.source_id or not update.frames:
            return
        try:
            arrays = [
                np.frombuffer(frame.frame, dtype=np.int16).astype(np.int32)
                for frame in update.frames
                if frame.frame
            ]
            if not arrays:
                return
            frame_len = min(map(len, arrays))
            mixed = np.zeros(frame_len, dtype=np.int32)
            for samples in arrays:
                mixed += samples[:frame_len]
            mixed //= max(len(arrays), 1)
            pcm = np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()
            processed = self.processor.process(pcm)
            await self.calls.send_frame(
                self.target_id,
                Device.MICROPHONE,
                processed,
            )
        except Exception:
            log.exception("Audio frame relay failed for source %s", self.source_id)

    def set_effect(self, name: str, value: float) -> float:
        return self.processor.update(name, value)

    async def disconnect(self):
        if not self.started:
            return
        for chat_id in (self.source_id, self.target_id):
            try:
                await self.calls.leave_call(chat_id)
            except Exception:
                log.debug("Call %s was already disconnected", chat_id, exc_info=True)
        self.started = False
