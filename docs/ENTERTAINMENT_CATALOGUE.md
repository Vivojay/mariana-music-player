# International entertainment catalogue

## Scope and current baseline

This is an incremental local delivery on `feature/homepage-discovery`, starting
from `ed2c250387b10068c24ed2544c87d95e73f1a694` and preserving the shared working
tree. It does not certify or replace the other in-progress development lanes.
No commit, publication, provider account, service deployment, or release is
part of this batch.

Audit findings from current code:

- `RadioCatalog` already supports curated stations, Radio Browser searches,
  endpoint resolution, health and favourites. SomaFM Groove Salad and Secret
  Agent are existing identities, not new station records.
- `beta.podcasts` already reads public RSS from numerous hosts, despite its
  Podbean compatibility names. Its legacy vendor dictionary includes Dateline,
  BBC comedy and several other research-adjacent programmes. Inclusion there
  is not evidence of current availability. The pre-existing Maintenance Phase /
  Storytime duplicate was subsequently corrected using the publisher evidence
  recorded below; no other legacy programme is newly certified by that check.
- Home has Bandcamp/ListenBrainz cards and official-link destinations.
  `DiscoverySelection` already owns bounded asynchronous lookups and typed,
  revision-bound Play/Queue choices. This batch extends that worker.
- LibriVox already has its own catalogue/section metadata, search, play, queue,
  and download support. It is not reimplemented as another generic RSS source.
- There was no shared searchable source registry, and the legacy podcast parser
  incorrectly accepted article links as playable enclosure fallbacks.

## Enabled source data and evidence

Checks below were performed on **2026-09-11**, without saving media. They are
point-in-time access observations, not worldwide availability guarantees or
permission to redistribute, record, rebroadcast, or scrape artwork.

