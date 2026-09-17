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
| `now`, `now*` | Show safe active-media metadata and status; `now*` adds source, queue, seekability, and chapter detail |
| `progress`, `prog` | Show one concise playback-status line with progress and queue position when available |
| `progress*`, `prog*` | Show detailed progress, source, state, seekability, queue position, and chapter |
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

## Video, captions, and chapters

`chapters` and `chapters list` show the complete chapter timeline with the
current chapter marked. `chapter`, `.chapter`, and `.chapters` are aliases.
`chapters current`, `chapters show [N]`, and `chapters find <text>` inspect
metadata without seeking. `chapters N` or `chapters goto N` selects a one-based
chapter. `next`, `prev`, `first`, `last`, `restart`, `+N`, and `-N`
are also supported after `chapters`. Navigation preserves pause state, respects
preferred play-region bounds, and does not wrap. Use `chapters help` for details.

`play <number|path|current> [--audio|--video|--auto]` chooses presentation.
Quote paths containing spaces. Selecting `current` changes presentation without
restarting audio. The same flags work with `/ys`, `/yl`, and `/ml`; for
example, `/ys "concert" 5 --video` preserves the existing result-choice flow.
Explicit video requires the desktop host. YouTube, radio, and live sources stay
audio-first under automatic presentation; local video can be presented when the
desktop video surface is connected. Unsupported picture preparation leaves the
authoritative audio pipeline unchanged.

| Command | Purpose |
| --- | --- |
| `captions`, `captions status` | Show caption availability, selection, language preferences, and offset |
| `captions tracks` | List available embedded, matching sidecar, or resolver-supplied tracks without fetching one merely to list it |
| `captions select N` | Select the numbered track from the current catalogue |
| `captions auto` | Restore automatic selection for the current media |
| `captions language en hi` | Persist ordered language preferences; `captions language auto` clears the preference |
| `captions load "movie.srt"` | Load a user-selected local subtitle file |
| `captions replace "replacement.vtt"` | Explicitly replace the selected subtitle file |
| `captions on`, `captions off`, `captions clear` | Enable, hide, or clear the current caption selection |
| `captions offset 250`, `captions shift -250` | Set an absolute caption delay or apply a relative shift, in whole milliseconds |
| `avsync`, `avsync status` | Inspect picture/audio synchronization offset |
| `avsync set 250`, `avsync shift -100`, `avsync reset` | Set, adjust, or clear synchronization offset without restarting the audio decoder |

`caption` is an alias for `captions`. Positive caption offsets display text
later. Positive `avsync` offsets mean audio is later relative to picture: Mariana
adjusts picture timing against its authoritative audio timeline rather than
creating another audible player. Caption selection and offset preferences use
hashed local-media identity; public control state does not expose local paths or
private resolver URLs. Captions are not generated and no subtitle-search service
is contacted automatically. `help video`, `help captions`, and `help chapters`
provide a compact command guide.

Long finite media can receive a saved resume-position offer after reopening.
Offering a position never seeks automatically; accepting it uses the ordinary
identity-bound seek boundary. Resume records stay in the local database, retain
at most 500 items for one year, and omit paths and transient playback URLs.

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
| `queue clear [y|yes|--yes]` | Confirm and remove all queue occurrences; media files are not deleted |
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
| `find --regex <pattern> [count]`, `find --re <pattern> [count]` | Search the selected collection with a case-insensitive regular expression |
| `.fN <terms>`, `.findN <terms>` | Play the Nth matching result (one-based), collecting at most N matches |
| `find --in favs <terms> [count]` | Search saved favourites |
| `find --in blocked <terms> [count]` | Search playback-blocked media without making it playable |
| `find --in queue <terms> [count]` | Search the current queue without changing its order |
| `find --in playlist "<name>" <terms> [count]` | Search one named playlist in playlist order |
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
play a random playable match. Append a positive result number to a dotted command,
such as `.f3 artist title`, to play that numbered match. The numbered form also
works with `find`, `rfind`/`rf`, and `lfind`/`lf`, including explicit scopes.
Available scopes are `library` (default), `favs`/`favorites`/`favourites`,
`blocked`/`blacklist`, `queue`, and `playlist "<name>"`.
Scoped matching includes trusted title, artist, album, and provenance text.
Results retain collection positions, active-media markers, independent hearts
and stars, local sizes, and detected formats. Immediate selection remains bound
to the displayed media identity and refuses stale collection positions.

