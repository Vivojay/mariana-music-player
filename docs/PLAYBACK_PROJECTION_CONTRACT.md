# Playback projection contract

This contract defines how Mariana turns backend playback state into safe,
consistent information for terminal, desktop, presence, tray, notification, and
future control surfaces. It does not transfer playback authority to those
surfaces.

## Layers and authority

- **Raw playback state** is the `PlaybackState` lifecycle value owned by
  `PlaybackController`: idle, resolving, buffering, playing, paused, seeking,
  crossfading, failed, or stopping. A state value alone does not identify the
  current media.
- **Current media identity** is the active `MediaRef` held by the controller.
  Its `stable_id`, source, provenance, and capabilities bind backend operations.
  Its `original_uri` and `resolver_data` are backend data and are not display
  fields. `ResolvedMedia` and signed playback URLs remain transient.
- **Playback snapshot** is the immutable `PlaybackSnapshot` returned by
  `PlaybackController.snapshot()`. It is the authoritative point-in-time read
  for state, media, position, duration, buffering, volume, mute, errors,
  loudness, stream metadata, output routing, and current chapter. Some fields
  are private or operational and must not be forwarded directly.
- **Playback status projection** is the sanitized, presentation-neutral
  `PlaybackStatusProjection` built in `mariana/playback_status.py`. It is the
  contract used by CLI status output and desktop playback events. Consumers
  render it; they do not amend it.
- **Provider projections** are narrower transformations for an external
  boundary. For example, Discord receives `PresenceProjection`, not a raw
  snapshot or the complete desktop payload.

`PlaybackController` remains the playback authority. The queue, library,
preferences, and policy services remain authoritative for their own data.
Projection code may query those services read-only; it must not resolve media,
perform network work, mutate playback, or persist state.

## Authoritative and display fields

The current projection schema is versioned. Consumers must tolerate missing
optional fields and must not infer backend state from formatted labels.

- `state` is the controller lifecycle value. `display_state` is a safe label
  such as `Playing`, `Paused`, `Finished`, or `Stopped`.
- `media_id` is an opaque local correlation value derived from the current
  durable media identity. It may be used by an authenticated typed control to
  reject a stale request. It must not be displayed, logged as user-facing
  metadata, or sent to external providers.
- `source`, `finite`, `live`, and `seekable` come from the current media and its
  capabilities. A UI must not infer seekability from duration alone.
- `title` and `artist` are sanitized display fields. Indexed local media may use
  trusted catalog metadata or its safe library display label. Unindexed local
  media falls back to `Local media`; online and live sources use source-specific
  safe fallbacks. A path or URL is never a title fallback.
- `library_index` is a one-based display locator for the current indexed local
  library occurrence. It is not durable identity and is null for online,
  radio, live, unindexed, or non-library media.
- `queue_position` is one-based and is present only when the active media
  matches the authoritative queue cursor. `queue_count` describes the current
  queue projection. Neither field identifies a media item by itself.
- Position, duration, percent, buffering, ReplayGain, and live-leveling values
  are normalized finite values. Unknown or invalid duration produces no
  percentage. Live media does not invent a finite duration or seekable state.
- `safe_error` is bounded, sanitized display text. Raw exceptions, process
  command lines, and resolver diagnostics remain in backend diagnostics.

Formatting, truncation, color, icons, and phrases such as `Ch 2/8` are
display-only. They must never be parsed back into an identity or command target.

## Identity and stale-field clearing

Every projection is rebuilt from one current snapshot plus read-only lookups.
Consumers replace the previous projection as a unit; they must not merge a new
partial event into identity fields from an older media item.

When `media.stable_id`, source, provenance, or the absence of media changes:

- recompute title, artist, source, capabilities, and all timing fields;
- clear `library_index` unless the new item is an indexed local occurrence;
- recompute queue position from the active stable identity and current cursor;
- recompute chapter and favourite state for the new identity;
- clear errors, live metadata, and policy labels that belong to the old item;
- never reuse a previous local index for online playback or a previous online
  title for local playback.

An idle snapshot with no media projects no current identity. If the controller
retains a completed media item so the backend can report `Finished`, that
identity still comes from that same snapshot; a renderer must not preserve it
after a later empty snapshot.

## Chapters and favourites

- Chapter projection contains only sanitized title, finite start/end times,
  and optional one-based index/count. Invalid chapter ranges are omitted.
- The current chapter is selected by backend playback position. UIs may format
  it, but must not independently advance chapter state from wall-clock time.
- Favourite projection contains only availability, current boolean state,
  toggle enablement, and a safe unavailable reason. It does not expose a
  preference key, path, URL, or database row.
- A favourite toggle sends typed intent with the projected opaque `media_id`.
  The backend compares it with the current snapshot before mutation, then the
  UI reconciles from the next authoritative projection. Renderer-only or
  permanently optimistic favourite state is forbidden.
