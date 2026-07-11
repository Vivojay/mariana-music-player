# Mariana Player test strategy

The normal suite is deterministic: network, audio hardware, VLC, Shazam, RSS, and
yt-dlp boundaries are mocked while their response normalization and failure
contracts are exercised. It runs on Windows and enforces branch-aware coverage.

## Normal gate

```powershell
python -m pytest -q --cov --cov-report=term-missing --cov-fail-under=55
```

The suite covers:

- additive configuration migration and invalid configuration roots;
- URL parsing with property-generated YouTube IDs;
- yt-dlp search, metadata, streaming, downloader options, and failures;
- fresh, cached, stale, corrupt, custom, and invalid podcast feeds;
- Shazam response normalization, related tracks, lyrics cache/HTML/CSS, and GUI spawning;
- safe first-boot archive download and path-traversal rejection;
- VLC media construction, radio aliases, state changes, timeouts, and missing-runtime behavior;
- local/online/radio playback state, seeking, volume, pause/fade/stop, recents, and representative command families;
- metadata extraction, logging formats, runtime checks, first-boot input validation, and retired RPAN behavior.

## Live service probes

```powershell
$env:MARIANA_LIVE_TESTS = "1"
python -m pytest -q -m live
```

These validate the installed FFmpeg/FFprobe/JavaScript runtime and make real
YouTube, podcast, and Shazam requests. They are opt-in because public services
can fail or rate-limit independently of the application.

## Manual Windows acceptance

Automated tests cannot prove speaker output or observe interactive GUI quality.
Before a release, verify local MP3 playback, pause/resume, seek, volume/mute,
queueing, VLC radio playback, one YouTube download, lyrics display, device-loss
messages, and clean exit on a Windows 64-bit machine with VLC 3.x.
