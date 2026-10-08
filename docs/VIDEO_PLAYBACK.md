# Video presentation: finite-media experimental slice

The first video slice adds an optional picture surface to the existing backend
audio player. It does not replace the queue, decoder controls, history, favourites,
or command loop. YouTube defaults to audio-only. In the desktop, local files and
direct online media files automatically use video when an actual moving-picture
track is present; audio files remain audio-only. File extensions and embedded
album covers do not decide presentation. No desktop attachment is created for a
standalone terminal; explicit video requests there explain the desktop requirement.

## Current interface

- In the desktop, start a supported finite item and select **Video**.
- `play <library number> --video` starts local playback and prepares its picture.
- `play "C:\Videos\Concert.mp4"` selects a local path with automatic presentation.
- `/yl "<YouTube URL>" --video` and `/ys "artist concert" 5 --video` request video
  through the existing link/search-and-select commands. Omitting the flag keeps
  YouTube audio-only, including a YouTube link supplied through `/ml`.
- `/ml "<public media-file URL>"` uses automatic presentation; `--audio` prevents
  video retrieval. Supported extractor pages also accept `--video`.
- `--audio`, `--video`, and `--auto` override presentation for that playback request.
- `play current --video` enables picture without restarting the audio.
- `play current --audio` / **Audio only** removes picture without seeking or
  recording another listen. Conflicting presentation flags are rejected.
- Existing pause/resume, seek, reset, volume and chapter controls remain authoritative.

The viewer overlays a centered play/pause control and Mariana's shared timeline
along its bottom edge, with elapsed/duration text. Chapter markers, snapping and
preferred-region clamping use the same components as the footer and Mini-player.
The seven-pixel visual track sits inside a thirty-two-pixel invisible hit target
in the video viewer, making pointer entry and clicking easier without thickening
the displayed bar. When local interaction history exists, its noninteractive
white hotspot silhouette appears above the track.
Main-track hover follows the pointer; the enlarged track refines a fixed range.
Leaving both tracks closes the preview after 300 ms unless it retains keyboard
focus. The precision panel stays inside the viewer in fullscreen.

Controls appear on viewer hover, keyboard focus, or pending actions, and remain
visible on touch devices. A stationary fine pointer no longer pins the controls:
after ten seconds without movement they fade away, while pointer movement, keyboard
focus, or a pending action reveals/pins them. The top overlay provides
Fullscreen/Exit fullscreen, Audio only, and the caption/synchronization menu.
Blank video space performs no action. Play/pause and seek use typed, identity-bound
backend controls, never terminal input or browser audio playback.

## Captions and synchronization

For local video, caption discovery runs asynchronously beside picture preparation.
Mariana first checks the media directory for an exact same-basename `.srt` or
`.vtt`, then a language-suffixed match such as `Movie.en.srt`. It also accepts
matching `.ass`, `.ssa`, and text `.sub` sidecars by converting them through the
managed FFmpeg tool. FFprobe also enumerates embedded **text** streams so the
user can choose alternatives even when a sidecar exists. Ordered preferred
languages rank first; without a language match, sidecars precede embedded tracks,
then default and forced flags break ties. Only the selected usable track is
decoded. The same first-usable embedded-text check applies to a supported finite online container
through its private bounded loopback handle; remote references never enter the
renderer contract. Bitmap subtitles such as PGS/VobSub require OCR and are not
treated as text. Discovery failure is nonfatal and never delays or interrupts audio
or the first picture window.

The main viewer also loads one explicit UTF-8 SRT or WebVTT file for the current
media. Files are limited to 2 MiB, 20,000 timed cues, and 1,000 plain-text
characters per cue. Markup and control characters are removed before the renderer
receives only active cue text, safe labels, language/codec/disposition information,
opaque selectors and origin (`sidecar`, `embedded`, `manual`, `provider`, or
`provider-generated`)—never caption paths or provider transport references.
A manual load is authoritative over an
in-flight automatic result. Loading refuses to overwrite an existing track; use
**Replace CC** or `captions replace <file>` when replacement is intentional. The
Mini-player can show/hide and shift a track loaded from the main viewer or command
line.

