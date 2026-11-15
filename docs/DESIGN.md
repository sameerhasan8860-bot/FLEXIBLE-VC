# UX and Audio Design

## Bot visual language
- Product name: FLEXIBLE-VC.
- Tone: compact, friendly, technical and readable in Hindi/English.
- Welcome: framed title, one-line purpose and clear next action.
- Main actions: Host Account, Help & Commands, Equalizer, Volume, Audio Effects.
- Use unique emoji prefixes and Unicode display typography.
- Telegram clients control inline-button rendering; universal custom button colors are not guaranteed by the Bot API.

## Help structure
- Hosting and VC: host, unhost, privategroup, join, leave.
- Equalizer: bass, treble.
- Volume: db, gain.
- Audio effects: echo, distortion.
- Each command has a dedicated explanation page with syntax, purpose and example.

## Audio behavior
- Input/output PCM: 16-bit signed, stereo, 48 kHz.
- Source audio frames are mixed before processing.
- Effects are applied in this order: bass/treble split, echo, distortion, gain and dB output level.
- Final samples are clipped to a safe PCM16 range.
- No call audio is intentionally written to disk or MongoDB.
