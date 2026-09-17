# Local session recipes

## Commands in the application

```text
session record evening
session status
session stop
session list
session inspect evening
session play evening
session seek 01:30
session stop
```

Recording is explicit and off until requested. Files live in the existing user
data directory under `sessions/<name>.jsonl`; names contain only letters, digits,
underscores and hyphens (at most 64 characters). Existing names are not overwritten.
`session stop` seals the recording, or stops replay if replay is active. Check
`session status` for errors or incomplete capture before treating it as reusable.
`session inspect` never plays media. `session play` confirms replacement of the
current queue/playback; `--yes` is the established explicit confirmation bypass.
`session seek` takes a recipe-relative time, not the current song's source time.
It only seeks an active replay. A completed or stopped recipe must be started
again with `session play`, including its normal queue-replacement confirmation.

The controller supplies immutable committed program events for recipe capture,
including both sources of a transition. The existing play/pause/seek analytics
multicast remains independent; the recipe service ignores that older projection
while its typed version-three capture is attached, so it does not capture twice. Its
active-media clear notification records stops; those notifications are labelled
automatic because that callback does not reliably distinguish user, shutdown,
and source-replacement stops. Successful command/control completion and ordinary
queue completion capture committed queue/settings state, not command text.
Identical queue/settings notifications are deduplicated. Automatic queue advance
and prefetch are suppressed during replay. Competing CLI and typed desktop
mutations are refused until `session stop`; read-only lyrics/status remains usable.

Current application acceptance is deliberately bounded: flat or nested queues, finite local
files verified by SHA-256 or freshly verified public YouTube identities, no
preferred-region overrides, supported two-source equal-power crossfades,
and no active loop/stem/station/Focus/sleep session when starting. Introducing
unsupported regions, source seeking or gain changes during an overlap, loop or stem semantics during recording
marks it incomplete. Local output volume and EQ are not restored. ReplayGain and
queue settings are restored through existing APIs and remain at their final
effective values after replay. Broader provider support and physical-device timing
acceptance remain separate work.

`mariana/session_recipes.py` implements strict version-one/two/three validation, a bounded recorder,
read-only inspector, checkpoint/state folder, and dependency-injected replay
engine. `mariana/recipe_playback.py` adapts supported replay events to the existing
playback controller. Neither module creates an independent player or accepts commands.
Application entry points and event-hook coverage have focused regression tests;
the existence of these modules does not imply every listening action is captured.

`mariana/session_service.py` supplies the application-facing lazy start/status/
stop/inspect/replay service. Its bounded serial worker receives compact committed
IDs, performs catalog lookup/content hashing away from capture callbacks, and
drives the same-controller replay adapter. Runtime reconfiguration is supported
by passing `playback=lambda: current_controller`. It deduplicates identical queue
notifications but does not infer changes from renderer/UI polling. Initial
positive crossfade settings use the controller's version-three capture; unsupported later actions explicitly
make recording incomplete. Replay accepts verified finite, seekable local files
and public YouTube identities already known to the application's catalog/current
media lookup. Other online references remain inspectable/recordable but replay
requires their own fresh-provider verification adapter, not a cached catalog guess.

For the current controller, `start` atomically attaches its typed capture sink
after queuing one authoritative initial state. This includes actual offsets and
effective gains when already inside a crossfade. Older injected hosts can still
multicast their committed playback-event sink to `service.capture_playback_event(**event)`
for version-two, non-overlapping capture. The root explicitly calls `capture_stop()`,
`capture_queue_snapshot(queue.export_snapshot())`, and
`capture_settings(kind, payload)` at their respective successful boundaries.
`mark_unsupported()` covers unrepresented changes such as region/stem
semantics. `start(name, initial_media_id=..., initial_playback_session_id=...,
position_ms=..., playing=..., queue_snapshot=queue.export_snapshot(), settings=...)`
captures one initial snapshot; initial catalog lookup/hash work is asynchronous,
and subsequent committed events retain their capture-time timestamps while it
runs. `status()` exposes preparation, recording, incomplete/failed, and replay
state. Recipe names are bounded opaque local names, not paths supplied by events.