`captions tracks` lists alternatives after a supported video has been opened;
`captions select <number>` chooses from that current revision. Desktop selections
carry both the media identity and catalogue revision. `captions language en hi`
persists ordered preferences; two- and three-letter codes are accepted, including
region subtags such as `pt-BR`. Up to five codes are allowed; common equivalents
are normalized (`en` → `eng`). `captions language auto` clears language preferences.
`captions auto` forgets the current file's explicit choice and rediscovers tracks.
All are available in **Captions & sync**; selection does not seek, pause, or
restart the audio decoder. Positive caption offsets display text later (±60,000 ms).

Local discovered-track selections, show/hide state, and caption offsets persist in the
existing user settings under `captions`. Up to 128 recent explicit choices use
hashed media identities, opaque track selectors, and a size/mtime file-change
guard—not file paths or secret URLs. This guard is not a cryptographic content
identity: moved or modified media may need a new selection. A missing/changed
saved track produces a visible message and no substitute; choose a listed track
or Automatic to recover. Manual file loading and Clear remain session-only;
Clear does not erase the remembered choice. Explicit preferences survive upgrades.

Discovery scans at most 1,024 directory entries and exposes up to 32 candidates.
One background worker holds one active and one latest pending request; new choices
cancel stale work. FFprobe/FFmpeg calls have 15-second timeouts and bounded output.
If the caption worker cannot start, its pending work is discarded, existing
captions and their display settings remain available, and a caption-only error is
shown. Video preparation continues. There is no automatic retry loop: select a
track or choose Automatic again to make another attempt. An unstarted worker is
never retained for shutdown to join.
Caption FFprobe output is capped at 128 KiB while it is received, not merely
checked after an unbounded capture. Cancellation is checked every 25 ms while
the probe or its output is pending, including a probe that closes stdout before
exiting. Termination is followed by bounded child reaping and reader cleanup.
Temporary conversion files are removed; shutdown cancels and joins caption work
within a shared 15-second deadline. Failed extraction or preference saving retains
previous captions where available and never interrupts playback.

Native-format acceptance exercises MP4 `mov_text`, Matroska SubRip/ASS tracks,
ASS/SSA and text MicroDVD sidecars, same-basename precedence, explicit alternative
selection, language metadata, and persisted selection/visibility/offset after
service reload. These are actual managed-FFmpeg extraction tests, not a claim of
packaged or public-provider subtitle acceptance. MicroDVD is frame-timed text;
bitmap `.sub`/VobSub is still excluded from text-caption support.

`avsync [status|set <signed-ms>|shift <signed-ms>|reset]` adjusts presentation
timing without restarting or seeking the authoritative audio decoder. A positive
value means audio is later than picture; Mariana therefore advances the muted
picture by that amount. A negative value makes audio earlier than picture. The
offset is bounded to ±5,000 ms. Audio/video synchronization remains scoped to the
current in-memory media occurrence and resets on a track change or restart.

### Provider caption tracks

For YouTube and existing extractor-supported finite video pages, Mariana retains
supported `subtitles` and `automatic_captions` references already supplied by the
video resolver. The [extractor metadata contract](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/common.py)
distinguishes provider subtitles from provider-generated captions. Mariana keeps
that distinction in labels and the public `source` field; it does not generate
or translate captions itself. One WebVTT (preferred) or SRT encoding per supplied
language/kind is exposed, up to 32 alternatives. Some extractors do not supply
subtitle metadata during ordinary video resolution; such sources still require
a manual local subtitle file. No extra scraping or catalogue-download flags are
enabled to manufacture missing alternatives.

Opening video lists available tracks but **does not fetch provider captions**.
Use **Captions & sync → Caption track (select to fetch)** or `captions tracks`
followed by `captions select <number>`. Selection explicitly downloads that track
on the existing bounded caption worker. It does not seek, pause or restart audio.
Provider choices, enabled state and timing remain session-only; restarting,
rediscovering or refreshing a provider catalogue never silently grants another
caption request. Local Automatic and language preference controls retain their
existing behavior and do not enable online retrieval.

Caption URLs and headers exist only in private, ephemeral video-resolution
objects. Neither `MediaRef`, queue snapshots, preferences nor renderer projections
receive them. Selectors bind the current media occurrence, catalogue revision and
exact transient reference; late responses after a new choice, media change, clear
or shutdown are rejected. Failed retrieval keeps prior captions. After a failed
provider selection, choose **Audio only**, then **Video**, and select a caption
track again. This refreshes the YouTube resolution rather than retrying a
known-failed reference indefinitely. Choosing Video while it is already ready
does not force a refresh.

