import asyncio
import logging
import subprocess
import numpy as np

from pytgcalls import PyTgCalls, filters
from pytgcalls.types import (
    Device, Direction, ExternalMedia,
    MediaStream, RecordStream, StreamFrames,
)
from pytgcalls.types.raw import AudioParameters
from audio import AudioProcessor

log = logging.getLogger("flexible_vc")

AUDIO      = AudioParameters(bitrate=48000, channels=2)
CHUNK_SIZE = 3840


class VoiceBridge:

    def __init__(self, client, source_id: int, target_id: int, effects=None):
        self.client       = client
        self.source_id    = int(source_id)
        self.target_id    = int(target_id)
        self.processor    = AudioProcessor(effects)
        self.calls        = PyTgCalls(client)
        self.engine_started  = False
        self.connected       = False

        self.dominant     = True
        self.host_boost   = 4.0

        # direct-pipe state
        self._direct_task   : asyncio.Task | None = None
        self._direct_proc   : subprocess.Popen | None = None
        self._direct_active = False

        # muteglitch state
        self._muteglitch        = False
        self._muteglitch_task   : asyncio.Task | None = None
        self._rejoin_lock       = asyncio.Lock()
        self._mute_cooldown     = 0.0   # epoch time of last rejoin

    # ──────────────────────────────────────────────────────────────────────
    def configure(self, source_id: int, target_id: int, effects=None):
        if self.connected:
            raise RuntimeError("Leave the current bridge before changing groups.")
        self.source_id = int(source_id)
        self.target_id = int(target_id)
        self.processor = AudioProcessor(effects)

    # ──────────────────────────────────────────────────────────────────────
    async def connect(self, source_auto_start=False, target_auto_start=False):
        if self.connected:
            return
        if not self.engine_started:
            await self.calls.start()
            # audio relay handler
            self.calls.on_update(
                filters.stream_frame(Direction.INCOMING, Device.MICROPHONE)
            )(self._on_audio)
            # mute/kick detection on target VC
            self.calls.on_update()(self._on_any_update)
            self.engine_started = True

        from pytgcalls.types import GroupCallConfig
        self.connected = True
        try:
            await self.calls.play(
                self.source_id,
                MediaStream(ExternalMedia.AUDIO, AUDIO),
                config=GroupCallConfig(auto_start=source_auto_start),
            )
            await self.calls.record(
                self.source_id,
                RecordStream(True, AUDIO),
            )
            await self._join_target(auto_start=target_auto_start)
        except Exception:
            await self.disconnect()
            raise

    async def _join_target(self, auto_start=False):
        from pytgcalls.types import GroupCallConfig
        await self.calls.play(
            self.target_id,
            MediaStream(ExternalMedia.AUDIO, AUDIO),
            config=GroupCallConfig(auto_start=auto_start),
        )

    # ──────────────────────────────────────────────────────────────────────
    # RELAY mode
    # ──────────────────────────────────────────────────────────────────────
    async def _on_audio(self, _engine: PyTgCalls, update: StreamFrames):
        if not self.connected or self._direct_active:
            return
        if int(update.chat_id) != self.source_id or not update.frames:
            return
        try:
            arrays = [
                np.frombuffer(frame.frame, dtype=np.int16).astype(np.int64)
                for frame in update.frames if frame.frame
            ]
            if not arrays:
                return

            frame_len = min(map(len, arrays))

            if self.dominant and len(arrays) >= 1:
                host  = arrays[0][:frame_len].astype(np.float64)
                mixed = host * self.host_boost
                if len(arrays) > 1:
                    bkg = np.zeros(frame_len, dtype=np.float64)
                    for a in arrays[1:]:
                        bkg += a[:frame_len]
                    bkg /= (len(arrays) - 1)
                    mixed += bkg * 0.30
            else:
                mixed = np.zeros(frame_len, dtype=np.float64)
                for a in arrays:
                    mixed += a[:frame_len]
                mixed /= max(len(arrays), 1)

            pcm = np.clip(mixed, -32768, 32767).astype(np.int16).tobytes()
            processed = self.processor.process(pcm)
            await self.calls.send_frame(self.target_id, Device.MICROPHONE, processed)

        except Exception:
            log.exception("Relay frame failed for source %s", self.source_id)

    # ──────────────────────────────────────────────────────────────────────
    # Mute / kick event catcher
    # ──────────────────────────────────────────────────────────────────────
    async def _on_any_update(self, _engine: PyTgCalls, update):
        if not self._muteglitch or not self.connected:
            return
        try:
            chat_id = getattr(update, "chat_id", None)
            if chat_id is None or int(chat_id) != self.target_id:
                return

            update_type = type(update).__name__.lower()

            # Covers: UpdatedGroupCallParticipant, MutedUpdate, KickedFromCall …
            # pytgcalls fires these when admin mutes/kicks bot in target VC
            is_mute_event = any(k in update_type for k in ("mute", "kick", "left", "ended"))

            if not is_mute_event:
                # Also check participant attribute if present
                participant = getattr(update, "participant", None)
                if participant is not None:
                    muted = getattr(participant, "muted", False)
                    if not muted:
                        return
                else:
                    return

            await self._do_rejoin()

        except Exception:
            log.exception("muteglitch update handler error")

    async def _do_rejoin(self):
        """Leave + rejoin target VC — resets server-side mute."""
        import time
        async with self._rejoin_lock:
            now = time.monotonic()
            if now - self._mute_cooldown < 0.8:   # debounce 800ms
                return
            self._mute_cooldown = now
            try:
                await self.calls.leave_call(self.target_id)
            except Exception:
                pass
            await asyncio.sleep(0.15)
            try:
                await self._join_target()
                log.info("muteglitch: rejoined target %s", self.target_id)
            except Exception:
                log.exception("muteglitch rejoin failed")

    # ──────────────────────────────────────────────────────────────────────
    # muteglitch watchdog — polls every 400ms as a fallback
    # (in case pytgcalls doesn't fire update for every mute action)
    # ──────────────────────────────────────────────────────────────────────
    async def _muteglitch_watchdog(self):
        """
        Fallback loop: tries send_frame with a silent frame.
        If the call raises (meaning we were kicked/muted and can't send),
        trigger a rejoin.
        """
        silence = bytes(CHUNK_SIZE)
        while self._muteglitch and self.connected:
            await asyncio.sleep(0.4)
            if not self._muteglitch or not self.connected:
                break
            try:
                await self.calls.send_frame(
                    self.target_id, Device.MICROPHONE, silence
                )
            except Exception:
                # send_frame raised → we were muted/kicked
                log.info("muteglitch watchdog detected mute — rejoining")
                await self._do_rejoin()

    # ──────────────────────────────────────────────────────────────────────
    # Public muteglitch toggle
    # ──────────────────────────────────────────────────────────────────────
    def set_muteglitch(self, enabled: bool):
        self._muteglitch = enabled
        if enabled:
            if self._muteglitch_task is None or self._muteglitch_task.done():
                self._muteglitch_task = asyncio.get_event_loop().create_task(
                    self._muteglitch_watchdog()
                )
        else:
            if self._muteglitch_task and not self._muteglitch_task.done():
                self._muteglitch_task.cancel()
            self._muteglitch_task = None

    # ──────────────────────────────────────────────────────────────────────
    # DIRECT mode
    # ──────────────────────────────────────────────────────────────────────
    async def start_direct(self, source_url: str):
        await self.stop_direct()
        ffmpeg_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-re", "-i", source_url,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "48000", "-ac", "2",
            "-f", "s16le", "pipe:1",
        ]
        self._direct_proc   = subprocess.Popen(
            ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        self._direct_active = True
        self._direct_task   = asyncio.get_event_loop().create_task(
            self._direct_loop()
        )

    async def _direct_loop(self):
        loop = asyncio.get_event_loop()
        try:
            while self._direct_active and self.connected:
                raw = await loop.run_in_executor(
                    None, self._direct_proc.stdout.read, CHUNK_SIZE
                )
                if not raw or len(raw) < CHUNK_SIZE:
                    break
                processed = self.processor.process(raw)
                await self.calls.send_frame(
                    self.target_id, Device.MICROPHONE, processed
                )
        except Exception:
            log.exception("Direct pipe loop error")
        finally:
            self._direct_active = False
            if self._direct_proc:
                try:
                    self._direct_proc.kill()
                except Exception:
                    pass

    async def stop_direct(self):
        self._direct_active = False
        if self._direct_task and not self._direct_task.done():
            self._direct_task.cancel()
            try:
                await self._direct_task
            except asyncio.CancelledError:
                pass
        if self._direct_proc:
            try:
                self._direct_proc.kill()
            except Exception:
                pass
        self._direct_proc = None
        self._direct_task = None

    # ──────────────────────────────────────────────────────────────────────
    def set_effect(self, name: str, value: float) -> float:
        return self.processor.update(name, value)

    def set_host_boost(self, multiplier: float) -> float:
        self.host_boost = max(1.0, float(multiplier))
        return self.host_boost

    def set_dominant(self, enabled: bool):
        self.dominant = bool(enabled)

    async def disconnect(self):
        if not self.connected:
            return
        self.set_muteglitch(False)
        await self.stop_direct()
        self.connected = False
        for chat_id in (self.source_id, self.target_id):
            try:
                await self.calls.leave_call(chat_id)
            except Exception:
                log.debug("Call %s already disconnected", chat_id, exc_info=True)
