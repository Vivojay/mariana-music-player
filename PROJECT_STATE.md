> This document describes the currently verified engineering state of the repository.
> It intentionally changes over time as releases, verification evidence, and repository state evolve.

# Mariana project state

## Document purpose

This document records the verified engineering state of Mariana at commit
`a053dbb4eebf85285b426f0cd5e38592d5b5862c`. Release-independent subsystem
design is documented in [ARCHITECTURE_STATE.md](ARCHITECTURE_STATE.md).
Detailed test evidence remains in
[docs/verification/2026-07-14.md](docs/verification/2026-07-14.md).

## Project overview

Mariana is a local-first command-line and Electron terminal media player. The
same Python REPL runs directly in a terminal or inside an Electron-owned native
PTY. Audio is resolved and decoded with FFmpeg, mixed in a bounded PCM pipeline,
and sent to the active output through `sounddevice`.

Supported source families are indexed local media, direct file/HTTP(S) media,
HLS/DASH over HTTP(S), YouTube, podcasts, M3U/M3U8/PLS playlists, and
Icecast/Shoutcast-compatible radio. Persistent SQLite services provide library
indexing, hierarchical queues, playlists, albums, downloads, identities,
lyrics, loudness profiles, radio health, preferences, stations, and
recommendations.

## Verified repository snapshot

| Property | Verified value |
|---|---|
| Repository | `https://github.com/Vivojay/mariana-music-player` |
| Flagship branch | `dev-6` |
| HEAD | `a053dbb4eebf85285b426f0cd5e38592d5b5862c` |
| Remote state | Local `dev-6` and `origin/dev-6` matched |
| Development version | `0.7.0-dev.4` |
| Canonical version file | `version.json` |
| Python target | CPython 3.12 |
| Desktop build target | Node.js 24 and Electron 43.1.0 |
| Database schema | Version 8 |

`version.json`, `package.json`, Python version reporting, CLI display, and the
packaged executable were synchronized at this snapshot.

## Verification evidence

### Final HEAD CI

