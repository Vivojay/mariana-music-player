# Verification matrix

Latest recorded run: [2026-07-17](verification/2026-07-17.md).

The verified [v0.7.0-dev.6 prerelease](https://github.com/Vivojay/mariana-music-player/releases/tag/v0.7.0-dev.6)
is unsigned Windows x64 only. It is not the stable release.

## Current capability evidence

| Area | Deterministic evidence | Live/native evidence | Release state |
|---|---|---|---|
| Local/HTTP/HLS playback | Resolver, decoder, seek, truncation, retry, cleanup, real FFmpeg fixtures | Speaker, device loss, sleep/resume | Native pending |
| YouTube and podcasts | Mocked extraction, expiry, metadata, feed caching, failure typing | Scheduled public probes | Live environment-dependent |
| Radio and ICY | Playlist recursion, metadata blocks, failover, health/backoff | SomaFM/Antenne probes and network-loss exercise | Live environment-dependent |
| Hierarchical queue/playlists | Tree depth/cycle/orphan invariants, flat migration, atomic groups, six deterministic strategies, cursor stability, undo/redo, versioned CRUD, M3U/YouTube snapshot import and export | Long mixed-session restore | Soak pending |
| Albums/download jobs | Edition separation, multidisc selectors, local preference, typed ambiguity/partial policy, verified YouTube fallback, single-versus-album safety, persistent progress, pause/resume/cancel and recovery | Live MusicBrainz/YouTube resolution and long download interruption | Live/soak pending |
| Library profiler | Incremental scans, moves, duplicates, watchers, leases, rollback, corruption | Large library and disappearing share | Soak/native pending |
| Identity and lyrics | Chromaprint fixtures; missing-fpcalc typed failure; mocked AcoustID, MusicBrainz, LRCLIB | Credentialed/public-domain probe | Credentials pending |
| ReplayGain | Tag parsing, album grouping, clipping, executable verification, immutable-media assertion | Audible A/B and rsgain tool check | Audible A/B pending |
| Icecast broadcast | Authentication tunnel, redaction, Opus/MP3 decode, reconnect | Configured remote server | Credentials pending |
| Recommendations | Ranking, negatives, diversity, persistence, explanations | Long-session taste review | Manual pending |
| Setup | Atomic state/lock, interruption, corruption, tool discovery/provisioning, optional-step failure, existing-install migration, relaunch | Four Windows packaged first-run/recovery scenarios plus native verified-tool bootstrap | Cross-platform package pending |
| Preferences/removal | Tri-state migration/idempotence, recommendation filtering, trash-only failure/recovery | Native recycle-bin restoration | Native restore pending |
| Electron/PTTY | 12 Vitest tests and 2 development PTY scenarios | 6 Windows packaged scenarios; native PTY passed on Windows, macOS ARM64, and Linux; signed multi-OS package pending | Source-native and Windows unpacked passed; signing pending |
| OTA/update | Preflight, safety state, checksum and migration contracts | Signed N to N+1 on every target | Signing pending |

No row marked pending may be represented as passed in release notes. External
unavailability is recorded separately from Mariana defects.

## June 2022 testing-repository command audit

Audited source: `mujcentral/mariana-music-player-testing` at `2302501`
(2022-06-12). Its unrelated Git history was not merged. Every externally
reachable command family is classified below; none is unreviewed.

| Snapshot command or alias | Classification | Current disposition |
|---|---|---|
| `exit`, `quit`, confirmed exit | Native | Clean supervised shutdown |
| `all`, `all*`, `list`, `ls`, numeric input, `play` | Native | Database-backed library projection and FFmpeg playback |
| `. <path>`, dotted numeric/path forms, `/open`, `open`, `view`, `path` | Modernized | Capability validation and cross-platform open/reveal adapters |
| `fav`, `fav !`, `fav +/-`, `favs` | Modernized | Persistent favorite/neutral state in SQLite |
| `bl`, `blacklisted`, `bl !`, `bl +/-`, `blacklist` | Modernized | Persistent blocked/neutral state; blocked items excluded from autofill |
| `last`, `last played`, `recent`, `recents`, `hist`, `history`, `open history` | Modernized | Writable persistent history/recents |
| `pod`, `podbean`, `pods`, `podbeans`, RSS forms | Modernized | Feedparser adapter, conditional caching, typed failures |
| `include/exclude downloads`; all historical `reload` spellings | Modernized | Separately identified managed download-library root; `lib.lib` preserved |
| `beta [on\|off]` | Compatibility-only | Formerly gated capabilities are always available |
| `check_dev` | Compatibility-only | Read-only development-status response |
| `refresh`, `refresh all`, `refresh lyrics`, `reload`, `sync media` | Modernized | Incremental library/lyrics refresh paths |
| `prev`, `next`, `-`, `+`, `.-`, `.+` | Native/compatibility | Queue navigation and historical display/play aliases |
| `.`, `.*`, `now`, `now*` | Native/compatibility | Current-media display |
| `output device`, `input device` | Native | Current OS endpoint reporting; Windows Core Audio/WASAPI mapping; active default-device auto-follow; typed unavailable response |
| `fade`, `fade in`, `fade out` | Native | Validated in/out/to/from-to and legacy numeric PCM gain automation |
| `m?`, `ism?`, `ispl`, `isplaying?`, `isloaded?` | Compatibility-only | Playback-state inspection |
| `seek`, `reset`, `t`, `prog`, `progress` | Native | Sample-derived progress; seconds, clocks, labeled durations, relative units, percentages, and start/end; seek only for verified finite sources |
| `download-*`, `dl-yv`, `dl-ya`, `download-ml` | Modernized | yt-dlp/FFmpeg downloader; misspellings only suggest a correction |
| `.rand`, `=rand`, `rand`, `rand*`, `/rand` and all `arand` forms | Native/compatibility | Current library random selection |
| `clear`, `cls`, `p`, `ph`, `s`, `stop`, `m`, `mute` | Native | PTY-safe terminal and playback controls |
| `count`, `howmany`, `total`, `l`, `len`, `length`, `lib`, `library` | Native | Current library/progress projections |
| `find/f`, `rfind/rf`, `lfind/lf`, dotted/slashed forms | Modernized | Normalized all-term, literal-number, loose any-term, first/random actions |
| `rm`, `del` | Modernized | Indexed local files only; confirmation plus Send2Trash; no permanent fallback |
| `v`, `vol`, `volume`, `vh`, `volh`, `volumeh` | Native/compatibility | Player-volume bus |
| `mv`, `mvol`, `mvolume` | Modernized | Platform master-volume adapter or explicit unsupported response |
| `music-downloads`, `md` | Native | Opens the managed download directory |
| `/ys`, `/youtube-search`, `/yl`, `/youtube-link` | Modernized | Resolve-at-play-time yt-dlp adapter |
| `youtube auth status/set/clear/test` | Native | One non-secret browser reference shared by search, validation, playback, and downloads |
| `/ml`, `/media-link` | Modernized | Unified direct HTTP(S)/file resolver |
| `/wra`, `/webradio` | Modernized | Radio catalog, playlist resolution, health and endpoint failover |
| `/rs`, `/reddit-session`, `/reddit-sessions`, `/rpan` | Retired | RPAN is gone; all aliases return the same explicit response |
| `lyrics`, `lyr`, `lyrics edit`, `lyr edit` | Modernized | Open identification/LRCLIB and durable adjacent `.lrc` editing |
| related-song behavior | Modernized | `recommend related [count]` and contextual queue autofill; no ShazamIO |
| `weblinks` | Retired | Old Google Drive URL collection replaced by radio search and queues |
| `vivojay fav`, `vivojay favourite` | Retired | Expired hard-coded URL removed; guidance points to preferences/recommendations |
| Obsolete commented/TODO-only commands | Demonstrably dead | Not external behavior and not imported |

The aliases in `mariana/commands.py` are the dispatch source of truth and are
checked against `help.md` and parameterized tests.

## June 2022 testing-repository file audit

Every path in the external tree is covered below. “Excluded” means the old
implementation was intentionally not imported; it does not mean its supported
user-facing behavior disappeared.

| External path(s) | Classification | Disposition |
|---|---|---|
| `Future Ideas and Issues to Address.md` | Preserved | Separate user-owned edit; never staged by this integration |
| `README.md`, `help.md` | Modernized | Current architecture, commands, setup, security, and evidence |
| `help_future.md`, `downgrade.txt` | Removed | Stale planning and obsolete dependency downgrade instructions deleted |
| `main.py` | Modernized | Existing command syntax routed into current services |
| `first_boot_setup.py`, `first_boot_welcome_screen.py` | Modernized | Transactional writable setup state and idempotent steps |
| `logger.py`, `restore_default.py`, `url_validate.py` | Modernized | Writable paths, fixed failures, unified resolver validation |
| `meta_getter.py` | Excluded | Replaced by persistent incremental library profiler |
| `requirements.txt` | Modernized | Resolver-generated Python 3.12 locks |
| `settings/settings.yml` | Removed | Stale mutable source-tree instance replaced by the runtime data directory |
| `settings/settings.yml.default`, `settings/system.toml` | Modernized | Packaged defaults use an additive schema and no mutable first-boot flag |
| `user/user_data.yml` | Modernized | Migrated additively into user data |
| `user/reddit_credentials.json` | Removed | Plaintext PRAW credential sample deleted after RPAN retirement |
| `beta/IPrint.py` | Modernized | Current terminal-color compatibility layer |
| `beta/YT_query.py` | Modernized | yt-dlp search adapter |
| `beta/master_volume_control.py` | Modernized | Cross-platform master-volume adapters |
| `beta/mediadl.py` | Modernized | yt-dlp/FFmpeg downloads and managed root |
| `beta/podcasts.py` | Modernized | Feedparser implementation with cache/failure handling |
| `beta/redditsessions.py` | Removed | Historical module deleted; command-registry aliases retain one explicit RPAN retirement response |
| `beta/radio_weblinks.yml` | Excluded | Binary Google Drive collection was not a radio catalog |
| `beta/vlc-async-stream.py` | Excluded | VLC replaced by supervised FFmpeg PCM playback |
| `beta/widget_display.py` | Demonstrably dead | Unused Tk experiment not part of the CLI |
| `beta/yt_urls.yml` | Removed | Expired snapshot deleted; URLs are resolved at playback and never persisted |
| `lyrics_provider/detect_song.py`, `lyrics_provider/get_lyrics.py` | Modernized | Chromaprint/AcoustID/MusicBrainz/LRCLIB pipeline |
| `lyrics_provider/get_related_music.py` | Excluded | Shazam related writer replaced by recommendation engine |
| `lyrics_provider/lyrics_window_spawn.py` | Modernized | Writable generated CSS and current lyrics data |
| `res/banner.banner`, `res/default.css`, `res/first_boot_startup_sound.mp3` | Native assets | Retained as immutable resources |
| External testing snapshot prompt/banner | Modernized | Rich two-line prompt ported; banner verified as the same mirrored blue gradient, with no rainbow asset present |
| `media info/fingerprint/identify/local-match` | Native | Indexed/current metadata, conservative identity inspection, and offline unique local-copy matching |
| `rename short` | Native | Transactional indexed-file rename with collision, extension, rollback, and source-ID safeguards |
| `autoplay`, `autonext`, `queue reset` | Native | Fresh queues mirror library order; direct selection preserves queue identity; custom queues are not overwritten; disabling discards prefetch and retains the completed end position |
| `queue tree/group/order/priority/dedupe`, `playlist *` | Native | Transactional hierarchical groups, deterministic upcoming-item strategies, versioned local snapshots, M3U/M3U8 and explicit YouTube-playlist import |
| `album search/show/tracks/fetch/play/queue/save` | Native | Release-specific local/MusicBrainz catalog, multidisc ordering, conservative local matching, verified canonical YouTube fallback |
| `download-ya --album`, `download-ya status/pause/resume/cancel` | Native | Explicit-only album expansion and persistent sequential jobs; plain `download-ya` remains current-track-only |
| Electron tabs and output search | Native | Shared single PTY, bounded replay history, directional search, and synchronized theme presets |
| `res/lyrics_icon.png`, `res/welcome_banner.png` | Native assets | Retained as immutable resources |
| `res/lyrics-wallpapers/1.DEFAULT.jpg` through `10.triangular-spiral-dark-purple-staircase.jpg` | Native assets | All ten retained |
| `res/font-faces/Elsie/Elsie-Regular.ttf`, `res/font-faces/Elsie/SIL Open Font License.txt` | Native assets | Font and license retained |
| `res/font-faces/Fira_Code/OFL.txt`, `static/FiraCode-Medium.ttf` | Native assets | The CSS-referenced font and upstream license retained |
| Other bundled Fira Code weights | Removed | Unreferenced duplicate variable/static files deleted |
| Three `my-directory-list.txt` files | Excluded | Generated binary directory listings, not source/assets |
| `res/style.css` | Excluded as mutable state | Generated lyrics CSS now lives under writable runtime data |

This audit accounts for all 61 paths at `2302501`; there are no “unreviewed”
entries.