The service's injected `restore_queue(state, resolved)` receives a validated state
with `queue` as the realized list of recipe media keys, occurrence-based
`current_index`, `shuffle_seed`, and a validated `queue_tree`; `resolved` maps those
keys to backend media objects. `mariana/recipe_queue.py::restore_snapshot` builds
the sanitized local input for the existing transactional `queue.restore_snapshot`.
The legacy service `queue_ids`/`capture_queue` inputs remain available for hosts
that intentionally record flat queues; the application uses committed snapshots.
`configure_queue(settings)` receives exactly `repeat`, `consume`, and `autofill`.
`lookup_media(stable_id)` returns that exact catalog/media object or `None`.
`set_replay_active(bool)` must guard competing user controls as well as independent
completion, prefetch, and queue-advance callbacks, including resolution time.
`seek_replay(at_ms)` restores an effective state on that same serial worker.
Completion, failure, and explicit replay stop halt the backend and release the
guard. Pause/resume/settings events do not re-hash the queue; new media starts and
media seeks reverify only the source they open. Queue changes verify their queued
references; initial start and recipe seek verify the whole effective state.

The service also polls the existing backend's buffering state on its nominal
50 ms worker cadence, independently of desktop visibility or CLI status reads.
This polling controls clock suspension only; it never infers committed actions.
Explicit `set_buffering` hooks are more precise. Detection is quantized to the
poll cadence and can be later while that worker is busy hashing or preparing a
source; this is not sample-exact transition timing. Repeated unchanged buffering
notifications are deduplicated.

## Fresh online verification

`mariana/recipe_sources.py` verifies the saved public YouTube video ID against the
existing resolver's freshly returned provider ID, finite/seekable capabilities,
canonical identity and duration. A missing saved duration, missing provider facts,
different recording, live source, or expired transport stops replay. The duration
tolerance is the same one-second floor/two-second ceiling used by the recipe
validator; stale catalog duration never substitutes for fresh provider evidence.
No title matching, first-result selection or alternate recording is attempted.

The verified transient `ResolvedMedia` is handed directly to the existing
controller for that play or seek. It is not resolved a second time between
verification and decoder creation. Each new recipe media start, media seek or
recipe-position restore performs fresh verification; pause/resume does not
needlessly contact the provider. Private playback URLs and headers stay only in
the worker/controller handoff. Queue restoration receives ordinary `MediaRef`
objects with public canonical links; recipe files retain only allowlisted IDs.

The backend-only resolved-input handoff rejects expired responses, mismatched
selected-media objects, and attempts to apply a different identity during seek.
It is not an IPC capability: renderers still submit typed media IDs/positions,
never resolver results or transport URLs. Ordinary CLI seeking is unchanged.

Provider calls run on the session worker with the existing resolver's network
timeouts. Cancellation and the service deadline are checked before and after
resolution, preventing late responses from starting playback. A blocked provider
call is not forcibly killed; bounded shutdown may report an unfinished worker.
Generic URLs and podcasts still require an appropriate durable, freshly
resolvable provider adapter. Equal ID/duration does not prove byte-identical
online content; replay reproduces verified listening intent, not sample identity.

## What is recorded

A recipe is structured committed state, not terminal history, rendered audio,
analytics, UI polling, or a macro. Each event has a contiguous sequence number,
relative integer millisecond time, enclosing session identity, manual/automatic/
recovery reason, allowlisted kind, and exact-schema payload.

The supported event vocabulary is `media_start`, `pause`, `resume`, `seek`,
`stop`, `queue_set`, `shuffle`, `queue_settings`, `gain_settings`,
`crossfade_settings`, and `transition`. Queue events store the realized media
order and occurrence-based current index; duplicate occurrences are retained.
Both `queue_set` and `shuffle` carry the current seed and complete hierarchy.
Shuffle records an explicit seed, but replay restores the committed order rather
than depending on a random-generator or recommendation implementation. Adding an
item after shuffle remains a queue change, not a shuffle that falsely claims to
preserve membership.

## Portable queue hierarchy

Every version-two or version-three initial state, queue event, and checkpoint has a mandatory
versioned `queue_tree`. It records manual/album/playlist groups, their parent and
mixed-sibling positions, atomic boundaries, priorities, existing strategy labels
and seeds, plus each occurrence's parent, position, priority and failure policy.
Repeat, consume and autofill remain ordinary queue settings. The depth-first
leaf order must exactly match the recorded occurrence list, not merely the same
set of media IDs. Thus a cursor on the second copy of a track cannot silently
move to its first copy. Restoring a tree never re-runs shuffle or smart ordering.

