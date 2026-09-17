# Occasion, identification, and collection completion

## Implementation plan

1. Extend the existing banner with a pinned offline holiday calendar, country and
   subdivision selection, preserved estimated-date labels, and occasion palettes.
   Keep OS region as the default. Country detection is an explicit, confirmed
   network action that stores only the resulting country code. Calendar lookup
   and its failures must not prevent startup. Add date preview and status help.
2. Protect every playlist read/edit/write with its original ID and revision.
   Preserve previous tree revisions transactionally and expose history/restore.
   A conflict asks the user to retry; it must never silently replace newer edits.
3. Bound invocation-time identification by both PCM duration and elapsed time,
   discard cancelled buffers, reject work after shutdown, and suppress late
   results. Exercise queue/playlist persistence and album download selection
   without contacting providers or writing to the user's media library.

## Acceptance

Use deterministic calendar, concurrency, lifecycle, PCM, and persistence tests;
then run ordinary Python validation and repository checks. Credentialed song
recognition, provider downloads, physical audio output, and long real-world
sessions are separate acceptance evidence. Do not claim them from mocked tests.

## Available commands

### Identify the current instant

```text
media identify listen 20
media identify status
media identify stop
media identify cancel
```

The capture begins with newly played programme PCM, not a file's opening audio
or earlier decoder samples. Its normal duration is 20 seconds, configurable
from 8 to 120 seconds. `stop` submits only after eight captured seconds. Paused
or buffering time adds no PCM; the capture expires after the greater of 60
seconds or the chosen duration plus 30 seconds. Provider lookup is asynchronous
and uses the existing fingerprint/identification service. No result is stored
as the identity of the entire mix. Cancel/seek/source change and shutdown cannot
publish a stale result as a newer invocation's match.

Before starting a capture, Mariana validates the requested duration, current
playback eligibility, and whether another capture is already active. A missing
or broken fpcalc then offers the existing guided tool setup, requiring explicit
confirmation before installation or selection. Decline or unsuccessful setup
starts no capture. A working tool prompts for nothing. Playback continues during
setup; capture starts from the fresh source position afterward, not the position
before the dialog. A changed media/session/decoder requires an explicit retry.
Status/stop/cancel and recognition-provider failures never trigger tool setup.
This preflight does not provide recognition credentials or change the existing
explicit provider-lookup policy.

### Occasion banner

```text
banner help
banner country IN
banner subdivision MH
banner preview 2026-11-08
banner occasions off
banner country auto
banner country detect
```

The standard terminal logo gets an occasion palette plus a named greeting. No
replacement image assets are downloaded. Explicit settings survive upgrades;
automatic country means OS region, not silent geolocation. A subdivision can
add regional observances to national ones. The optional detection command asks
before contacting its provider and clears an old subdivision when country changes.
This is a pinned calendar snapshot, not an exhaustive calendar of every culture;
estimated dates and reference-calendar differences stay visible.

### Collections and albums

```text
queue tree
queue order shuffle --seed 42
playlist create "Evening"
playlist add "Evening" album 1
playlist order "Evening" shuffle --seed 42
playlist history "Evening"
playlist restore "Evening" 1
album search "artist album" --scope local
album tracks 1
album play 1 --order shuffle --seed 42
album play 1 --order custom --tracks 2,1
album queue 1 --at end
download-ya current --track
download-ya --album current
download-ya --album 1 --tracks 1-3
download-ya status
```

Album result numbers refer to the current catalog selection; search/show the
edition before using a numbered reference. Missing or ambiguous media is not
silently replaced. Local-only album search needs no network. Nested album and
playlist groups, sequential/shuffle/priority/artist-fair/smart/custom queue
strategies, track selection, and persisted download jobs reuse existing services.
An album group stays atomic during root ordering. Plain `download-ya` downloads
one current YouTube track; `--album` is required for expansion, and an explicit
album reference works without playing it. Local files are not downloaded again.

Playlist tree edits and renames now check the original ID/name/revision under
the same write transaction that records history. Stale edits are rejected.
Restoring a prior tree creates a new revision and preserves the displaced tree;
names/descriptions are not version-restored. This does not provide a remote
collaboration service or a backup of deleted data.

## Calendar sources

- [Holiday calendar API](https://holidays.readthedocs.io/en/main/api/) supports
  country/subdivision calendars, explicit language, and observed-date policy.
- [India calendar](https://holidays.readthedocs.io/en/latest/auto_gen_docs/india/)
  documents estimated Islamic dates and regional variation.
- [Country lookup API](https://ipapi.co/api/) provides a country-only response.
  An explicit lookup discloses the connection's public address to that provider;
  VPNs and network routing can affect the result.

## Local verification

- Focused identification, calendar, collection, album, download, and command
  regressions: 142 passed.
- Full ordinary Python suite: 2,199 passed, 24 optional/environment-dependent
  skips. Two final test additions were then included in a 67-test passing run:
  calendar packaging and 25 repeated database reopen/order/save cycles.
- Installed FFmpeg/Chromaprint decoder, fingerprint, capture, and short lifecycle
  probes: 18 passed after explicitly configuring the managed tool paths.
- Direct eight-second generated-PCM fingerprint: eight seconds recognized as
  input duration, nonempty fingerprint, 1.345 seconds processing on this machine.
- Desktop units: 277 passed. Desktop typecheck/lint, Python compilation,
  Ruff, repository hygiene, documentation links, text integrity, and whitespace
  checks passed. The protected document was excluded from text/link inspection.
- The initial full Python type check passed. During final verification,
  concurrent video-cache edits introduced three diagnostics in `video.py` and
  `video_cache.py` (optional media/descriptor access and a constructor argument).
  A later lint pass also found import ordering in `video.py`. The four changed
  backend modules for this task passed their scoped type check. Those unrelated
  video files were left untouched; the earlier full-suite results do not certify
  edits that arrived after they ran.

No recognition-service credential was configured, so live identification was
not exercised. No external album download, physical speaker/listening test,
eight-hour soak, new native window inspection, or packaged build was performed
for this completion. Existing native evidence is not a substitute for these
acceptance checks. Changes are local and uncommitted.