Add `--regex` (or `--re`) to interpret the complete query as one case-insensitive
regular expression, for example `find --regex "^(Alpha|Gamma) - Live$"`.
Regex mode also works with scopes and immediate selection. Library searches
match displayed titles; other scopes match their trusted metadata projection.
Expressions are limited to 512 characters; invalid expressions are reported
without changing playback.

Online resolution can fail because of network
availability, authentication, rate limits, geographic restrictions, DRM, or
provider changes. Mariana reports these failures and does not bypass service
protections. `/ml` supports sources that yt-dlp and FFmpeg can access; it is not
a universal authenticated or DRM playback command.

Mariana does not currently provide SoundCloud catalog search, so `queue sc`
and `/scq` are not commands. Known public SoundCloud URLs remain supported by
the extractor-backed `/ml` playback and `download-ml` commands.

### LibriVox audiobooks

LibriVox uses its official, keyless catalog API only after an explicit command.
Search result numbers belong to the latest LibriVox search; use
`id:<catalog-id>` when you need an unambiguous reference that does not depend on
that result list. The short aliases are `lv` and `libri`.

| Command | Purpose |
| --- | --- |
| `librivox help`, `lv help` | Show the complete audiobook command family |
| `librivox status` | Show local result state and the official API reference without making a network request |
| `librivox search <title> [--limit N] [--offset N]` | Search audiobook titles |
| `librivox author <surname> [--limit N] [--offset N]` | Search by author surname |
| `librivox genre <genre> [--limit N] [--offset N]` | Search catalog genre text |
| `librivox recent [days] [--limit N] [--offset N]` | List projects added during a recent time window |
| `librivox show <result|id:ID|current>` | Show project, attribution, source, feed, archive, artwork, and description metadata |
| `librivox chapters <result|id:ID|current>` | List playable sections, readers, languages, and durations |
| `librivox play <result|id:ID|current> [chapter]` | Play a section and append any missing sections from that book to the persistent queue |
| `librivox current` | Show the active/selected book, chapter number, reader, state, and safe stable IDs without a network request |
| `librivox goto <chapter>` | Play a numbered chapter from the current audiobook |
| `librivox next [count]`, `librivox previous [count]` | Move between the current book's separate section files without wrapping; `prev` aliases `previous` |
| `librivox first`, `librivox last` | Play the first or final chapter of the current audiobook |
| `librivox restart` | Seek the current chapter to its start while preserving the controller's playback state |
| `librivox resume` | Resume a paused current chapter, or start the chapter selected by the restart-persistent queue cursor |
| `librivox queue <result|id:ID|current> [chapter|all]` | Append one section or the complete book to the existing queue |
| `librivox download <result|id:ID|current> [chapter|all] [--format mp3|flac|wav|m4a|opus] [--to <folder>] [--yes]` | Confirm and download finite chapter audio through the existing media downloader |
| `librivox rss <result|id:ID|current>` | Open the official project RSS feed |
| `librivox open <result|id:ID|current> [catalog|text|archive|download|rss]` | Open an official project destination or whole-book ZIP link |

Chapter favourites and queued entries use the LibriVox catalog ID plus section
ID within the official project feed. The downloadable MP3 address is transport,
not identity, so an updated archive URL does not turn the same chapter into a
different favourite. LibriVox sections are separate finite audio resources rather
than timestamp markers inside one file: ordinary `seek` and the progress bar move
within a section, while the `librivox goto/next/previous` family moves between
sections. Normal automatic queue advancement applies when autoplay is enabled.
Artwork and descriptions come only from catalog metadata;
Mariana does not scrape book-cover images. See [docs/LIBRIVOX.md](docs/LIBRIVOX.md)
for source, privacy, and availability details.

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
| `download-yv [YouTube URL] [y|yes|--yes]`, `dl-yv ...` | Download YouTube video; omit the URL to use the active YouTube item |
| `download-ya [current|YouTube URL] [--track] [--quality best|worst] [--to <directory>] [y|yes|--yes]`, `dl-ya ...` | Download one audio item |
| `download-ya --album [current|album-ref|YouTube-playlist-URL] [--tracks <selector>] [--missing-only] [--allow-partial] [--quality best|worst] [--to <directory>] [y|yes|--yes]` | Create an explicit album download job |
| `download-ya status [job-id]` | Inspect persistent download work |
| `download-ya pause|resume|cancel <job-id>` | Control a download job |
| `download-ml <current|URL> [mp3|flac|wav|m4a|opus] [output path] [--yes]`, `dl-ml ...` | Download the active finite online item, public extractor-backed page, or direct media URL; an existing output requires confirmation |