Explicit retrieval reuses the public-address-pinned transport, hostname-verified
TLS, redirect validation and narrow header policy. Private network destinations,
URL user credentials, cookie/authorization headers, HTTPS downgrades, compressed
payloads and unsupported response types are refused. Redirects are limited to
three, socket operations use the existing five-second timeout, and transfer has
a fifteen-second cooperative budget checked between operations and again after
connection setup, before sending a request. OS DNS resolution cannot be
interrupted by this transport, and an in-flight socket operation can take up to
its timeout. The budget is therefore not a strict wall-clock completion guarantee;
late connection completion closes the connection without sending a new request.
UTF-8 text is held only
in memory with the same 2 MiB, 20,000-cue and 1,000-character cue limits. There is
no caption file download, persistent caption cache, online-account setup or new
command family. Public-provider availability and packaged/native readability
remain separate acceptance work; mocked transport and component tests do not
establish that a provider will serve a particular track.

Online subtitle-database lookup, requested translation, bitmap-subtitle OCR,
and online-container multi-track selection remain pending.
Online database lookup will require an explicit network action and
provider credentials because it discloses a media fingerprint or title; it will not
be silently coupled to local playback.

Preparation is asynchronous. Local files prepare an initial eight-second picture
window around the current position, then prefetch twenty-second windows with
four-second overlaps. A distant seek cancels obsolete work and prepares a
new window at that position. Paused playback stays paused and prepares at most
the current and following windows; it does not convert the rest of the movie.
Each window has an explicit source-timeline offset, subtracted by the renderer
when following the backend clock. Local windows use accurate input seeking and
H.264 conversion at up to 1280×720/30 fps, an ultrafast low-latency preset, a
two-second keyframe interval, fragmented MP4 output, and two threads. Fragmented
output avoids the separate end-of-encode metadata relocation performed by
`faststart`; longer overlapping windows reduce source swaps while keeping work and
cache size bounded. No local file is converted in full before the first picture.
This does not make the split backend-audio/muted-picture design equivalent to a
single-decoder player; native long-playback latency and hardware-decoding work
remain separate acceptance items.

Online files use the same short rolling-window model. A backend-owned loopback
transport gives FFprobe/FFmpeg bounded range access to the selected remote video
track; the signed/provider URL and request headers never enter Electron or a
renderer projection. The first picture therefore needs only the current short
window, not a complete 80-minute file. A distant seek discards obsolete work and
prepares a fresh window around the authoritative audio position. There is no
image scraping and this presentation cache is not a permanent download.

Only supported finite audiovisual files are supported: at most two hours, input
dimensions up to 7680×4320. Windows have a 30-second preparation deadline and a
32 MiB per-window limit. Unsupported/oversized files leave audio unchanged and
report a nonfatal error. Silent videos require a future backend video clock.
Source replacement during preparation is rejected.

Online window transport is capped at 4 GiB over one presentation session, with
per-request deadlines and the same short-window output limits. Selected audio and
video tracks from one extractor response remain separate backend-only values. Only
video bytes are retrieved for picture; the existing backend audio decoder is
unchanged. Extractor selection requests at most 720p public HTTP file formats;
available formats remain provider-dependent.
Resolution is fresh on each video request. Expired/access-denied transport fails
with safe retry guidance, never signed-link output. A duration mismatch with the
active recording refuses picture instead of displaying a mismatched timeline.

The public-file transport validates and pins public addresses before connecting,
checks every redirect, verifies TLS hostnames, and does not forward provider
headers across origins. Cookie/authorization-dependent picture transport,
private-network URLs, DRM, HLS/DASH manifests, live sources, and providers that
ignore nonzero byte-range requests are refused. Media tools see only the random
loopback URL and a restricted protocol/demuxer allowlist, never the remote URL.

The application-owned `runtime/cache/video` area contains temporary video-only
windows under random handles. Local and online workers retain only current/next
windows and retry removal of obsolete files still open in the viewer, refusing
further work if the cleanup backlog exceeds six files. Owned temporary files are
removed on cancellation and normal shutdown.

Rolling windows now have small versioned ownership records with a nonblocking
operating-system lease per instance. Each record contains only random window
names and file identities, never source paths or provider references. The output
is exclusively created and recorded before encoding; FFmpeg writes its fragmented
MP4 to that already-open descriptor instead of reopening a pathname. Completed
and partially written windows from a crashed owner are therefore recoverable.

