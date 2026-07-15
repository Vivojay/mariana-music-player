# Mariana Command Help

Mariana is a local-first media player. Enter commands at the `)>` prompt. Use
`help`, `h`, or `?` for the compact command map, and `help <topic>` for examples
from one category. `help all` and `help full` show the complete map.

Arguments in angle brackets are required. Items in square brackets are
optional. A vertical bar separates alternatives. Quote names and paths that
contain spaces.

## Getting started

| Command | Purpose |
| --- | --- |
| `help [topic]`, `h [topic]`, `? [topic]` | Show all help categories or one category |
| `all`, `all*` | List the first configured number of library items, or all items |
| `ls [count]` | List library items |
| `<number>`, `play <number>` | Play a library item by its one-based number |
| `now` | Show the active media, playback state, progress, and chapter when available |
| `progress`, `prog` | Show elapsed time, duration, and completion percentage |
| `cls`, `clear` | Clear the terminal display |
| `exit`, `quit` | Confirm and close Mariana |

Start with `library status`, then use `all` or `ls` to see indexed local media.
If the library is empty, inspect its configured roots with `library roots` and
run `library scan changed` after correcting them.

## Playback

| Command | Purpose |
| --- | --- |
| `<number>`, `play <number>` | Play local media by library number |
| `p`, `pause` | Pause or resume |
| `s`, `stop` | Stop playback |
| `+`, `next`, `queue next` | Play the next queue item |
| `-`, `prev`, `queue previous` | Play the previous queue item |
| `m`, `mute` | Toggle mute |
| `v`, `vol`, `volume [0-100]` | Show or set Mariana playback volume |
| `mv`, `mvol`, `mvolume [0-100]` | Show or set host master volume when supported |
| `autonext [on|off|status]`, `autoplay [on|off|status]` | Continue through queue/library order after a track ends |
| `reset` | Seek the current finite item to its beginning |
| `open [number|path]` | Reveal local media, or open the active online source in a browser |
| `path [number]` | Show the active or selected local path |

`autonext off` leaves playback stopped at the end of the active item. Local
stop, pause, and exit always remain under the user's control.

## Seek and fade

Seeking is available only for media that Mariana has verified as finite and
seekable. Live radio and other non-seekable streams reject seek requests.

| Command | Purpose |
| --- | --- |
| `seek 90` | Seek to 90 seconds |
| `seek :30`, `seek 01:20`, `seek 01:20:30` | Seek using clock notation |
| `seek 1:02:03:04` | Seek using `DD:HH:MM:SS` |
| `seek 1d 2h 3m 4s` | Seek using labeled duration fields |
| `seek +30`, `seek +30s`, `seek -2m`, `seek +1h` | Seek relative to the current position |
| `seek 50%` | Seek to a percentage of known duration |
| `seek start`, `seek end` | Seek to the beginning or safe end margin |
| `fade in [seconds]`, `fade out [seconds]` | Fade from silence or toward silence; default is five seconds |
| `fade to <0-100> [in <seconds>]` | Fade from current volume to a target |
| `fade from <0-100> to <0-100> [in <seconds>]` | Fade between explicit volumes |
| `fade <from> <to> [seconds]` | Legacy fade syntax, retained for compatibility |

Relative seeks clamp to the playable range. `seek end` avoids requesting an
exact decoder EOF position. A zero-second fade applies its target immediately.

## Queue

The persistent queue is the source of next/previous playback. It is initialized
in library order and can contain nested groups up to eight levels deep.

| Command | Purpose |
| --- | --- |
| `queue list`, `queue tree` | Show the flat queue or hierarchical groups |
| `queue add <media>` | Add a library number, indexed path, or supported URL |
| `queue ys "<query>" [count]`, `queue youtube "<query>" [count]` | Search YouTube, select a result when needed, and append its canonical reference without interrupting playback |
| `/ysq "<query>" [count]` | Short alias for `queue ys` |
| `queue insert <position> <media>` | Insert media at a one-based position |
| `queue remove <position>` | Remove an occurrence from the queue |
| `queue move <from> <to>`, `queue swap <a> <b>` | Reorder occurrences |
| `queue jump <position>` | Move the cursor and play that item |
| `queue next`, `queue previous` | Navigate the queue |
| `queue shuffle [seed]` | Shuffle reproducibly when a seed is supplied |
| `queue repeat off|one|all` | Configure repeat policy |
| `queue consume on|off`, `queue autofill on|off` | Configure consumption or recommendation refill |
| `queue save <name>`, `queue load <name>` | Save or restore a compatible queue snapshot |
| `queue undo`, `queue redo` | Restore a prior queue mutation |
| `queue reset` | Rebuild the queue from current library order |
| `queue clear` | Remove all queue occurrences; media files are not deleted |
| `queue group create|rename|move|remove|atomic ...` | Manage nested groups |
| `queue order sequential|shuffle|priority|artist-fair|smart|custom [--group <path>] [--seed N]` | Order upcoming nodes without restarting the active item |
| `queue priority <path> <integer>` | Assign stable priority |
| `queue dedupe identity|uri` | Remove duplicate occurrences by the selected key |