Plain `download-ya` means the active track, never the entire album. Complete
album expansion requires `--album`. Downloads run in the current Mariana
session and do not start a nested Mariana REPL. The same external-service
limitations described under online sources apply to extractor-backed downloads.

## Library

`lib.lib` remains the human-editable source of library roots. The incremental
profiler stores its catalog and resumable work in Mariana's writable SQLite
database.

Use `ls all` or `ls *` for the whole library, or a case-insensitive title
expression such as `ls "^Alpha|Gamma$"` to filter it. `recents` accepts the same
filtering syntax. Existing count, index, numeric range, `o`, and `desc` forms
remain available; hyphens inside a pattern are not numeric ranges.

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
| `library clean --missing [y|yes|--yes]` | Confirm and remove missing-file tombstones only; never delete media |
| `reload` | Refresh the legacy library projection from the current index |
| `include downloads`, `exclude downloads` | Add or remove Mariana's managed download root without editing user roots |
| `rename short [current|index|path] [--dry-run] [y|yes|--yes]` | Preview a confidence-labeled rename from trusted metadata; placeholder-only or equivalent proposals are refused |
| `replaygain scan [changed|full]`, `replaygain rescan <index|path>` | Queue non-destructive loudness analysis |
| `rating`, `rating current` | Show the current media rating (zero means unrated) |
| `rating <1-5>`, `rate <1-5>` | Rate the current media with one to five stars |
| `rating clear` | Clear the current media rating |
| `rating <current|library-index> <1-5|clear>` | Set or clear a durable rating for current or indexed media |
| `ratings [count]` | List positively rated media, highest ratings first |
| `rating show <rated-index>` | Inspect one entry using its stable number from `ratings` |
| `.rating <rated-index>` | Immediately play that rated entry |
| `fav`, `fav current` | Inspect the current media's saved-favourite heart without changing it |
| `fav +`, `fav -`, `fav !` | Add, remove, or toggle the heart; preserve stars and block policy |
| `favs [count]`, `fav list` | List saved favourites, whether rated or unrated |
| `fav <favorite-index>`, `.fav <favorite-index>` | Inspect or immediately play an entry from the favourite list (not the rated list) |
| `block current`, `block <library-index>` | Block future playback without hiding, deleting, or unfavouriting the media |
| `unblock <library-index|current>` | Restore playback eligibility |
| `blocked`, `blocked list`, `blocked <count>` | List playback-blocked media; legacy `blacklist` remains an alias |
| `region <current|library-index> <start> <end>` | Save both non-destructive preferred playback bounds |
| `region <current|library-index> start <time>` | Change ONLY the starting bound; preserve the saved ending bound |
| `region <current|library-index> end <time>` | Change ONLY the ending bound; preserve the saved starting bound |
| `help region`, `region help` | Show complete region syntax, examples, and validation rules |
| `region show <current|library-index>` | Show the saved preferred play region |
| `region clear|clear-start|clear-end <current|library-index>` | Clear both bounds or one bound |
| `regions` | List saved preferred play regions without revealing paths |
| `bl [!|+|-]`, `like`, `dislike` | Compatibility forms for active-media preference changes |

Unavailable roots do not block startup. Missing media remains as history-aware
tombstones until explicitly cleaned.

Hearts and stars answer different questions: **a heart saves a favourite** for
quick access; **one to five stars assess the media**, with zero meaning unrated.
Neither implies the other: an unrated favourite and a rated non-favourite are
both valid. Clearing stars leaves the heart; removing the heart leaves stars.
Blocking remains independent of both. `rate` is the short alias for `rating`.
The desktop footer exposes both controls and waits for backend-confirmed state.
Both use the same durable media identity; transient generic URLs remain ineligible.

