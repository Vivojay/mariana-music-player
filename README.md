# Mariana Music Player

Mariana is a local-first command-line and Electron terminal media player for
64-bit Windows, macOS, and Linux. The 0.7 development platform decodes audio
with FFmpeg into a bounded PCM pipeline,
plays it through `sounddevice`, and uses FFplay only as an external diagnostic
or video fallback. The working version is `0.7.0-dev.4`; the stable release remains 0.6.2 until every
release gate—including manual speaker and soak acceptance—has passed.

Supported sources include local audio, YouTube, podcasts, custom HTTP media,
HLS/PLS/M3U streams, and internet radio. Queue, identity, lyrics, radio health,
interaction history, and recommendation models are persisted in SQLite.

The desktop UI is not a command reimplementation. React renders an xterm.js
terminal connected to the real Mariana process through a native PTY, so ANSI
output, nested prompts, Ctrl+C, resizing, and every CLI command remain intact.

## Supported environment

- Windows 10 or 11 x64
- macOS x64 or Apple Silicon
- Linux x64 with PortAudio/PipeWire or PulseAudio output
- CPython 3.12 x64
- FFmpeg, FFprobe, and FFplay from the same x64 build
- Deno or Node.js 22+ for reliable yt-dlp extraction
- Chromaprint `fpcalc` 1.6.0 for acoustic identification
- rsgain 3.7 for non-destructive ReplayGain 2 loudness analysis

Existing external tool paths remain supported. Packaged desktop releases use a
signed manifest to download the matching checksum-verified FFmpeg 8.1.2,
Chromaprint 1.6.0, rsgain 3.7, and Deno toolchain into the user-data directory. Source
launches may instead configure either an executable or its containing directory,
for example:

```text
C:\Tools\ffmpeg\bin\ffmpeg.exe
C:\Tools\ffmpeg\bin
```

First boot checks explicit settings, managed tools, `PATH`, and common system,
package-manager, and extracted-build locations. Every candidate is started and
version-checked. If anything is missing, the first/default choice (press Enter)
downloads pinned archives, verifies every SHA-256, extracts into staging, checks
all executables, and atomically activates the result. Download byte counts,
percentages, and progress bars are shown while each archive is transferred. The second choice accepts
manual paths. Run `tools setup` at any later time to repeat this flow.

On Windows, the source-build fallback downloads the pinned FFmpeg 8.1.2
**essentials** ZIP from gyan.dev (one of the Windows builders linked by
ffmpeg.org), official Chromaprint 1.6.0, official rsgain 3.7, and official
Deno 2.9.2. The Gyan
essentials archive is an external GPLv3 tool; its notices remain in the
installed archive. Production desktop bundles continue to prefer Mariana's
release manifest and native managed-tool builds.

Development builds deliberately ship with an unpublished manifest. The manual
managed-tool workflow must publish all four native archives and its signed
manifest, and that generated manifest must be reviewed into the release tag,
before the production release preflight can pass.

## Installation

### Windows installer (development pre-release)

