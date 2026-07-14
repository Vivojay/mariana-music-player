# Mariana Product Roadmap

## Status vocabulary

- Done: implemented and verified in source; packaged-release status is tracked separately.
- Now: active or next planned implementation work.
- Next: high-confidence work after the current batch.
- Later: directionally desirable but not yet scheduled.
- Research: speculative until prototypes prove value.

Status labels describe roadmap maturity, not release verification. Release evidence remains authoritative in the state and verification documents referenced below.

## Product direction

Mariana is intended to become a privacy-first, local-first media operating system that owns user intent, playback, queueing, library intelligence, and synchronization while integrating external platforms through safe adapters instead of becoming dependent on them.

The delivery strategy is:

1. High-return playback and command polish.
2. Local listening intelligence and library depth.
3. Companion control and private collaboration foundations.
4. Mariana-native synchronized listening and social features.
5. Optional provider, cloud, federation, and research capabilities when product demand justifies them.

This document records product direction, not verified release state. Current implementation and verification evidence remain in `PROJECT_STATE.md`, `ARCHITECTURE_STATE.md`, and `docs/VERIFICATION_MATRIX.md`.

## Non-negotiable engineering principles

- Local-first by default.
- One backend authority, one playback authority, and one queue authority.
- Electron remains presentation; it must not become a second application brain.
- `MediaRef` is durable; `ResolvedMedia` is transient.
- Cookies, signed URLs, browser profiles, authorization headers, and tokens must never be persisted.
- External platforms integrate through typed adapters and official interfaces, not fragile scraping or private-API workarounds.
- DRM, authentication, geographic controls, and service protections must not be bypassed.
- Local playback must remain operational when every cloud, social, and provider integration is disabled or unavailable.
- External failures must be typed, actionable, and isolated from playback.
- Large features must be delivered as small, reversible vertical slices and atomic commits.
- Every user-visible feature requires tests, help/documentation updates, and explicit non-goals.
- Visible user value takes precedence over speculative scaffolding.
- New foundations should be introduced only when an implemented vertical slice needs them.
- Privacy-sensitive features are opt-in and disclose what leaves the device.
- Deterministic and transactional behavior is preferred wherever practical.

## Delivery priorities

### 1. Immediate playback and command polish

#### Seek grammar

Support clear, compatible seek forms:

```text
seek 90
seek 01:30
seek 1:02:30
seek +30s
seek -2m
seek 50%
seek start
seek end
```

Consider labeled day/hour/minute/second input such as `seek 1d 2h 3m 4s` after the core grammar is stable. Parsing must reject ambiguity, respect verified seekability, and handle unknown duration and end-of-media behavior safely.

#### Fade suite

Provide one consistent command family:

```text
fade in
fade out
fade to 50
fade to 50 over 10s
fade from 20 to 80
fade from 20 to 80 over 15s
```

Manual fading must remain independent from user volume, mute, ReplayGain, broadcast gain, and sleep automation. Linear, exponential, and logarithmic curves are later extensions.

#### Confirmation bypass

- Normalize deliberate `y`, `yes`, and `--yes` handling.
- Preserve `exit y`.
- Add bypasses only where a confirmation already exists or clearly protects a destructive action.
- Never apply a global token-removal rule that could reinterpret a path, title, or playlist name.
- Never bypass destructive actions implicitly.

#### Local-copy hints

- Detect when finite online music is already present in the indexed library.
- Prefer exact source provenance, MusicBrainz recording identity, Chromaprint evidence, and unique conservative metadata matches in that order.
- Show a local path only in an appropriate local interface and never in presence, broadcast metadata, remote events, or sanitized logs.
- Never substitute local playback automatically. A future explicit command may opt into substitution.
- Local-copy hints v1 must inspect only Mariana's indexed library and use existing local evidence: source provenance, recording identity, fingerprint, and conservative metadata-duration matches.
- Ambiguous or weak matches must produce no hint; v1 must prefer false negatives over misleading matches.
- Online PCM fingerprinting, AcoustID lookup, and network-assisted matching are later extensions.