Recovery runs lazily on the picture worker, not during application construction
or on the audio/control thread. Each allocation examines at most 32 directory entries and uses
a 100 ms scheduling budget, checking the deadline between filesystem operations.
An individual slow filesystem operation is not forcibly interrupted. Active leases
are skipped without waiting. A retained scan cursor continues on later window
allocations so legacy entries cannot permanently starve newer records; shutdown
closes the cursor. This is bounded incremental cleanup, not a startup-wide
filesystem sweep. Each record
is limited to 8 KiB and eight windows, and no directory is recursively removed.

Recovery removes only a manifest-listed ordinary file whose device/inode and,
where available, birth identity still match. Symlinks, reparse points, hardlinks,
changed roots/files, malformed records, unmarked legacy windows, and unrelated
files are preserved. Windows removal acts on a verified delete-capable file handle;
POSIX removal is anchored to a verified directory descriptor with a final identity
check. This protects against normal replacement and link redirection, but the
cache is private application state—not a security boundary against malicious
same-account editing of ownership records or concurrent POSIX directory entries.

If a viewer temporarily prevents deletion, the record remains for retry. A worker
that exceeds shutdown's join budget retains its lease until it actually exits;
shutdown does not delete a window still being produced. This remains a disposable
picture cache, not a durable video library. Real FFmpeg preparation and native
Windows cross-process lease recovery are covered by focused tests; POSIX-native
filesystem and packaged acceptance remain separate evidence.

## Boundaries and synchronization

### YouTube source-quality switching

For finite YouTube media, `play current --video` / **Video** asynchronously adds
the selected original video-only stream. `play current --audio` / **Audio only**
removes picture immediately. Neither operation restarts/seeks the audio decoder,
changes the queue, or records a new listen. Picture joins the *current* audio
position after preparation; audio keeps advancing while picture loads.

This YouTube-only path supersedes the 720p window-conversion limits described
above. It selects the best available supported H.264, VP9 or AV1 public HTTPS
file, at source resolution/frame rate, and does **not** re-encode. Chromium must
support the actual selected codec/profile; unsupported or unavailable picture
remains a nonfatal error, without a hidden quality downgrade. Other providers
and local files retain their existing bounded-window path. The two-hour duration,
8K input-dimension, authenticated-transport and live/DRM restrictions still apply.

The backend range cache contains original compressed picture bytes in RAM only:
64 MiB by default, adjustable from 16–256 MiB through `youtube video cache.memory
mib` in settings. Its idle expiry defaults to 600 seconds (30–1800 configurable
via `idle seconds`). Settings take effect on restart. One cache is shared by the
main and Mini viewers. Requests use 256 KiB blocks, an LRU memory budget and
coalesced misses; no parallel duplicate block downloads are made. A 4 GiB source
size/transfer budget applies to one retained recording. No cache files, signed
URLs or cookies are written to disk. Source changes and shutdown clear the cache;
idle entries are cleared within five seconds of expiry.

Audio-only mode does not start picture retrieval. Returning to audio cancels
pending picture requests; up to one in-flight block may finish at the transport
boundary. Existing bytes remain briefly reusable, but no hidden video downloader
keeps following the audio. An uncached later position consequently needs new data.
There is no claim of instantaneous switching on an arbitrary connection or a
guaranteed network-bandwidth reservation for audio. The browser requests its own
decode buffer while picture is enabled and uses metadata-only preload when paused.

`media video-cache status` reports cached, downloaded and reused bytes;
`media video-cache clear` drops retained bytes without seeking or stopping audio.
It can cancel a pending picture read; selecting **Video** again recovers it.
Transport resolution is reused for at most two minutes, subject to known expiry.
Renewed URLs reuse cached bytes only when format metadata, size and a strong ETag
agree. Without that validator, a changed URL starts a fresh byte cache. Changing
from an audio upload to a different music-video upload is not attempted: presentation
switching retains the same YouTube recording identity.

The host receives a short-lived loopback capability over the authenticated backend
channel. It strips that value before sending status to either renderer. The
existing `mariana-video` protocol validates the current handle/identity/revision
and streams only that capability, with no redirects, cookies or arbitrary request
headers. The renderer still has a muted picture element and the backend audio clock.

