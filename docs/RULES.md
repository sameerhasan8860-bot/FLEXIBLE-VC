# Project Rules

1. Never log or print bot tokens, API hashes, MongoDB URIs, OTPs, 2FA passwords, or session strings.
2. Never store plaintext Telegram sessions in MongoDB; encrypt with the repository secret Fernet key.
3. A hosted user's actions may only mutate that user's own state unless a documented privategroup-admin command intentionally controls that hosted user's bridge.
4. /unhost must stop that user's bridge, disconnect that user's Telethon client, and delete only that user's MongoDB document.
5. Every user gets an independent Telegram client, PyTgCalls engine, audio processor and bridge state.
6. A user may have only one active source-target pair. A new target requires leaving the existing pair first.
7. Preflight both voice chats before joining. If a required call is off and the hosted account cannot start it, do not leave a half-connected bridge.
8. Audio callbacks must forward only source frames to the configured target; do not create a source-target feedback loop.
9. Accept finite numeric audio input but clamp DSP values to stable ranges. Never describe physical amplification as infinite.
10. Do not claim full integration success until tests with real Telegram accounts and two live voice chats pass.
11. Keep all credentials in GitHub Actions secrets; never commit .env.
12. Avoid destructive database operations outside the requesting user's own record.
