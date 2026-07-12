# Known limitations

- A third-party station, feed, YouTube item, AcoustID record, MusicBrainz
  endpoint, or LRCLIB lyric may disappear or be unavailable. Mariana returns a
  typed failure and does not report false success.
- DRM, geographic restrictions, authenticated services without an explicit
  credential reference, and unsupported protocols are not bypassed.
- Seek, duration, resume, fingerprinting, and crossfade depend on verified
  source capabilities. Live streams normally support resynchronization instead
  of seeking.
- Acoustic identification is conservative. Insufficient or ambiguous audio is
  never guessed, and MusicBrainz does not itself provide lyric text.
- ReplayGain analysis and optional recommendation embeddings require separately
  managed tools or optional dependencies. Playback remains available when they
  are absent.
- Native speaker/device switching, signed packaging, credentialed remote
  broadcasting, and the eight-hour soak require real target environments.
  Automated mocks are not substitutes for those release gates.
- The legacy REPL is intentionally preserved for command compatibility. Its
  remaining extraction into smaller command handlers is maintenance work, not
  a condition for using the modern media pipeline.
- Setup state is scoped to one application data directory. Explicitly choosing
  a different data directory correctly creates a separate first-run state.
- Sending a file to trash and updating SQLite cannot be one operating-system
  transaction. Mariana journals and reconciles that boundary on restart, but a
  native trash facility that is unavailable or refuses a file remains an
  explicit failure.