Group IDs are opaque `g1`, `g2`, and so on, stable within one recording but not
installation identifiers. User-defined group names, source bindings, metadata,
timestamps, paths and URLs are omitted. Replay uses generated labels such as
`Album group 1`; original cosmetic names and album-refresh bindings are not
recovered. Media references still undergo the independent exact-source preflight.
Restoration rejects unavailable or blocked sources before committing any queue
change. Future queue edits use the preserved policies; the recorded realized
order is the authority for replay itself.

Validation rejects extra fields, unknown kinds/strategies, malformed policies,
cycles, dangling/orphaned groups, colliding or missing mixed-sibling slots,
inconsistent depth-first order and out-of-range cursors. Limits are 2,048 leaves,
512 groups, eight nested group levels, and 2,048 unique group identities across
one recording. Integer seeds and priorities must fit a signed 64-bit value. The
existing journal and total-byte limits apply in addition; a configuration hitting
several individual maxima may reach the byte limit sooner. Exceeding a limit
makes capture incomplete rather than flattening or silently discarding groups.

Version-one exports and journals are first validated against their exact original
schema, events, checkpoints and seal. Only then are they upgraded in memory to
version two with an explicit flat tree. Source files are never rewritten. New
fields cannot be smuggled into legacy records, and a version-two file missing a
tree is rejected rather than treated as legacy. Hosts must advertise `queue_tree`
capability before accepting a recipe containing groups or non-default root/item
policies; flat legacy recipes remain compatible with flat-queue hosts.

Gain settings use the existing ReplayGain enabled/mode/preamp/clipping settings.
Version three additionally records the effective source program gain, including
after an incoming source is promoted. This gain is not reconstructed from changed
library loudness metadata during replay. Output device, local volume, credentials, publishing, deletion,
download, script text, arbitrary extensions, and unknown fields are prohibited.
They are not silently ignored. Secret-bearing resolver dictionaries, raw URLs,
titles, and local filenames are never serialized. References contain only an
allowlisted source, hash-form catalog identity, optional SHA-256 content hash,
expected duration, live flag, and an eligible public YouTube video ID. Other
online sources are catalog-only references, not portable playback URLs.

Local content hashing is an explicit preflight operation; do it on a background
worker, never in audio/control callbacks. A recipe without a local content hash
can be inspected and retained, but exact replay pauses with
`unverified_local_source`. A hash-form catalog ID alone cannot establish that a
file's content has not changed. Live references require a separate verified
finite archive; this version cannot substitute a present-day live stream.
Hashing checks cancellation/deadline between bounded 1 MiB reads and rejects
files whose identity/size/modification time changes during the read. The service
uses a ten-second budget per queued operation and cancellation on shutdown or
timed-out stop. A blocked operating-system read is not forcibly killed; service
shutdown still has a bounded join and reports failure instead of claiming success.

## Host integration

1. Explicit user opt-in constructs `SessionRecipeRecorder(path, ...)`. Its file
   is created exclusively, so an existing recipe is never overwritten. The
   application selects version three; the low-level recorder retains version two
   as its legacy default unless `version=3` is explicitly supplied.
2. Supply a sanitized media manifest, initial settings, and initial effective
   state. Register newly committed media through `register_media(key, ref)`.
3. Call `commit(kind, data, reason=...)` only after the authoritative backend
   operation has succeeded. Record actual media offsets, full committed queue
   changes, realized shuffle order/seed, gain changes, and transition state.
   Legacy play/pause/seek analytics cannot infer the other events.
4. Call `set_buffering(True/False)` at the real buffering boundaries. Buffering
   is removed from the logical clock; intentional user pauses remain in it.
5. Call `checkpoint()` periodically after committed hooks have run. Overflow,
   invalid committed events, and persistence limits make the session incomplete.
6. `close(timeout=2)` drains within a bounded wait. Inspect its result/status;
   a false result is not successful recording completion.