Group paths are one-based, such as `2.3.1`; durable node IDs are also accepted.

## Search and online sources

| Command | Purpose |
| --- | --- |
| `find <terms> [count]`, `f <terms> [count]` | Match all normalized terms in the local library |
| `rfind <terms> [count]`, `rf <terms> [count]` | Match terms while treating numbers literally |
| `lfind <terms> [count]`, `lf <terms> [count]` | Match any normalized term |
| `/ys <query> [count]` | Search YouTube and play the selected result |
| `queue ys "<query>" [count]`, `/ysq "<query>" [count]` | Search YouTube and queue the selected result without playing it |
| `/yl <YouTube URL>` | Play a YouTube URL |
| `/ml <URL>` | Resolve and play a public yt-dlp-supported media page or direct media URL |
| `pod <vendor>`, `pods <vendor>` | Browse configured podcast vendors |
| `/rss <feed URL>` | Browse an RSS feed |
| `album search|show|tracks|fetch|play|queue|save ...` | Resolve distinct album editions and their tracks |
| `station start|status|list|more|pause|resume|stop ...` | Build a music-only station from a verified track seed |
| `recommend [count]`, `recommend related [count]` | Show explainable local recommendations |
| `recommend autofill [count]`, `recommend train` | Fill the queue or train the lightweight local model |

Prefix `find`, `rfind`, or `lfind` with `.` to play the first match, or `/` to
play a random match. Online resolution can fail because of network
availability, authentication, rate limits, geographic restrictions, DRM, or
provider changes. Mariana reports these failures and does not bypass service
protections. `/ml` supports sources that yt-dlp and FFmpeg can access; it is not
a universal authenticated or DRM playback command.

Mariana does not currently provide SoundCloud catalog search, so `queue sc`
and `/scq` are not commands. Known public SoundCloud URLs remain supported by
the extractor-backed `/ml` playback and `download-ml` commands.

YouTube operations share one optional browser-profile reference:

```text
youtube auth status
youtube auth set firefox
youtube auth set edge:Default
youtube auth clear
youtube auth test <YouTube URL>
```

Browser cookies are read by yt-dlp only while a YouTube command runs; Mariana
does not persist cookie data.

## Downloads

| Command | Purpose |
| --- | --- |
| `download-yv [YouTube URL]`, `dl-yv [YouTube URL]` | Download YouTube video; omit the URL to use the active YouTube item |
| `download-ya [current|YouTube URL] [--track] [--quality best|worst] [--to <directory>]`, `dl-ya ...` | Download one audio item |
| `download-ya --album [current|album-ref|YouTube-playlist-URL] [--tracks <selector>] [--missing-only] [--allow-partial] [--quality best|worst] [--to <directory>] [--yes]` | Create an explicit album download job |
| `download-ya status [job-id]` | Inspect persistent download work |
| `download-ya pause|resume|cancel <job-id>` | Control a download job |
| `download-ml <URL> [mp3|flac|wav|m4a|opus] [output path]`, `dl-ml ...` | Download a public extractor-backed media page or direct media URL |

Plain `download-ya` means the active track, never the entire album. Complete
album expansion requires `--album`. Downloads run in the current Mariana
session and do not start a nested Mariana REPL. The same external-service
limitations described under online sources apply to extractor-backed downloads.

## Library

`lib.lib` remains the human-editable source of library roots. The incremental
profiler stores its catalog and resumable work in Mariana's writable SQLite
database.

| Command | Purpose |
| --- | --- |
| `library roots` | Show configured roots and availability |
| `library scan [changed|full]` | Reconcile changed files or request a full discovery pass |
| `library status` | Show file counts and profiler state |
| `library pause`, `library resume` | Control background profiling |
| `library errors` | Show per-file profiling failures |
| `library retry [file|all]` | Retry failed profiling stages |
| `library verify` | Check database health and unavailable paths |
| `library info <index|path>` | Show indexed metadata and profiler state |
| `library clean --missing` | Remove missing-file tombstones only; never delete media |
| `reload` | Refresh the legacy library projection from the current index |
| `include downloads`, `exclude downloads` | Add or remove Mariana's managed download root without editing user roots |
| `rename short [current|index|path] [--dry-run|--yes]` | Rename indexed local media from trusted metadata and provenance |
| `replaygain scan [changed|full]`, `replaygain rescan <index|path>` | Queue non-destructive loudness analysis |
| `fav [!|+|-]`, `bl [!|+|-]` | Inspect, toggle, set, or clear favorite/blocked state for active media |
| `like`, `dislike` | Set the active item to favorite or blocked |
| `favs [count]`, `blacklist [count]` | List persistent media preferences |

