# Product Requirements — FLEXIBLE-VC

## Goal
Let each authorized user host their own Telegram account and bridge incoming audio from one source voice chat to one target voice chat.

## Core requirements
1. User starts account hosting through the bot DM with /host.
2. Login sessions are encrypted before MongoDB persistence.
3. Each hosted user has isolated settings, source/target configuration and session state.
4. /unhost deletes only the requesting user's data and stops only their client.
5. /privategroup <id> configures a source group after the bot has administrator access.
6. /join <target> uses the configured source; /join <target> <source> configures a direct pair.
7. One active source-target pair per hosted account.
8. Source incoming audio is captured as frames and relayed to target in real time.
9. /leave and .leave disconnect both calls.
10. Slash commands are bot replies in bot DM/privategroup; privategroup use is administrator-only.
11. Dot commands are hosted-account replies and can be issued from chats accessible to that account.
12. Audio controls persist in MongoDB and are applied to the relay pipeline.

## UX
- Stylish welcome message and inline menu.
- Separate categories for equalizer, volume/gain and effects.
- Every command has a short explanation and example.

## Non-goals
- Permanent hosting on GitHub Actions.
- Infinite/physically unbounded DSP values.
- Recording or storing call audio.
