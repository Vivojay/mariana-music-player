# Desktop Mouse Seek Safety Audit

## Status and scope

This document began as the hover-preview and mouse-seek audit. The typed
identity-bound backend seek contract and main-window click/tap surface are now
implemented. Hover preview, drag/keyboard seeking, and Mini-player seek remain
deferred. This document does not itself change runtime or release state.

Electron remains a presentation and intent surface; the Python backend and
`PlaybackController` remain authoritative.

## Current state

- `mariana/playback_status.py` projects sanitized finite/live/seekable state,
  position, duration, percentage, stable current-media identity, chapters,
  playback policy, and preferred-region bounds.
- `desktop/shared.ts` types that projection as `PlaybackStatus`.
- `desktop/PlaybackStatusBar.tsx` renders a native progress element, chapter
  boundaries, the active chapter segment, preferred-region bounds, and textual
  playback state. The main surface attaches a single click/tap handler only
  when the projected media is eligible; the Mini-player uses the same rendering
  without a seek handler.
- `desktop/main.ts` and `desktop/preload.cts` expose an allowlisted typed
  seek intent alongside the favourite intent. The main process validates
  sender and payload, sends an authenticated request, and correlates a bounded
  response; it does not treat renderer state as authoritative.
- `main.py::_desktop_control_request` revalidates the projected media identity
  and current playback capabilities before delegating the finite absolute
  target to the playback authority.
- `PlaybackController.seek()` rejects absent and nonseekable media, clamps a
  target to the finite source duration and preferred start bound, and completes
  playback when a target reaches a preferred end bound. Clean finite EOF seeks
  use the existing near-end completion rule.
- The CLI seek parser supports absolute, relative, percentage, start/end, and
  duration forms, but the desktop must not invoke it by writing text to the
  terminal.
- `docs/MINI_PLAYER_MVP_DESIGN.md` keeps the Mini-player timeline read-only;
  only the main desktop progress surface uses the seek intent.

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

The hover slice must not add a second click/tap request or respond to drag,
wheel, or keyboard gestures. Existing typed click/tap behavior remains
unchanged.

### Implemented main-window click-to-seek

A primary-button click or tap on an eligible track submits one absolute
target to a dedicated typed backend intent. The UI may show a pending marker,
but it must not optimistically replace the authoritative progress position.
The next backend projection settles the visible state.

Clicks are disabled while a prior seek is being applied; repeated clicks are
ignored rather than queued. A media transition or backend restart discards the
pending target.

## Eligibility matrix

| Projected state | Future hover preview | Main click/tap seek |
| --- | --- | --- |
| Playing or paused, finite, seekable, playable | Yes | Yes |
| Seeking | Read-only current/pending display | No new request until settled |
| Resolving, buffering, crossfading, or stopping | No | No |
| Finished, idle, failed, or backend unavailable | No | No |
| Live, radio, nonseekable, or unknown/invalid duration | No | No |
| Blocked or otherwise unplayable | No | No |

The renderer derives eligibility only from the current sanitized projection
and backend readiness. The backend independently validates every submitted seek;
renderer eligibility is never authorization.

## Safety and authority model

The implemented flow is:

1. Backend emits a canonical `PlaybackStatusProjection`.
2. Renderer derives a bounded source-timeline target from click/tap geometry
   and that projection without changing displayed progress.
3. On an enabled main-surface click/tap, preload accepts a narrow typed seek
   request.
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

Implement a future hover calculation as a pure, tested presentation helper:

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

The implemented control uses a dedicated method rather than exposing a generic
command channel. Its minimal request is:

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

Preload exposes one narrowly typed `seek` method. Electron main must
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
- The implemented click/tap submits the clamped absolute target, and the backend recomputes
  the clamp against current policy.
- Seeking to a preferred end follows the controller's existing completion
  semantics. Seeking near the finite source end follows its existing safe-EOF
  behavior.

## Failure and transition behavior

- A media or queue transition clears pending seek state before rendering the
  new projection; a future hover slice must clear its preview too.
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
- The main pointer surface retains progress semantics and is not exposed as a
  keyboard slider. Slider semantics require complete keyboard operation through
  the same backend validation.
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

1. **Pending - hover-only preview:** use the existing sanitized projection on the main
   desktop timeline; add no IPC, preload method, or click handler.
2. **Completed - backend typed seek intent:** identity-bound request, backend
   validation, safe outcomes, and authoritative republish without UI wiring.
3. **Completed - main desktop click-to-seek:** primary click/tap uses the typed intent,
   serialize requests, and reconcile from projection.
4. **Pending - Mini-player hover preview:** reuse a proven pure timeline helper.
5. **Pending - Mini-player click-to-seek:** reuse the proven intent only after the main
   surface has passed development and packaged acceptance.
6. **Pending - keyboard seeking:** add accessible slider/shortcut behavior through the
   same typed backend control.

The next smallest safe slice is hover-only preview. It must remain local
presentation and cannot send an additional seek.

## Non-goals

- No hover preview or Mini-player seek is implemented by the completed main
  click/tap slice.
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