The recorder uses one daemon writer and a bounded nonblocking queue (256 records
by default). The format limits are 8 MiB total, 256 KiB per journal record, 20,000
events, 512 references, 2,048 queue occurrences, 512 checkpoints, and seven days
of relative session time. It stops accepting events after data loss rather than
pretending the remaining stream is faithful. A journal without a valid seal is
incomplete and cannot replay. A partially written JSON record is rejected, not
guessed. A validated normal JSON export is also accepted by `load_recipe`.

`inspect_recipe(load_recipe(path))` is read-only and reports counts, event kinds,
privacy restrictions, required host capabilities, non-replayable live entries,
unverified local entries, and catalog-only references. It makes no availability
claim and performs no network requests. The replay resolver is a separate,
explicit availability/integrity boundary.

## Replay authority and timing

`RecipeReplayEngine(recipe, host)` exposes `start(at_ms=0)`, `seek(at_ms)`,
`tick(max_events=128)`, `set_buffering(bool)`, and `stop()`. The application
dispatches it on its existing serial control worker. It is not a standalone
application or a background scheduler. Start and seek validate the entire recipe
and restore one effective state; they do not execute skipped historical actions.
Checkpoints are recomputed against event history during validation, so a forged
checkpoint cannot silently inject unrelated state.

The host has explicit `resolve`, `restore`, `apply`, `halt`, and `is_buffering`
methods and declares its supported capabilities. Resolution must use existing
source policy and freshly establish the exact reference/content. The engine
rejects missing identities, mismatched hashes/provider identities, and duration
changes larger than 1% with a floor of one second and a ceiling of two seconds.
It does not select a similar title or skip an unavailable item automatically.
Backend failures use fixed error codes and halt the player. There is no automatic
retry or fallback source. A user can repair a missing source and explicitly retry.

`ExistingPlaybackRecipeHost` requires callbacks for exact resolution, queue
restoration, queue settings, and an application-level replay-active guard. That
guard must disable independent completion/auto-advance/prefetch paths while the
recipe owns the timeline. Queue restoration is deliberately supplied by the
composition root: the adapter must not mutate an unrelated queue or run command
text. The adapter delegates play, pause, resume, seek, ReplayGain, crossfade
settings, and stop to the existing controller's public typed methods.

Ticks preserve event order, including equal-timestamp order. Time spent in
synchronous resolution/preparation is excluded from the replay clock. Explicit
buffering hooks provide the precise freeze boundary; polling `is_buffering`
alone detects the transition only at the next tick. Tick cadence determines
scheduling tolerance. Recipe completion halts playback instead of allowing
unrecorded queue advancement. User-paused intervals preserve position while the
recipe clock advances toward the later recorded resume.

Automatic source recovery is suspended while the recipe owns playback, including
late provider responses from an earlier recovery request. Output-device recovery
remains independent. A decoder failure pauses recipe execution with
`playback_failed` and halts the backend instead of advancing to a later event or
restarting an unrelated previously requested track. Explicit retry still uses
fresh identity/duration verification.

## Exact limits, not feature claims

The state model can preserve both crossfade offsets, per-source program gains,
duration, and equal-power-envelope elapsed time. Position folding advances both
sources while playing and freezes both during pauses. Once the known envelope
duration elapses, the incoming source becomes current. Actual buffering must
have been excluded by host hooks for that calculation to be meaningful.

The current controller exposes backend-only preparation, block-boundary commit,
and discard operations. `ExistingPlaybackRecipeHost` advertises overlap and
frozen-program-gain support only for controllers implementing that boundary.
Version-three recipes can restore a complete pair; version-two overlapping
recipes still fail with `unsupported_overlap` because their post-promotion gain
is absent. Missing gains are not invented during migration. Legacy finite,
non-overlapping replay remains supported.

Restoring an already-paused version-three checkpoint installs paused intent with
the complete prepared mix. Legacy single-source replay uses
`play(start_paused=True)`. Paused state is established before a new or
existing output callback can read the replacement decoder, avoiding an audible
play-then-pause interval. Event-timing replay is not sample-identical
audio; decoder/output latency, changed provider content with unchanged identity,
missing content fingerprints on online media, and settings-derived ReplayGain
metadata limit that claim. No such claim is made by these modules.

