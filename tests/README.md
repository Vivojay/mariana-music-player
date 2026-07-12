# Mariana test strategy

The deterministic suite mocks external network and audio-device boundaries but
uses real SQLite transactions. It covers configuration migration, canonical
media references, queue property tests and crash restoration, FFmpeg state and
PCM math, conservative AcoustID policy, MusicBrainz rate/caching behavior,
LRCLIB resolution, radio playlists/failover, recommendation ranking/models,
downloads, first boot, podcasts, YouTube, logging, source resolver conformance,
incremental library migrations/jobs/watchers, and the legacy CLI surface.

`test_real_media_pipeline.py` additionally invokes the installed tools to
generate, inspect, decode, seek, and clean up WAV, MP3, FLAC, OGG, AAC, and WebM
media and to produce a real Chromaprint fingerprint.

```powershell
python -m pytest -q --cov --cov-branch --cov-fail-under=80 --cov-report=term-missing
```

Opt-in network probes:

```powershell
$env:MARIANA_LIVE_TESTS = "1"
python -m pytest -q -m live
```

Public services can fail independently, so their live probes are not normal CI
gates. Manual Windows acceptance must still verify real speaker output, output
device loss/recovery, rapid pause/seek/next, radio failover, synchronized lyric
display, one custom download, recommendation explanations, and clean exit. An
eight-hour mixed local/URL/radio soak while library profiling is active is
required before changing the release version to 0.7.0.
