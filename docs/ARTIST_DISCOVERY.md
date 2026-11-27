# Artist discovery and culture sources

Mariana Home offers 78 external destination cards alongside its existing playable catalogue and opt-in news and releases. After a successful release refresh, Home spotlights up to four distinct credited artists. The selection rotates daily over its cached release metadata. Its offline index can be searched in the Electron Home panel. The Python CLI prints the same cards and links with `home`. The standalone web player and phone wrappers bundle the same 78 records, with search, category filters, source links, and URL copying in the Culture directory. Their console accepts `sources QUERY` or `home sources QUERY`. Use `home sources QUERY` in a terminal to filter the directory. A source card opens its official site in the desktop app. Each external URL passes the desktop's exact-destination check.


In the full Electron app, choose **Home** on the terminal-view strip or type `home`. **Settings** inside Home controls startup visibility and online discovery independently. A later feed refresh updates the open page without reopening it after you close it.

While a local video is loaded and its picture is ready, **Loop video preview** on the current-video card plays up to four seconds of the current picture on repeat. **Stop preview** removes the muted loop without affecting playback position or volume. The card uses the prepared local video, makes no network request, and honors the desktop motion setting. Editorial cards use cached artwork from their sources when supplied.

In a native paired browser, open **Flow → Home**. The tab reads the host's cached headlines, release cards and bundled official destinations. It displays cached publisher artwork on editorial, release and artist spotlight cards when available. The paired tab retrieves only validated still images referenced by the current native feed through its authenticated loopback connection. Missing or expired images leave readable text cards. **Enable online discovery** delegates to the same native setting as `home online enable`. **Refresh news and releases** delegates to `home refresh`. Opting out of library sharing keeps native library summaries and locally matched discovery versions off the page. For available programme and release choices, the browser uses the same `home pick`, `home versions`, `home play`, and `home queue` commands. Version selection checks the host's current revision before applying a choice. Opening a source uses its public destination in your browser. See [the paired workspace](SURFACE_PARITY.md).

## Finding and following artists

| Mariana command | Result |
|---|---|
| `artist discover` or `artist discover electronic` | Distinct credited artists on recently or soon-to-be released MusicBrainz releases, optionally restricted by genre tag. |
| `artist emerging indie` | Groups formed since January 1 two calendar years ago, optionally tagged with the supplied genre. Group formation is a proxy for career stage. Use discovery or name search for solo performers. |
| `artist search Suggahunny` | Searches MusicBrainz by name. When it returns no artist or a provider error, Mariana searches Apple Music. When both services have no fresh results it can display saved follows, previous results during an outage, and a Bandcamp search link. It displays the source of fallback results and any provider error. |
| `artist follow ID` | Verifies the selected identity and stores the canonical name and ID in the existing local SQLite database. |
| `artist list`, `artist unfollow ID` | Read or edit the local watchlist offline. |
| `artist releases`, `artist tracks` | Finds indexed release groups or recordings with first release dates between 90 days ago and 90 days ahead. Shows dates and links to the corresponding MusicBrainz or Apple Music records. Append a followed ID to narrow the check. |
| `artist news` | Reads up to 100 recent RSS headlines per publisher from BrooklynVegan, Louder Than War and GoldFlakePaint. Name matching uses whole names, case-insensitively. Reports unavailable feeds separately. Append a followed ID to narrow results. |

The explicitly requested artist searches, follows and refreshes make network requests. Home retains its independent automatic-discovery preference. Each MusicBrainz search uses the player's existing rate-limited client, returns up to 100 provider-ranked records per request, and prints up to 25 artists per discovery page. MusicBrainz follows are grouped into batches of 12 for release and recording queries, with MusicBrainz IDs checked on the returned credits. Future dates come from submitted metadata and can change. Identical artist names and common words can produce unrelated headline matches. No article bodies, press images or third-party recordings are redistributed.