#### Now-playing and progress output

- Show title, artist, album, source, queue state, elapsed time, duration, percentage, seekability, ReplayGain status, and enabled presence state without clutter.
- Use a compact CLI progress bar for finite media.
- Represent live streams explicitly rather than inventing a duration or percentage.
- Show queue position and current chapter when available.

### 2. Discord Rich Presence completion

The opt-in local Rich Presence vertical slice exists. Remaining product-quality work is:

- Create and maintain the official Mariana Discord application.
- Supply its public Application ID through maintainer-controlled build configuration.
- Live-test against Discord Desktop.
- Verify `off`, `app`, `track`, and `session` privacy modes.
- Verify that paths, URLs, secrets, browser references, stable identifiers, and private session data never leave Mariana.
- Rebuild the backend and Electron package from the verified source revision.
- Smoke-test the packaged application.
- Document maintainer release setup without requiring end users to create Discord applications or provide tokens.

Possible later additions include richer assets, optional buttons, an opt-in join bridge to Mariana-native rooms, and Discord invite/presence bridging. Discord must never become Mariana's identity, room, or playback source of truth.

### 3. Core playback and command experience

- Consolidate command grammar and error reporting without rewriting the command loop prematurely.
- Improve aliases, help discoverability, invalid-command suggestions, command history, and contextual hints.
- Improve queue, album, playlist, search, and library displays.
- Improve themes, colors, startup diagnostics, and typed explanations of playback failures.
- Add a concise `status` command that explains current activity and degraded dependencies.
- Add shell-like affordances incrementally: repeat the previous command, command hints, and completion only after input semantics are stable.

### 4. Local listening intelligence

- Record bounded, local listening sessions.
- Produce session summaries and exportable reports.
- Track per-track starts, played duration, completion, skips, replays, seeks, likes, dislikes, and technical failures without treating technical failure as negative preference.
- Summarize recent habits, rediscovered albums, frequently skipped artists, and time/day patterns.
- Build a local-only analytics view.
- Keep raw listening history on-device by default and define explicit retention and export controls.

### 5. Timed notes, bookmarks, and annotations

Begin as a private local feature:

```text
annotation add current "text"
annotation add 01:23 "text"
annotation list current
annotation edit ...
annotation delete ...
```

Support song bookmarks, timed tags, chorus/drop/highlight markers, lyric annotations, and adjacent export formats. Shared room annotations and public or federated annotations belong to later social phases.

### 6. Library and local media intelligence

- Improve duplicate, corrupt, unsupported, missing, and tombstoned-media detection and UX.
- Add BPM, musical key, mood, energy, genre, danceability, and acoustic-similarity analysis without fabricating values.
- Reuse content signatures and fingerprint caches across identical occurrences.
- Improve online-to-local matching.
- Add safe metadata editing for artist, title, album, genre, year, and local tags.
- Improve library verification, file-manager reveal actions, and downloaded-file provenance.
- Keep expensive analysis staged, resumable, playback-aware, and optional.

### 7. Recommendation engine evolution

Maintain explicit boundaries between:

1. Candidate retrieval.
2. Personalized ranking.
3. Diversity and fatigue reranking.
4. Explanation.
5. Offline evaluation.

Candidate sources should progressively include local acoustic neighbors, metadata similarity, album and artist affinity, recent-session context, ListenBrainz/Troi-style discovery, and deliberate bounded exploration.

Priorities:

- Close feature-loading gaps and actually connect available features and embeddings to candidate generation.
- Improve completion and skip feedback.
- Make explanations truthful by exposing score contributions and provenance.
- Evaluate Recall@10, NDCG@10, novelty, diversity, artist concentration, and skip-rate impact.
- Compare implicit-feedback BPR/ALS and sequential challengers before promotion.
- Add CLAP-style local audio embeddings only as an optional tier.
- Consider privacy-preserving collaborative signals only after the local recommender is demonstrably useful.

### 8. Downloads and managed media