Upgrades preserve saved hearts and explicit star values. Older heart-only records
remain unrated rather than receiving an invented five-star assessment. If a prior
development build already stored both values from one action, both are retained:
the original intent cannot be inferred safely, so either can now be cleared independently.

Local media rows in library/search, favourites, rated-media, blocked, queue, playlist,
recommendation, station, region, album-track, and recent listings include a
human-readable file size plus the FFprobe-detected container/audio codec (for
example `WebM / Opus`). `Unknown` means the profiler has not established the
actual format; Mariana does not infer it from the filename extension. These
media tables show a heart (`♥`) in `Fav` for saved favourites and independent
stars in `Rating`; an empty star cell means unrated. Only the favourite list omits
the redundant heart column. It retains stars because its entries may be unrated
or have different assessments. Favourite and rated lists have separate index spaces.
`▶` in the `Now` column marks the authoritative active item across these media
lists while it is playing or paused. The marker is bound by stable identity, so
matching titles or stale search/queue indices cannot highlight the wrong row.

Blocking is a playback policy, not deletion or hiding. Blocked items remain in
the library, searches, ratings, and queue with a `Blocked` marker. Direct
play refuses them; random and automatic queue traversal skip them. Bare numeric
targets in `block N` and `unblock N` always mean library indices.

Preferred play regions do not trim or rewrite media. A start-only region begins
at its saved timestamp; an end-only region completes through the normal queue
path at that timestamp; two bounds do both. Times accept `5.180`, `5.180s`,
`00:05.180`, `1:05:03.180`, `1h5m3.180s`, or spaced forms such as `1h 5m 3s
180ms`. Quote a spaced timestamp when using the two-bound form. Region commands
require finite media with a known duration, bind bare numbers to library indices,
and never alter the source file. Blocking remains independent and takes
precedence over a saved region.

For example, `region current start 0:30` changes only the start to 30 seconds;
`region current end 3:45` changes only the end to 3 minutes 45 seconds. Use
`region 12 start 5.180` to change the start of library item 12 instead of the
active track. If the other bound has never been set, it remains unset (the
natural beginning or end). A lone unlabeled timestamp is refused: explicitly
write `start` or `end` so there is no ambiguity. Invalid updates leave both
saved bounds unchanged. Bounds persist across restarts and apply on the next
playback start; saving them does not interrupt or seek the current playback.

## Playlists

| Command | Purpose |
| --- | --- |
| `playlist list` | List local versioned playlists |
| `playlist create <name> [--description <text>]` | Create a playlist |
| `playlist show <name> [--tree]` | Show tracks or nested structure |
| `playlist rename <old> <new>` | Rename a playlist |
| `playlist delete <name> [y|yes|--yes]` | Delete the playlist record after confirmation unless a bypass token is supplied |
| `playlist clear <name> [y|yes|--yes]` | Confirm and remove all playlist contents |
| `playlist history <name>` | Show the current and retained playlist revisions |
| `playlist restore <name> <revision> [--yes]` | Confirm restoring an earlier tree as a new revision; retain the current tree in history |
| `playlist add <name> media <reference> [<reference> ...] [--at <path>]` | Add one or several library indexes, local paths, or media URLs as one playlist revision |
| `playlist add <name> album|playlist <reference> [--at <path>]` | Add an atomic album or nested-playlist snapshot |
| `playlist remove <name> <path>` | Remove a node |
| `playlist move <name> <path> --parent <path|root> [--at N]` | Move a node |
| `playlist order <name> <strategy> [--group <path>] [--seed N]` | Apply a queue-compatible strategy |
| `playlist play <name>` | Replace the active queue and begin playback |
| `playlist queue <name> [--at next|end|N] [--flatten]` | Add a snapshot to the current queue |
| `playlist import <name> <m3u|m3u8|YouTube-playlist-URL>` | Import a snapshot without modifying its remote source |
| `playlist export <name> <path.m3u8> [--yes]` | Export canonical references as UTF-8 M3U8; an existing file requires confirmation |
| `transfer copy to playlist <name> from playlist <name> items <selection> [...]` | Copy ordered selections from one or several playlists in one atomic command |
| `transfer move to playlist <name> from favs items <selection> [--yes]` | Move favourites to a playlist; destructive moves confirm unless `--yes` is supplied |
| `transfer copy|move to favs from playlist <name> items <selection> [...]` | Add selections from one or several playlists to favourites; `move` also removes the source rows |
| `transfer ... --dry-run` | Preview every selected row and destination without changing any collection |