| Source | Existing/new path | Evidence and health |
| --- | --- | --- |
| SomaFM Groove Salad / Secret Agent | Reuse existing station IDs and radio pipeline | [Official external-player directory](https://somafm.com/listen/). Existing endpoint configuration retained; not newly claimed as decoder-tested. |
| WFMU | Add one station through existing radio seed/store | [Official direct-stream links](https://www.wfmu.org/audiostream.shtml). HTTPS MP3 stream returned 200, `audio/mpeg`; read and discarded 8192 bytes. No recording/download capability. |
| Live on KEXP | Shared public RSS parser and `pod live_on_kexp` alias | [Official audio-feed description/subscription](https://www.kexp.org/podcasts/live-on-kexp/). Feed: 200; 1,240 enclosure-bearing entries; 4,689,567 bytes. Publisher KEXP, host Omny Studio. Not extracted YouTube audio. |
| Circle Round | Shared RSS parser and `pod circle_round` alias | [WBUR page with RSS subscription](https://www.wbur.org/podcasts/circleround). Feed: 200; 462 enclosure-bearing entries; 1,427,625 bytes. Public edition, not Circle Round Club. |
| Kulturfragen | Shared RSS parser and `pod kulturfragen` alias | [Deutschlandfunk page with RSS subscription](https://www.deutschlandfunk.de/kulturfragen-100.html). Feed: 200; 32 enclosure-bearing entries; 58,166 bytes. German-language cultural programming. |

The KEXP radio endpoint could not be reached during this check. It is not added
as a newly healthy radio station. Its podcast feed is a different, successfully
checked resource. KEXP's former homepage link card is replaced by one programme
card so it is not displayed twice.

### Legacy programme-identity correction — 2026-09-12

The `maintenance_phase` alias incorrectly used the same Simplecast feed as
`storytime_with_seth_rogen`. The correction changes only Maintenance Phase's
endpoint, not Storytime's endpoint or any stored media/favourite identities.

| Programme | Official identity evidence | Bounded feed verification |
| --- | --- | --- |
| Maintenance Phase | [Programme website](https://www.maintenancephase.com/) and [publisher-hosted About page with RSS subscription](https://www.buzzsprout.com/1411126/about) identify Aubrey Gordon and Michael Hobbes. | The linked [public RSS](https://feeds.buzzsprout.com/1411126.rss) returned 200 after one redirect to `rss.buzzsprout.com`: 644,283 bytes, title `Maintenance Phase`, 97 supported enclosure-bearing episodes, GUID identities. |
| Storytime with Seth Rogen | [Earwolf's programme page](https://www.earwolf.com/show/storytime-with-seth-rogen/) identifies the show and its published episode catalogue. | The existing [Simplecast RSS](https://feeds.simplecast.com/ZK9BGVQN) returned 200 without redirects: 32,553 bytes, title `Storytime with Seth Rogen`, author `Earwolf`, 10 supported episodes. The latest episode title matched Earwolf's catalogue. |

These were metadata-only requests with an 8 MiB decoded-byte limit, bounded
redirects/timeouts and in-memory parsing through the application parser. No
episode media, artwork, account-only content or response files were downloaded.
The dictionary audit found this was its only exact duplicate feed URL; it does
not establish that every other legacy feed is currently healthy or correctly
labelled.

New legacy feed caches record a SHA-256 `feed_identity` for their exact source
reference, not the raw URL or any custom-feed query credentials. A mismatched
source is not reused. Because old Maintenance Phase caches can contain Storytime episodes,
that corrected alias also requires one successful source-bound refresh when an
older cache lacks this field—even if its date is today. If that refresh fails,
the old file is preserved but its wrong-programme episodes are not presented as
Maintenance Phase. Unrelated unbound legacy caches retain their existing behavior.
No favourites, recents, playlists or selected episode identities are migrated to
another programme.

## Identity, metadata and actions

`CatalogueEntry` distinguishes station/programme from publisher and optional
hosting platform. It records the canonical official page, feed/station
reference, language, region, category, attribution, artwork provenance,
validation date, health, restrictions and supported actions. Episode records
come from the feed; a publisher's entire catalogue is never implied.

Podcast media uses the existing `MediaRef`/`podcast_episode_identity` boundary.
Feed-scoped GUID identity takes precedence over the changing enclosure URL.
Duplicates are collapsed only within that feed by durable identity (or exact
enclosure when no durable identity exists), not by title. Different feeds remain
separate unless their equivalence is explicitly established. Hosting-platform
aliases do not create additional programme records.

Trusted feed metadata includes full title, creator, programme, description,
publication date, explicit flag, supplied image reference, duration and valid
inline chapters. Metadata is mapped identically for Home and legacy podcast
commands. Linked external chapter documents are not fetched in this slice.

Home retains one source card per entry, explicit Details, and native
Browse/Inspect actions. Its existing selection component now supports published
media choices and 15-item pages (up to 120 episodes per programme). Request IDs,
card binding, revision, expiry, eligibility and policy are rechecked before
Play/Queue. A page refresh cannot activate an earlier selection. No action writes
command text into a PTY or creates a second playback authority.

Existing `pod`, `radio`, `media info`, and finite-media `download-ml current`
commands remain the CLI paths. No new provider-specific family or favourite
store is added. Live radio has no finite seek, download or recording capability.
Subscription/follow management and homepage download buttons are **not**
implemented by this slice; the audit found no reusable general subscription
store to expose as if it were already present.

## Consent, limits and failure policy

- Bundled catalogue search and source cards work offline. They do not fetch
  content or images during startup. Native Home inspection requires existing
  online-discovery consent; automatic artwork consent remains independent.
- Feed retrieval uses the existing public-target/redirect/peer-checked HTTP
  transport with podcast Accept/User-Agent headers. It has bounded redirects,
  read/connect timeouts, a 25-second request budget and an 8 MiB decoded-byte
  ceiling. It does not retry indefinitely or weaken provider restrictions.
- The parser rejects XML DTD/entity declarations, malformed feeds, absent media
  enclosures, credential-bearing/private literal references and live playlists.
  It considers at most 1,500 feed entries. Article RSS is not podcast media.
- One existing discovery worker does the reads. Cancellation is checked between
  network chunks and before publishing/caching. A blocked socket can remain
  until its bounded timeout; cancellation is not claimed to be instantaneous.
- The in-memory cache holds at most eight feeds with 120 bounded episode records
  each, fresh for fifteen minutes. It stores no files or credentials. A failed
  refresh does not silently use an expired media transport. Source cards remain
  visible offline with an actionable lookup error; no fabricated episodes.
- Feed images remain references for the existing validated current-artwork
  service. Home source cards use placeholders. No new image search/scraping or
  public filesystem/transport projection is introduced.
- Renderer projections contain source display data and opaque selection handles,
  never enclosure URLs, private paths or authentication details. Existing
  queue/library persistence sanitization remains in place.

## Search coverage

`home search` and `find --in catalogue` search the bundled programme/station
index, not provider-wide catalogues or every episode. Supported fields are
`title:`, `creator:`, `programme:`, `provider:`, `language:`, `region:` and
`category:`. Words combine with AND. At programme level creator refers to the
credited publisher/source, not every guest. Quote values containing spaces.

Home's search box also filters other currently displayed cards. Date bounds
`after:`/`before:` can match dated release/editorial cards; programme and station
records have no synthetic release date and cannot match date bounds. Broader
episode indexing, remote search coverage and incremental feed subscriptions
remain a later, separately validated slice.

## Remaining research candidates and exact status

These are backlog records, not enabled playback providers. "Partial" refers to
current code or existing official links; "new" means a shared-standard candidate
still needs programme/endpoint acceptance. "Conditional" requires additional
access/rights evidence. The status of a corporation never enables every item.

| Candidate(s) | Status / next acceptance boundary |
| --- | --- |
| [Radio Paradise](https://radioparadise.com/listen/stream-links) | New; choose and smoke-test an official external-player stream. |
| [KEXP radio](https://www.kexp.org/mobile/kexp-livestreams/) | Conditional; published stream route, unsuccessful local access check. Do not infer failure of the separately verified podcast. |
| [Song Exploder](https://songexploder.net/), [Twenty Thousand Hertz](https://www.20k.org/) | New; verify publisher-linked public RSS and enclosure access. Song Exploder's page rejected the local HTTP check; do not work around provider controls. |
| [Dateline / NBCUniversal](https://www.nbcuniversal.com/article/dateline-launches-dateline-en-espanol-peacock) | Partial; legacy Dateline alias exists but needs current-feed validation. English/Spanish podcast editions are distinct from Peacock TV access. |
| [BBC](https://help.bbc.com/hc/en-us/articles/42652680528659-Update-on-access-to-BBC-Sounds-outside-the-UK) | Partial/conditional; existing comedy alias is not certification. Validate each public edition and international availability; Sounds is not a blanket global catalogue. |
| [WNYC](https://www.wnycstudios.org/), [Radiolab](https://radiolab.org/how-to-listen) | New; selected public feeds. Keep member archives separate. |
| [Maximum Fun](https://maximumfun.org/podcasts/), [Radiotopia](https://www.radiotopia.fm/podcasts) | New; select individual programmes, not network-wide download grants. |
| [SBS](https://www.sbs.com.au/audio/podcasts), [ABC Australia](https://www.abc.net.au/listen/podcasts/categories), [RNZ](https://www.rnz.co.nz/podcasts) | New; select multilingual/regional programmes with verified public enclosures. ABC Like A Version already has an external-link card. |
| [Deutschlandfunk](https://www.deutschlandfunk.de/podcasts) | Partial; Kulturfragen enabled, other programme editions remain candidates. |
| [Radio Ambulante / El hilo](https://radioambulante.org/sobre-nosotros), [Sowt](https://www.sowt.com/) | New; Spanish/Arabic programme-level feed acceptance. Ordinary website article RSS is insufficient. |
| [RTHK](https://podcasts.rthk.hk/podcast/guide_e.php), [KBS](https://world.kbs.co.kr/service/about_podcasts.htm?lang=e) | New; official podcast directories, select individual feeds and validate editions. |
| [Akashvani](https://prasarbharati.gov.in/listeners-corner/) | New; prioritize Vividh Bharati/Raagam/regional station endpoints, not the entire app catalogue. |
| [HT Smartcast](https://www.htsmartcast.com/), [Audiomatic](https://www.audiomatic.in/) | New; choose currently available programme feeds and distinguish archives from active shows. |
| [Brains On!](https://brainson.org/), [Storynory](https://www.storynory.com/) | New; family-feed verification. WBUR Circle Round is enabled separately. Hosting overlap does not imply programme duplication. |
| [LibriVox](https://librivox.org/api/info) | Already supported by the current local audiobook implementation. Native/provider/download acceptance still has its own ledger; do not duplicate it here. US public-domain status is not a universal territorial assertion. |
| [Boiler Room](https://boilerroom.tv/), [Book Club Radio](https://www.bookclub.radio/about), [COLORS](https://colorsxstudios.com/), [Cercle](https://www.cercle.io/) | Partial: existing official-link cards. Native video/player permissions are conditional, not inferred from an extractor. |
| [Elevator Music](https://elevatormusic.live/), [NTS](https://www.nts.live/) | Partial: existing official destinations. Verify exact entity and catalogue/player route before expansion. |
| [Sofar](https://www.sofarsounds.com/), [ARTE](https://corporate.arte.tv/en/general-conditions-of-use/) | Conditional: official link/approved player; territorial and expiry boundaries remain. |
| [KCRW](https://www.kcrw.com/live-now), [dublab](https://www.dublab.com/), [Worldwide FM](https://www.worldwidefm.net/) | New/conditional: select public streams or programme feeds, assess member content separately. |
| [Oroko](https://oroko.live/) | Conditional; broadcast-hiatus notice means it must not be presented as dependable always-on radio. |
| [Radio France](https://developers.radiofrance.fr/doc/tutorial-by-example/show), [RTVE/RNE](https://www.rtve.es/play/radio/) | New/conditional; individual public feeds/live routes, not whole player catalogues. |
| [NPR](https://www.npr.org/podcasts-and-shows/) | Partial; Planet Money already has a legacy feed alias. Other public editions need individual checks. |
| CBC English / [Radio-Canada OHdio](https://assistance.radio-canada.ca/hc/fr/articles/360062489331-Pourquoi-les-flux-RSS-de-Radio-Canada-OHdio-ne-sont-ils-plus-disponibles) | Conditional; do not conflate English public podcasts with OHdio's withdrawn RSS availability. |
| [The Moth](https://www.themoth.org/stories/library?episodeType=the-moth-podcast), [Night Vale](https://www.welcometonightvale.com/listen), [Magnus Archives](https://rustyquill.com/show/the-magnus-archives/) | New; public audio/storytelling/fiction programme verification with content labels. |
| [Internet Archive](https://archive.org/developers/), [PeerTube](https://docs.joinpeertube.org/api/rest-getting-started), [Blender films](https://studio.blender.org/films/) | Conditional; trusted collection/instance/creator and per-item licence verification. Not unrestricted catalogues. |
| [NASA](https://www.nasa.gov/podcasts), [TED](https://www.ted.com/about/our-organization/our-policies-terms) | New/conditional; distinguish public podcast media from approved video routes and reuse restrictions. |
| [Podbean](https://help.podbean.com/support/solutions/articles/25000005057-what-is-my-podbean-feed-url), [Acast](https://www.acast.com/en-ca/blog/how-to-set-up-rss-for-your-podcast), [Spotify public podcast RSS](https://support.spotify.com/cw-en/creators/article/finding-and-enabling-your-rss-feed/) | Shared-standard hosting, not three parallel programme frameworks. Existing RSS ingestion can handle accepted public feeds. This does not enable Spotify music/exclusive video. |
| [Podcast Index](https://podcastindex-org.github.io/docs-api/), [Radio Browser](https://docs.radio-browser.info/) | Discovery infrastructure, not content licences. Radio Browser already exists; its broader mirror/discovery policy is outside this batch. |
| [SoundCloud](https://developers.soundcloud.com/docs/api/), [Mixcloud](https://www.mixcloud.com/developers/) | Conditional official API/player integration. Track downloads require separate permission. |
| Netflix, Hulu, Prime Video, Peacock, Disney+, Apple TV and comparable premium TV catalogues | Unsupported native catalogue integration in this lane. No authentication/DRM/territory bypass, raw-stream extraction or unofficial account handling. |

## Verification boundaries

Automated checks cover parser refusal cases, identity stability across enclosure
changes, title-safe deduplication, metadata/chapters, shared legacy mapping,
cache expiry/cancellation, offline consent, typed paging and stale-selection
rejection, search, and existing radio/playback/queue contracts.

Official page/feed and small radio-prefix requests are live evidence, but are
not audible/native video acceptance or packaged acceptance. No full media was
downloaded, no screenshots were created, and no build artifacts are required
for the no-emit desktop/component checks. Fresh exact command results are
reported with the delivery; older evidence does not certify concurrent edits.