- Continue hardening extractor-backed downloads for legally accessible sources.
- Improve SoundCloud, Bandcamp, Vimeo, and similar handling only where official access and terms permit it.
- Improve yt-dlp diagnostics, authentication guidance, provenance, status, pause/resume/cancel, and failure classification.
- Complete album, selector, missing-only, and managed-download-root workflows.
- Detect already-downloaded and local-equivalent tracks.
- Improve portable filename sanitation and post-download metadata.
- Keep downloads in Mariana's supervised process and persistent job model.

## Universal provider integration

### 9. Provider strategy

Potential providers include Discord, YouTube, Spotify, SoundCloud, Bandcamp, TIDAL, Deezer, Apple Music, Amazon Music, Qobuz, Audius, Mixcloud, Reddit, Instagram/Meta, Snapchat, podcast providers, ListenBrainz, MusicBrainz, and Radio Browser.

Add a provider only through a real user-visible vertical slice. Each adapter must define:

- A capability manifest.
- An authentication boundary.
- Sanitized durable provider and account references.
- Typed failures.
- Secret, cache, and retention rules.
- Rate-limit and retry behavior.
- Official playback, handoff, or remote-control boundaries.
- Legal and API constraints.

Do not introduce a broad provider framework until a second or third real integration proves the shared contract.

### 10. Provider capabilities

Capabilities may include, only where an official API or lawful public interface permits them:

- Catalog search and browsing.
- Metadata retrieval.
- Playlist import, export, and mutation.
- External library read/write.
- Official-player handoff.
- Provider-device remote control.
- Share and timestamped-share links.
- Store/catalog and Bandcamp purchase handoff.
- Social-graph suggestions.
- Presence publication and reading.
- Official comments or annotations.
- Clipping and saving within explicit legal/API limits.

## Companion, identity, and private collaboration

### 11. Mariana Companion Mode

Build personal remote control before multi-user rooms:

- Phone, tablet, or second-computer controller.
- QR and LAN pairing.
- Device certificates and explicit capability grants.
- Now-playing, queue, library search, playback controls, seek, volume, lyrics, album art, annotations, recommendations, and download status.
- No cloud requirement.
- No second playback authority.
- Local stop and local privacy controls always win.

This phase should establish reusable secure transport and device trust without introducing friends, public identity, or synchronized playback.

### 12. Identity and device model

- Local identity by default; optional Mariana user identity later.
- User-controlled device identities and labels.
- Revocable device certificates stored through the operating-system keychain.
- Pairing codes and QR pairing.
- Session pseudonyms and scoped capability grants.
- No permanent MAC, IP, Windows ID, or invasive device fingerprint as the primary identity.
- Optional account verification only when public abuse prevention requires it.

### 13. LAN private rooms

Initial room scope:

```text
room create --lan
room invite
room join <code>
```

Support members, roles, permissions, chat, reactions, queue proposals, collaborative playlist editing, and local room history. Explicitly defer synchronized playback, cloud services, public discovery, and Discord dependence.

### 14. Self-hosted coordination

After LAN state is reliable, add an optional self-hosted service for private WAN rooms:

- Signaling and invite delivery.
- Friend requests and presence leases.
- Event relay, snapshots, recovery, and reconnect.
- Explicit server trust records.
- No audio relay or public rooms initially.

Start with the smallest service and SQLite or PostgreSQL as justified. Redis becomes relevant only for presence and rate limits at meaningful concurrency. TURN is introduced only for connectivity fallback.

## Synchronized and social listening

### 15. Mariana Jams and tune-ins

Initial Jams should synchronize independent playback rather than relay audio:

```text
jam start
jam join
```

Capabilities:

- Shared queue.
- Authoritative room clock.
- Future scheduled starts.
- Participant readiness and sync health.
- Bounded drift correction.
- Scheduled seek, pause, and resume.
- Host transfer and participant status.
- Local stop always wins.
- No perfect-synchronization claim without measurements.