Unavailable roots do not block startup. Missing media remains as history-aware
tombstones until explicitly cleaned.

## Playlists

| Command | Purpose |
| --- | --- |
| `playlist list` | List local versioned playlists |
| `playlist create <name> [--description <text>]` | Create a playlist |
| `playlist show <name> [--tree]` | Show tracks or nested structure |
| `playlist rename <old> <new>` | Rename a playlist |
| `playlist delete <name> [--yes]` | Delete the playlist record after confirmation unless `--yes` is supplied |
| `playlist clear <name>` | Remove all playlist contents |
| `playlist add <name> media|album|playlist <reference> [--at <path>]` | Add media or an atomic snapshot |
| `playlist remove <name> <path>` | Remove a node |
| `playlist move <name> <path> --parent <path|root> [--at N]` | Move a node |
| `playlist order <name> <strategy> [--group <path>] [--seed N]` | Apply a queue-compatible strategy |
| `playlist play <name>` | Replace the active queue and begin playback |
| `playlist queue <name> [--at next|end|N] [--flatten]` | Add a snapshot to the current queue |
| `playlist import <name> <m3u|m3u8|YouTube-playlist-URL>` | Import a snapshot without modifying its remote source |
| `playlist export <name> <path.m3u8>` | Export canonical references as UTF-8 M3U8 |

## Lyrics

| Command | Purpose |
| --- | --- |
| `lyrics`, `lyr` | Display lyrics for the active item |
| `lyrics edit`, `lyr edit` | Edit an adjacent `.lrc`, confirming before cached lyrics create one |
| `open lyrics`, `open lyr` | Open the current lyrics file in the configured editor |

Resolution prefers embedded or adjacent local lyrics, then cached or provider
results. Missing identities or provider records produce a clear no-lyrics
result; Mariana does not fabricate lyric text.

## Radio

| Command | Purpose |
| --- | --- |
| `radio search <query>` | Search the station catalog |
| `radio list [favorites]` | List available or favorite stations |
| `radio play <station>` | Play a station by ID or slug |
| `radio add <URL> [name]` | Add a direct station URL |
| `radio info <station>` | Show station and endpoint health information |
| `radio metadata` | Show current ICY metadata |
| `radio resync` | Restart the active radio stream at the live edge |
| `radio favorite <station> [off]` | Set or clear favorite state |
| `radio health [station]`, `radio refresh [station]` | Probe cached or freshly resolved endpoints |
| `radio leveling on|off|status` | Control optional live loudness leveling |
| `radio credentials set|delete|status <station> [username]` | Manage private-stream credentials in the OS keychain |
| `broadcast profiles|start|stop|test|status` | Control one configured Icecast source broadcast |
| `broadcast credentials set|delete|status <profile>` | Manage broadcast credentials in the OS keychain |

Station availability is external and cannot be guaranteed. Endpoint failure
does not silently become success; Mariana reports health and failover state.

## Discord Presence

Discord Rich Presence is optional, off by default, and uses local Discord RPC.
It does not use OAuth or require an end-user token.

| Command | Purpose |
| --- | --- |
| `discord presence status` | Show mode and publisher state |
| `discord presence app` | Publish only that Mariana is running |
| `discord presence track` | Publish sanitized title/artist when safe |
| `discord presence session` | Add safe album/source/timing context when available |
| `discord presence refresh` | Republish the current projection |
| `discord presence off` | Clear presence and disable publishing |

Paths, URLs, filenames derived only from paths, cookies, tokens, browser
profiles, queue contents, device names, and host identity are never published.
Discord absence or failure never affects playback or startup.

## Settings

| Command | Purpose |
| --- | --- |
| `theme aurora|windows|kitty|gruvbox` | Select a terminal preset |
| `theme list`, `theme current` | List presets or show the active one |
| `autonext [on|off|status]` | Configure automatic queue progression |
| `sleep <duration> [pause|stop] [fade <duration>]` | Start a session-scoped sleep timer |
| `sleep status`, `sleep cancel` | Inspect or cancel the sleep timer |
| `youtube auth status|set|clear|test ...` | Configure the optional YouTube browser-profile reference |
| `replaygain on [track|album|auto]`, `replaygain off` | Enable or disable non-destructive normalization |
| `replaygain mode <track|album|auto>`, `replaygain preamp <dB>` | Configure ReplayGain selection and preamp |
| `output device` | Show the operating system default and Mariana's active-device handoff state |
| `include downloads`, `exclude downloads` | Configure managed-download library inclusion |

