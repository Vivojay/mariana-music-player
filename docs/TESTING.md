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
python tools/coverage_gate.py coverage.json --minimum 95
python -m pip check
python -m pip_audit -r requirements.txt
npm audit --audit-level=high
npm run lint
npm test
npm run build
npm run rebuild:native
npm run test:e2e:dev
```

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
