# Testing Mariana

Install the locked development environment first:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
npm ci
```

## Deterministic gate

```powershell
python tools/check_version.py
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

Targeted UX and media-management checks can be run with:

```powershell
python -m pytest -q tests/test_media_details.py tests/test_tool_setup.py tests/test_lyrics_ui.py
npm test -- --run desktop/App.test.tsx desktop/TerminalSurface.test.tsx
```

These cover safe metadata-derived renames, stable library identity, tool-bundle
validation/progress, the non-recursive lyrics-window path, multiple terminal
views, directional output search, and CLI/UI theme synchronization.

On Windows, rebuilding `node-pty` requires the Visual Studio C++ build tools.
The development and packaged PTY tests may use a verified prebuilt binary, but
a native release build must still pass `npm run rebuild:native` on its CI
runner before signing.

Repository branch coverage must be at least 90%. Each module listed by
`tools/coverage_gate.py` must independently reach 95%; an aggregate package
percentage cannot hide a weak module.

## Mutation, live, and packaged gates

Mutmut runs on Linux because it does not support native Windows. The scheduled
reliability workflow exports `mutmut-cicd-stats.json`; the conservative killed
mutants divided by all non-skipped mutants must be at least 80%.

Public live probes run only with `MARIANA_LIVE_TESTS=1`. Credentialed AcoustID,
private-radio, remote-Icecast, and authenticated YouTube tests require explicit
test credentials and must never print them. Packaged Electron tests require
`MARIANA_PACKAGED_EXE` pointing at an unpacked signed candidate.

Fresh-data first-run package tests additionally accept
`MARIANA_TEST_FFMPEG_BIN` so an isolated data directory can use a verified
external FFmpeg/FFprobe/FFplay directory before managed release tools are
published. The real-process pytest and short soak scenarios use the same
variable when FFmpeg is not already on `PATH`:

```powershell
$env:MARIANA_PACKAGED_EXE = "$PWD\release\win-unpacked\Mariana.exe"
$env:MARIANA_TEST_FFMPEG_BIN = "C:\path\to\ffmpeg\bin"
npm run test:e2e:packaged
```

The live packaged YouTube-download case is opt-in. Use a media URL that the
test account is authorized to access, and explicitly name a browser profile
only when credentialed verification is intended:

```powershell
$env:MARIANA_LIVE_DOWNLOAD_URL = "https://www.youtube.com/watch?v=..."
$env:MARIANA_LIVE_BROWSER_PROFILE = "edge:Default"
npm run test:e2e:packaged
```

Omit `MARIANA_LIVE_BROWSER_PROFILE` for the credential-free probe. A YouTube
bot/login challenge is an external authentication requirement and must fail
with actionable terminal guidance rather than be reported as a successful
download. Set `MARIANA_LIVE_EXPECT_AUTH_CHALLENGE=1` only when deliberately
verifying that negative path; the test then requires the precise authentication
guidance and still rejects certificate or generic failures.

The packaged suite proves setup completes once, the same data directory does
not show the wizard on relaunch, interrupted setup resumes, and corrupt state
offers repair.

The media-tool setup suite additionally proves discovery-before-download,
default auto-selection, exact-executable/directory normalization, version
validation, trusted-host allowlisting, SHA-256 rejection, archive traversal
rejection, atomic activation, and non-interactive no-prompt behavior. A native
Windows acceptance run should execute:

```powershell
python -m mariana.tool_setup
python main.py
# In Mariana:
tools status
replaygain verify
replaygain scan changed
replaygain status
```

For a non-destructive rsgain check, hash and record the modification time of a
test media file, run a scan-only (`-s s`) analysis, and prove both values are
unchanged. Do not use tag-writing mode in Mariana acceptance tests.

## Native and endurance acceptance

Record operating system, architecture, audio device, tool versions, result,
and defect/external-outage classification for speaker output, device changes,
sleep/resume, rapid controls, network loss, library changes, radio failover,
lyrics, download, recommendations, ReplayGain, and Icecast broadcasting.

The release soak is:

```powershell
python -m tools.soak_test --seconds 28800 --broadcast --library-files 10000 `
  --ffmpeg-bin "C:\path\to\ffmpeg\bin"
```

It passes only with no orphan processes or running leases, intact SQLite state,
bounded queues/buffers, less than 64 MiB unexplained growth, and no accumulating
broadcast latency. Short CI soaks do not satisfy this gate.
