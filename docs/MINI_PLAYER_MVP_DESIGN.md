# Mini-player MVP Design

## Status and intent

This document began as the Mini-player design and now records the implemented
source MVP plus the deliberately deferred slices. It does not itself change
runtime, packaging, or release state.

The Mini-player is a compact local desktop surface driven by Mariana's
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
- Play/Pause/Previous/Next through a dedicated identity-bound typed control
  path.
- A local artwork placeholder; no media-art fetch pipeline.

The implemented window is single-instance, opens from the main **Mini** button,
and provides Show Mariana and Hide. Closing it or pressing Escape hides it.
Theme selection, pin/always-on-top, bounds persistence, Mini-player favourite
and volume controls, and tray-specific Mini-player actions remain deferred.

## Non-goals

- Stop, volume, queue mutation, or arbitrary playback commands.
- Mini-player click, drag, keyboard, wheel, or mouse seeking.
- Hover seek previews or waveform previews.
- Terminal command injection or a general command-execution IPC API.
- A second playback controller, queue, media resolver, or state store.
- Album-art fetching, network metadata lookup, or animated ambient artwork.
- Raw source links or arbitrary external URL opening in the initial slices.

The main desktop now has a typed, backend-validated click/tap seek path. The
Mini-player deliberately does not expose it.

## Existing foundations

The current desktop already provides the required playback data:

- `mariana/playback_status.py` emits the canonical safe projection.
- `desktop/shared.ts` types playback, favourite, chapter marker, policy, and
  preferred-region fields.
- `desktop/PlaybackStatusBar.tsx` renders finite/live/unknown progress and
  chapter markers.
- `desktop/main.ts` caches the latest playback payload and mediates typed
  favourite, seek, and Mini-player playback requests.
- `mariana/desktop_control.py` carries authenticated local events and requests.
- The tray lifecycle already provides single-instance tray creation and clean
  Show, Hide, and Quit actions.

The Mini-player reuses these contracts rather than duplicating their state or
deriving media identity from terminal output.

## Layout contract

1. **Header:** draggable region plus Show Mariana and Hide controls. Pin and
   Theme remain deferred.
2. **Identity:** safe artist/title with bounded ellipsis and full sanitized text
   available as an accessible label.
3. **Timeline:** elapsed/duration, percentage when valid, read-only track,
   chapters, and preferred-region indication. A distinct thumb is deferred.
4. **Context:** `Ch N/M · Title`, queue position, LIVE/unknown-duration text,
   or a blocked/unplayable badge.
5. **Actions:** Play/Pause/Previous/Next. Favourite, volume, and any safe
   provider-link action remain later slices.

No media path, URL, resolver value, fingerprint, credential, device identity,
or private identifier is displayed.

## Shared playback presentation

The existing `PlaybackStatusBar` is the shared presentation boundary. Both the
main footer and Mini-player consume it; the Mini-player omits the seek callback
and therefore receives a noninteractive progress track.

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

### Deferred hover and focus polish

- Track height is `4px` normally and `7px` on hover or focus.
- Thumb diameter is `8px` normally and `11px` on hover or focus.
- Changes use a subtle `140ms ease-out` transition.
- Reduced-motion mode disables the transition.
- The timeline uses the normal cursor and has no pointer or key handlers that
  seek.
- The current read-only surface exposes `role="progressbar"`, bounded numeric
  values, and meaningful `aria-valuetext`. Any future focusable timeline must
  retain those semantics without implying keyboard seeking.

## Window and tray lifecycle

- Create the Mini-player lazily and retain at most one instance.
- Closing it or pressing Escape hides it; neither action exits Mariana.
- The main window provides the implemented Mini-player open action. Dedicated
  Show/Hide Mini-player tray entries remain deferred.
- Tray Quit remains an explicit application/backend shutdown.
- Main-window close-to-tray behavior remains unchanged.
- Backend exit/restart leaves the Mini-player open in an unavailable state and
  restores it from the next canonical snapshot/event.
- Renderer reload requests the cached playback snapshot before displaying
  current-media data.
- If the tray is unavailable, the main-window toggle remains the recovery path
  for a hidden Mini-player.

Any future Pin control must call Electron's window authority and persist only
validated presentation state. Always-on-top is not currently implemented.

## Desktop security boundary

The Mini-player uses a dedicated least-privilege preload. It exposes only:

- a sanitized Mini-player snapshot;
- safe playback/readiness event subscription;
- identity-bound Play/Pause/Previous/Next intents;
- the host platform label needed for local window styling;
- Show main and Hide Mini-player.

It does not expose the terminal, arbitrary backend commands, update controls,
filesystem access, Node.js, or arbitrary `openExternal` access. Electron keeps
context isolation, sandboxing, disabled Node integration, navigation blocking,
and surface-specific IPC sender validation.

Raw PTY output remains main-window-only. The main process broadcasts only
sanitized playback/readiness data to the Mini-player. Renderer state is never
treated as authoritative.

## Future favourite control reuse

If added, the Mini-player should send the current projected media identity through the existing
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
implemented.

## Future themes and presentation persistence

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

1. **Completed - shared read-only presentation:** finite/live/unknown progress
   and sanitized chapter markers are shared with the main footer.
2. **Completed - separate Mini-player window:** dedicated renderer/preload,
   single-window lifecycle, cached snapshot/events, main visibility action, and
   close/Escape-to-hide behavior.
3. **Pending - themes and persistence:** add the three themes, validated bounds,
   and optional remembered pin state.
4. **Pending - favourite reuse:** add an identity-bound Mini-player favourite
   intent and authoritative reconciliation.
5. **Completed - playback context visualization:** safe identity/source/queue,
   blocked/live/unknown states, chapter label/markers/current segment, and
   preferred-region bounds.
6. **Partially completed - progress polish:** compact responsive layout exists;
   hover/focus thumb animation and theme/reduced-motion polish remain pending.
7. **Safe provider opening:** implement the separate availability-only and
   typed-open security slice described above.
8. **Later research:** hover preview.
9. **After main-surface native/package acceptance:** consider Mini-player
   click/drag/keyboard seeking through the existing typed seek contract.

## Verification status and remaining plan

- Current pure view tests cover finite, live, unknown-duration, idle, failed,
  blocked, missing, and backend-unavailable states.
- Current timeline tests cover progress clamping, chapters, current segment,
  preferred bounds, invalid data, and read-only behavior. Focus, hover, and
  reduced-motion polish remain pending.
- Window lifecycle tests cover single instance, show/hide/close, backend
  snapshots, and renderer reload. Tray entries, pin, bounds persistence, and
  packaged lifecycle remain pending.
- IPC/preload tests cover least privilege, sender validation, event filtering,
  playback-control identity binding, and absence of terminal access. Favourite
  serialization remains pending for this surface.
- Development Electron E2E currently covers one-instance creation, safe
  unavailable rendering, least-privilege preload, disabled controls without
  media, and close-to-hide. Eligible-media transitions, auto-advance,
  chapter/region changes, and backend recovery remain native/E2E follow-ups.
- Packaged E2E before any release claim, confirming no second backend or PTY
  session is created.
- Privacy assertions that no path, raw URL, cookie, header, credential,
  resolver field, fingerprint, device identity, or private ID is rendered or
  emitted to the Mini-player.

Manual acceptance should cover the current compact layout, long labels,
keyboard-only use, screen-reader labels, display scaling, and backend recovery.
Future themes, multiple-monitor bounds, tray actions, pinning, and reduced
motion require their own implementation before acceptance.
