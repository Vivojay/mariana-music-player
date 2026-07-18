# Mini-player MVP Design

## Status and intent

This document defines a future Mini-player implementation. It does not change
runtime behavior, playback, IPC, persistence, packaging, or release state.

The Mini-player will be a compact local desktop surface driven by Mariana's
canonical `PlaybackStatusProjection`. The backend remains the only playback
and media-state authority. The renderer formats sanitized state and, where
explicitly allowed, sends a narrow typed intent.

## MVP scope

- One compact, single-instance Mini-player window independent of the main
  terminal window.
- Safe title/artist, source, playback state, elapsed/duration, percentage, and
  queue position when present.
- A read-only visual timeline with current position, chapter boundaries,
  current-chapter highlight, chapter label, and preferred play-region bounds.
- Clear live, unknown-duration, idle, failed, blocked, and backend-unavailable
  states.
- Favourite state and toggle through the existing typed backend control path.
- Mini-player themes: `offwhite`, `dark`, and `ambient`.
- Optional always-on-top mode, off by default.
- Validated local persistence of window bounds, theme, and pinned state.

The initial size is `400 x 172`, with a supported range of `340 x 150` to
`600 x 240`. The window is opaque, frameless, resizable, and visible in the
taskbar. Custom controls provide Show main, Pin, Theme, and Hide.

## Non-goals

- Play, pause, stop, next, previous, volume, queue, or other playback controls.
- Click, drag, keyboard, wheel, or mouse seeking.
- Hover seek previews or waveform previews.
- Terminal command injection or a general command-execution IPC API.
- A second playback controller, queue, media resolver, or state store.
- Album-art fetching, network metadata lookup, or animated ambient artwork.
- Raw source links or arbitrary external URL opening in the initial slices.

Seeking remains deferred until the dedicated mouse-seek audit defines a typed,
backend-validated intent and failure contract.

## Existing foundations

The current desktop already provides the required playback data:

- `mariana/playback_status.py` emits the canonical safe projection.
- `desktop/shared.ts` types playback, favourite, chapter marker, policy, and
  preferred-region fields.
- `desktop/PlaybackStatusBar.tsx` renders finite/live/unknown progress and
  chapter markers.
- `desktop/main.ts` caches the latest playback payload and mediates the typed
  favourite request.
- `mariana/desktop_control.py` carries authenticated local events and requests.
- The tray lifecycle already provides single-instance tray creation and clean
  Show, Hide, and Quit actions.

The Mini-player must reuse these contracts rather than duplicate their state or
derive media identity from terminal output.

## Proposed layout

1. **Header:** draggable region, source badge, playback-state badge, Show main,
   Pin, Theme, and Hide controls.
2. **Identity:** safe artist/title with bounded ellipsis and full sanitized text
   available as an accessible label.
3. **Timeline:** elapsed/duration, percentage when valid, read-only track,
   current-position thumb, chapters, and preferred-region indication.
4. **Context:** `Ch N/M · Title`, queue position, LIVE/unknown-duration text,
   or a blocked/unplayable badge.
5. **Actions:** favourite toggle and, in a later security slice, an optional
   safe provider-link action.

No media path, URL, resolver value, fingerprint, credential, device identity,
or private identifier is displayed.

## Shared playback presentation

Extract a pure presentation mapper and shared `PlaybackTimeline` from the
existing desktop status bar. Both the main footer and Mini-player consume the
same primitives.

The mapper may derive formatted time, display title, source label, chapter
label, progress availability, and accessible descriptions. It cannot retain
state, resolve media, or mutate playback.

The timeline remains on the source timeline:

- chapter markers use the sanitized percentages already projected by the
  backend;
- the current chapter segment is visually distinct;
- preferred bounds shade or bracket the playable region without rebasing
  chapter positions;
- invalid, overlapping, non-finite, or unavailable marker data is ignored;
- live and unknown-duration media show no numeric track, thumb, chapters, or
  region masks.

### Hover and focus behavior

- Track height is `4px` normally and `7px` on hover or focus.
- Thumb diameter is `8px` normally and `11px` on hover or focus.
- Changes use a subtle `140ms ease-out` transition.
- Reduced-motion mode disables the transition.
- The timeline uses the normal cursor and has no pointer or key handlers that
  seek.
- The focusable progress surface exposes `role="progressbar"`, bounded numeric
  values, and meaningful `aria-valuetext`.

## Window and tray lifecycle

- Create the Mini-player lazily and retain at most one instance.
- Closing it or pressing Escape hides it; neither action exits Mariana.
- Add Show Mini-player and Hide Mini-player to the existing tray menu and a
  Mini-player toggle in the main window.
- Tray Quit remains an explicit application/backend shutdown.
- Main-window close-to-tray behavior remains unchanged.
- Backend exit/restart leaves the Mini-player open in an unavailable state and
  restores it from the next canonical snapshot/event.
- Renderer reload requests the cached playback snapshot before displaying
  current-media data.
- If the tray is unavailable, the main-window toggle remains the recovery path
  for a hidden Mini-player.