Synthetic tests cover schema/authority rejection, canonical privacy projection,
event order, committed shuffle order, nested restoration through the actual queue
database, duplicate-occurrence cursors, strict legacy migration, checkpoint validation, pause/seek folding,
overlap-state folding, legacy overlap refusal, source failures, buffering/rebasing, async
recording, overflow, exclusive creation, and bounded close. Native media and
end-to-end application-hook acceptance remain separate gates.

`tests/test_session_real_audio.py` adds bounded installed-FFmpeg acceptance: it
generates a tone FLAC, decodes it through the real `PlaybackController`, records
committed play/pause/seek/resume offsets, seals and reloads the recipe, and
restores a paused checkpoint through that same controller. A deterministic
output-stream substitute verifies zero PCM and unchanged position while paused,
then nonzero decoded PCM after the recorded resume. The test also verifies
retired decoder processes and stream cleanup. This is real decoding/PCM
acceptance, not physical-speaker, audible-device, or full CLI-hook acceptance.

## Implemented atomic two-source replay

The version-three path uses the same controller, FFmpeg decoder sessions, output
stream, source verification, and program bus as ordinary playback. Its typed
runtime is in `mariana/recipe_mix.py`; it is not a general mixing-script API.

The current automatic crossfade derives its fraction from the outgoing source's
remaining duration and clamps the window against its decoder start offset.
Reopening a decoder partway through a fade therefore cannot recover the original
envelope by setting `crossfade_seconds` and calling `prefetch`. The callback also
reads the two buffers independently; one starved input can let the other advance.
Assigning `_active` and `_next` under the existing state lock is insufficient:
the callback releases that lock before consuming its captured decoder references.

### Controller boundary

The controller accepts narrowly typed backend-only restore inputs, not renderer payloads or
recipe dictionaries inside the decoder. A source input contains the verified
`MediaRef`/`ResolvedMedia` pair, source offset, and effective program gain. A mix
input contains one or two such sources, explicit equal-power duration/elapsed
frames, and paused intent. These objects never expose transport URLs publicly.
The lifecycle is prepare, commit, and discard:

- Prepare at most one replacement mix on the existing serial session worker.
  Resolve/hash, validate finite seekability and remaining source lengths, design
  no new effects, construct both decoder sessions, and prebuffer them outside
  the controller lock and audio callback. Reuse existing source verification,
  FFmpeg decoding, cancellation, and a ten-second default preparation deadline. Failure of either
  input discards both preparations without publishing a new active identity.
- Bind the prepared result to its controller and playback-generation token.
  It is single-use; stop, close, replacement, or superseding restore invalidates
  it. Recheck cancellation, source ownership, and generation before commit.
  Do not reuse the live-metadata generation counter as a general playback epoch.
- Submit one bounded pending commit for installation at an audio-block boundary.
  The callback swaps the complete pair, offsets, envelope, paused intent, and
  runtime playback-session identity together. A paused restore must emit no new
  source PCM before or after acknowledgement. A stalled output cannot imply a
  successful commit: acknowledgement has a two-second default deadline and cancellation.
- Publish generation-checked active-media/commit notifications outside the
  callback. Retire old decoders, wait for child processes, and perform all storage
  and queue work on workers. Reject stale preparations and stale retirement/
  completion notifications without touching the newly committed mix. Decoder
  retirement uses the controller worker; producer locks and the audio-block
  serialization lock are acquired nonblocking by the recipe callback.

The callback owns explicit overlap progress in emitted frames, independently of
the media's total duration or the time required to prepare decoders. Both inputs
must consume the same number of overlap frames or neither may advance. On
starvation, publish silence and backend buffering state; freeze both source
offsets and the envelope. The service freezes its logical clock when that state
is observed, with the polling tolerance documented above. Premature EOF is a source failure, not permission to substitute
or promote. Split a block at the exact envelope endpoint, promote once, and use
the incoming source for any remaining frames. Pause freezes both offsets and
progress. Ordinary non-recipe automatic crossfade behavior remains a separate,
regression-protected policy.

