# Mariana Music Player

Mariana is a local-first command-line and Electron terminal media player for
64-bit Windows, macOS, and Linux. The 0.7 development platform decodes audio
with FFmpeg into a bounded PCM pipeline,
plays it through `sounddevice`, and uses FFplay only as an external diagnostic
or video fallback. The working version is `0.7.0-dev.1`; the stable release remains 0.6.2 until every
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

Existing external tool paths remain supported. Packaged desktop releases use a
signed manifest to download the matching checksum-verified FFmpeg 8.1.2,
Chromaprint 1.6.0, and Deno toolchain into the user-data directory. Source
launches may instead configure a local directory such as:

```text
C:\Users\Vivan.Jaiswal\Documents\ffmpeg-2025-12-18-git-78c75d546a-essentials_build\bin
```

Change `media tools.ffmpeg bin` in the user settings on another machine, run
`tools install`, or put the executables on `PATH`.

Development builds deliberately ship with an unpublished manifest. The manual
managed-tool workflow must publish all four native archives and its signed
manifest, and that generated manifest must be reviewed into the release tag,
before the production release preflight can pass.

## Installation

```powershell
git clone https://github.com/Vivojay/mariana-music-player.git
Set-Location mariana-music-player
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
.\tools\install_chromaprint.ps1
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
queue add|insert|remove|move|swap|jump|list|clear
queue next|previous|shuffle|repeat|consume|save|load|undo|redo|autofill
radio search|list|play|favorite|refresh|health
library roots|scan|status|pause|resume|errors|retry|verify|info
library clean --missing
recommend [count]
recommend autofill [count]
recommend train
like
dislike
sleep <duration> [pause|stop] [fade <duration>]
sleep status|cancel
tools status|install|repair
download-ml <URL> [mp3|flac|wav|m4a|opus] [output path]
```

Sleep timers are session-only. They default to pausing and fade perceptually
over the final ten minutes (or the whole timer when shorter), without replacing
the user's base volume.

## Desktop updates and state

Packaged releases keep immutable application resources separate from settings,
SQLite, logs, `lib.lib`, lyrics, and model state in the operating system's user
data directory. Legacy source-tree state is copied and verified on first launch
without deleting the originals.

The signed desktop updater checks the stable GitHub Releases channel shortly
after startup and every six hours. It downloads in-app but will not install
while playback, a sleep timer, a command, or a profiler transaction is active.
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

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall -q .
python -m ruff check .
python -m pytest -q --cov --cov-branch --cov-report=term-missing
python -m pip_audit -r requirements.txt
```

Normal tests mock public services and audio hardware. Real-process tests create
WAV, MP3, FLAC, OGG, AAC, and WebM fixtures and exercise installed FFmpeg,
FFprobe, and `fpcalc`. Opt-in network probes use `MARIANA_LIVE_TESTS=1`.

Run the release-duration lifecycle soak with:

```powershell
python -m tools.soak_test --seconds 28800 --live-radio `
  --library-files 10000 `
  --ffmpeg-bin "C:\path\to\ffmpeg\bin"
```

## Reliability boundary

Mariana guarantees typed failures, transactional state, bounded buffers and
timeouts, and child-process cleanup under tested conditions. It cannot promise
that a third-party stream stays online, that AcoustID contains a fingerprint,
or that LRCLIB contains lyrics. Manual speaker output, rapid device switching,
and the eight-hour soak remain release gates and must not be inferred from unit
tests.