Local M3U/M3U8 imports must be valid UTF-8 (an optional BOM is accepted), at most
8 MiB, with no more than 5,000 media entries and 64 KiB per line. Tabs and ordinary
line endings are supported; malformed text or oversized input is rejected before
any playlist is written. Importing references does not fetch or play them, and a
missing local file remains an explicit reference rather than being substituted.

Transfer item selections use the one-based row numbers shown by `playlist show <name>`
or `favs`. Combine indexes and inclusive ranges with commas, such as `1,2,6`,
`3-5,9`, or use `all`. Each additional source begins with another `from` clause:

```text
transfer copy to playlist "playlist7" from playlist "playlist1" items 1,2,6 from playlist "playlist4" items 3,9
transfer move to favs from playlist "playlist1" items 1-3 from playlist "playlist4" items 3,9 --yes
transfer copy to playlist "Road trip" from favs items 1-5 --dry-run
```

`copy` leaves every source unchanged. `move` is atomic: either all selected rows move,
or no collection changes. Use the existing `playlist move` command to reorder nodes
inside one playlist.

Playlist edits bind the original playlist ID and revision. A concurrent edit or
rename rejects the stale operation without overwriting newer contents. History
survives restarts; restore recovers tracks, nesting, and ordering, not an old
playlist name or description. Deleting a playlist still deletes its history.

## Tags and tag-result playback

`tag` lists definitions; `tag help` explains the complete family. For example:

```text
tag create "Late night"
tag attach current "Late night" instrumental
tag show current
tag find --all instrumental --not live
tag play 1
tag queue 2
tag detach current instrumental
tag group create "Quiet music"
tag group add "Quiet music" ambient instrumental
tag find --group "Quiet music"
```

Attach/show targets are the current durable item or a library number. Play/queue
numbers refer specifically to the last tag result set, bound by media identity.
They are not interpreted as changing library indexes. Tags do not rewrite media
files or change ratings/block policy. Deleting an in-use tag requires explicit
confirmation. See [tags and reusable groups](docs/TAGS.md) for every operation.


## Lyrics

| Command | Purpose |
| --- | --- |
| `lyrics`, `lyr` | Display lyrics for the active item |
| `lyrics edit [y|yes|--yes]`, `lyr edit ...` | Edit an adjacent `.lrc`, confirming before cached lyrics create one |
| `open lyrics`, `open lyr` | Open the current lyrics file in the configured editor |

Resolution prefers embedded or adjacent local lyrics, then cached or provider
results. Missing identities or provider records produce a clear no-lyrics
result; Mariana does not fabricate lyric text.

## Local session recipes

Use `session record <name>` to start an opt-in local listening recipe, then
`session stop` to seal it. `session status` reports preparation, recording,
replay, errors, and incomplete capture. `session list` lists names;
`session inspect <name>` validates and describes one without playing anything.

`session play <name>` asks before replacing current playback and the queue.
Use `--yes` only when you explicitly intend that replacement. During replay,
`session seek <seconds|mm:ss|hh:mm:ss>` restores effective recipe state and
`session stop` stops replay. Ordinary playback/queue controls remain guarded.

Replay supports verified finite local files and freshly verified public YouTube
identities in flat or nested queues. Missing/changed provider identity or duration stops
replay; no other recording is substituted. Generic URLs/podcasts and preferred
regions are not supported for replay. Version-three recipes also restore supported
two-source equal-power crossfades and their frozen program gains. Nested groups,
effective order, duplicate occurrences, seeds and policies are preserved; private
group names are replaced with generated labels. Older recipes are validated and
upgraded in memory without modifying the original file.
Source seeks or gain-setting changes during an overlap remain unsupported;
use recipe-relative seeking to restore an already recorded mix. Stop active sleep,
station, Focus, loop, and stem sessions first. No audio recording, terminal
commands, paths, signed URLs, deletion, downloads, or credentials are stored in
the journal. ReplayGain settings are included; local EQ and volume are not.
See [Session recipes](docs/SESSION_RECIPES.md) for exact limits and timing behavior.

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
| `radio credentials set|status <station> [username]` | Store or inspect private-stream credentials in the OS keychain |
| `radio credentials delete <station> [y|yes|--yes]` | Confirm and delete a private-stream credential |
| `broadcast profiles|start|stop|test|status` | Control one configured Icecast source broadcast |
| `broadcast credentials set|status <profile>` | Store or inspect broadcast credentials in the OS keychain |
| `broadcast credentials delete <profile> [y|yes|--yes]` | Confirm and delete a broadcast credential |

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
Mariana packages its public Discord Application ID; users do not configure an
application, secret, token, or account. `status` distinguishes not configured,
the local RPC dependency being unavailable, Discord Desktop being absent, and
a lost transport that is retrying. If it reports connected but no activity is
visible, check Discord's Activity Privacy setting. Discord absence or failure
never affects playback or startup.