Copy the UUID or `apple:NUMBER` exactly as printed to follow the artist. You can also paste the artist’s official MusicBrainz or Apple Music artist URL after `artist follow`. Mariana extracts the ID and verifies it with the corresponding catalogue. Apple lookups use the selected storefront. Apple follows use ID lookups for albums and songs in the selected storefront, checked against the returned artist ID and the same 90-day window. The storefront defaults to US. In PowerShell, set `$env:MARIANA_APPLE_COUNTRY = "IN"` before starting Mariana to use India for search, follow and refresh. For example, run `artist follow apple:6784762054` to confirm the ID listed on [Suggahunny’s Apple Music page](https://music.apple.com/in/artist/suggahunny/6784762054). `artist tracks apple:6784762054` then checks for that follow’s recordings. Search history retains the last 64 successful queries locally. A rate limit, TLS error, timeout, malformed response, empty catalogue result, and match in your offline follows each have distinct feedback. Catalogues can index different spellings and catalogue coverage varies by region. [Apple Search API](https://performance-partners.apple.com/search-api) and [artist and release lookups](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/LookupExamples.html).

## Updates inbox

Run `artist refresh` to collect matching releases, tracks and press headlines together. A second refresh recognises the same public URLs across sessions. The result shows the number newly saved and individual feed failures. `artist inbox` lists unread items offline. Use `artist read ITEM_ID` or `artist read all` to acknowledge updates, and `artist inbox all` to include read items. `artist refresh ID` narrows the check to one follow. Mariana admits up to 400 new items from a refresh and keeps the latest 1,000 saved items. Deduplication covers that retained history.

## Source inventory

| Group | Added destinations |
|---|---|
| Press and criticism | Dork, Stereogum, NME, Consequence, DIY, The Quietus, The Line of Best Fit, Clash, Louder Than War, GoldFlakePaint, BrooklynVegan, The Needle Drop, Resident Advisor, Tiny Mix Tapes, Gorilla vs. Bear, Rockdelux, JUICE, Les Inrockuptibles, Mixmag, DMY (Dummy Mag), Soompi, Tone Deaf, The Caravan, Rolling Stone, Rolling Stone India, Homegrown India |
| Catalogues and stores | Rate Your Music, Every Noise at Once, Album of the Year, Discogs, Hype Machine, Last.fm, Encyclopaedia Metallum, Beatport, Juno Records |
| Live performance and art | KEXP's official YouTube channel, Seattle Channel Art Zone, NPR Music Tiny Desk, Sigil Radio and PAN!C ROOM |
| Festivals and conventions | Primavera Sound, Glastonbury, Cannes, Sundance, New York Comic Con, Angoulême, Tokyo Game Show, Gamescom, Amsterdam Dance Event, Eurosonic Noorderslag, The Great Escape, Roskilde, Fuji Rock, Montreux Jazz, Sónar, Comic Con India, India Art Fair and WonderCon |

SXSW, Comic-Con International/San Diego Comic-Con and COLORSxSTUDIOS already had destinations. The KEXP video channel complements the existing native Live on KEXP podcast. Comic-Con entries identify their individual organisers. The directory does not assume that all conventions belong to a single global franchise. JUICE links to its video archive and Tiny Mix Tapes is labelled as an archive. Event sites provide their current cities and dates.

Directory addresses live in `desktop/culture_sources.json`. More programme candidates and earlier verification evidence are in [the entertainment catalogue](ENTERTAINMENT_CATALOGUE.md) and [discovery roadmap](DISCOVERY_COMMUNITY_AND_SESSION_ROADMAP.md).

## Coverage and open work

| Status | Capability | Acceptance for remaining work |
|---|---|---|
| Implemented | On-demand search, ID-based follows, date-windowed tracks and releases, headline checks, persistent deduplicated updates inbox with read state, offline links and local watchlist | Fixture tests cover distinct identities, partial news coverage and missing data. |
| Requires live acceptance | Provider availability in the user's region and lesser-known artists with sparse metadata | Run discovery, follow two returned IDs, then check releases, tracks and news. News providers can reject or change feeds. |
| Pending | Continuous notifications, background schedules, cross-device inboxes and additional native provider feeds | Add opt-in scheduling, deduplication, quotas, vendor-specific attribution and a verified adapter for each source. |
| Pending | Cross-device watchlist sync, full app-specific watchlist UI, distribution terms for commercial API deployments | Finish identity reconciliation, privacy controls, platform acceptance and provider approvals where required. |

Research references include the [MusicBrainz artist index](https://musicbrainz.org/doc/MusicBrainz_API/Search/ArtistSearch), [release and recording search fields](https://musicbrainz.org/doc/MusicBrainz_API/Search), [API application requirements](https://musicbrainz.org/doc/MusicBrainz_API), [KEXP performance catalogue](https://www.kexp.org/watch/), [Sigil Radio’s community mission](https://sigilradio.live/about), [PAN!C ROOM's official channel](https://www.youtube.com/channel/UCANlvQuGwrusnPsc3SlTsmw), [GoldFlakePaint](https://goldflakepaint.ghost.io/), [Seattle Art Zone](https://www.seattlechannel.org/artZone), [Angoulême’s current organiser](https://www.angouleme-bandedessinee.com/) and [Tiny Mix Tapes’ hiatus announcement coverage](https://ra.co/news/71537).