The optional Pin control calls Electron's window authority and persists its
state. Always-on-top is off by default.

## Desktop security boundary

The Mini-player uses a dedicated least-privilege preload. It exposes only:

- a sanitized Mini-player snapshot;
- safe playback/readiness event subscription;
- favourite intent;
- Mini-player theme/pin/bounds actions;
- Show main and Hide Mini-player.

It does not expose the terminal, arbitrary backend commands, update controls,
filesystem access, Node.js, or arbitrary `openExternal` access. Electron keeps
context isolation, sandboxing, disabled Node integration, navigation blocking,
and surface-specific IPC sender validation.

Raw PTY output remains main-window-only. The main process broadcasts only
sanitized playback/readiness data to the Mini-player. Renderer state is never
treated as authoritative.

## Favourite control reuse

The Mini-player sends the current projected media identity through the existing
typed favourite boundary. The backend revalidates that the active media still
matches before mutation and republishes the complete authoritative projection.

Both windows reconcile from that projection. Pending requests are serialized
in the main process so simultaneous clicks cannot double-toggle. Track changes,
auto-advance, unavailable media, and backend restart clear stale pending state.
Failures use fixed sanitized messages and never affect playback.

## Safe online-source action: later slice

The current playback projection intentionally contains no source URL. The
initial Mini-player therefore renders no provider-link button.

A later contained slice may add an availability-only capability such as
`external_open: {available, provider, label}` and a typed
`external.open-current` intent. It must:

- support only locally derivable, allowlisted canonical sources in v1;
- start with canonical public YouTube watch links only;
- revalidate current media in the backend;
- pass the sanitized link to Electron main, not the renderer;
- validate HTTPS host, path, and query again before opening;
- never forward the link in playback events or control-result events;
- omit the action for local files, radio, generic URLs, signed/query-bearing
  sources, credentials, and ambiguous providers.

This capability, any projection schema bump, and source-opening tests are not
part of the documentation or first implementation slice.

## Themes and presentation persistence

- `offwhite`: warm light surface with dark AA-contrast text.
- `dark`: neutral charcoal and the default Mini-player theme.
- `ambient`: static Mariana teal/violet gradient, optionally varied only by the
  sanitized source type. It does not fetch or analyze artwork.

Store versioned presentation-only state under Electron user data, not in the
media database. Persist bounds, theme, and pinned state using debounced writes.
Reject corrupt/non-finite values, clamp sizes to the supported range, and move
off-screen restored bounds onto a connected display.

## Accessibility checklist

- Every control has an accessible name, focus indication, and disabled reason.
- Keyboard order follows visual order; Enter/Space operate buttons; Escape
  hides the window.
- Progress, chapter, region, blocked, LIVE, and unavailable states have textual
  equivalents independent of color.
- Long labels are safely truncated visually without truncating accessible
  sanitized text.
- Theme contrast meets WCAG AA for normal text and controls.
- Reduced-motion preference removes nonessential transitions.
- No passive status update steals focus or repeatedly announces unchanged
  content.

## Staged implementation

1. **Shared read-only presentation:** extract pure playback formatting and a
   timeline primitive while preserving the main footer's behavior.
2. **Separate Mini-player window:** add the dedicated renderer/preload,
   single-window lifecycle, safe snapshot/events, and main/tray visibility
   actions.
3. **Themes and persistence:** add the three themes, validated bounds, and the
   optional remembered pin state.
4. **Favourite reuse:** share pending/error reconciliation and serialize typed
   favourite requests across both windows.
5. **Playback context visualization:** render chapter label/markers, preferred
   region, queue position, and blocked/unplayable state.
6. **Progress polish:** add the specified hover/focus thumb and track behavior,
   reduced-motion handling, and responsive layout.
7. **Safe provider opening:** implement the separate availability-only and
   typed-open security slice described above.
8. **Later research:** hover preview.
9. **After a dedicated audit:** click/drag/keyboard seeking.

The first implementation slice changes presentation primitives only. It adds no
window, route, preload, IPC, persistence, schema, or control behavior.

## Verification plan

- Pure view tests for finite, live, unknown-duration, idle, failed, blocked,
  missing, and backend-unavailable states.
- Timeline tests for progress clamping, chapters, current segment, preferred
  bounds, invalid data, focus, hover, and reduced motion.
- Window lifecycle tests for single instance, show/hide/close, tray, pin,
  bounds validation, backend restart, renderer reload, and explicit quit.
- IPC/preload tests for least privilege, sender validation, event filtering,
  favourite serialization, and absence of terminal access.
- Development Electron E2E for hidden-main operation, playback transitions,
  auto-advance, chapter/region/blocked changes, favourite reconciliation, and
  backend recovery.
- Packaged E2E before any release claim, confirming no second backend or PTY
  session is created.
- Privacy assertions that no path, raw URL, cookie, header, credential,
  resolver field, fingerprint, device identity, or private ID is rendered or
  emitted to the Mini-player.

Manual acceptance should cover all themes, display scaling, keyboard-only use,
screen reader labels, multiple monitors, tray-unavailable fallback, and reduced
motion.
