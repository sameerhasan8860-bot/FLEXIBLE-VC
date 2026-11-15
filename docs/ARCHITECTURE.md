# Architecture

## Components
- aiogram bot: private onboarding, slash commands, help UI and admin checks.
- Telethon hosted clients: one MTProto client per hosted user; listens for outgoing dot commands.
- PyTgCalls: one engine per hosted user; connects source and target voice chats.
- AudioProcessor: PCM16 stereo processing for gain, dB, bass, treble, echo and distortion.
- MongoDB: one hosted-user document containing encrypted session and that user's settings.
- GitHub Actions: temporary Ubuntu runner.

## Audio flow
Source VC incoming frames → frame mix → DSP processing → send_frame(target, Device.MICROPHONE, pcm) → Target VC.

The source capture is based on PyTgCalls' bridged-call example using Direction.INCOMING and RecordStream. The target call is prepared as an outgoing external-audio stream.

## Isolation
Every hosted user owns a separate Telethon client, PyTgCalls instance, processor and MongoDB document. No user's /unhost operation may disconnect or delete another user's state.

## Startup
1. Validate environment.
2. Connect MongoDB.
3. Load encrypted sessions and restore authorized Telethon clients.
4. Register outgoing dot-command handlers.
5. Start bot polling.

## Connection safety
Both source and target are preflighted before the bridge starts. If a required VC is off and the hosted account lacks manage_call, the operation is rejected. If either join fails, cleanup attempts to leave both sides.
