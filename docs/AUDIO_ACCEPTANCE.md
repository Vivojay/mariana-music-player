# Audio feature acceptance

The replay-gain, karaoke and stem regression recheck passed 221 cases. The live rsgain test was skipped because the executable was unavailable. The stem pipeline included local FFmpeg decoding and mixing against prepared sources.

## Built-in effects and optional plug-ins

The built-in rack, tone generator and procedural foley require no third-party effect packages. Bitcrush is available as `fx set bitcrush 75` or `fx preset bit-sampler` on native and browser audio. Package ingestion accepts a local ZIP or a direct HTTPS vendor ZIP with an explicit SHA-256. Vendor plugins remain outside the base release. See [on-demand installation and the offline host](SOUND_DESIGN.md#optional-vst3-and-audio-unit-effects).

Native tests cover DSP limits, delay and stream reset, partition-independent bitcrush, a real FFmpeg tempo bounce, preservation of dry recording feeds, profile-specific package installation, checksum mismatch, rejected ZIP paths and alias routing. The plug-in helper's input duration and latency flush were tested with a controlled effect. A real third-party binary and physical device loopback still need acceptance on their own target systems.

## ReplayGain

The scanner runs rsgain in scan-only mode. A grouped result carries album loudness and peak. rsgain 3.7 can report a bare filename for each track. When two results have the same bare name, Mariana obtains each ambiguous track's gain independently and retains the album summary from the group.

The regression suite exercises real-format 3.7 output fixtures, duplicate names in different directories, ReplayGain and Opus tags, album identity, peak-safe gain, database persistence and scan-only arguments. The optional integration test uses live rsgain to scan two generated WAVs with distinct gains and identical names. It checks the album result, expected 6 dB difference and that neither file was modified. The integration test was skipped on the Linux build host because rsgain was unavailable.

From PowerShell in the checkout, point to the actual installed executable and run the test with the project's development dependencies present.

```powershell
$env:MARIANA_TEST_RSGAIN = 'D:\tools\rsgain.exe'
& .\.venv\Scripts\python.exe -m pytest -q tests/test_loudness.py
```

## Karaoke

The packaged Linux TUI opened the six-second practice duet, displayed both timed singer parts, accepted a transport toggle, returned to the player and reported the score state. Native and browser fixtures cover the recording hash, duration, minimum word confidence across both singers, stage navigation, timed lyrics evidence, part selection and practice invitations. Browser fixtures also cover vocal/backing alignment for audio that is already separated. Automatic sung-word timing and overlapping singer identification need their own multilingual ground-truth acceptance corpus. The bundled duet uses a known, sample-scheduled score.

## Stem preparation and monitoring

The local Demucs worker remains optional. The tests exercised real FFmpeg stem decoding and PCM summation, managed child cancellation, immutable source snapshots, cache reuse, source and cache corruption rejection, cleanup, safe export and stable transport when switching mixes. Most preparation fixtures provide controlled separated tracks to test the library and playback pipeline. Running Demucs itself and evaluating the separation from an unseen song require an installed worker runtime and model weights. No live LALAL.AI service was exercised. See [local stem monitoring](STEM_MONITORING.md).

To repeat the local checks with the project's development dependencies installed:

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests/test_effect_studio.py tests/test_karaoke.py tests/test_stems.py tests/test_stem_process.py tests/test_stem_monitor.py tests/test_stem_ownership.py tests/test_stem_export.py tests/test_stem_lifecycle.py
node --test tests/web_effect_studio.test.mjs tests/web_karaoke.test.mjs
```