Download `Mariana-0.7.0-dev.3-windows-x64.exe` from the
[v0.7.0-dev.3 pre-release](https://github.com/Vivojay/mariana-music-player/releases/tag/v0.7.0-dev.3),
then launch it from Explorer or PowerShell:

```powershell
.\Mariana-0.7.0-dev.3-windows-x64.exe
```

This development installer is not Authenticode-signed, so Windows may display
a publisher warning. It is not the stable `0.7.0` release. First boot discovers
or offers to provision the media toolchain as described above.

### Source and CLI

```powershell
git clone https://github.com/Vivojay/mariana-music-player.git
Set-Location mariana-music-player
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python main.py
```

To run the React terminal during development:

```powershell
npm install
npm run dev
```

Frontend verification uses `npm run lint`, `npm test`, `npm run build`, and
`npm run test:e2e`. Production packaging uses `npm run dist` after building the
platform-native `mariana-cli` backend.

The Chromaprint installer downloads the official Windows x64 1.6.0 archive and
rejects it unless SHA-256 equals
`30179d3d0dc4cc92f1a0995c1a2e523fb4867724c2ee6a6ceae474f8e4d6937a`.

AcoustID requires an application API key. Set `ACOUSTID_API_KEY` or
`identification.acoustid api key`. Without a key, playback continues and
identification returns a typed unavailable result—it never guesses.

## Playback and command compatibility

Existing local, URL, YouTube, podcast, pause, stop, seek, progress, volume,
mute, fade, lyrics, next/previous, recent, and download syntax remains. New
command families include:

```text
queue add|insert|remove|move|swap|jump|list|clear|reset
queue next|previous|shuffle|repeat|consume|save|load|undo|redo|autofill
queue tree|group|order|priority|dedupe
playlist list|create|show|rename|delete|clear
playlist add|remove|move|order|play|queue|import|export
album search|show|tracks|fetch|play|queue|save
radio search|list|play|favorite|refresh|health
radio add|info|metadata|resync|leveling
radio credentials set|delete|status <station> [username]
library roots|scan|status|pause|resume|errors|retry|verify|info
library clean --missing
recommend [count]
recommend autofill [count]
recommend related [count]
recommend train
fav|bl [!|+|-]
favs|blacklist [count]
like|dislike
hist|history [count]
include|exclude downloads
lyrics|lyr edit
rm|del <library-index|indexed-path>
setup status|resume|restart|repair
sleep <duration> [pause|stop] [fade <duration>]
sleep status|cancel
replaygain on [track|album|auto]
replaygain off|status|verify|mode|preamp|scan|rescan
broadcast profiles|status|start|stop|test
broadcast credentials set|delete|status <profile>
tools status|setup|install|repair
help|h|? [playback|queue|online|library|details|app]
autoplay [on|off|status]
autonext [on|off|status]
output device
media info|probe|metadata [current|library-index|indexed-path]
media fingerprint [current|library-index|indexed-path] [--full]
media identify [current|library-index|indexed-path]
rename short [current|library-index|indexed-path] [--dry-run|--yes]
theme aurora|windows|kitty|gruvbox|list|current
youtube auth status|set <browser[:profile]>|clear|test <YouTube URL>
download-yv [YouTube URL]
download-ya [current|YouTube URL] [--track] [--quality best|worst] [--to <directory>]
download-ya --album [current|album-ref|YouTube-playlist-URL] [--tracks <selector>]
download-ya status [job-id]|pause|resume|cancel <job-id>
download-ml <URL> [mp3|flac|wav|m4a|opus] [output path]
```

Omit the URL from `download-yv` or `download-ya` to download the active
YouTube item. After confirmation, the download runs in the current Mariana
session and reports its result there; it never opens another REPL.
YouTube downloads retain the eleven-character source ID in both output naming
and embedded metadata so `rename short` can produce
`Creator - Title Year [YouTube-ID].ext` without guessing provenance.

Queues are persistent trees. A group can contain tracks or other groups up to
eight levels deep; album and playlist groups are atomic by default, so root
ordering moves each group as one block while retaining its internal order.
`queue order` supports `sequential`, reproducible `shuffle`, stable `priority`,
deterministic `artist-fair`, recommendation-backed `smart`, and stored `custom`
ordering. Strategies affect upcoming media only and never restart the active
track. Structural edits, policies, and cursor changes participate in undo/redo.

Playlists are versioned snapshots managed in Mariana's SQLite database. They
can retain nested groups, embed another playlist or complete album as a group,
import M3U/M3U8 or an explicitly supplied YouTube playlist, and export portable
UTF-8 M3U8. Remote playlist imports are snapshots; Mariana never edits a remote
YouTube playlist. Existing `queue save/load` commands remain compatible and
use the same snapshot store.

Album search keeps editions separate. Local release MBIDs and normalized album
tags are preferred; hybrid search can add MusicBrainz releases, conservatively
match known tracks, then use canonical YouTube videos for unresolved music.
Multidisc selectors accept flattened positions (`1`, `1-5`) and disc positions
(`2.4`); an explicit comma list is also the custom playback permutation.
`album play` replaces the queue and starts playback, whereas `album queue`
preserves the current track and appends an atomic album group by default.

Plain `download-ya` always means one active track. A complete album is expanded
only when `--album` is present. Album jobs are persisted and resumable, process
one item at a time, show per-item and overall progress, and support
pause/resume/cancel without starting another Mariana process. Local tracks are
not downloaded again; `--missing-only` restricts an album job to its missing
YouTube-backed tracks. Output uses portable
`Album Artist/Album/Disc-Track Artist - Title [YouTube-ID].ext` naming.

`media info`/`media probe` show FFprobe and Mutagen fields, filesystem dates,
codec/container details, and saved analysis state. `media fingerprint` reports
the stored Chromaprint object (use `--full` only when the raw value is needed),
while `media identify` queries the configured AcoustID/MusicBrainz path and
returns an explicit unavailable, ambiguous, or no-match status instead of a guess.

Sequential playback (`autoplay` and `autonext` are equivalent) is enabled by
default. A fresh queue mirrors every indexed library item in library order and
stays synchronized until it is explicitly edited. `queue reset` restores that
library projection after custom queue work. Auto-next advances only through the
active queue; it stops at the final item unless `queue repeat all` is enabled.
Disabling auto-next discards any prefetch, leaves the queue pointer unchanged,
and retains the completed item's exact end position in `progress`/`now` until
another playback or explicit stop action occurs.

`output device` reports the operating system's current default endpoint, not a
cached PortAudio label. While playback is active Mariana checks that endpoint
roughly once per second and reopens its bounded PCM output stream when the
default changes. On Windows, Core Audio supplies the authoritative friendly
name and endpoint ID; WASAPI is preferred, with the Windows system mapper used
when a newly connected Bluetooth device has not yet appeared in PortAudio's
device list.

Sleep timers are session-only. They default to pausing and fade perceptually
over the final ten minutes (or the whole timer when shorter), without replacing
the user's base volume.

ReplayGain is disabled by default and never writes media tags. Embedded
`REPLAYGAIN_*` and Opus `R128_*_GAIN` values are reused; missing values are
analyzed by checksum-pinned rsgain and stored only in SQLite. Track, album, and
queue-aware auto modes apply before crossfade and broadcast, while user volume,
mute, manual fade, and sleep automation remain local-only.

`replaygain verify` starts the configured `rsgain` binary and reports its exact
path/version. `replaygain scan changed` schedules missing profiles;
`replaygain status` then distinguishes the analyzer state, the current track's
profile, and the dB actually applied. `applied=0 dB` with `profile=not analyzed`
means normalization is enabled but that track has no usable loudness profile
yet—not that gain was silently guessed.

Mariana receives Icecast/Shoutcast-compatible HTTP(S), ICY, HLS, M3U, and PLS
streams. Optional live leveling is separately controlled by `radio leveling`
and restarts a live decoder at the current edge. Private-stream and broadcast
passwords are referenced from the operating-system keychain (Windows
Credential Manager, macOS Keychain, or Linux Secret Service), never settings,
SQLite, URLs, logs, or FFmpeg arguments.

Broadcast profiles live under `broadcast.profiles` in settings. For example:

```yaml
broadcast:
  profiles:
    home:
      server url: https://radio.example.net:8443
      mount: /mariana.opus
      username: source
      credential reference: home
      codec: opus
      bitrate kbps: 128
      station name: Mariana
      description: Personal Mariana stream
      genre: Music
      public: false
```

`broadcast credentials set home` stores the password securely. Ogg Opus is the
default; MP3 is available as an explicit compatibility profile. Broadcasting
continues with silence during local pause, stop, queue gaps, and recovery. It
disconnects only on `broadcast stop`, terminal failure, or application exit.

## Desktop updates and state

Packaged releases keep immutable application resources separate from settings,
SQLite, logs, `lib.lib`, lyrics, and model state in the operating system's user
data directory. Legacy source-tree state is copied and verified on first launch
without deleting the originals.

First-run setup is tracked in an atomically replaced writable state file, not
in packaged settings. A completed setup never runs again for the same data
directory. Setup records its attempt, current and completed steps, timestamps,
and sanitized failures; a PID/creation-time lock prevents concurrent wizards.
Interrupted or corrupt setup offers resume, safe restart, repair, or an explicit
skip of a failed optional sample download. `setup restart` resets only setup
progress and preserves settings, media, history, the library, and preferences.
Media-tool discovery/provisioning is its own idempotent first step; it is marked
complete only after validation (or an explicit limited-mode choice when the
required FFmpeg suite is already usable).
Installations whose setup completed before the current full tool bundle receive
one versioned, default-yes repair offer; declining it does not rerun the setup
wizard and `tools setup` remains available.

The CLI uses a two-line, media-aware prompt showing the active item, elapsed and
total time, percentage, and playback state. The external June 2022 testing
snapshot used the same mirrored blue-gradient banner as this repository—not a
rainbow banner—so no nonexistent rainbow asset is claimed or synthesized.

The Electron shell supports multiple terminal views over the one authoritative
Mariana PTY. Each view keeps terminal state and can be searched independently;
tabs intentionally share playback, queue, and database state rather than
starting conflicting player processes. The Find Output field supports
incremental highlighting, Enter/Shift+Enter navigation, arrow buttons, and
Escape-to-clear. Theme changes made in the selector issue the same `theme`
command as the CLI, keeping runtime settings, the preset selector, and future
launches synchronized.

The signed desktop updater checks the stable GitHub Releases channel shortly
after startup and every six hours. It downloads in-app but will not install
while playback, a broadcast, a sleep timer, a command, or a profiler transaction is active.
A verified SQLite/configuration backup is required before restart-and-install.
Release publication is manual and fails closed when the platform tool manifest,
Apple notarization credentials, Windows signing certificate, or Linux signing
key is absent.

`lib.lib` remains the human-editable list of library roots. Mariana indexes it
incrementally in SQLite: unchanged files are not re-probed, renames retain their
library identity, unavailable drives do not erase tracks, and deleted files are
tombstoned until `library clean --missing` is explicitly issued. Native file
events are debounced; network/removable roots use bounded polling. Fingerprint
and recommendation feature work pauses while media is playing.

Capabilities are explicit. Pause, stop, volume, mute, progress, history,
queueing, and `now` apply to successfully decoded sources. Seeking is rejected
for live/non-seekable streams. Radio resync restarts at the live edge. Mariana
does not bypass DRM, authentication, geographic restrictions, or server access
controls.

Direct URLs are restricted to `file`, `http`, and `https`. HLS/DASH and
Icecast/Shoutcast are supported over HTTP(S); arbitrary FFmpeg device and
transport protocols are rejected. YouTube stream URLs are resolved immediately
before use and are never stored. Optional authenticated YouTube access can
reference a browser profile through `sources.youtube.browser profile`; Mariana
does not copy cookies into its database or logs.

Some YouTube media requires a signed-in session or triggers the site's bot
challenge. Configure one browser profile from inside Mariana; the setting is
applied immediately to search, validation, playback, and downloads:

```text
youtube auth set firefox
youtube auth status
youtube auth test https://www.youtube.com/watch?v=...
```

Firefox is the recommended first choice. Named Firefox and Chromium profiles
can use `browser:profile`, for example `firefox:default-release` or
`edge:Default`. Use `youtube auth clear` to return to anonymous access.

The equivalent writable setting is:

```yaml
sources:
  youtube:
    browser profile: edge:Default
```

Mariana stores only this reference. yt-dlp reads cookies directly from the
selected local profile when a YouTube command runs; Mariana does not copy them
into settings, SQLite, logs, or the packaged application. Sign in to YouTube in
that browser and close it before retrying if its cookie database is locked.
HTTPS uses the operating-system trust store, so an office TLS-inspection root
certificate must be trusted by the host OS; Mariana never disables certificate
verification. YouTube can still impose IP rate limits or change its player and
attestation requirements, so external rejection is reported explicitly rather
than hidden or treated as an invalid command.

The June 2022 testing snapshot was audited semantically rather than merged.
Historical aliases—including `.`, `.*`, `+`, `-`, the `arand` family,
`vh`/`volh`/`volumeh`, and `dl-yv`/`dl-ya`—route to current implementations.
Advanced `find`/`rfind`/`lfind`, history, managed-download inclusion, persistent
favorites/blocks, local lyric editing, and trash-only `rm`/`del` are retained.
RPAN aliases remain recognized but report service retirement. VLC, pygame,
ShazamIO, PRAW credentials, generated metadata, expired hard-coded URLs, and
binary runtime state were deliberately not imported. The exhaustive audit is
recorded in the [verification matrix](docs/VERIFICATION_MATRIX.md).

## Open identification and lyrics

Playback PCM feeds the sole acoustic fingerprint implementation, Chromaprint.
AcoustID resolves fingerprints, MusicBrainz enriches recording/work metadata,
and LRCLIB supplies synchronized or plain lyrics. Local embedded lyrics and
adjacent `.lrc` files take precedence. Conservative acceptance requires score
`>=0.85`, runner-up margin `>=0.05`, and duration agreement within five seconds
when duration is known. Missing and ambiguous results remain missing or
ambiguous.

MusicBrainz calls carry a Mariana User-Agent, are limited to one request per
second, and use cached offline fallback. Lyrics cache records provider,
retrieval time, identity confidence, and attribution.

## Recommendations and privacy

The default CPU engine stays on-device. It combines stable metadata features,
an online Bayesian preference ranker, 10% Thompson exploration, MMR diversity
at 0.75, recent-session context, explicit negative feedback, and a maximum of
two tracks by one artist in a ten-item window. Every result explains its
signals. Lightweight retraining occurs after 50 weighted events and model
artifacts are written atomically while the previous champion is retained.

The optional frozen LAION-CLAP tier has its own lock:

```powershell
python -m pip install -r requirements-recommendation-ai.txt
```

It is not part of core playback. ListenBrainz is opt-in and disabled until a
token is supplied. Raw audio and local listening history are not uploaded.
RecBole/Implicit challenger research is isolated from the runtime; see
`recommendation_engine/RESEARCH.md`.

## Verification

The latest Windows verification run passed 856 deterministic Python tests,
the 90% repository coverage gate (90.78%), every independent 95%
critical-module branch gate, 9 React unit tests, and 5 freshly packaged
Electron/backend scenarios with one explicitly opt-in live download skipped.
The real installed-tool suite added 17 passing FFmpeg, FFprobe, Chromaprint,
ReplayGain, Icecast, and short-soak scenarios. Five credential-free public
service probes passed earlier on the branch but were not rerun at the recorded
commit. See
the [dated verification report](docs/verification/2026-07-13.md) for exact
versions, metrics, and the release gates that remain pending.

A real silent-device check resolved and opened the current Windows endpoint as
`Speakers (JBL Flip 5)` through WASAPI. An audible physical hot-switch test is
still a separate manual release gate.

```powershell
python -m pip install -r requirements-dev.txt
python tools/verify_repository.py
python tools/verify_text_integrity.py
python tools/verify_docs.py
python -m compileall -q main.py mariana beta lyrics_provider recommendation_engine tools
python -m ruff check .
pyright
python -m pytest -q --cov --cov-branch --cov-report=json:coverage.json --cov-fail-under=90
python tools/coverage_gate.py coverage.json --minimum 95
python -m pip_audit -r requirements.txt
```

Normal tests mock public services and audio hardware. Real-process tests create
WAV, MP3, FLAC, OGG, AAC, and WebM fixtures and exercise installed FFmpeg,
FFprobe, and `fpcalc`. Opt-in network probes use `MARIANA_LIVE_TESTS=1`.

Run the release-duration lifecycle soak with:

```powershell
python -m tools.soak_test --seconds 28800 --live-radio --broadcast `
  --library-files 10000 `
  --ffmpeg-bin "C:\path\to\ffmpeg\bin"
```

## Reliability boundary

Mariana guarantees typed failures, transactional state, bounded buffers and
timeouts, and child-process cleanup under tested conditions. It cannot promise
that a third-party stream stays online, that AcoustID contains a fingerprint,
or that LRCLIB contains lyrics. Manual speaker output, rapid device switching,
the Linux mutation score, cross-platform native acceptance, signed OTA testing,
credentialed integrations, and the eight-hour soak remain release gates and
must not be inferred from unit tests.

## Engineering reference

- [Architecture](docs/ARCHITECTURE.md)
- [Security and privacy](docs/SECURITY.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Repository hygiene and source map](docs/REPOSITORY_HYGIENE.md)
- [Testing and release gates](docs/TESTING.md)
- [Verification matrix](docs/VERIFICATION_MATRIX.md)
- [Changelog](CHANGELOG.md)
