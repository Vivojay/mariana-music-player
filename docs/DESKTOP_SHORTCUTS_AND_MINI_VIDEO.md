# Desktop shortcuts and compact video

## Local implementation

Open **Keys**, **Settings → Configure keyboard shortcuts**, or press Ctrl+/ to
toggle the guide (Command+/ on macOS). Optional app shortcuts default to off.
The guide contains the enable checkbox and the exact available bindings for the
current window. The preference persists in the desktop profile and synchronizes
between the main window and Mini-player. Copy/paste, terminal interrupt, Tab,
and ordinary focused-control keys do not depend on this preference.

Optional combinations use Ctrl+Shift or Command+Shift. They ignore key repeat,
composition and AltGr, do not run underneath a modal, and never write command text
to the terminal. Playback requests retain current-media identity and backend
validation. Shortcuts for settings, queue, downloads, artwork and other panels
open existing surfaces; they do not start downloads or confirm destructive actions.
The Video shortcut focuses the existing presentation button rather than enabling
network picture retrieval implicitly. Restart, exit and destructive operations
remain explicit controls rather than one-key actions.

## Focus and keyboard interaction

Home keeps Tab navigation inside its currently available controls, including
Search Home and expanded source details. Hidden, inert, disabled, and collapsed
detail contents are not tab stops; closing an overlay does not restart the
terminal. When two modal surfaces overlap, only the foreground one contains
focus or handles an outside press.

The shortcut guide restores the original usable control after closing. If that
control was removed (for example, opening the guide replaced Home), focus returns
to **Keys**. Deferred terminal sizing and activation respect this destination.
Recognized app shortcuts are consumed while a modal is open: they neither change
playback nor accidentally activate its focused checkbox or button. Ordinary Tab,
text editing, copy/paste, and focused video/caption controls keep their usual
behavior. Key repeats and composition do not dismiss the guide.

Browser keyboard regressions use real Home, shortcut, terminal and caption
components with an isolated in-memory control boundary. They exercise native
Tab order, committed close/focus handoff, and zero terminal writes from handled
shortcuts at 760×520, 1280×820 and 1920×1080 with renderer zoom 100%, 125% and 150%.
These are renderer acceptance checks, not physical display-scaling, audible
playback, or packaged-application acceptance.

```powershell
npm test -- --run desktop/modalFocus.test.tsx desktop/KeyboardShortcuts.test.tsx `
  desktop/TerminalSurface.test.tsx desktop/HomepagePanel.test.tsx
npx playwright test desktop/e2e/keyboardInteraction.spec.ts --reporter=line
```

The browser fixture builds into temporary storage and removes that build after
the run; it does not replace the running application's renderer or Electron files.

## Compact video

The existing Mini-player window now displays current video silently, follows the
same backend clock as the main video view, and overlays the shared chapter/seek
bar, compact elapsed/duration, play/pause, previous/next and download controls on
the picture. Video mode is resizable; switching to audio restores fixed audio
dimensions and the original compact layout immediately. The window stays on top,
can be reopened from the tray, and closing hides it rather than exiting Mariana.
Overlay controls fade outside pointer hover, but remain accessible on keyboard
focus and touch devices. Video errors do not stop audio. Stale or mismatched video
metadata cannot attach a previous media item's picture to the new item.

Finite current YouTube, podcast, and supported online media also expose typed
Mini-player download actions. In video mode **Download video** saves MP4 video
with audio by default and **Download audio** extracts MP3 separately. Audio mode
offers MP3 only. Progress and transfer speed come from the existing downloader's
bounded progress hook. The renderer supplies only the current opaque media ID and
the selected format; the backend owns the source URL and destination, rechecks
identity/policy/download eligibility, and retains no-clobber output behavior.
Local files and live or unknown-duration sources remain unavailable.

YouTube video search already uses `/ys "artist concert" 5 --video`; YouTube stays
audio-only without that flag. See [video limitations](VIDEO_PLAYBACK.md).

## Not completed by this slice

- The opt-in Windows development Electron scenario passes with a real synthetic
  local-video picture, always-on-top/resizable Mini-player geometry and audio-layout
  fallback. Physical display scaling, provider playback, long-running audible
  synchronization and packaged acceptance remain separate gates.
- Automatic playback of homepage tiles. Editorial and release metadata do not
  identify an exact playable recording. Resolved media cards need backend-owned
  handles; ambiguous releases retain explicit version selection.
- Broad news/image import. Images remain validated provider-supplied cached data,
  with honest placeholders when unavailable. Links are not imported feeds.

The official [triple j Like A Version catalogue](https://www.abc.net.au/triplej/programs/like-a-version)
is now an offline-available destination. It links to performances and the official
playlists, but this addition does not import or promise playback of its catalogue.
Billboard was already present as an official chart link, not copied rankings.

[Pitchfork publishes RSS feeds](https://pitchfork.com/info/rss/), but the same page
also restricts reuse of its content. RSS availability alone is not a blanket
image-redistribution permission. Provider-specific feed and image terms must be
settled before enabling a new cached-content adapter. SXSW image permissions
likewise need checking; this slice does not scrape full articles or event images.

## Deferred account-linked features

No trial counters or account gates are implemented. The selected policy is five
uses **per eligible feature**, not one shared pool. The future design still must
name each eligible feature and precisely define when a use is consumed. Required
rules are first-use explicit confirmation before dispatch, cancellation before
dispatch consuming nothing, idempotent usage accounting so retries do not consume
twice, visible remaining uses, and no charge for an operation that fails before
delivering its result.
After exhaustion, explain that registration is free; do not interrupt existing
local playback. Account/trust/storage and offline behavior require a separate
design and migration, not hidden switches added to existing commands.
