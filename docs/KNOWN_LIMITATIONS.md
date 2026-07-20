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
- Desktop autocomplete is currently a safe command explorer backed by the
  sanitized command catalog. Selecting a suggestion updates only its controlled
  field; it does not edit terminal input, write to the PTY, or execute a
  command. Tab completion, argument completion, dynamic media/path suggestions,
  and command submission require a future backend-owned line-editor contract.
- Command-catalog risk labels are informational. They do not replace runtime
  validation or confirmation, and autocomplete cannot approve or execute a
  destructive command.
- Desktop playback projection validation currently accepts schema 7 only and
  fails closed when development builds mix incompatible backend and renderer
  versions. Malformed updates are silently ignored, leaving the last accepted
  status visible; a dedicated user-facing protocol diagnostic is not yet
  available. Event freshness uses strictly increasing envelope timestamps
  rather than a dedicated monotonic projection sequence.
- Mini-player chapter and preferred-region progress is intentionally read-only.
  It renders only validated finite source-timeline data and suppresses markers
  for live or unknown-duration media; seeking remains limited to the main
  desktop progress surface. The current Mini-player provides
  Play/Pause/Previous/Next and a local artwork placeholder, but not favourite
  or volume controls, artwork retrieval, themes, pin/always-on-top, remembered
  bounds, provider links, hover preview, or packaged/native acceptance.
- Main-window mouse/tap seeking is a single-click absolute seek through the
  typed backend boundary. It has no drag scrubbing, hover preview, waveform,
  keyboard/slider seeking, or Mini-player seek. Live, unknown-duration,
  nonseekable, blocked, transitional, and backend-unavailable states remain
  noninteractive, and preferred-region bounds clamp the submitted source-time
  target.
- Playlist delete/clear are revision-bound, but add/remove/move/order still do
  not use compare-and-swap revisions for concurrent writers. Revision restore
  should be exposed before claiming full concurrent-edit recovery.
- `library clean --missing` is confirmed as a global operation but currently
  evaluates the missing-record set at execution time rather than binding the
  exact tombstone IDs displayed before confirmation.
