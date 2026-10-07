# Synchronized lyrics

Mariana's desktop lyrics panel presents line-synchronized LRC lyrics using the
authoritative playback source position. It does not create an audio player,
independent playback clock, browser view, or external lyrics viewer. Pauses hold the current
cue, and seeking immediately selects the cue at the new source position. Blank
LRC cues are retained as instrumental gaps.

## Requests, privacy, and fallback

Opening/showing lyrics is an explicit user operation. Playback observation,
status reads, media changes, and offset changes do not resolve lyrics or send
metadata anywhere. Show and Refresh use the existing
`IdentificationService.lyrics(media, identity, refresh=...)` path:

1. Local `.lrc` sidecar or embedded lyrics.
2. Existing lyrics cache (unless explicitly refreshing).
3. The existing LRCLIB client when local/cache results are absent.

An explicit lookup can send track metadata to the existing online provider. The
service does not infer artist/title from a private filename or URL and does not
start fingerprinting. Callers can provide the existing cached `TrackIdentity`;
otherwise declared current-media title/artist/album/duration are used. The legacy
lyrics command/viewer remains a separate compatibility path.

Use `lyrics current` to request current-track lyrics, `lyrics current --refresh`
to bypass the lyrics cache, `lyrics status` to inspect without fetching,
`lyrics offset +250` to delay display by 250 ms, and `lyrics hide` to dismiss.
Existing `lyrics`, `lyr`, `open lyrics`, and lyrics editing behavior is preserved.

Malformed or absent LRC timing falls back to available plain lyrics. If neither
usable timing nor plain text exists, the panel shows an unavailable state; offline
and lookup errors are nonfatal. Refresh is explicit, not a retry loop.

Local-sidecar attribution is a generic label, never its filesystem path. Public
projections omit source URLs, credentials, filenames, raw provider records, and
identity metadata. Lyric text is rendered as React text, never interpreted as HTML.

## Display offset

The user offset is an integer from −60,000 to +60,000 milliseconds. Positive
values delay lyric display; negative values advance it. It combines with the
LRC `[offset:...]` field without altering the source cues, audio transport, or
media file. The correction is in-memory and resets when media, playback session,
or supplied identity changes. It is not a persistent per-track preference.

## Backend integration contract

Create one `LyricsPresentationService(identification, on_change=...,
snapshot=lambda: controller.snapshot())` for the application lifetime. The
`on_change` callback receives allowlisted dictionaries for a `lyrics` desktop
event and should only perform fast event delivery. The optional `snapshot`
callback must return the authoritative `PlaybackSnapshot`, including its session
token, and should be a fast read without network access.

- `update_playback(snapshot, session_id=None, identity=None)` updates the source
  cursor without I/O. By default it uses the atomically captured
  `snapshot.session_id`. A new token invalidates results even when replaying the
  same stable media ID. Feed media transitions immediately as well as periodic
  playback snapshots; optional changed `TrackIdentity` invalidates old lyrics.
- `request(media_id=..., refresh=False, identity=None)` explicitly shows/resolves
  current-media lyrics asynchronously. Media-bound controls reject obsolete IDs.
- `set_offset(media_id, offset_ms)` validates and updates display correction.
- `hide()` marks the panel hidden and invalidates pending results so they cannot
  reopen it. Already-ready lyrics can be shown again without another lookup.
- `projection()` returns an independent public dictionary and does not fetch.
- `close()` invalidates all pending/active results immediately. Call this before
  tearing down the application. Late results/errors cannot emit desktop events.

Only one daemon worker can be resolving at a time; one pending slot is replaced
by newer requests. That same lazy worker samples `snapshot()` at a nominal 100 ms
cadence only while ready timed lyrics are visible. Hidden, plain, unavailable,
and idle states use an indefinite condition wait, not active polling. Reopening
ready lyrics wakes the existing worker without a new lookup. The snapshot callback
runs outside the lyrics lock; a delayed sample cannot override a newer explicit
playback observation, media/session change, hide, or shutdown. No playback time
is extrapolated, and polls never call the lyrics resolver.

