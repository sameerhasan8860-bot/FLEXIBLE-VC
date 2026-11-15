# FLEXIBLE-VC

A Telegram user-account voice-chat bridge bot. Each authorized user can host their own Telegram account, select a source voice chat and a target voice chat, and relay incoming source audio frames to the target in real time.

## Current implementation

- Bot DM onboarding with /host (phone, Telegram login code, optional 2FA).
- Per-user encrypted Telethon StringSession storage in MongoDB.
- Per-user isolation and /unhost cleanup.
- /privategroup <group_id> source-group configuration.
- /join <target_id> and /join <target_id> <source_id>.
- /leave disconnects the source and target calls.
- Hosted-account dot-command handler for .join, .leave, and audio controls.
- Incoming PyTgCalls frame capture and source-to-target forwarding.
- Audio controls: dB, gain, bass, treble, echo, distortion, and combined `/level` master profile.
- GitHub Actions workflow for Ubuntu 22.04.

## Important audio note

The bridge uses the PyTgCalls upstream bridged-call API: Direction.INCOMING, Device.MICROPHONE, RecordStream, and send_frame. This is the correct API family for receiving incoming VC frames and publishing frames to another call. Actual mixed-audio behavior must still be integration-tested with real Telegram accounts and two active group calls.

## Required GitHub Actions secrets

Add these under Settings → Secrets and variables → Actions → New repository secret:

| Secret | Value |
|---|---|
| BOT_TOKEN | Telegram bot token |
| API_ID | Telegram API ID |
| API_HASH | Telegram API hash |
| MONGO_URI | MongoDB connection URI |
| DB_NAME | Optional database name; e.g. flexible_vc |
| SESSION_ENCRYPTION_KEY | Fernet key used to encrypt hosted user sessions |

Generate an encryption key locally:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Keep the key stable. If it is lost or changed, previously stored sessions cannot be decrypted.

## Run on GitHub Actions

1. Add all required repository secrets.
2. Open Actions → FLEXIBLE-VC → Run workflow.
3. Select the main branch and run it.
4. Keep the workflow running while you test the bot.

The workflow timeout is 350 minutes (5 hours 50 minutes), within the normal GitHub-hosted runner job limit. It is not permanent hosting; start a new workflow after the run ends.

## Commands

### Hosting and VC

- /host — host your own Telegram account in the private bot DM.
- /unhost — remove your own hosted session and all your stored settings.
- /privategroup <group_id> — set a source group. Add the private bot as an administrator first.
- /join <target_group_id> — connect configured source to target.
- /join <target_group_id> <source_group_id> — direct source/target connection.
- /leave — leave both voice chats.

### Hosted-account commands

- .join in a group — use that group as the target.
- .join <target_group_id> — use an explicit target (useful in DM or Saved Messages).
- .leave — leave both calls.
- .db <value>, .gain <value>, .bass <value>, .treble <value>, .echo <value>, .distortion <value>, .level <number>.

Slash commands are handled by the bot in private DM and the configured privategroup. In a privategroup, only Telegram administrators can use them. Dot commands are handled by the hosted account.

## Master audio level

`/level <number>` and `.level <number>` apply a combined profile across dB, gain, bass, treble, echo and distortion. Any finite non-negative numeric level is accepted; the profile grows logarithmically, so 1000 is stronger than 100 without allowing unbounded digital output. The PCM output stage remains bounded to prevent clipping and unsafe runaway levels. Individual effect commands remain available for manual adjustment after setting the master level.

The individual DSP controls retain safe operating bounds: dB -60..+24, gain 0..8, EQ bands -24..+24, echo/distortion 0..100.

## Security

- Never commit bot tokens, API hashes, MongoDB credentials, login codes, 2FA passwords, or session strings.
- Hosted sessions are encrypted at rest using the Fernet key.
- Login codes and 2FA messages are deleted where Telegram allows it; never host another person's account without their explicit consent.
- Each user's data is stored in a single MongoDB document. /unhost deletes only that user's document.

## Current limitations to validate

- The first integration test must confirm that the deployed PyTgCalls build and Telegram account can receive all expected incoming source frames and relay them without clipping.
- Auto-start permission detection is implemented for supergroups/channels. Basic legacy groups are not yet supported by the permission preflight.
- The GitHub Actions runner is temporary and the process stops when the job ends.
