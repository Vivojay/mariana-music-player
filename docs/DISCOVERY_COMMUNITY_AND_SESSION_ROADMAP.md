# Discovery, community, and session recipe roadmap

This document records the implemented local-first discovery boundary, its first
visual content expansion, and researched options for later discovery and
community work. Future sections remain design proposals, not implemented-feature
claims.

## Status and boundaries

Mariana has one backend and playback authority, typed desktop controls, source
resolvers, queues, podcasts, settings, local persistence, and an Icecast source
broadcaster. Phase 1 adds a local-first startup homepage. Its separately opt-in,
asynchronously cached discovery now includes Bandcamp Daily stories and
ListenBrainz fresh releases, with validated Bandcamp/Cover Art Archive imagery.
Future work should compose
those capabilities rather than create a second player, renderer-owned state, or
command-text control path.

Ranked chart providers, livestream accounts or ingest, chat, and recipient ACLs
are **not implemented**. Session recording, inspection, and verified local
single-source replay are now connected, including freshly verified public
YouTube references; other online providers, nested-queue, and overlap replay
remain future work. All provider access must remain optional, asynchronous,
cached, and independent from homepage visibility and playback.

### Requirement-by-requirement delivery status

| Requested capability | Current implementation | What remains |
| --- | --- | --- |
| Startup Home and settings | Default-on startup visibility; persistent independent online permission; manual `home`; desktop Home and Settings buttons. Windows development Electron verifies offline startup, manual reopen, focus, and supported-size geometry. | Native first-boot/relaunch, display scaling, and packaged acceptance. |
| Culture excerpts | Bounded, attributed Bandcamp Daily excerpts; separate official destinations for Grammys, SXSW, Pitchfork, Playbill, Indian Express, BFI, and Comic-Con. | Other providers' permitted feeds and image reuse must be confirmed before automated imports. Official links are not news excerpts. |
| New releases | ListenBrainz metadata, MusicBrainz edition links, eligible Cover Art Archive images, existing CLI album lookup instructions, and typed desktop recording/version choices. Inspection does not start playback; Play now and Queue require explicit selection. | Real-provider edition/matching acceptance. No automatic first-result substitution. |
| Charts | Separate official-link section for Billboard, UK Official Charts, and IFPI. | Licensed ranking import with territory, date, and real positions; playback selection after identity resolution. No ranking is fabricated. |
| Performance channels | Official-link cards for Boiler Room, Book Club Radio, KEXP, NTS, COLORS, Cercle, and confirmed Elevator Music Live. | Permitted catalogue feeds and typed playback choices for channel entries. |
| Current-media artwork | Embedded/adjacent/provider precedence, bounded private cache, asynchronous retrieval, stale rejection, `thumb` settings/show, desktop display and direct CLI viewer. | Native viewer/visual acceptance and providers which supply no supported image. |
| Homepage images | Validated Bandcamp and release images; each ready image is projected without waiting for slower covers. | Permission for additional imagery. Directory cards use placeholders, not scraped logos or invented event art. |
| Artist listings, ingest, relay, chat | Design only; no publishing or relay controls are shown. | Paired-device trust, creator permissions, supported protocols, moderation and retention. |
| Private sharing | Existing portable exports are not recipient-restricted shares. | Pairing and per-recipient permission enforcement. |
| Session recipes | Versioned bounded recording, validation, inspection, and verified local/public-YouTube flat/nested-queue replay through the existing player. | Other provider adapters, atomic two-source overlap restoration, and native acceptance; see [implemented limits](SESSION_RECIPES.md). |

The earlier bounded delivery deliberately implemented the homepage/artwork
foundation while researching providers and designing community/session work.
It did not complete every item in the wider vision. These distinctions must
remain visible in help, UI labels, and completion reports.

## Editorial and discovery sources

The [international entertainment catalogue](ENTERTAINMENT_CATALOGUE.md) records
the current programme/station batch, official access evidence, shared RSS/radio
reuse, and the remaining candidate statuses. It extends Home and its existing
typed selection worker; it is not a second discovery application or provider
framework. See that ledger rather than inferring native playback from older
external-link cards.

Every card should retain provider, author when supplied, publication date,
canonical article link, cache age, and an explicitly bounded provider-supplied
excerpt. Mariana should neither copy full articles nor invent headlines, chart
positions, or playable matches.