For progress `p` in `[0, 1]`, the gains remain
`10 ** (outgoing_db / 20) * cos(pi * p / 2)` and
`10 ** (incoming_db / 20) * sin(pi * p / 2)`. Recorded dB values are per-source
program gains, not already-envelope-scaled samples. Apply this mix before the
existing program/broadcast tap; local EQ, volume/mute, and sleep gain retain their
existing independent placement. The recipe must not recompute frozen source
gains from newly changed loudness metadata or alter local volume.

Queue ownership stays in the existing composition root. During replay, ordinary
prefetch, completion-driven queue advancement, consume, and autofill remain
suppressed. A mix handoff changes the authoritative audible media once; recorded
queue events restore their exact occurrence cursor/order separately. Duplicate
media IDs must not be mistaken for the same decoder or queue occurrence. Runtime
playback-session IDs are freshly generated, not restored from imported content.
Committed transition capture supplies both source offsets, gains, and elapsed
frames; the existing primary-only play/pause/seek events do not reconstruct it.
The initial state is queued before the typed sink is installed under the same
controller lock. Transition capture occurs once when the ordinary mixer actually
consumes the pair. Pause/resume include the effective pair state, and promotion
records the incoming source's actual position and frozen gain. Capture metadata
or sink errors never interrupt playback; unrepresentable events make recording
incomplete instead of silently producing a faithful-looking recipe.
The typed capture entry uses a nonblocking service-lock attempt and bounded
queue insertion. Queue saturation or lock contention sets a sticky loss flag;
the worker and final seal mark recording incomplete with `overflow`. The audio
callback never acquires the recorder/writer lock to report loss.

### Versioned format implications

Version two retains frozen program gains only inside `overlap`, so a checkpoint
after the fade cannot recover the incoming gain independently of current
ReplayGain metadata. Version three carries `program_gain_db` in initial state,
checkpoints, media starts and gain-setting events. Promotion retains the incoming
gain. Validation recomputes this state and rejects inconsistent checkpoints;
strict schemas reject forged fields or unrepresented operations. Version-three
transition/pause/resume/seek events also carry current source identity and actual
overlap state. Legacy input is validated in its original schema and never
rewritten; no missing legacy gain is invented. Source-seek and gain-setting changes
during an overlap remain rejected until their full effective two-source semantics are
explicitly represented. Preferred regions, live sources, stems, and arbitrary
mixing remain outside this milestone.

### Verification and remaining acceptance

`tests/test_recipe_mix.py` includes focused cases using two
distinguishable stereo tones, installed FFmpeg decoders and the existing
deterministic output-stream substitute. These verify measured equal-power PCM
at the beginning, middle and late overlap; real source offsets; a transition
endpoint inside a block; paused restore and pause/resume; all-or-neither buffer
consumption; premature EOF; and frozen incoming gain after promotion despite
changed loudness metadata. The actual controller/service recording test seals
and reloads a version-three transition/pause/resume/promotion journal without
duplicate analytics captures.

Unequal partial reads during ordinary crossfade recording explicitly make capture
incomplete, including starvation after the first transition block. This protects
capture fidelity without changing ordinary playback's existing buffer policy.

Additional cases cover cancellation, superseded/foreign/single-use preparations,
expired or wrong-identity resolutions, finite bounds, bad gains/timeouts,
preparation failure preserving current media, missing callback acknowledgement,
stop invalidation, muted local output with an unaffected broadcast/program tap,
independent volume/sleep gain, and output-interruption freezing. Resource cleanup
is exercised without opening a native output device. Existing queue tests retain
duplicate occurrences and exact cursor ownership, and playback/state-machine
regressions protect the non-recipe path.

Real PCM comparisons use 48 kHz generated inputs, source offsets representable by
FFmpeg's millisecond seek arguments, and a small numeric tolerance for float32
decoding/mixing. This does not measure physical-device latency or guarantee
sample-identical reproduction: ordinary recording uses the existing
block-based crossfade policy, replay uses an emitted-frame envelope, recipe times
are integer milliseconds, and the service tick is nominally 50 ms. Native audible
continuity, device timing and packaged acceptance remain outstanding.

Broader provider adapters, preferred regions, live replay without a retained
archive, stems in recipes, source seeks or gain changes inside overlaps, and
arbitrary mixing remain deliberately unsupported. The UI/control surface still
uses the existing session family and never accepts decoder URLs or recipe code.