- Playback-policy projection contains only whether the current item is blocked,
  whether a fresh play request is allowed, and a sanitized unavailable reason.
  Blocking is independent from favourite state and never removes an item from
  the library, search results, favourites, or queue.

## Privacy boundary

Public display and provider projections must never contain:

- canonical local paths or path-derived filenames without trusted metadata;
- source URLs, signed stream URLs, radio endpoints, or YouTube identifiers;
- resolver internals, browser profiles, cookies, request headers, or tokens;
- credentials, command lines, output-device names, host/user identity, or
  private database identifiers;
- queue contents, history, lyrics, recommendation features, or unrelated
  session state.

The authenticated local desktop bridge may carry the opaque `media_id` only
for compare-and-apply controls. It is not public display data. External
integrations must define a smaller allowlisted projection and apply their own
sanitizer; they must not serialize the desktop contract wholesale.

## Desktop readiness and typed control

- Python emits a structured `ready` event after backend initialization.
  Terminal text containing the word `ready` is not readiness evidence.
- Electron remains in a waiting state until that structured event arrives and
  caches the latest safe playback projection for renderer reloads.
- Shutdown acknowledgement and fatal backend events clear readiness. Fatal
  errors remain visible even when the main window was hidden to the tray.
- The renderer is a presentation and intent surface. It sends allowlisted,
  authenticated typed requests through the desktop control channel.
- The backend validates readiness, action type, current identity, capability,
  and policy before changing state. Results and subsequent projections settle
  the UI.

Terminal commands remain a separate user command surface. New desktop controls
must not be implemented by injecting command text into the PTY.

## Consumer rules

- `now`, `progress`, the rich terminal header, and desktop footer render the
  canonical playback status projection.
- A future mini-player, tray tooltip, or notification should subscribe to the
  same projection and select a minimal safe subset. It must not create another
  media cache or playback clock.
- Discord and future external providers consume provider-specific projections
  derived from authoritative backend state. Provider failures never mutate or
  stop playback.
- Passive rendering sends no commands. Interactive controls send intent only;
  the backend validates and applies it.

## Safe command target binding

Projection indices are convenient display locators, not immutable command
targets. Commands that mutate files, preferences, queues, or future playback
policies must resolve a locator once to a stable backend object and bind the
operation to that object.

The current command-by-command findings are recorded in the
[destructive command audit](DESTRUCTIVE_COMMAND_AUDIT.md).

- A destructive command resolves the explicit library target, records its
  stable library identity and canonical path internally, and shows that same
  target in confirmation.
- Confirmation and execution use the bound target, not a repeated lookup into
  mutable search, favourite, queue, or active-playback state.
- If identity or path changes before execution, abort rather than guess.
- List-local selectors such as favourite positions remain scoped to their
  explicit command family. They must not poison bare library-number semantics.
- Playback-policy changes must likewise carry the expected media identity and
  reject stale intent after a track transition.

Paths may appear only where an existing explicit local-file inspection or
destructive confirmation requires them. They do not enter playback projection,
desktop events, presence, history, or remote surfaces.

## Playback policies

Blocked-media policy is a backend authority keyed by durable media identity.
Preferred play-region policy remains future work. Policy surfaces must:

- use the versioned, sanitized policy projection rather than exposing
  persistence rows;
- describe only the current media's effective policy and whether a control is
  available;
- send policy changes as typed intent with the expected `media_id`;
- validate ranges and blocking decisions in the backend;
- clear policy display state on every media transition; and
- never let projected policy metadata override controller or queue state.

## Correct and incorrect flows

Correct playback display:

```text
PlaybackController.snapshot()
  -> backend read-only library/queue/favourite lookups
  -> PlaybackStatusProjection
  -> CLI or authenticated desktop event
  -> renderer
```

Correct control:

```text
renderer click + projected media_id
  -> authenticated typed intent
  -> backend compares current identity and validates capability
  -> backend mutation
  -> fresh projection reconciles renderer
```

Incorrect flows include:

- renderer changes playback or favourite state locally and treats it as final;
- a new online event retains the previous local `library_index`;
- a UI derives a title from a local path or displays `original_uri`;
- a delete or policy command re-resolves a number after confirmation;
- an external provider receives the full playback snapshot or desktop payload.

## Future-feature checklist

- Read state from one authoritative snapshot.
- Rebuild and replace projections atomically on identity changes.
- Use stable identity for backend comparison; use indices only for display or
  explicitly scoped selection.
- Allowlist projected fields and sanitize every display string.
- Keep paths, URLs, secrets, resolver data, and private identifiers out of
  public/provider output.
- Send typed intent; validate and mutate in the backend; reconcile from a new
  projection.
- Clear unsupported, unavailable, and stale state explicitly.
- Test local-to-online, online-to-local, queue auto-advance, idle, live,
  failure, and renderer-reload transitions.
- Test that target confirmation and execution remain bound to the same object.
- Version contract changes and keep older consumers tolerant of optional data.
