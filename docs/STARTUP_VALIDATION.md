# Startup preparation and native readiness validation

## Follow-up: normal tool checks and output handoff

The normal first-run/managed-tool migration path validates five installed tools;
the native test mode bypasses that migration. Previously their read-only version
subprocesses ran serially. Discovery still uses the same configured, managed,
PATH and supported-location precedence, but version checks now run in at most
three temporary workers. Each subprocess retains its eight-second timeout, every
result is checked, and all started workers finish before results are returned.
No successful/failed validation is cached, no prerequisite is removed, and no
network request or download is added. If a worker cannot start, its undispatched
batch is validated on the caller; probes are not duplicated.

Five alternating measurements of the previous serial algorithm and current
`discover_media_tools` on the same Windows host included executable discovery and
real FFmpeg, FFprobe, FFplay, fpcalc and rsgain version subprocesses. All five tools
validated successfully in both arms:

| Validation implementation | Five samples, milliseconds | Median | Range |
| --- | --- | ---: | --- |
| Serial | 1662.12, 1678.31, 1815.81, 1972.97, 1840.38 | 1815.81 ms | 1662.12–1972.97 ms |
| Bounded workers | 758.98, 833.95, 839.28, 917.23, 1106.45 | 839.28 ms | 758.98–1106.45 ms |

The measured median reduction is 976.53 ms (53.8%) for this stage. It applies
when the tool-check stage actually runs, not every launch after migration was
acknowledged. This is not an end-to-end startup claim, a cold-disk benchmark,
or a guarantee for other installations.

The existing isolated native fixture also gained optional memory-only profiling:
`MARIANA_NATIVE_STARTUP_PROFILE=1` prints aggregate source-basename/function
timings to the test output, without a persisted profile, user paths, settings or
media references. Profiling changes timings and should be off for comparisons.
Native fresh/reused empty-profile samples observed backend readiness at
15,697/9,279 ms in one unprofiled run and 5,994/5,398 ms in a later profiled run;
that variability is not attributed to a code speedup. Mini first presentation
was 111/74 ms and reopening 98/65 ms in the unprofiled run. Physical output
validation, populated personal libraries, migration prompts and packaged startup
are not represented by those measurements.

Output-device investigation found that fuzzy display-name scoring could select
an old route (for example WH-1000XM4) while labelling it with a newly connected
endpoint identity (WH-1000XM5). The monitor would then consider the identities
equal and stop trying to migrate. Explicit routes now require complete matching
device tokens; generic Windows wrappers may differ. Ambiguous, truncated or
missing matches use the live system mapper. Without a confirmed route or mapper,
recovery waits rather than opening an unrelated output.

Each monitor now owns its cancellation token, so a native query that outlives a
bounded shutdown join cannot reopen output or publish an old failure after a new
monitor starts. Monitor thread-start failure does not reject already successful
playback. Output reopening also captures the controller request generation:
if Stop or another request wins while the native stream opens, that stale stream
is closed rather than published. The stopped-during-open regression reproduced
the previous incorrect publication before this guard was added.

Source retries also reserve the controller's request generation before provider
work begins. The supervisor maintains its own operation epoch across backoff,
deferred recovery and Stop; a new selection invalidates old work even when the
shared cancellation event is cleared for that selection. The controller checks
the same reservation at admission, closing the race after a caller-side check.
Stop detaches its own monitor before retiring playback and joins only that old
monitor afterwards. A newer request cannot be stopped by a retired join or stop
admission. Close is terminal for the supervisor. These ownership checks preserve
explicit playback while preventing obsolete recovery from replacing it.
Decoder failures carry their original backend request generation into deferred
recovery. Admission conditionally reserves a replacement only while that same
generation is still current, so even a late failure for the identical media
cannot restart a newer playback request. This token stays backend-only.

The integrated tool/output/supervisor/runtime, diagnostic compatibility and
playback-state-machine checks passed 188 tests with coverage. Output-device
selection has 100% statement/branch coverage in that suite; the supervisor has
100% statements and 98.8% branches.
Scoped Ruff, Pyright, both desktop TypeScript
checks and native-fixture lint passed. These are scoped results, not a full
repository gate. A first user-run physical acceptance pass after restarting the
normal application switched speakers to Bluetooth and back while playing, paused
and stopped. The user reported smooth behavior with nothing amiss. This is
user-reported route/lifecycle evidence, not exhaustive hardware certification.
Their likely launch preceded the final delayed-failure generation guard; that
last guard is covered by deterministic tests, not this physical pass.

## Native application and Mini-player: 2026-09-12

The native startup fixture now builds the current Electron host and renderer in
an isolated temporary application, launches the real Python backend, and measures
first contentful paint, terminal mounting, backend readiness, Home, command-prompt
readiness, first Mini presentation, and Mini reopening separately. Existing
application processes, library state, and runtime outputs are preserved. There
is one authoritative backend in each isolated test instance.

