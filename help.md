## About This Help

EBNF metasyntax is used for syntax formatting here.
Lines written after a \` `#` \` symbol are not of any importance, they are stale unimplemented features or future ideas.

Show commands shows files matching query in 4 columns by default.
This can be changed in the config file.

All searches are fuzzy

**Basic syntax rules are summarized as follows:**

| Command             | Description                        |
| ------------------- | ---------------------------------- |
| this \| that        | Option between values              |
| optional_ie_0_or_1? | Optional value                     |
| zero_or_more\*      | Value may occur zero or more times |
| one_or_more+        | Value may occur one or more times  |

<br>

## Controls/Commands

### Persistent queue, radio, and recommendations

| Command | Description |
| --- | --- |
| `queue add <media>` | Add a library index, path, or URL |
| `queue insert/remove/move/swap/jump` | Mutate queue order transactionally |
| `queue list/clear/reset/undo/redo` | Inspect, customize, or restore the ordered library queue |
| `queue shuffle [seed]` | Reproducible shuffle |
| `queue repeat off\|one\|all` | Set repeat mode |
| `queue save/load <name>` | Persist or restore a named queue |
| `queue tree` | Display one-based hierarchical paths and durable node IDs |
| `queue group create/rename/move/remove/atomic` | Manage nested queue groups (maximum depth: eight) |
| `queue order sequential\|shuffle\|priority\|artist-fair\|smart\|custom [--group <path>] [--seed N]` | Reorder upcoming nodes without restarting the active track |
| `queue priority <path> <integer>` / `queue dedupe identity\|uri` | Set stable priority or remove duplicate occurrences |
| `playlist list/create/show/rename/delete/clear` | Manage versioned local playlist snapshots |
| `playlist add/remove/move/order` | Edit media, album, playlist, and nested-group content |
| `playlist play/queue <name> [--flatten]` | Replace playback or append an atomic snapshot |
| `playlist import <name> <m3u\|m3u8\|YouTube-playlist-URL>` | Import a snapshot without modifying its remote source |
| `playlist export <name> <path.m3u8>` | Export canonical references as portable UTF-8 M3U8 |
| `album search <query> [--scope local\|online\|hybrid] [--limit N]` | Find distinct local/MusicBrainz release editions |
| `album show/tracks/fetch <album-ref>` | Inspect or refresh one edition and its resolution status |
| `album play/queue <album-ref> [--order release\|shuffle\|smart\|custom] [--tracks <selector>]` | Play or enqueue a complete/selected multidisc album |
| `album save <album-ref> <playlist-name>` | Save the resolved edition as a versioned playlist |
| `radio search/list/play/favorite/refresh/health` | Discover and validate stations |
| `radio add/info/metadata/resync` | Import or inspect a direct station and restart at the live edge |
| `radio leveling on\|off\|status` | Control dynamic loudness leveling for live streams |
| `radio credentials set\|delete\|status <station> [username]` | Reference private-stream credentials in the OS keychain |
| `library roots/status/errors/verify` | Inspect the incremental local-library index |
| `library scan [changed\|full]` | Reconcile configured `lib.lib` roots |
| `library pause/resume/retry` | Control or retry background profiling |
| `library info <index\|path>` | Show indexed metadata and profiler state |
| `library clean --missing` | Remove tombstones only; never delete media files |
| `sleep <duration> [pause\|stop] [fade <duration>]` | Fade near expiry, then pause or stop |
| `sleep status\|cancel` | Inspect or cancel the session sleep timer |
| `replaygain on [track\|album\|auto]` | Enable non-destructive loudness normalization |
| `replaygain off\|status\|verify\|mode\|preamp\|scan\|rescan` | Verify rsgain, configure policy, or analyze loudness data |
| `broadcast profiles\|start\|stop\|test\|status` | Control one Icecast source broadcast |
| `broadcast credentials set\|delete\|status <profile>` | Manage a broadcast password through the OS keychain |
| `tools status\|setup\|install\|repair` | Inspect, discover/configure, or provision checksum-verified media tools |
| `discord presence off\|app\|track\|session\|status\|refresh` | Control optional, privacy-scoped Discord desktop Rich Presence over local RPC |
| `youtube auth status` | Show the browser profile reference used by all YouTube operations |
| `youtube auth set <browser[:profile]>` | Use a signed-in local browser profile; `firefox` is recommended first |
| `youtube auth clear` | Return YouTube operations to anonymous access |
| `youtube auth test <YouTube URL>` | Test extraction without displaying or persisting the signed stream URL |
| `recommend [count]` | Show explainable local recommendations |
| `recommend autofill [count]` | Add recommendations to the queue |
| `recommend related [count]` | Recommend from the active media context |
| `like` / `dislike` | Set the current item to favorite or blocked |
| `fav`, `fav !`, `fav +`, `fav -` | Inspect, toggle, set, or clear favorite state |
| `bl`, `bl !`, `bl +`, `bl -` | Inspect, toggle, set, or clear blocked state |
| `favs [count]` / `blacklist [count]` | List persistent media preferences |
| `hist` / `history [count]` | Show persistent playback history or its count |
| `open hist` / `open history` | Open persistent history in the configured editor |
| `include downloads` / `exclude downloads` | Toggle Mariana's managed download root without editing `lib.lib` |
| `lyrics edit` / `lyr edit` | Edit an adjacent `.lrc`, with confirmation before cached lyrics create one |
| `rm <index\|path>` / `del <index\|path>` | Confirm and send indexed local media to the operating-system trash |
| `setup status\|resume\|restart\|repair` | Inspect or recover transactional first-run setup |
| `download-ml <URL> [format] [path]` | Bounded custom-media download |
| `download-ya [current\|YouTube-URL] [--track] [--quality best\|worst] [--to <directory>]` | Download exactly one active/referenced track |
| `download-ya --album [current\|album-ref\|YouTube-playlist-URL] [--tracks <selector>] [--missing-only] [--allow-partial] [--yes]` | Explicitly create a resumable complete-album job |
| `download-ya status [job-id]` / `pause\|resume\|cancel <job-id>` | Inspect or control persistent download work |