| Source | Editorial value and breadth | Access and restrictions | Reliability / effort |
| --- | --- | --- | --- |
| [Bandcamp Daily](https://daily.bandcamp.com/feed) | Independent releases, regional scenes, labels, interviews, and experimental or underrepresented music. | Official RSS contains title, author, date, category, link, a short excerpt, and provider-hosted card imagery. Feed availability is not a redistribution licence: the implemented opt-in adapter bounds and attributes excerpts, while a current terms/reuse review remains required before broader distribution. | High / low technically. **Implemented, including validated feed-supplied images; terms posture still to verify.** |
| [Pitchfork](https://pitchfork.com/info/rss/) | Established music news, criticism, interviews, album and track reviews; comparatively US/Anglophone. | Official category feeds exist, but Condé Nast terms restrict reproduction, distribution, transmission, and caching. Treat it as permission-required or link-only unless suitable rights are obtained. | High editorial reliability / medium legal-integration effort. Useful alongside, not instead of, geographically broader sources. |
| [Resident Advisor](https://ra.co/news/9078) | Strong electronic music, club culture, festivals, films, and regional event discovery. | RA announced news, feature, review, and regional event RSS feeds. Verify each current endpoint and current reuse terms before enabling it because the announcement is old. | Medium / medium. |
| [Indian Express](https://indianexpress.com/rss/) and [Hindustan Times](https://www.hindustantimes.com/rss) | Bollywood, Indian music and culture, Hollywood, and regional cinema, including Tamil and Telugu categories. | Official RSS indexes exist, but their published feed/website terms limit reuse and automated caching. Keep them permission-required or link-only; editorial selection should also prevent celebrity-volume feeds from overwhelming music and regional arts. | Medium / medium-to-high rights effort. |
| [Playbill](https://playbill.com/article/playbill-rss-feeds) | Authoritative Broadway, Off-Broadway, theatre, and musicals coverage. | Official news, feature, combined, and video feeds supply summaries and links. It is US-theatre-specific, should be paired with regional sources, and still needs a reuse-terms review before excerpt caching. | High / low technical effort, pending terms review. |
| [GRAMMY.com](https://www.grammy.com/news) and [SXSW](https://sxsw.com/music-film-interactive-sxsw-eco/news/) | Primary sources for their own awards, rules, programmes, and event announcements. | No suitable public syndication API was identified. Start with attributed official-link cards or a curated calendar; do not scrape or present either as independent criticism. SXSW labels its [press images](https://sxsw.com/press-images/) for press use, so Mariana must not repurpose that library as general card art without permission. | High authority / medium maintenance. |

Genius is not selected as an editorial-feed provider. Its song annotations may
be useful during explicit media inspection, but API availability, permitted
display, and lyrics rights require direct partner/terms verification first.

Provider acceptance should require a live official endpoint, documented reuse
terms, stable item identifiers, attribution fields, bounded content, locale or
category metadata, cache validators, and graceful rate-limit and failure
behaviour. For example, BBC metadata and business RSS use require permission or
a licence under the [BBC terms](https://downloads.bbc.co.uk/usingthebbc/bbc_terms_of_use_31March2022english.pdf),
so those feeds should not be silently added.

### Implemented first content slice

Phase 1 implements a read-only Bandcamp Daily adapter behind the homepage's
separate, default-off online-content preference. It stores a normalized,
size-bounded cache, renders cached cards immediately, and refreshes on a bounded
worker while retaining visibly aged content after failure. Cards expose only
attributed excerpts and original links; playing or queueing an article title is
forbidden because an article is not a media identity. This conservative display
does not itself settle redistribution rights; complete a current terms review
before shipping the adapter broadly. The visual expansion extracts only the
image already supplied by that official feed, validates it through Mariana's
bounded still-image boundary, and exposes only an opaque cache key. Failed or
missing images use a designed placeholder rather than page scraping.

The homepage also contains a locally bundled directory of 17 official
destinations, grouped into culture, charts, and performances. These entries
have no publication dates or claimed rankings. They are visible offline and
perform no requests until the user opens one in their browser. Renderer
validation accepts only the exact listed destination URLs, not arbitrary pages
on those domains. The existing external-link boundary is reused; no terminal
input or playback intent is emitted by a directory card.

## New releases

- **Implemented metadata provider:** ListenBrainz
  [`GET /1/explore/fresh-releases/`](https://listenbrainz.readthedocs.io/en/latest/users/api/misc.html).
  It exposes recent and upcoming releases, dates, artist credits, release types,
  and MusicBrainz release/release-group identifiers without turning them into
  alleged sales rankings. Mariana uses those stable release IDs for original
  MusicBrainz links and optional [Cover Art Archive](https://musicbrainz.org/doc/Cover_Art_Archive/API)
  covers; a release card remains metadata, not an automatic playable match.
- Use [MusicBrainz](https://musicbrainz.org/doc/MusicBrainz_API) for stable
  identity and metadata enrichment. Its service requires a meaningful
  User-Agent and no more than one request per second. Core data is CC0, while
  supplementary data has separate attribution/noncommercial/share-alike terms
  documented by [MetaBrainz](https://musicbrainz.org/doc/About/Data_License).
- Do not choose Spotify as the homepage release feed: Spotify marks Get New
  Releases deprecated. Its February 2026 rules remove it for new or updated
  Development Mode access, while Extended Quota is unaffected and changes for
  existing Development Mode integrations were postponed
  ([migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide)).

A release remains metadata until Mariana resolves it through existing search
and source services. When recordings or editions are ambiguous, show choices;
never silently substitute a similarly named item.

The displayed lookup uses MusicBrainz's public release identifier in the
[`reid` indexed search field](https://musicbrainz.org/doc/MusicBrainz_API/Search):
`album search reid:<release-id> --scope online`. It is generated in the backend
from a validated canonical release link, never a title. No action is executed
by displaying or selecting a card; the user explicitly runs existing album
search/fetch/tracks/play/queue commands and checks the edition first.

The desktop now also offers **Find playable versions** for a current release
card, with online discovery enabled. It fetches the exact MusicBrainz edition
without changing the CLI's last album search. Selecting a recording searches
available library and online versions; the actual provider title, performer,
duration, source, and match basis are shown. A search hit is not assigned an
unverified recording or release identity. Multiple local matches remain choices.
**Play now** uses direct playback without clearing the queue; **Queue** appends.

The typed `discovery.begin`, `discovery.choose`, and `discovery.cancel` controls
accept opaque handles, not command text or renderer-provided playback URLs.
One background worker retains only the latest pending lookup. Source-card
binding, a backend generation, a ten-minute session expiry, and per-update
revisions reject stale choices. Policy is rechecked before applying a selection.
The main process and renderer independently validate the bounded projection.
Provider errors are replaced by fixed safe messages; the Mini-player receives
no discovery or capture methods.

## Legitimate charts

Charts must show provider chart name, territory/category, rank, and provider
chart date. If a provider supplies no chart date, show a fetched-at timestamp
instead of manufacturing one.

| Provider | Supported path | Decision |
| --- | --- | --- |
| [Apple public marketing feeds](https://performance-partners.apple.com/tools) | Apple's RSS generator explicitly supports incorporating top-content feeds. On 2026-09-08, the [US Top Songs JSON feed](https://rss.marketingtools.apple.com/api/v2/us/music/most-played/10/songs.json) returned HTTP 200 without credentials: ten ordered entries, country `us`, a feed update timestamp, copyright, provider links, and artwork references. | First no-paid-access candidate, not enabled yet. Finish ranking semantics and artwork/caching reuse checks; retain provider order and territory, label the feed update separately from a chart date, and never call it Billboard. |
| [Apple Music Charts API](https://developer.apple.com/documentation/applemusicapi/charts) | Ordered charts through developer-token authentication. | Not selected for the no-paid-access delivery; distinct from the public marketing feeds. |
| [Luminate Music API](https://docs.luminatedata.com/reference/get-charts) | Authenticated Billboard- and Luminate-owned chart catalogues. Luminate identifies itself as Billboard's official data partner. | Use only under a suitable commercial licence. Never scrape Billboard or label another ranking "Billboard." High effort/cost. |
| [Official Charts Company](https://www.officialcharts.com/our-business-services/chart-licensing/) | Licensed UK current, historic, genre, and bespoke charts. | Partnership/licence required; link-only until obtained. |
| [IFPI Global Charts](https://www.ifpi.org/our-industry/global-charts/) | Authoritative annual global artist, single, and album rankings. | Suitable as attributed annual link cards; no general frequently updated public API was identified. |
| [YouTube Charts](https://support.google.com/youtube/answer/9014376) | Official country chart pages. | Link to the official chart. A YouTube search or trending result is not an official chart and must not be labelled as one. |

Selections from a chart should use the same resolver choice flow as releases;
the chart's identity and rank must remain separate from whichever playable
recording the user selects.

## Curated performance channels

| Channel | Distinctive value | Practical Mariana access |
| --- | --- | --- |
| [KEXP](https://www.kexp.org/about/) | Nonprofit global discovery, interviews, specialty shows, and live performances. | Official-link card implemented. Its [Live on KEXP page](https://www.kexp.org/podcasts/live-on-kexp/) advertises an audio podcast, but the current [terms](https://www.kexp.org/terms-and-conditions/) restrict copying/distribution. Confirm the feed-specific integration terms before adding a built-in fetch, image cache, or relay. |
| [NTS Radio](https://www.nts.live/about) | Two 24/7 channels, a large human-curated archive, broad genres, and hosts from more than 80 countries. | Start with explicit official live streams/provider pages if current terms permit. Do not scrape the archive without a documented API or agreement. |
| [Boiler Room](https://boilerroom.tv/page/about/) | Global club culture and grassroots scenes; its archive reports more than 9,000 artists across 300 locations. | Use official YouTube, SoundCloud, or Boiler Room pages through existing supported resolvers. Public availability does not grant download or rebroadcast rights. |
| [Book Club Radio](https://www.bookclub.radio/about) | Newer NYC community-led dance-floor programming and recorded DJ sets. | Use its official YouTube uploads/provider page; it complements but does not provide broad geographic coverage alone. |
| [COLORS](https://colorsxstudios.com/) | Distinctive emerging-artist performances with international reach. | Official provider links or verified YouTube channel only; no public catalogue API was identified. |
| [Cercle](https://www.cercle.io/) | High-production electronic performances connected to landscapes and cultural sites. | Official provider links/YouTube only, with the same no-relay assumption. |

The requested entity is confirmed as **Elevator Music Live**, whose
[official link hub](https://linktr.ee/elevatormusiclive) points to
`@elevatormusiclive`. Its directory entry opens only that exact destination.
Do not confuse it with generic elevator music, unrelated
artists, retailers, or licensing businesses.

For verified YouTube channels, read the channel's uploads playlist via
[`playlistItems.list`](https://developers.google.com/youtube/v3/docs/playlistItems).
YouTube explicitly warns that date-ordered search can be delayed or incomplete;
[`search.list`](https://developers.google.com/youtube/v3/docs/search/list) is
still useful for explicit `live` and `upcoming` event queries. Cache only public
canonical IDs and sanitized metadata, not signed playback URLs.

## Creator livestream roadmap

### Approved delivery order and defaults

These milestones remain future work, not implemented services:

1. Finish discovery-to-playback and native homepage/artwork acceptance first.
2. Pair Mariana desktops over an opt-in authenticated encrypted LAN boundary.
   Begin with read-only status; pairing alone grants no remote playback access.
   Share portable references and explicitly selected owned files per recipient,
   with recipient acceptance, integrity verification, no-clobber finalization,
   and revocation of future access. Received copies cannot be recalled.
3. Add approved creator listings and bounded room chat. Chat is session-only
   by default; seven-day replay requires explicit consent and deletion controls.
4. Add built-in camera/microphone preview and capture, bounded MediaRecorder
   input, and managed FFmpeg rolling HLS. Start at 720p/30 fps, one publisher
   and four viewers, with several seconds of buffering. Existing backend
   playback owns audio; muted video follows its timeline. Native synchronization,
   permission-denial, reconnect, and shutdown acceptance gates the feature.
5. Make local media archives separately opt-in per stream, visibly recorded
   and quota-limited. Chat archive, source archive, and sharing permissions are
   independent. Retention buffers are not permanent archives. Existing Icecast
   remains the authorized audio-broadcast path; external forwarding requires a
   verified supported destination and explicit rights.
6. Deliver structured session recording, inspection, and replay including the
   existing two-source crossfade and program-gain timing. Checkpoints preserve
   both overlapping sources and envelope progress. Use backend events rather
   than UI polling; overflow marks recipes incomplete. Buffering pauses/rebases
   the recipe clock. Missing/changed sources require explicit handling, never
   substitution. Live replay requires a separately retained source archive.

No paid provider access, mandatory cloud services, public rooms, automatic
firewall/router changes, or implicit recording consent. Phone clients,
self-hosted coordination, and synchronized rooms follow proven paired-desktop
trust. Each milestone is reviewed locally before committing or publishing.
No new network listener is introduced by the current release-selection slice.

These capabilities have different trust, rights, and infrastructure boundaries
and must not be represented as one feature:

1. **List or link an external event.** Store a creator-supplied public provider
   identity, canonical link, title, scheduled time, and status. Validate the
   provider and refresh only through official APIs or calendars.
2. **Play a supported external stream.** Use an official embed or an existing
   Mariana resolver when provider terms permit. YouTube offers an official
   [IFrame Player API](https://developers.google.com/youtube/iframe_api_reference).
   Twitch supports live/VOD embeds but requires HTTPS, a declared `parent`, and
   a minimum 400 by 300 viewport
   ([Twitch embed requirements](https://dev.twitch.tv/docs/embed/video-and-clips/)).
   An Electron file or custom-protocol page may not satisfy Twitch's web-parent
   rule, so Mariana must prove a stable HTTPS origin before promising an embed.
3. **Ingest a creator's stream.** Require creator authentication and explicit
   control of the source. YouTube's
   [Live Streaming API](https://developers.google.com/youtube/v3/live/getting-started)
   manages broadcasts for the authenticated channel owner; it is not an API for
   pulling arbitrary third-party streams.
4. **Relay or rebroadcast.** Require explicit creator and rights-holder
   authorization, a named destination, revocation, and an auditable rights
   record. Mariana's existing Icecast broadcaster can send Mariana-controlled
   audio, and Icecast technically supports
   [mountpoint relays](https://icecast.org/docs/icecast-latest/relaying/), but
   technical capability never implies permission to relay provider content.
5. **Host chat and replay data.** Provider chat is the safe first option. Twitch
   [EventSub](https://dev.twitch.tv/docs/eventsub/) is at-least-once and requires
   deduplication and replay-attack handling. YouTube states that API live-chat
   messages are available only while the event is live
   ([live chat API](https://developers.google.com/youtube/v3/live/docs/liveChatMessages));
   Mariana-owned replay would therefore require consent, identity, moderation,
   reporting/blocking, rate limits, retention, export, and deletion.

Instagram should initially be **official-link only**. Research of the currently
documented [Instagram Platform](https://developers.facebook.com/docs/instagram-platform/)
did not verify a general integration for pulling and forwarding arbitrary
Instagram Live streams; do not turn that research finding into a claim that no
partner capability exists. Reconfirm with Meta or a formal partner programme
before implementation.

The agreed sequence above supersedes the earlier audio-only ingest sketch:
paired trust and listings/chat precede built-in audio/video capture and buffered
HLS. Camera/microphone capture uses [MediaRecorder](https://www.w3.org/TR/mediastream-recording/)
and managed [FFmpeg HLS](https://ffmpeg.org/ffmpeg-formats.html#hls-2), subject to
the native synchronization gate. [WHIP](https://www.rfc-editor.org/rfc/rfc9725.html)
is a possible later external-encoder ingest protocol, not a first-slice dependency
or a reason to replace the playback engine.

## Private playlist sharing

- **Exported playlist file:** a portable copy with no ongoing ACL or revocation.
  Remove absolute local paths and secrets; retain only portable stable media
  references.
- **Provider link:** the provider controls access and availability. Mariana only
  forwards the link and cannot promise recipient restriction.
- **Named-recipient share:** requires authenticated user/device identities,
  encrypted transport and storage, per-share ACLs, expiry/revocation, and audit
  behaviour. An unguessable public URL is bearer access, not named-recipient
  authorization.

**Selected direction: paired local-network devices first.** Do not start with
a hosted account system, public directory, or cloud dependency.

Follow the existing direction: Companion Mode pairing with short-lived codes
and device keys; approved-device LAN exports; private LAN rooms with host
authority; then an optional self-hosted coordinator with minimal retained
metadata, ACLs, revocation, rate limits, and abuse controls. Cross-provider
items remain links resolved independently by each recipient; unavailable media
is reported and never replaced silently.

### Paired-device implementation order

1. **Trust and consent:** opt-in local listener, time-limited single-use pairing
   invitation, explicit approval on the host, device key binding, encrypted
   transport, bounded attempts, restart-safe trust records, and device revocation.
   Sharing network proximity or knowing a bearer link is not sufficient identity.
2. **Read-only companion:** allowlisted status snapshots only. Do not expose
   terminal access, raw paths, credentials, or generic remote commands. Pairing
   must not silently grant playback control.
3. **Playlist sharing:** choose already-approved recipient devices per share;
   send a sanitized portable snapshot only after authentication and ACL checks.
   Revocation prevents subsequent retrieval, but cannot erase copies already
   received. State that limitation before the user shares.
   Explicit owned-file transfers disclose detected format, size, and required
   storage before recipient acceptance. Use bounded staging, integrity checks,
   and existing no-clobber finalization; reject traversal, source replacement,
   partial-file activation, and unauthorized resume requests.
4. **Local creator listings:** approved creators publish canonical provider
   links and scheduled times to the private room. Label listings separately
   from playable, actively streaming, or archived content. Existing supported
   resolvers remain the only playback path.
5. **Room chat:** explicit participation, bounded messages/history, host removal
   and blocking, retention controls, and no external embeds from chat text.
   Chat replay and media replay are separate permissions and data stores.
6. **Authorized audio relay:** only after device trust and creator/source rights
   exist; reuse the broadcaster with destination confirmation. No automatic
   Instagram forwarding and no implicit permission to relay provider streams.

Tests must cover invitation reuse/expiry, unpaired and revoked requests,
recipient isolation, secret-free exports, reconnect/restart, hostile input,
and cleanup. Native two-device acceptance is required before calling this
recipient-restricted sharing. No listener or new service is launched by the
homepage itself.

## Reproducible listening sessions

Implementation update: the local recorder, strict inspector, checkpoint folder,
and finite local/public-YouTube replay service now have command entry points. See
[Session recipes](SESSION_RECIPES.md) for the current format, exact supported
events, queue-replacement consent, and test evidence. The design below remains
the wider target, not a claim that every online provider or
two-source overlap restoration have been completed. The current implementation
refuses those unsupported replay semantics explicitly.

A session recipe records listening intent, not rendered audio and not terminal
commands. A proposed version-one envelope is:

```json
{
  "format": "mariana-session-recipe",
  "version": 1,
  "clock": "relative-ms",
  "media": {},
  "settings": {},
  "events": []
}
```

### Allowlisted model

- A local media reference contains a catalog/content fingerprint, never an
  absolute path. An online reference contains a canonical, non-secret provider
  identity, never a signed playback URL, cookie, header, token, or credential.
- Version-one events are limited to `media_start`, `pause`, `resume`, `seek`,
  `transition`, queue add/remove/reorder/clear, repeat-mode changes, and shuffle
  with an explicit seed, plus supported program-gain and two-source crossfade
  settings. Each has a relative monotonic timestamp, stable media key, expected
  duration/version hints, and manual or automatic reason. Device routing and
  local output volume are not replay events.
- Periodic checkpoints capture the effective current media, position, queue,
  and allowlisted settings, including both source offsets and envelope progress
  during a crossfade. Seeking within a recipe folds events from the nearest
  checkpoint instead of executing skipped history.
- Replay uses typed internal queue and playback intents. Schema validation
  rejects unknown event types, excessive sizes, and any request to delete,
  download, publish, restore credentials, or execute arbitrary commands.

### Replay contract

- Online references are freshly resolved. A changed edition or materially
  different duration requires an explicit choice.
- Missing or moved media follows a declared `pause`, `skip`, or `ask` policy.
  Mariana never silently substitutes an unrelated recording.
- Live media is marked non-replayable unless its provider supplies a verified
  archive identity for the same event.
- Replay promises event order and position within documented tolerances, not
  sample-identical audio. Buffering, network delays, source revisions, decoder
  versions, and output hardware make sample identity impossible to guarantee.

### Delivery stages

1. Specify the schema, threat model, fixtures, size limits, and property tests.
2. Add a local recorder fed by an allowlisted backend event stream.
3. Add a read-only inspector and dry-run availability/privacy report.
4. Replay local recipes with deterministic shuffle and explicit missing-source
   handling.
5. Add checkpoints and seeking within a recorded session.
6. Consider encrypted recipe sharing only after recipient identity and ACLs
   exist.

Compatible local-first follow-ups include artist/label watchlists keyed by
MusicBrainz IDs, an offline discovery digest, a verified-channel registry, and
a recipe portability preflight. None requires a speculative social cloud or a
second playback authority.
