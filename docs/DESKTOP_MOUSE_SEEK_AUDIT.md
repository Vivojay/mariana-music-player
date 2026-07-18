# Desktop Mouse Seek Safety Audit

## Status and scope

This document audits a future hover preview and mouse-seek design. It does not
change playback, desktop IPC, the renderer, persistence, packaging, or release
state. Mariana's existing desktop progress bar remains read-only.

The safe sequence is hover preview first, followed by a separate typed seek
contract. Electron remains a presentation and intent surface; the Python
backend and `PlaybackController` remain authoritative.

## Current state

- `mariana/playback_status.py` projects sanitized finite/live/seekable state,
  position, duration, percentage, stable current-media identity, chapters,
  playback policy, and preferred-region bounds.
- `desktop/shared.ts` types that projection as `PlaybackStatus`.
- `desktop/PlaybackStatusBar.tsx` renders a native progress element, chapter
  boundaries, the active chapter segment, and textual playback state. The
  progress and marker layers have no seek handlers.
- `desktop/main.ts` and `desktop/preload.cts` expose an allowlisted typed
  favourite intent. The main process sends an authenticated request to the
  backend and correlates a bounded response; it does not treat renderer state
  as authoritative.
- `main.py::_desktop_control_request` revalidates the projected media identity
  before applying the favourite mutation. It currently rejects every other
  desktop control action.
- `PlaybackController.seek()` rejects absent and nonseekable media, clamps a
  target to the finite source duration and preferred start bound, and completes
  playback when a target reaches a preferred end bound. Clean finite EOF seeks
  use the existing near-end completion rule.
- The CLI seek parser supports absolute, relative, percentage, start/end, and
  duration forms, but the desktop must not invoke it by writing text to the
  terminal.
- `docs/MINI_PLAYER_MVP_DESIGN.md` deliberately keeps both main and Mini-player
  timelines read-only until this contract is implemented and proven.

These foundations are sufficient. Mouse seeking does not require a new
playback controller, projection source, database migration, or broad desktop
architecture change.

## Desired UX

### Hover preview

For finite, seekable, playable media with a valid positive duration, hovering
the main progress track may show:

- the clamped target time;
- the sanitized chapter label at that time, when present; and
- a concise preferred-bound indication when the pointer lies outside the
  configured region.

The preview is local presentation only. It performs no backend request, seek,
logging, history update, persistence, or network access. Leaving the track,
moving focus away, pressing Escape, losing backend readiness, or changing
media clears it.

The first hover slice must not respond to click, tap, drag, wheel, or keyboard
seek gestures. Touch interaction remains unchanged.

### Later click-to-seek

A primary-button click on an eligible track may later submit one absolute
target to a dedicated typed backend intent. The UI may show a pending marker,
but it must not optimistically replace the authoritative progress position.
The next backend projection settles the visible state.

Clicks are disabled while a prior seek is being applied. If multiple targets
are accepted by a later interaction design, requests are serialized and only
the newest queued target for the same media may survive. A media transition or
backend restart discards every pending target.

## Eligibility matrix

| Projected state | Hover preview | Later seek intent |
| --- | --- | --- |
| Playing or paused, finite, seekable, playable | Yes | Yes |
| Seeking | Read-only current/pending display | No new request until settled |
| Resolving, buffering, crossfading, or stopping | No | No |
| Finished, idle, failed, or backend unavailable | No | No |
| Live, radio, nonseekable, or unknown/invalid duration | No | No |
| Blocked or otherwise unplayable | No | No |

The renderer derives eligibility only from the current sanitized projection
and backend readiness. The backend independently validates every future seek;
renderer eligibility is never authorization.

## Safety and authority model

The future flow is:

1. Backend emits a canonical `PlaybackStatusProjection`.
2. Renderer derives a display-only hover target from track geometry and that
   projection.
3. On a later enabled click, preload accepts a narrow typed seek request.
4. Electron main validates sender and payload shape, then forwards an
   allowlisted authenticated backend request.
5. Backend verifies current media identity, playback state, policy,
   seekability, duration, finite target, and current preferred bounds.
6. `PlaybackController.seek()` applies the authoritative seek.
7. Backend emits a fresh canonical projection; all surfaces reconcile from it.

Incorrect flow: renderer formats `seek 50%` and writes it to the PTY. This is
terminal command injection, loses target identity, and races media changes.

Incorrect flow: renderer moves its stored playback position before backend
acceptance. This creates a second playback truth and can display a seek that
never occurred.

No hover or seek payload may contain a path, raw URL, cookie, header,
credential, resolver field, private identifier, device identifier, or command
line.

## Hover-preview calculation

Implement the future calculation as a pure, tested presentation helper:

1. Convert the pointer's horizontal position within the measured track to a
   ratio clamped to `0..1`.
2. Multiply by the valid source duration to obtain a source-timeline target.
3. Compute effective bounds as preferred start or `0`, and preferred end or
   source duration.
4. Clamp the preview target to those effective bounds.
5. Select the sanitized chapter whose source-timeline range contains the
   target. At a shared boundary, use the chapter that starts at the boundary.
6. Format time and optional `Ch N/M · Title` from sanitized projection data.

Chapter markers and preferred regions remain on the original source timeline;
neither is rebased. Invalid, non-finite, reversed, overlapping, or out-of-range
chapter/region data disables the affected decoration rather than guessing.
Backend validation remains decisive if bounds change after the preview.

Pointer updates should be frame-coalesced to avoid excessive React renders.
They must not generate backend traffic or live-region announcements on every
pixel.

## Typed seek-control contract

The later control slice should add a dedicated method rather than exposing a
generic command channel. A minimal request is:

