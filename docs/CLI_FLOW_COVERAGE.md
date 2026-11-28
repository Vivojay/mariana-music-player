# Native command coverage in paired Flow

Pair with `web session flow --trust --share-output` at the Mariana terminal. The browser uses the active native listener's playback engine, settings, queue, database and command dispatcher. Start with `web session flow` for per-command approval. The tab keeps the browser interface, while native prompts and windows stay with the host.

## What you can control directly

| View | Controls backed by native Mariana |
| --- | --- |
| Player | Play and pause, previous and next, ±10 seconds, a scrubber for seekable media, player volume and mute, speed, a binary favourite, independent star rating, queue shuffle and repeat. Seek sends the final position after drag or keyboard input. The native handler rechecks the playback occurrence and seekability. |
| Home | The existing Home service, local overview when shared, cached/provider news and picks, cached publisher thumbnails, culture links, programme and release selection, and explicit refresh. Online fetches require the native online-discovery preference. The Electron **Home** button reopens the native panel. |
| Local library | Search the host's indexed recordings and play, queue or find similar items. Library browsing is chosen when pairing. |
| Similar | Compare an indexed local recording by audio and tags, audio, tags, or fingerprint. Inspect the evidence, play or queue a result, and request the next analysis batch. |
| Queue | Current native ordering, groups, playback, move within a group, remove, shuffle and repeat, consume and autofill, clear and undo/redo. The clear operation uses the native confirmation. |
| Playlists | Saved playlists with their revisions, track previews, play and queue. |
| Albums | Indexed local albums and saved editions, playable track or album selections, and add to queue. |
| Likes | Native saved favourites and playback of a selected item. Stars are a separate playback preference. |
| Live | Native radio stations, favourites, and live playback. The player displays the live clock without a scrubber. |
| Commands | Search the installed catalog by category, canonical name, command form or alias. The console and this editor share native command assistance, the dispatcher and a tab-local history. |

Collection and discovery actions use the native stores. A selection made against an earlier ordering or revision can be rejected after the corresponding collection changes. The tab receives display data and selection identifiers. Host paths and provider credentials stay with the host.

## CLI access and graphical coverage

| Native feature family | Paired availability |
| --- | --- |
| Playback, library, tags, search, queue, groups, playlists, albums, favourites, ratings, radio | The dispatcher accepts command forms supported by the current native version. The table above lists the graphical workflows in this patch. Advanced group construction, bulk operations and library administration use commands. |
| Online sources, news, artist discovery, recommendations, subscriptions, podcasts and audiobooks | Home and Live cover their stated workflows. Search and provider-specific features use the native commands and each service's configured credentials and consent. |
| EQ, effects, tone and stored scores, wavetable bank, Strudel, stem tools | Use the native command catalog. Device-dependent playback, microphone access, file pickers and editor windows remain on the host. |
| Video, filters, chapters, lyrics, karaoke, clips, DJ | Use native commands and the native host for output. Full picture, timeline annotation, karaoke stage, DJ mixing and per-feature controls need dedicated paired widgets. |
| Accounts, profiles, downloads, sessions, jams, fan rooms, updates and diagnostics | Use the native command catalog. Progress, device authorization or prompts can run on the host. Requests remain subject to that player's current policy. |
| System-specific and destructive commands | Existing native confirmations, blocked media checks, Focus mode, compatible tools, provider gates and session-replay rules still apply. |

Use **Console** for the native prompt, command input in the same scrollback viewport, actual supported ANSI styles, keyboard history and command completion. Its backend dispatches native commands and returns approved command output. Continuous raw TTY streams, full-screen terminal programs, arbitrary cursor control and interactive native subprocesses remain on the host.

The standalone web player has a browser-owned library, local imports, links and its own command subset. Pairing grants access to the native computer's collections without migrating them to the portable website. Neither connection works as a remote-account synchronization service.

## Verification and Git handoff

The Chromium check used the actual paired HTTP server and native dispatcher. It previewed three drag positions and sent one exact 37.25-second seek to a paused FFmpeg-backed recording. Shuffle changed in the shared queue, and switching to Console kept the native command editor in its viewport. The native audio test used a clocked test sink. The dedicated collection check exercised queue reordering, playlist queueing, album drill-down, favourites and live radio. The Home check used a cached news and programme fixture. Restarting the Electron source app on Windows remains a target-specific check.

The Find Similar Chromium check used the paired HTTP server and a two-recording SQLite library. Both the library row and the player opened matching results. Queue submitted the selected recording's exact library key. Native regression tests also rejected stale library ordering, mismatched playback, and pairing without library sharing.

- The checkout for this patch starts at the supplied Pairing and Video patch. It is reconstructed for testing. Apply this patch to the actual Windows development checkout before committing the corresponding branch.
- Start the native player and pair Flow. Seek in one drag, set player volume, like a recording, shuffle or repeat the queue, browse the collections and switch to Console. When sharing output, use `help` or `now` from Console.
- Run `git status --short --branch`, `git remote -v` and `git diff --stat` in the development checkout before staging earlier or current changes for publication. Check the active branch and destination first. The patch installer never stages or publishes code.

[Surface policy](SURFACE_PARITY.md) · [Collections](WEB_COLLECTIONS.md) · [Homepage](ARTIST_DISCOVERY.md)

[Similarity modes and indexing](MEDIA_SIMILARITY.md)