Initial media scope should be the same canonical YouTube item, matching local files, and finite HTTP media. Podcasts may follow. Live radio should not be an initial sync target.

### 16. Relay, broadcast, and public rooms

Only after independent Jams are reliable:

- TURN fallback.
- Optional Opus or host-audio relay.
- Host migration and SFU-backed larger rooms.
- Public broadcast mode and room discovery.
- Moderation, rate limits, abuse reporting, and retention policy.
- Copyright and source-policy enforcement.

### 17. Mariana-native social platform

Potential long-term capabilities:

- Profiles, friends, presence, and lightweight messaging.
- Private rooms, public listening parties, and communities.
- Shared queues, playlists, annotations, sessions, and reactions.
- Discovery and moderation.

Discord and other providers remain bridges rather than the core source of truth.

### 18. Federation and bridges

Research only after native social behavior is stable:

- Mariana homeservers and self-hosted communities.
- Cross-server rooms.
- Matrix bridging for chat and durable events.
- ActivityPub for explicitly public playlists or session posts.
- Discord invite and presence bridges.
- Separate public and private identity surfaces.
- Federation blocklists, domain trust, and explicit deletion limitations.

## Experience and content surfaces

### 19. Visual and desktop experience

- 2D and 3D visualizers.
- Refined themes, animation, progress, and album art.
- Mini now-playing window, tray controls, media keys, lock-screen integration, and notifications.
- Rich terminal UI, reliable session restore, multi-view polish, and accessible Electron controls.
- Reduced-motion, reduced-transparency, keyboard, screen-reader, scaling, and contrast support.

### 20. Lyrics, podcasts, and spoken content

- Improve synchronized lyrics, full-text fallback, editing, LRC handling, and timed annotations.
- Expand standards-compliant podcast discovery and playback.
- Add local text-to-speech and article/post reading as an optional spoken-content mode.
- Integrate external TTS providers only through opt-in adapters.
- Respect platform terms and content rights for Reddit and other social sources.

### 21. Safety and wellness

- Configurable hearing-safety volume warnings.
- Persistent, clear warning when safety controls are disabled.
- Sleep-timer and fade-out improvements.
- Session-duration reminders and late-night mode.
- ReplayGain education and safe defaults.
- Sudden-volume-spike protection and output-device-change warnings.

### 22. Broadcasting and creator workflows

- Improve Icecast broadcast profiles, diagnostics, preview, metadata, and secure credential handling.
- Add explicit broadcast and session recording with legal warnings.
- Add creator/host status views.
- Defer public-room relay and generalized remote listeners until the collaboration security model is ready.

### 23. File and library operations

- Strengthen trash-only removal and add an optional restore journal.
- Improve safe rename, convert, copy, and replace workflows.
- Reveal media in the platform file manager.
- Mark corrupt, blocked, favorite, and locally tagged media clearly.
- Improve find/list and columnar library views.
- Preserve file provenance and distinguish managed from unmanaged media.

### 24. Commands and settings

- Strengthen the settings schema and validation.
- Apply safe setting changes immediately.
- Add `config show`, `config set`, and `config reset` incrementally.
- Add settings profiles and explicit feature flags where useful.
- Make log levels effective.
- Add structured, sanitized logs, a privacy dashboard, and diagnostics export.

## Release engineering and quality

### 25. Packaging, releases, and trust

- Signed Windows installer.
- Signed and notarized macOS packages.
- Linux AppImage.
- Signed, hash-verified updates.
- SBOM, license notices, dependency audits, and build provenance.
- Reproducible or independently verifiable builds where feasible.
- Packaged E2E, native hardware acceptance, soak evidence, and package-freshness checks.
- Never present a stale backend or desktop package as matching current source.

### 26. Testing and verification

- Repository branch coverage at or above 90%.
- Critical-module branch coverage at or above 95%.
- Mutation score target at or above 80% for critical logic.
- More property/state-machine and fault-injection tests.
- Packaged Electron E2E and real-process FFmpeg tests.
- Real output-device, sleep/resume, Bluetooth-switch, and network-impairment acceptance where feasible.
- CI evidence for each release.
- No generated artifacts or stale package claims in commits.
- Never report an unexecuted live, manual, native, or endurance check as passed.