```text
seek.request {
  media_id: <current projected stable identity>,
  target_seconds: <finite absolute source-timeline seconds>
}
```

`media_id` binds the request to the item the user saw. The backend refuses the
request if current media no longer matches. Percentages, chapter objects,
paths, and source URLs are unnecessary in the request.

The backend must:

- accept only finite numeric targets and bounded payload sizes;
- require matching current media and an eligible playback state;
- require finite duration, seekability, and non-live media;
- reject blocked or otherwise unplayable media;
- reload current preferred-region policy and apply its clamp/completion rules;
- delegate the operation to `PlaybackController`;
- return a typed safe outcome and publish the authoritative projection.

Useful fixed outcomes are `accepted`, `completed`, `media_changed`,
`not_seekable`, `unplayable`, `duration_unknown`, `invalid_target`,
`backend_unavailable`, `timed_out`, and `seek_failed`. Human messages must be
short and fixed; raw third-party exceptions never cross into Electron.

Preload should expose one narrowly typed `seek` method. Electron main must
retain sender validation, request correlation, a bounded timeout, and safe
failure sanitization. The request path must remain separate from
`terminal:write`.

## Chapters and preferred regions

- Hover chapter lookup uses only projected, sanitized markers.
- Marker positions continue to represent the full source duration.
- The active preferred region may be shaded or bracketed; it does not hide
  chapters outside the region.
- Hover outside a preferred region previews the nearest valid boundary and may
  label it `Preferred start` or `Preferred end`.
- A later click submits the clamped absolute target, and the backend recomputes
  the clamp against current policy.
- Seeking to a preferred end follows the controller's existing completion
  semantics. Seeking near the finite source end follows its existing safe-EOF
  behavior.

## Failure and transition behavior

- A media or queue transition clears hover and pending state before rendering
  the new projection.
- Backend disconnect/restart disables the surface and clears pending requests.
- A rejected seek leaves the progress bar at the last authoritative position
  and shows one concise sanitized error.
- Paused media remains paused after a successful seek, matching controller
  behavior.
- Live, radio, unknown-duration, blocked, and failed media keep their existing
  noninteractive status presentation.
- A stale response whose media identity no longer matches is ignored after its
  request is settled.

## Accessibility and keyboard behavior

- Hover information also needs a focus equivalent before it is considered
  complete; focus may show current time/chapter without enabling seek.
- Tooltip text must not be pointer-only and must remain within the viewport.
- Do not use an assertive live region for continuous pointer movement.
- Eligibility and disabled reasons require text, not color alone.
- Reduced-motion mode removes nonessential tooltip/track transitions.
- The read-only first slice keeps progress semantics and does not present a
  slider. The later seekable surface may use slider semantics only when full
  keyboard operation and backend validation exist.
- Arrow/Page/Home/End seeking is deferred to the final typed-control stage.

## Testing plan

### Hover-only slice

- Pure geometry tests for left/right edges, zero-width tracks, clamping, and
  non-finite input.
- Preferred start/end tests, including a pointer outside either bound.
- Chapter lookup at starts, interiors, shared boundaries, and the final end.
- No preview for live, radio, unknown duration, nonseekable, blocked,
  unplayable, failed, idle, or backend-unavailable states.
- Media transition, pointer leave, blur, and Escape clear preview state.
- Assertions that hover performs no terminal write, IPC request, persistence,
  network call, or playback mutation.
- Accessibility and reduced-motion rendering tests.

### Typed seek and click slices

- Preload surface and IPC sender/payload validation.
- Backend rejection for stale media identity, invalid duration/target,
  nonseekable/live media, blocked policy, and unavailable backend.
- Preferred-bound clamping, paused-state preservation, near-end completion,
  and fresh-projection reconciliation.
- Serialization/coalescing tests for rapid requests and media transitions.
- Safe timeout/transport/controller failure messages without private data.
- Development Electron E2E for click intent, backend restart, auto-advance,
  chaptered media, and preferred regions.
- Packaged E2E before any release claim.

## Staged implementation

1. **Hover-only preview:** use the existing sanitized projection on the main
   desktop timeline; add no IPC, preload method, or click handler.
2. **Backend typed seek intent:** add the identity-bound request, backend
   validation, safe outcomes, and authoritative republish without UI wiring.
3. **Main desktop click-to-seek:** connect primary click to the typed intent,
   serialize requests, and reconcile from projection.
4. **Mini-player hover preview:** reuse the proven pure timeline helper after
   the Mini-player exists.
5. **Mini-player click-to-seek:** reuse the proven intent only after the main
   surface has passed development and packaged acceptance.
6. **Keyboard seeking:** add accessible slider/shortcut behavior through the
   same typed backend control.

The smallest safe future slice is stage 1. It changes presentation only and
cannot seek. Stage 2 should be a separate backend/control commit so identity,
policy, error, and concurrency behavior can be reviewed before any pointer
action is enabled.

## Non-goals

- No seeking, hover preview, IPC, preload, or schema change in this audit.
- No drag scrubbing, waveform thumbnails, video-frame previews, or network
  preview generation.
- No terminal injection, generic command executor, or renderer-owned playback
  state.
- No Mini-player, autocomplete, Discord, release, or packaging work.
- No persistence of hover, pending seek, or preview state.

## Future-feature checklist

- Uses only the canonical sanitized projection for display.
- Sends one typed, identity-bound intent through least-privilege preload.
- Revalidates media, state, capability, policy, duration, and region in the
  backend immediately before seeking.
- Delegates playback mutation to `PlaybackController`.
- Reconciles every result from a new authoritative projection.
- Clears stale UI state on media change or backend restart.
- Contains no terminal command construction and no private data.
- Includes focused unit, IPC, backend, development E2E, and packaged E2E
  evidence before a release claim.