There is no general `config set` command. Other validated settings remain in
Mariana's writable user settings file.

## Diagnostics

| Command | Purpose |
| --- | --- |
| `now`, `progress` | Inspect active playback |
| `media info|probe|metadata [current|index|path]` | Show catalog and FFprobe metadata |
| `media fingerprint [current|index|path] [--full]` | Show or calculate a Chromaprint fingerprint |
| `media identify [current|index|path]` | Resolve a conservative AcoustID/MusicBrainz identity |
| `tools status` | Show FFmpeg, FFprobe, FFplay, fpcalc, rsgain, and JavaScript-runtime status |
| `tools setup`, `tools install`, `tools repair` | Configure or provision managed media tools |
| `setup status`, `setup resume`, `setup repair` | Inspect or recover transactional first-run setup |
| `library status`, `library errors`, `library verify` | Inspect profiler and catalog health |
| `replaygain status`, `replaygain verify` | Inspect active gain or run the rsgain verification probe |
| `discord presence status` | Inspect presence without changing its mode |
| `station status`, `broadcast status` | Inspect background station or broadcast state |
| `hist`, `history [count]`, `open history` | Open persistent history or show its entry count |
| `check_dev` | Show whether development mode is active |

There is no consolidated `doctor` command yet. Use `tools status`,
`library verify`, `setup status`, and the feature-specific status commands.

## Dangerous/destructive commands

| Command | Effect and safeguard |
| --- | --- |
| `rm <index|path>`, `del <index|path>` | Confirms, then sends indexed local media to the OS trash; it refuses URLs, directories, and paths outside the indexed library |
| `playlist delete <name> [--yes]` | Deletes a playlist record, not media files; prompts unless `--yes` is supplied |
| `playlist clear <name>` | Clears playlist contents without deleting media |
| `queue clear` | Clears queue occurrences without deleting media |
| `library clean --missing` | Permanently removes missing-file tombstone records, never media files |
| `setup restart` | Resets setup progress while preserving settings, media, history, library data, and preferences |
| `rename short ... --yes` | Renames an indexed media file without prompting; use `--dry-run` first |
| `exit y`, `quit y` | Bypasses only the normal exit confirmation |

## Common workflows

Play local media:

```text
library status
all
1
now
```

Search and play online media:

```text
/ys artist title 5
/yl https://www.youtube.com/watch?v=...
/ml https://soundcloud.com/artist/track
```

Build and navigate a queue:

```text
queue add 4
queue add 9
queue ys "artist title" 5
queue list
autonext on
queue next
```

Download media in the current session:

```text
download-ya current --yes
download-ml https://soundcloud.com/artist/track mp3
download-ya status
```

Seek and fade:

```text
seek +30s
seek 50%
fade to 35 in 3
fade out 10
```

Inspect and maintain the library:

```text
library roots
library scan changed
library status
library errors
```

Enable privacy-scoped Discord presence, then disable it:

```text
discord presence status
discord presence track
discord presence off
```

Inspect runtime health:

```text
tools status
setup status
library verify
help diagnostics
```

## Desktop terminal behavior

In the Electron terminal, Ctrl+C copies selected text. With no selection it
sends an interrupt to the Mariana PTY. When a secondary terminal view exits,
that view closes cleanly and a remaining view becomes active; the desktop
restart action explicitly starts a replacement session.

## Compatibility aliases and retired commands

These testing-snapshot aliases remain recognized and route to modern behavior:

| Aliases | Behavior |
| --- | --- |
| `.`, `.*` | Show the current media name or full reference |
| `+`, `-`, `.+`, `.-` | Historical next/previous display or play forms |
| `.arand`, `=arand`, `arand`, `arand*`, `/arand` | Historical random-media forms |
| `mute` | Alias for `m` |
| `vh`, `volh`, `volumeh` | Player-volume compatibility forms |
| `dl-yv`, `dl-ya`, `dl-ml` | Download command aliases |
| `/ysq` | Queue the selected YouTube search result without starting playback |
| `/reddit-session`, `/reddit-sessions`, `/rpan` | Recognized retired RPAN forms; no network action occurs |

`beta [on|off]` remains recognized and explains that formerly gated features
are always available. Misspelled download commands offer a correction and do
not execute. The legacy Google Drive `weblinks` collection and RPAN service are
retired; use radio, queue, and supported online-source commands instead.