### 27. Observability and diagnostics

Add user-facing `status` and `doctor` surfaces backed by sanitized diagnostics for:

- Playback and decoder pipeline.
- Queue and database state.
- Library and profiler health.
- Provider and network health.
- Discord presence.
- Downloads, station generation, recommendations, and broadcast.
- Runtime, managed tools, and package freshness.

Diagnostic bundles must redact secrets, signed URLs, private headers, browser references, and user paths unless the user explicitly opts to include local path information.

## Infrastructure and research

### 28. Infrastructure only when justified

Adopt infrastructure in this order:

1. SQLite for local state.
2. A lightweight self-hosted coordination service.
3. PostgreSQL for real multi-user coordination.
4. Redis for presence, ephemeral state, and distributed rate limits.
5. TURN for connectivity fallback.
6. Object storage for explicit attachments or artifacts only.
7. Pub/Sub for demonstrated event scale.
8. SFU infrastructure for large relayed rooms.
9. Kafka only for a proven large event or analytics pipeline.
10. Workflow orchestration only when ML/data pipelines require it.
11. Graph storage only after PostgreSQL traversal and indexing are demonstrably insufficient.

Managed cloud services remain optional. Self-hosted and local modes must stay viable where technically reasonable.

### 29. Advanced ML direction

- Improve the on-device recommender and taste graph first.
- Add local embeddings, acoustic similarity, mood inference, smart stations, playlist generation, listening summaries, metadata correction, and assisted tagging incrementally.
- Explore friend matching, collaborative recommendations, federated learning, and secure aggregation only with explicit privacy boundaries.
- Never centralize raw listening history by default.
- Treat generated summaries, inferred tags, and recommendations as explainable suggestions rather than authoritative metadata.

### 30. Research moonshots

Long-term research topics include:

- Near-zero-skew Jams and perceptual synchronization metrics.
- Clock drift and output-latency modeling.
- Cross-edition acoustic alignment.
- Future encoded-frame windows and predictive scheduling.
- Host migration without audible interruption.
- Decoder-state synchronization and waveform prediction.
- Disclosed loss concealment.
- Rollback-inspired distributed playback correction.
- Massive public synchronized listening rooms.
- Mariana as a distributed media operating system.

These ideas must be classified as research until prototypes provide measurable advantages over authoritative-clock scheduling, future starts, adaptive buffering, and bounded drift correction.

## Preferred implementation sequence

1. Treat the verified seek and fade polish as done in source; carry it into the next package rebuild without reopening playback architecture.
2. Normalize confirmation bypass handling only for commands that already require deliberate confirmation.
3. Add conservative, indexed-library-only local-copy hints without automatic playback substitution.
4. Live-test Discord Rich Presence and all privacy modes against Discord Desktop.
5. Rebuild and verify backend and desktop packages from the same source revision.
6. Improve now-playing and progress UX.
7. Add local sessions and private annotations.
8. Build Companion Mode.
9. Build LAN private rooms without synchronized playback.
10. Add optional self-hosted private-room coordination.
11. Build measured Mariana Jams using independent playback first.
12. Introduce a general provider-adapter contract only when multiple real integrations require it.
13. Expand official provider integrations according to capability, privacy, and legal constraints.
14. Add managed cloud, federation, large relays, and research systems only when demonstrated product demand justifies them.

## Near-term non-goals

- No playback, decoder, queue, or command-loop rewrite for the polish batch.
- No automatic replacement of online playback with a local file.
- No network-assisted or whole-filesystem local-copy matching in v1.
- No broad provider framework before multiple implemented integrations demonstrate a shared contract.
- No OAuth, cloud account, friend graph, public room, synchronized Jam, federation, or audio-relay work in the immediate polish and packaging sequence.
- No claim that a source-verified change is shipped until matching packaged artifacts pass their release gates.