[GitHub Actions run 29329927424](https://github.com/Vivojay/mariana-music-player/actions/runs/29329927424)
completed successfully for `a053dbb` on:

- Windows.
- Ubuntu.
- macOS ARM64.

The workflow passed repository integrity, version and documentation checks,
Ruff, Pyright, Python branch coverage, independent critical-module coverage,
React tests/build, native Electron dependency rebuild, native PTY tests,
dependency audits, and artifact collection.

### Recorded deterministic and integration evidence

The latest full recorded verification includes:

- 992 deterministic Python tests passed.
- 17 opt-in or environment-dependent scenarios explicitly skipped.
- 93.95% aggregate statement/branch coverage.
- 90.1% repository-wide branch coverage.
- At least 95% branch coverage independently for every module enforced by
  `tools/coverage_gate.py`.
- 12 Vitest tests passed.
- Two native development PTY scenarios passed.
- Six Windows packaged Electron scenarios passed.
- 17 real-process media tests passed.
- Five public live probes passed.
- `pip check`, `pip-audit`, and `npm audit --audit-level=high` passed.

The package tests verified bundled-backend launch, version reporting,
same-session download creation, first setup exactly once, interrupted setup
resume, corrupt setup repair, and recovery from an empty user-state file.

## Current release status

The current public development release is
[v0.7.0-dev.4](https://github.com/Vivojay/mariana-music-player/releases/tag/v0.7.0-dev.4).
It is a public, non-draft prerelease targeting commit
`53330305e4187f3bdcba31b1df11c884532e97e4`. Commits between that tag and the
verified project snapshot contain documentation changes only.

Published assets:

- `Mariana-0.7.0-dev.4-windows-x64.exe`
- `Mariana-0.7.0-dev.4-windows-x64.exe.blockmap`
- `latest.yml`
- `SHA256SUMS.txt`

The installer is Windows x64 only and is not Authenticode-signed. Its SHA-256
is:

```text
C5537C030EBAB7EF9E6B5B4D60EA1538B74DEA86A89E885EFBBD081A392DEB19
```

The verified unpacked application identities are:

| Artifact | SHA-256 |
|---|---|
| `release/win-unpacked/Mariana.exe` | `01FF00B1AE55C5B222B5F5F1AB4FC542E672ABC101CC88D4EF805CE5BB46BAF5` |
| Bundled `mariana-cli.exe` | `EE05BC3DE09F797D9FAE15D4B35299D189A18C3B5B7E64FDD066AC5B04DFA49F` |
| `app.asar` | `4A848DBBD702D5BBA8AEAD2F153F63C6FD9542F3F2A89D37403C51A9A423161B` |

The stable release remains `0.6.2`. Version `0.7.0-dev.4` must not be presented
as stable.

## Remaining release blockers

Stable `0.7.0` remains blocked on evidence for:

- The scheduled 80% mutation-score gate.
- An eight-hour mixed playback, library, radio, and broadcast soak.
- Audible native speaker playback and rapid Bluetooth/default-device switching.
- Native sleep/resume and hardware-loss recovery.
- Credentialed packaged YouTube download.
- Credentialed AcoustID identification.
- Authenticated remote Icecast broadcasting.
- Signed Windows packaging.
- Signed and notarized macOS x64 and ARM64 packages.
- Signed Linux AppImage and checksum artifacts.
- Signed N-to-N+1 OTA update acceptance on every target.
- Production managed-tool artifacts and a populated signed
  `tools/manifest.json`.
- Native recycle-bin restoration acceptance.
- Long-session recommendation quality review.
- macOS and Linux packaged-application acceptance.

Pending gates must remain explicitly pending in release notes and verification
documents.

## Known limitations

- Third-party streams and the YouTube, Radio Browser, MusicBrainz, AcoustID,
  LRCLIB, ListenBrainz, and podcast services can be unavailable or change.
- YouTube can require a signed-in browser profile, reject an IP, rate-limit
  requests, or change player attestation. Mariana reports these conditions but
  does not bypass them.
- Seek, resume, crossfade, fingerprinting, and duration depend on verified source
  capabilities. Live media generally supports resynchronization instead of
  seeking.
- Online album resolution can remain partial. Ambiguous editions are not
  combined automatically.
- Imported YouTube playlists are local snapshots and are not synchronized back
  to YouTube.
- Download pause is checkpoint-based rather than a byte-exact suspension
  guarantee for every transport.
- ReplayGain scans and optional CLAP embeddings require separately available
  tools/dependencies; their absence does not disable core playback.
- Electron tabs are separate terminal views over one PTY, not independent
  playback sessions.
- Terminal output search is limited to the bounded history retained by the
  Electron host.

## Important engineering decisions

- FFmpeg decoding plus `sounddevice` is authoritative. FFplay is limited to
  diagnostic/video fallback use.
- VLC, pygame playback, ShazamIO, PRAW, and RPAN runtime integrations are not
  part of the modern platform.
- The June 2022 testing repository was integrated semantically; its unrelated
  Git history and obsolete runtime files were not merged.
- The legacy REPL and its command aliases remain supported. New behavior is
  implemented in focused `mariana/` services rather than by rewriting the REPL.
- Runtime state is stored outside immutable application resources.
- Signed URLs, cookies, passwords, authorization headers, and secret query data
  are not persisted.
- ReplayGain analysis never modifies media files.
- File removal uses the native trash facility and never falls back to permanent
  deletion.
- External failures produce typed, actionable results rather than guessed or
  silent success.

## Repository directory map

| Path | Responsibility |
|---|---|
| `main.py` | CLI entry point, REPL, and compatibility dispatch |
| `mariana/` | Modern playback, persistence, library, queue, album, radio, setup, and security services |
| `desktop/` | Electron main/preload processes and React/xterm renderer |
| `lyrics_provider/` | Lyrics identification and display integration |
| `recommendation_engine/` | Local ranking, optional embeddings, ListenBrainz, and research harness |
| `beta/` | Legacy-named adapters still required by supported commands |
| `tests/` | Deterministic, fault-injection, real-process, live, and package tests |
| `tools/` | Verification, cleanup, packaging, release, soak, mutation, and toolchain utilities |
| `settings/` | Immutable factory configuration defaults |
| `user/` | Immutable factory user-data defaults |
| `res/` | Curated immutable application and lyrics-window assets |
| `docs/` | Architecture, testing, security, limitations, hygiene, and verification evidence |
| `.github/workflows/` | CI, reliability, toolchain, and signed-release automation |

## Important entry points and critical modules

| Path | Responsibility |
|---|---|
| `main.py` | Initializes runtime services and owns the command loop |
| `mariana/models.py` | Shared serialized media, playback, queue, album, station, and download contracts |
| `mariana/database.py` | SQLite schema, transactions, backups, and migrations |
| `mariana/paths.py` | Immutable resource and writable data-directory separation |
| `mariana/setup.py` | Transactional setup state and stale-aware setup lock |
| `mariana/toolchain.py` | Verified tool downloads, validation, staging, and atomic activation |
| `mariana/playback.py` | FFmpeg decoder sessions, PCM mixing, gain stages, output, and process ownership |
| `mariana/supervisor.py` | Retry, refresh, failover, output recovery, and cancellation policy |
| `mariana/sources.py` | Source resolution, probing, capabilities, and typed failures |
| `mariana/output_devices.py` | OS-default endpoint discovery and PortAudio route mapping |
| `mariana/library.py` | Incremental catalog, staged jobs, identity preservation, and tombstones |
| `mariana/library_service.py` | Watchers, workers, reconciliation, and playback-aware scheduling |
| `mariana/queueing.py` | Hierarchical queue, strategies, policies, cursor, and undo/redo |
| `mariana/playlists.py` | Versioned playlist snapshots and import/export |
| `mariana/albums.py` | Release-specific album discovery and track resolution |
| `mariana/download_jobs.py` | Persistent transactional track/album downloads |
| `mariana/station.py` | Persistent station lifecycle and queue restoration |
| `mariana/station_discovery.py` | Local and online station candidate generation |
| `mariana/identity.py` | Chromaprint, AcoustID, MusicBrainz, and LRCLIB pipeline |
| `mariana/loudness.py` | ReplayGain tags, rsgain analysis, persistence, and gain policy |
| `mariana/radio.py` | Catalog, playlist resolution, health, metadata, and failover |
| `mariana/broadcast.py` | Icecast encoding, secure tunnel, and broadcast supervision |
| `recommendation_engine/engine.py` | Explainable Bayesian/MMR ranking and model persistence |
| `desktop/main.ts` | Electron lifecycle, PTY ownership, updates, and structured events |
| `desktop/TerminalSurface.tsx` | xterm rendering, terminal views, search, and resizing |

## High-level dependencies and data flows

The durable component relationships are defined in
[ARCHITECTURE_STATE.md](ARCHITECTURE_STATE.md). At an operational level:

```text
CLI or Electron PTY
  -> main.py command dispatch
  -> mariana services
  -> SQLite and platform data directory
  -> source adapters and managed external tools
  -> FFmpeg PCM playback
  -> sounddevice and optional Icecast broadcast
```

Primary media flow:

```text
MediaRef -> resolver -> probe -> FFmpeg decoder -> normalization/crossfade
         -> broadcast tap -> local controls/sleep gain -> sounddevice
```

Primary library flow:

```text
lib.lib -> discovery -> changed-file comparison -> probe/tags
        -> fingerprint/loudness/features -> optional enrichment -> SQLite
```

## Persistent storage and configuration

`mariana/paths.py` resolves runtime resources and state. Electron passes
`MARIANA_RESOURCE_DIR` and `MARIANA_DATA_DIR`; direct CLI launches use
`platformdirs`.

Main writable files under the platform data directory:

- `settings/settings.yml`
- `setup-state.json`
- `.setup.lock`
- `lib.lib`
- `data/mariana.db`
- `user/user_data.yml`
- `logs/`
- `temp/`
- `tools/`

Configuration behavior:

- `settings/settings.yml.default` is the additive YAML schema.
- Existing user values are preserved when missing defaults are merged.
- `settings/system.toml` contains packaged system defaults.
- `version.json` is the canonical application version.
- Environment variables select runtime paths and opt-in test/integration
  behavior.
- Credentials use the operating-system keyring or explicit headless environment
  references; plaintext fallback is prohibited.

## External integrations

| Integration | Use |
|---|---|
| FFmpeg/FFprobe/FFplay | Decode, probe, encode, and diagnostic/video fallback |
| yt-dlp | YouTube search, metadata, playback resolution, and downloads |
| feedparser | Podcast RSS/Atom parsing |
| Chromaprint/fpcalc | Sole acoustic fingerprint implementation |
| AcoustID | Fingerprint-to-recording lookup |
| MusicBrainz | Recording, artist, release, and tag enrichment |
| LRCLIB | Synchronized and plain lyric lookup |
| Radio Browser | Station search and import |
| SomaFM/Antenne Bayern | Curated radio seeds and live probes |
| ListenBrainz | Optional station/recommendation candidate source |
| Icecast | Radio reception and optional source broadcasting |
| OS keyring | Private radio and broadcast credentials |
| Send2Trash | Non-destructive indexed-media removal |

## Build and operational procedures

### Source environment

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
python main.py
```

### React development host

```powershell
npm ci
npm run dev
```

### Windows unpacked package

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
python -m PyInstaller --clean --noconfirm `
  --distpath dist-backend/win-x64 mariana-cli.spec
npm run rebuild:native
npm run pack
.\release\win-unpacked\Mariana.exe
```

The Python backend must be rebuilt before Electron packaging. Packaging only
the renderer can silently reuse an obsolete `mariana-cli` binary.

### Deterministic verification

```powershell
python tools/check_version.py
python tools/verify_repository.py
python tools/verify_text_integrity.py
python tools/verify_docs.py
python -m compileall -q main.py mariana beta lyrics_provider recommendation_engine tools
python -m ruff check .
pyright
python -m pytest -q --cov --cov-branch --cov-report=json:coverage.json --cov-fail-under=90
python tools/coverage_gate.py coverage.json --minimum 95 --repository-minimum 90
python -m pip check
python -m pip_audit -r requirements.txt
npm audit --audit-level=high
npm run lint
npm test
npm run build
npm run rebuild:native
npm run test:e2e:dev
```

### Packaged acceptance

```powershell
$env:MARIANA_PACKAGED_EXE = "$PWD\release\win-unpacked\Mariana.exe"
$env:MARIANA_TEST_FFMPEG_BIN = "C:\path\to\ffmpeg\bin"
npm run test:e2e:packaged
```

### Workspace hygiene

```powershell
python tools/clean_workspace.py
python tools/clean_workspace.py --apply
```

Default cleanup preserves `.venv`, `node_modules`, managed tools, and the
current `release/win-unpacked` application.

## CI and release workflow

- `.github/workflows/ci.yml` runs on pushes and pull requests across Windows,
  Ubuntu, and macOS with Python 3.12 and Node.js 24.
- `.github/workflows/reliability.yml` runs scheduled mutation and public-live
  gates.
- `.github/workflows/toolchain.yml` builds and attests pinned native media tools
  after explicit `PUBLISH-TOOLS` authorization.
- `.github/workflows/release.yml` is a manual signed release transaction. It
  requires an existing stable `vX.Y.Z` tag and explicit `PUBLISH` confirmation.
- Release preflight fails closed when platform signing credentials, a populated
  tool manifest, or required artifacts are absent.
- The updater consumes signed stable GitHub Releases only. Local packages and
  ordinary branch pushes are not update releases.

## Testing strategy

- Unit and state-machine tests cover deterministic behavior and invariants.
- Network and hardware are mocked in the normal suite.
- Fault-injection tests cover subprocess failure, broken I/O, SQLite rollback,
  partial state, cancellation, and shutdown races.
- Real-process tests generate media fixtures and exercise installed FFmpeg,
  FFprobe, FFplay, and fpcalc.
- Live tests are explicit opt-in and classify external unavailability separately
  from Mariana defects.
- Package tests use isolated writable data directories and verify first-run
  recovery and same-PTY behavior.
- Repository branch coverage must be at least 90%; every critical module listed
  by `tools/coverage_gate.py` must independently reach 95%.
- The scheduled mutation gate requires at least 80%.
- Short CI soaks do not replace the required eight-hour acceptance soak.

## Release history summary

| Version | Architectural/product milestone |
|---|---|
| `0.6.2` | Current stable legacy release |
| `0.7.0-dev.2` | FFmpeg PCM platform, SQLite services, React/Electron host, first-run state, ReplayGain, Icecast, and testing-snapshot compatibility |
| `0.7.0-dev.3` | Rich prompt/help/themes, managed tools, media details/rename, same-session downloads, output-device following, autoplay, and multi-view terminal |
| `0.7.0-dev.4` | Hierarchical queues, playlists, albums, persistent album downloads, track-seeded stations, YouTube chapters, and expanded release verification |

`CHANGELOG.md` is the authoritative concise change history. Dated evidence under
`docs/verification/` records what was actually executed for each development
snapshot.
