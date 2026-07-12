# Verification matrix

Latest recorded run: [2026-07-12](verification/2026-07-12.md).

| Area | Deterministic evidence | Live/native evidence | Release state |
|---|---|---|---|
| Local/HTTP/HLS playback | Resolver, decoder, seek, truncation, retry, cleanup, real FFmpeg fixtures | Speaker, device loss, sleep/resume | Native pending |
| YouTube and podcasts | Mocked extraction, expiry, metadata, feed caching, failure typing | Scheduled public probes | Live environment-dependent |
| Radio and ICY | Playlist recursion, metadata blocks, failover, health/backoff | SomaFM/Antenne probes and network-loss exercise | Live environment-dependent |
| Queue and persistence | Property tests, crash restore, undo/redo, failure policy, SQLite rollback | Long mixed-session restore | Soak pending |
| Library profiler | Incremental scans, moves, duplicates, watchers, leases, rollback, corruption | Large library and disappearing share | Soak/native pending |
| Identity and lyrics | Chromaprint fixtures; mocked AcoustID, MusicBrainz, LRCLIB | Credentialed/public-domain probe | Credentials pending |
| ReplayGain | Tag parsing, album grouping, clipping, immutable-media assertion | Audible A/B and rsgain tool check | Native pending |
| Icecast broadcast | Authentication tunnel, redaction, Opus/MP3 decode, reconnect | Configured remote server | Credentials pending |
| Recommendations | Ranking, negatives, diversity, persistence, explanations | Long-session taste review | Manual pending |
| Electron/PTTY | Vitest security/state tests and Playwright PTY/history/restart/theme checks | DPI, IME, clipboard, signed package | Native/signing pending |
| OTA/update | Preflight, safety state, checksum and migration contracts | Signed N to N+1 on every target | Signing pending |

No row marked pending may be represented as passed in release notes. External
unavailability is recorded separately from Mariana defects.
