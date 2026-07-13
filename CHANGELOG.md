# Changelog

## Unreleased

- Added persistent eight-level queue groups, atomic album/playlist nodes,
  deterministic sequential/shuffle/priority/artist-fair/smart/custom ordering,
  cursor-safe mutations, and structural undo/redo.
- Added versioned playlist CRUD, nested snapshot composition, M3U/M3U8 import
  and export, and explicit YouTube-playlist snapshot imports.
- Added release-specific local/MusicBrainz album discovery, multidisc selectors,
  conservative local matching, verified canonical YouTube fallback, album
  playback/queueing, and playlist snapshots.
- Replaced loose audio downloads with persistent current-track and explicit
  `--album` jobs supporting progress, pause, resume, cancel, safe naming, and
  restart recovery.
- Added an explicit 90% repository branch gate alongside independent 95%
  critical-module branch gates; the queue/album/download closure suite verifies
  migration, rollback, tree invariants, ambiguity, cancellation, and CLI errors.

## 0.7.0-dev.3

- Added synchronized startup progress bars, a richer two-line playback prompt,
  compact `help` aliases, persisted autoplay, CLI-controlled terminal themes,
  media inspection/identification commands, and safe metadata-derived renames.
- Added multiple searchable terminal views backed by one authoritative PTY;
  closing, opening, or clearing a view never starts a second player process.
- Made shutdown concurrent and bounded, and removed packaged subprocess paths
  that could relaunch the complete application instead of the intended helper.
- Expanded first-run provisioning to checksum-verified FFmpeg, FFprobe, FFplay,
  Chromaprint, rsgain, and Deno downloads with byte and percentage progress.
- Fixed packaged `download-yv` and `download-ya` commands so confirmed
  downloads run as tracked background jobs in the current Mariana session
  instead of relaunching the packaged backend as a second REPL.
- YouTube downloads now pass Mariana's configured FFmpeg directory to yt-dlp
  and report completion or configuration failures in the originating session.
- YouTube download commands validate URL structure locally instead of making a
  redundant extraction request before confirmation.
- Added automatic operating-system default-output following. Windows uses Core
  Audio endpoint identity, prefers WASAPI, and safely reopens the bounded PCM
  stream after Bluetooth/default-speaker changes without restarting playback.
- Added `autonext` as the explicit alias for persisted sequential playback;
  disabling it now discards prefetch and stops both queue and library playback
  exactly at the current item's end.
- Fresh persistent queues now mirror the full indexed library in order, retain
  custom edits across scans, and can be deliberately restored with
  `queue reset`. Direct local playback now retains the queue's stable identity,
  and natural completion keeps an exact end-position snapshot when auto-next
  is disabled.

## 0.7.0-dev.2

- Replaced legacy playback integrations with a supervised FFmpeg PCM platform.
- Added persistent queueing, incremental library profiling, open fingerprint
  identification, lyrics resolution, radio health, and recommendations.
- Added the React/Electron PTY shell, sleep timers, managed tools, and safe OTA
  coordination.
- Added non-destructive ReplayGain 2 support and secure Icecast broadcasting.
- Added independent critical-module branch gates, static typing, mutation
  testing, text/document integrity checks, expanded fault injection, and native
  release verification.
- Semantically integrated the June 2022 testing snapshot: restored its safe
  aliases, advanced searches, history, managed-download root, preferences,
  local lyric editing, and contextual related recommendations while explicitly
  retiring RPAN, expired hard-coded shortcuts, and obsolete runtime code.
- Replaced first-run configuration flags with atomic resumable setup state and
  a stale-aware process lock. Added safe repair/restart/optional-sample recovery.
- Added persistent favorite/neutral/blocked preferences and confirmation-based,
  trash-only removal for indexed local media with crash reconciliation.

This is a development version. The deterministic 90% repository and 95%
critical-module coverage gates now pass. Stable `0.7.0` remains blocked on the
documented mutation, native, credentialed, signing/OTA, and eight-hour soak
gates.
