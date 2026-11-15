# Implementation and validation checklist

- [x] Create repository structure and GitHub Actions workflow.
- [x] Add encrypted MongoDB session storage.
- [x] Add hosted-account lifecycle and per-user manager.
- [x] Add incoming-frame relay and audio DSP processor.
- [x] Add bot onboarding and slash-command handlers.
- [ ] Verify imports against the exact installed PyTgCalls commit on Ubuntu 22.04.
- [ ] Run an end-to-end host/login test with a test Telegram account.
- [ ] Test two simultaneous active VCs and source-to-target mixed audio.
- [ ] Test source/target VC-off permission matrix.
- [ ] Test one user's /unhost while another user's bridge remains active.
- [ ] Test reconnect and GitHub Actions restart behavior.