There is no growing request queue. An already-running legacy
resolver call cannot be interrupted by this adapter and may finish its timed I/O
or cache write after invalidation. Its results are discarded. The resolver owns
its network timeouts and I/O behavior. Local LRC reads are capped at 4 MiB (with
an extra-byte race check); unreadable, malformed-UTF-8, or oversized sidecars fall
through to embedded lyrics. LRCLIB streams decoded response bytes with an 8 MiB
limit and a bounded response-read deadline. Existing injected in-memory response
adapters remain supported and their serialized JSON size is checked as well.

After resolution, synchronized text is limited to 1,000,000 characters and 10,000
cues by the existing timeline parser. Public plain text is capped at 64,000
characters and each visible cue at 2,000 characters. The desktop projection does
not carry the entire synchronized timeline.

## Renderer contract

`desktop/lyricsProjection.ts` exports `LyricsProjection`, `projectLyrics`, and
`acceptLyricsProjection`. Schema version 1 contains a monotonic `revision`, public
`session_revision`, stable `media_id`, availability/state/visibility, source
position in milliseconds, display offsets, cue count/index, previous/active/
following `{start_ms, text}` cues, plain fallback, provider, safe attribution, and
unavailability message. Internal source-session tokens are never exposed.

Project every snapshot/event before retaining it. Reject a projection for another
current media ID and ignore older revisions/session revisions. On backend
`starting`, clear retained state so a restarted backend can begin at revision 0.

`LyricsPanel` is a reusable controlled React modal with these callbacks:

```tsx
<LyricsPanel
  status={lyrics}
  mediaId={playback?.media_id ?? null}
  onRequest={(mediaId, refresh) => backend.lyricsRequest(mediaId, refresh)}
  onOffset={(mediaId, offsetMs) => backend.lyricsOffset(mediaId, offsetMs)}
  onHide={hideLyrics}
/>
```

The request and offset callbacks return `Promise<DesktopControlResult>`; `onHide`
closes the parent-owned panel and sends the typed hide control. The panel never
writes terminal command strings or accesses backend globals. Merely mounting the
panel does not request lyrics. There is no local lyric-advance interval.

The general desktop monitor and explicit status/control reads still supply source
snapshots. When the optional snapshot callback is connected, visible timed lyrics
also receive the worker's nominal 100 ms source samples without accelerating the
general monitor. Scheduling or a slow source read can add latency; this remains
line synchronization, not word-level karaoke or sample-accurate presentation.
Without that callback, cadence remains entirely caller-driven.

The modal has a labelled dialog, keyboard-focus containment, Escape/outside-click
dismissal, opener-focus restoration, explicit previous/current/following labels,
polite current-line announcements, and a keyboard-scrollable plain-text fallback.
Controls remain dismissible while a request is pending. Media/session changes
discard pending UI errors and input drafts; late request failures cannot overwrite
the newly displayed media.

## Verification

Deterministic Python tests cover source cursor selection, pause/seek/end/blank
cues, local/cache preference, explicit lookup, source/user offsets, media and
same-media session changes, identity changes, stale success/failure, bounded latest
pending work, malformed/oversized timing, plain fallback, privacy, hide, and
shutdown. Event/condition-based tests also verify visible-only source sampling,
pause/seek observations without refetch, hidden/idle waits, same-worker reopen,
out-of-lock source reads, stale sample rejection, and nonfatal observation errors.
Renderer tests cover projection rejection, typed controls, accessibility,
focus, plain-text escaping, media/session races, and unavailable/error states.
Native packaged-window visual verification remains a separate manual check.

```text
.venv/Scripts/python.exe -m pytest -p no:cacheprovider tests/test_lyrics_presentation.py tests/test_lyrics_timeline.py
npm test -- desktop/LyricsPanel.test.tsx desktop/lyricsProjection.test.ts
```
