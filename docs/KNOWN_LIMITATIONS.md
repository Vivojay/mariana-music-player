# Known limitations

- Online album discovery depends on MusicBrainz and YouTube availability. A
  release may therefore remain partial; Mariana reports unresolved tracks and
  requires `--allow-partial` instead of silently substituting a different
  edition or similarly named recording.
- Imported YouTube playlists are local snapshots. Mariana neither synchronizes
  later remote edits nor writes changes back to YouTube.
- Download pause takes effect between items or at the downloader's next safe
  checkpoint; it is not a byte-exact suspension guarantee for every remote
  transport.

- A third-party station, feed, YouTube item, AcoustID record, MusicBrainz
  endpoint, or LRCLIB lyric may disappear or be unavailable. Mariana returns a
  typed failure and does not report false success.
- DRM, geographic restrictions, authenticated services without an explicit
  credential reference, and unsupported protocols are not bypassed.
- YouTube may require a signed-in browser, temporarily rate-limit an IP, or
  change player/attestation requirements. `youtube auth set firefox` applies a
  local browser reference across search, playback, and downloads, but no client
  can guarantee third-party acceptance. Mariana never bypasses the challenge or
  reports an authentication rejection as an invalid command.
- Seek, duration, resume, fingerprinting, and crossfade depend on verified
  source capabilities. Live streams normally support resynchronization instead
  of seeking.
- Acoustic identification is conservative. Insufficient or ambiguous audio is
  never guessed, and MusicBrainz does not itself provide lyric text.
- ReplayGain analysis and optional recommendation embeddings require separately
  managed tools or optional dependencies. Playback remains available when they
  are absent.
- Automatic default-speaker following is implemented and deterministically
  tested, but native Bluetooth/speaker switching, signed packaging,
  credentialed remote broadcasting, and the eight-hour soak still require real
  target environments. Automated mocks are not substitutes for those release
  gates.
- The legacy REPL is intentionally preserved for command compatibility. Its
  remaining extraction into smaller command handlers is maintenance work, not
  a condition for using the modern media pipeline.
- Setup state is scoped to one application data directory. Explicitly choosing
  a different data directory correctly creates a separate first-run state.
- Sending a file to trash and updating SQLite cannot be one operating-system
  transaction. Mariana journals and reconciles that boundary on restart, but a
  native trash facility that is unavailable or refuses a file remains an
  explicit failure.
- Electron tabs are independent terminal views over one Mariana PTY, not
  independent player processes. This preserves single ownership of the audio
  device, queue, and SQLite data directory.
- Output search uses xterm.js scrollback retained by the desktop host. Retained
  history is bounded to one million characters and resets on a full terminal
  clear sequence.