The host no longer sends full Mini snapshots for unrelated Home, lyrics, EQ,
or control-result events. Hidden/minimized Mini windows receive no unsolicited
snapshots. Showing/restoring the window sends the latest complete host projection
and updates its audio/video geometry. A video-status read refreshes its clock
without delaying window presentation or extrapolating an obsolete timestamp.
Failed Mini loads are destroyed so the next opening retries; an old failed load
cannot destroy a newer window. Hidden warmup remains enabled, and the existing
restricted preload and playback authority are unchanged.

Native tests exercised 15 real backend projection requests while Mini was hidden
and observed zero Mini update messages. Ten unrelated visible projection requests
also produced no extra snapshots. Changing the isolated artwork preference while
hidden was reflected by the next complete projection on show. Silent synthetic
video-to-audio switching while hidden restored the correct current identity,
video/audio window geometry, and resize policy. Native Windows DIP conversion
rounded one requested width by one pixel, which the geometry assertion permits.

Final observed native timings with calendar prewarm, using
Windows, Node 25.8.2, Python 3.12.10, Electron 43.1.0 and an empty library:

| Phase | Fresh profile | Reused profile |
| --- | ---: | ---: |
| First contentful paint | 2508 ms | 2992 ms |
| Terminal DOM mounted | 2729 ms | 2515 ms |
| Backend ready observed | 5843 ms | 6419 ms |
| Command prompt observed | 5951 ms | 6639 ms |
| Home visible | 6173 ms | 6471 ms |
| First warmed Mini presentation | 81 ms | 56 ms |
| Mini reopening | 55 ms | 68 ms |

These are observations, not enforced performance thresholds. DOM mounting is not
the same as paint, input readiness, or backend readiness. Independent polling can
observe Home before a readiness sample. Repeated local samples varied; Mini
presentation was generally 50–110 ms. No before/after startup speedup is attributed
to the snapshot-traffic change without a paired startup measurement.

The fixture bypasses first-boot prompts, managed-tool migration and initial audio
output validation through the existing test mode. Its optional silent-video case
does open the real audio pipeline. It does not measure Vite startup, development
preparation, a populated personal library, physical Bluetooth recovery, cold disk
caches, packaged startup, or user-perceived rendering under every display scale.
Thus these results do not certify the reported normal-launch delay as eliminated.

## Offline calendar preparation

A separate memory-only profile identified about 0.63 seconds of occasion-calendar
construction before the command prompt. Startup now begins that optional offline
work on one daemon worker after settings load, overlapping subsequent service
initialization. Disabled greetings or invisible output do not start it. The worker
never prints, performs location lookup, or changes user preferences. Country,
subdivision and year remain the existing cache keys; date-sensitive selection
still occurs in the normal banner. Expensive concurrent cache misses are serialized
so warmup and the banner cannot construct the same country calendar twice.

The normal banner is unchanged and is the fallback if warmup is not yet complete.
This preserves greetings rather than dropping one or printing it over typed input.
Consequently there is no promise that a very slow first calendar import can never
delay the prompt. Errors in optional warmup are nonfatal. The bounded daemon has
no persistence, application-state writes or shutdown join that can stall exit.

Six alternating fresh subprocesses compared the same source and empty isolated
profile, with prewarm disabled only in the baseline arm. Timings exclude profiling
overhead and include import through startup's command-prompt entry:

| Measurement | Baseline median | Prewarm median |
| --- | ---: | ---: |
| Import and service initialization | 3445.04 ms | 3305.08 ms |
| Command-prompt entry | 4037.78 ms | 3381.53 ms |
| Final banner work | 594.12 ms | 69.45 ms |

Prompt-entry samples were 4037.78, 4158.09 and 3772.08 ms for baseline; 3175.30,
3381.53 and 3757.95 ms for prewarm. The median improvement was 656.25 ms (16%).
This is an isolated local comparison, not a guarantee for other profiles/hardware.
The temporary profile and diagnostic outputs were removed after each run.

Run the native acceptance with the existing installed development dependencies:

```text
node node_modules/@playwright/test/cli.js test desktop/e2e/startup.spec.ts --reporter=line --output=<temporary-output-directory>
```

Set `MARIANA_NATIVE_VIDEO_ACCEPTANCE=1` to include the silent video/audio transition
case, with the installed FFmpeg on PATH. Traces, screenshots and video recording
are disabled. Build/profile directories are owned and removed by this fixture;
the caller should remove its Playwright output directory after inspection.

Focused regressions include `desktop/miniPlayerUpdates.test.ts`,
`desktop/windowLifecycle.test.ts`, `tests/test_occasion_warmup.py`,
`tests/test_occasions.py`, and `tests/test_occasion_banner_cli.py`.
The native suite passed all three cases (40.9 seconds), including the opt-in
silent media transition. The focused Python suites passed 33 tests and the
focused desktop lifecycle suites passed 28 tests. Scoped lint and both desktop
TypeScript checks passed; these counts are not a full-repository certification.

## Measured scope