Seeking applies only when the active source reports that capability. Use radio
resync to restart a live stream at its current edge.

### Testing-snapshot compatibility aliases

These aliases are retained by the machine-readable compatibility registry and
route through the same modern implementations:

| Aliases | Modern behavior |
| --- | --- |
| `.`, `.*` | Show the current media name or full reference |
| `+`, `-`, `.+`, `.-` | Next/previous display or play behavior |
| `.arand`, `=arand`, `arand`, `arand*`, `/arand` | Historical random-media forms |
| `mute` | Mute/unmute (`m`) |
| `vh`, `volh`, `volumeh` | Player-volume compatibility forms |
| `download-yv` / `dl-yv`, `download-ya` / `dl-ya`, `download-ml` / `dl-ml` | Download YouTube video/audio or a yt-dlp-supported media link in the current session; omit the URL for YouTube commands to use the active item |
| `/reddit-session`, `/reddit-sessions`, `/rpan` | Recognized retired RPAN forms; no network action |

`all*`, advanced `find`/`rfind`/`lfind` searches, dotted/slashed search
variants, `beta`, and `check_dev` remain recognized. Misspelled download
commands receive a correction message and never execute. The old `weblinks`
collection and `vivojay fav` hard-coded URL are retired with explicit guidance.

### General

| Command   | Description                    |
| --------- | ------------------------------ |
| all       | display all sound files        |
| <number\> | show name of \`number\`th song |

| Command          | Description                                                           |
| ---------------- | --------------------------------------------------------------------- |
| e[xit] \| quit   | stop and exit after confirming, show warning if song is still playing |
| e[xit] \| quit y | stop and exit w/o confirmation, show warning if song is still playing |

| Command          | Description                                                                             |
| ---------------- | --------------------------------------------------------------------------------------- |
| . <filepath\>    | check if \`filepath\` is of a valid supported song file                                 |
| open             | open current song file in Windows File Explorer                                         |
| open <filepath\> | open file at \`filepath\` in Windows File Explorer if it is a valid supported song file |

| Command   | Description                            |
| --------- | -------------------------------------- |
| path <n\> | show path of audio file at given index |
| now       | show currently playing song name       |

### Music Controls Overview

#### Legacy Functions

| Command                                                                                      | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| p                                                                                            | pause/resume                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| s[top]                                                                                       | stop                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| play <number\>                                                                               | play track                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| m                                                                                            | mute/unmute                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| seek <timeobject\> | Seek finite media only. Accepts seconds, `MM:SS`, `HH:MM:SS`, `DD:HH:MM:SS`, `1d 2h 3m 4s`, relative `+30s`/`-2m`, percentages, and `start`/`end`. Relative seeks clamp safely to the playable range. |
| fade in\|out [seconds] | Fade between silence and the current user volume; the default duration is five seconds. |
| fade to <0-100> [in <seconds>] | Fade from the current user volume to a target volume. |
| fade from <0-100> to <0-100> [in <seconds>] | Fade between explicit volumes. Legacy `fade <from> <to> [seconds]` remains supported. |
| reset                                                                                        | Same as seek 0, seeks current song to start, (song play/pause status stays same)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

#### Beta Functions

### Volume

| Commands                            | Description                              |
| ----------------------------------- | ---------------------------------------- |
| v \| vol \| volume <percentage\>    | set player volume to provided percentage |
| v \| vol \| volume                  | show current player volume as percentage |
| mv \| mvol \| mvolume <percentage\> | set system volume to provided percentage |
| mv \| mvol \| mvolume               | show system volume as percentage         |

### Finding / Searching songs

| Commands                                                 | Description                                                  |
| -------------------------------------------------------- | ------------------------------------------------------------ |
| ['f' \| 'find'] "Search Query" [<results_count\> \| all] | Find locally, 10 results by default. Shows all results if "all" is mentioned |

<br>

## Settings
### Functional Settings
- display items count
- maximum youtube-search results count
- loglevel
- visible

### Non Functional Settings
The following settings are never used.
They are available for possible future usage
- show banner
- show about

#### download
**download quality**
It is defined for two kinds of downloads

**Audio Only:**       Sets the quality of audio-only downloads
**Video with Audio:** Sets the quality of video downloads (videos are always downloaded with audio)

A value of 0 for either of these parameters means you want the WORST QUALITY download by default
A value of 1 for either of these parameters means you want the BEST QUALITY download by default

\*NOTE: You may override the download quality directly in the player as well...

### display items count
**general:** number of items to display (general purpose)
**youtube-search results:** number of items to display in YouTube search results