The main-window preload exposes video status and identity-bound mode changes,
plus narrow play/pause and seek intents for the overlay controls.
The Mini-player preload additionally exposes a read-only video-status refresh;
its snapshot carries validated current-video metadata and the sampling timestamp.
The existing Mini-player window shows a muted picture using the same clock follower
as the main viewer. Its playback/chapter/seek controls stay backend-authoritative.
It is always-on-top, resizable in video mode, and returns to fixed audio geometry
when the active media is no longer video. Closing still hides the auxiliary window.
The opt-in Windows development test passes a real synthetic local video through both
windows and verifies muted frames, backend-clock following, overlay geometry,
always-on-top/resizable video mode and fixed-size audio fallback. Public-provider,
physical display-scaling and packaged acceptance remain pending.
A private application protocol serves only
the current validated handle from the bounded cache, with byte-range support.
Renderer state contains no filesystem paths, provider credentials or signed URLs.
The cache has no audio stream, so the browser cannot produce duplicate sound.

For finite online media, the same Mini-player offers **Download video** and
**Download audio** while picture is active. Video is the primary action and saves
MP4 with audio; audio is an explicit MP3 extraction. The buttons use a typed,
identity-bound backend request and a bounded progress projection, so download
percentage and transfer speed do not expose paths or signed media references.
Audio-only Mini-player mode offers MP3. Local files, live streams, unknown-duration
items, stale identities, blocked media, and non-downloadable sources are refused.

The video surface follows backend samples, interpolates fresh playing samples,
and corrects drift above 180 ms. Samples older than one second freeze picture.
This is an experimental synchronization policy, **not measured native A/V accuracy**.
Automated frame-clock checks and native FFmpeg preparation do not substitute for
long-running native output/latency measurement on each operating system.

The shared footer, main-video, and seek-enabled Mini-player timelines render the
real decoder buffer-ahead value from the authoritative playback snapshot. The
buffered band begins at the current position, ends at `position + buffered_seconds`,
and is clamped to the finite duration. It is queued decoded audio, not a claim that
the corresponding remote file bytes have been permanently downloaded.

Video and video Mini-player timelines additionally show a separate lower stripe
for the video element's actual `buffered` intervals. The upper stripe remains
queued decoded audio. Picture-buffer gaps are preserved, including after seeks;
a local source or a prepared transcode window is not assumed to be fully buffered.
Window-relative timestamps and audio timing offsets are mapped back onto the same
audio timeline used for seeking, then clamped to finite media duration. The footer
continues to show only authoritative audio buffering.

Measurements are event-driven, coalesced to at most four updates per second, and
limited to the first 64 browser intervals. Media/window/offset changes discard
stale measurements; error, empty and abort events clear them. These stripes report
presentation readiness, not download progress or permanently cached bytes. They
never seek, change playback, or add network requests.

Native buffer acceptance uses the current isolated desktop sources and a generated
45-second silent H.264/AAC fixture. It compares each main-viewer and Mini-player
stripe with the real element's `TimeRanges`, including its geometry, rather than
mocking buffered values. Positive/negative 500 ms audio offsets remap those ranges
without moving paused backend playback. The controlled Windows run passed at
760×520, 1280×820 and 1920×1080, with renderer zoom 100%, 125% and 150%, windowed and
fullscreen; audio-only fallback removed the picture-buffer stripes. The existing
pointer/precision-seek, muted-picture and no-terminal-write checks also passed.
Two earlier runs stopped at pointer-sensitive visibility assertions; the controlled
pass explicitly focused only the isolated fixture while other windows were left
untouched. This is not physical DPI, public-provider buffering, hardware A/V-sync
or packaged acceptance. Disjoint/window-relative edge cases also have deterministic
mapping tests; the native fixture does not establish every transport's behavior.

## Deferred milestones

1. Native synchronization acceptance, same-recording mode switching, source
   replacement/decoder failure cases, and video-only sources with a backend clock.
2. Native public-provider acceptance, authenticated request transports, and
   resilience measurement for providers with slow or specialized range behavior.
   Rolling windows do not make this universal YouTube/web streaming support.
3. Persist per-occurrence presentation in mixed queues without changing recording
   identity, favourites or audio-only crossfade behavior.
4. Direct-terminal attachment to one existing backend, additional provider subtitle
   formats/catalogues, online-container multi-track selection, and an optional
   persistent presentation default.
5. Supported live HLS/DASH and verified DVR ranges, followed by temporal previews.

Defaults also apply to newly activated queue items. Explicit mode choices are
currently bound to the active in-memory media attempt; mixed-queue per-occurrence
mode persistence is not implemented. No universal source support, live recording,
DRM bypass, packaged acceptance or multi-platform A/V readiness is claimed.