## Settings

| Command | Purpose |
| --- | --- |
| `theme aurora|windows|kitty|gruvbox` | Select a terminal preset |
| `theme list`, `theme current` | List presets or show the active one |
| `banner status`, `banner show` | Inspect occasion greeting policy or redraw the startup banner |
| `banner occasions on|off` | Enable or disable date-aware greetings without hiding the normal banner |
| `banner country auto|<ISO>` | Use the operating-system region or an explicit two-letter country code |
| `banner subdivision <code|none>` | Select a supported state/province calendar; an invalid code lists available choices |
| `banner country detect [--yes]` | Confirm a country-only network lookup, then save that country; never runs automatically |
| `banner preview YYYY-MM-DD`, `banner help` | Preview an occasion palette/greeting or explain calendar controls |
| `desktop close [tray|quit|status]` | Hide to the system tray on window close (default), quit on close, or show the current policy |
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

### Personal interaction hotspots

Local interaction history is disabled by default. It stores successful play,
pause, and seek actions, not listening duration or global popularity.

```text
hotspots status
hotspots enable
hotspots disable
hotspots retention 90
hotspots logging on
hotspots clear --yes
hotspots current 10 linear
hotspots current 10 log1p
```

Retention accepts 1–3650 days. Disabling capture retains existing history; clearing
requires explicit confirmation. Ordinary logging is optional and independent of
structured persistence. See [capture and aggregation](docs/PERSONAL_INTERACTION_HOTSPOTS.md)
for privacy, overflow, shutdown, and normalization behavior. The visual overlay is
a separate delivery.

## Diagnostics

| Command | Purpose |
| --- | --- |
| `now`, `progress` | Inspect active playback |
| `media info|probe|metadata [current|index|path]` | Show catalog and FFprobe metadata |
| `media fingerprint [current|index|path] [--full]` | Show or calculate a Chromaprint fingerprint |
| `media identify [current|index|path]` | Resolve a conservative AcoustID/MusicBrainz identity |
| `media local-match current` | Check for exactly one strong indexed local copy without network lookup or playback substitution |
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
| `rm <index|path> [y|yes|--yes]`, `del ...` | Confirms, then sends indexed local media to the OS trash; it refuses URLs, directories, and paths outside the indexed library |
| `playlist delete <name> [y|yes|--yes]` | Deletes a playlist record, not media files; prompts unless a bypass token is supplied |
| `playlist clear <name> [y|yes|--yes]` | Confirms before clearing playlist contents without deleting media |
| `queue clear [y|yes|--yes]` | Confirms before clearing queue occurrences without deleting media |
| `library clean --missing [y|yes|--yes]` | Confirms before permanently removing missing-file tombstone records, never media files |
| `setup restart [y|yes|--yes]` | Confirms before resetting setup progress while preserving settings, media, history, library data, and preferences |
| `rename short ... [y|yes|--yes]` | Renames an indexed media file without prompting when bypassed; use `--dry-run` first |
| `refresh all [y|yes|--yes]` | Confirms before refreshing library metadata and related state |
| `lyrics edit [y|yes|--yes]` | Bypasses only creation of a missing adjacent `.lrc`; editing an existing sidecar needs no prompt |
| `exit|quit [y|yes|--yes]` | Bypasses only the normal exit confirmation |

Confirmation tokens are command-scoped; Mariana never strips a trailing `y` or
`yes` globally. Bare forms are recognized only as a final, unambiguous argument.
If a playlist, album reference, or indexed path is literally named `y` or `yes`,
leave it in the normal positional slot and use `--yes` as the bypass flag.

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