The first step of `npm run dev` is `node tools/transpile-electron.mjs`.
Previously every invocation loaded TypeScript, transpiled all top-level Electron
TypeScript sources, and rewrote their outputs. This work happened before Vite
and Electron started, even when no source had changed.

Measurements on 2026-09-11 used the installed Windows Node.js v24.19.0 and
TypeScript 6.0.3. Each sample launches a fresh Node process. The benchmark copies
the actual desktop sources into a temporary repository and runs the real
preparation script there. No live Electron app is required, and the existing
repository `dist-electron` runtime is neither rewritten nor deleted by these
validation runs.

An initial measurement before implementation produced 27 outputs in five runs:
1245.25, 1262.48, 1100.64, 1201.22, and 1214.32 ms (median 1214.32 ms).

The final paired benchmark runs the preserved pre-cache algorithm and current
script against exactly the same copied source snapshot. It also checks that all
27 resulting JavaScript/CommonJS files are byte-for-byte identical.

| Preparation state | Samples | Median / single duration |
| --- | ---: | ---: |
| Previous implementation, repeated runs | 5 | 1415.19 ms |
| Current implementation, cache miss with existing outputs | 1 | 1337.95 ms |
| Current implementation, verified warm cache | 4 | 305.97 ms |

The paired warm median is approximately 78% lower, or 4.6 times faster. Each
warm run reused all 27 outputs and did not load the TypeScript compiler.

Paired baseline samples were 1328.65, 1385.55, 1415.19, 1446.87, and 1499.33 ms.
Optimized samples were 1337.95 ms for the cache miss, followed by 312.77, 299.16,
297.62, and 371.83 ms. These are local observations, not performance thresholds.
Host contention, antivirus checks, filesystem caching, and source changes affect
timings. A separate earlier cold-cache run took 1688.99 ms, so the cache does not
promise a cold-start speedup. Its benefit is avoiding repeated preparation.

This is not an end-to-end `npm run dev` or application-ready benchmark. It does
not measure Vite startup, Electron window creation, Python/backend startup,
library scans, media extraction, audio-device initialization, or playback.

## Cache correctness and ownership

The cache lives at `node_modules/.cache/mariana-electron/transpile.json`.
It is an optional local build cache, not an application setting or runtime asset.
No changes to package scripts or installed dependencies are needed.

- Source and output contents are SHA-256 checked; timestamps alone never prove
  freshness. A missing or modified output is regenerated.
- Compiler implementation, compiler package metadata, Node version, preparation
  script, root package metadata, and dependency lockfiles participate in cache
  invalidation.
- Configuration reads and configuration-resolution probes are recorded, including
  extended configs and package-based configs. Changed config contents invalidate
  reuse. Invalid configs and syntax errors fail preparation.
- Unchanged sources can be reused when another source changes. Newly added files
  are compiled; removed source outputs are removed only if a prior successful
  cache record owns them and their contents are still unchanged.
- Existing unowned runtime files are preserved. A modified stale output causes
  an explicit failure rather than being silently deleted or accepted.
- All changed sources must transpile successfully before new output is published.
  Individual output/cache files are replaced atomically. Failed syntax does not
  publish a successful cache or partially replace other changed-source outputs.
- `.ts` remains ES-module `.js`; `.cts` remains CommonJS `.cjs`. Declaration files
  and test files are not emitted. This is transpilation, not a replacement for the
  separate full type-checking command.
- Malformed or missing cache data is a cache miss. A read-only cache directory can
  disable cache persistence without preventing otherwise valid runtime generation.

The source-discovery scope remains the script's top-level `desktop` `.ts`/`.cts`
files. This change does not introduce bundling, recursive source discovery, or
type checking.

## Reproduce

```text
.venv\Scripts\python.exe -m pytest tests/test_electron_transpile.py -q -s -p no:cacheprovider --basetemp=temp/validation-transpile
.venv\Scripts\python.exe -m ruff check tests/test_electron_transpile.py --no-cache
node --check tools/transpile-electron.mjs
```

The focused suite passed all 17 tests. It covers warm reuse, preserved source
timestamps, source dependency changes, added/deleted files and changed module
extensions, output tampering/removal, stale-output ownership, failed compilation,
compiler/package/lockfile/script changes, extended configs, corrupt cache input,
and actual execution of both ES-module and CommonJS output. No timing threshold
is asserted; the benchmark prints measurements and validates reuse and output
equivalence. Ruff and Node's syntax check also passed.

Tests skip when Node.js or the repository's installed TypeScript package is
unavailable. On this Windows host, pytest's private temporary-directory ACLs
required running the validation outside the sandbox; no test fixture was changed
to bypass that limitation. Only generated validation directories are cleaned up.

For a manual diagnostic, setting `MARIANA_TRANSPILE_STATS=1` makes preparation
print a single JSON summary containing `compilerLoaded`, `transpiled`, `reused`,
and `removed`. Normal development preparation stays silent. The summary does
not create a log file or expose source paths.
