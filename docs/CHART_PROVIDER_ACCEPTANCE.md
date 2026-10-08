# Apple public Top Songs feed: acceptance hold

Reviewed 2026-09-11. **No chart adapter is enabled or implemented by this review.**
Apple's public marketing feed is a credible first candidate, but the requested
desktop reuse boundary is not yet sufficiently verified. This is an integration
acceptance record, not a claim that all RSS display is prohibited.

## Verified source and payload

Apple's [official tools page](https://performance-partners.apple.com/tools)
invites incorporation of top-content RSS lists into websites and viewing in
standard RSS readers. Its [RSS builder](https://rss.marketingtools.apple.com/)
offers storefront, feed, result-limit, and format settings. This establishes an
intended public feed use; it is not an invented or scraped chart source.

An approved, bounded GET of the [US music most-played feed, requested limit 10](https://rss.marketingtools.apple.com/api/v2/us/music/most-played/10/songs.json)
returned HTTP 200 without credentials during this review. No images were fetched.

| Field | Observed value or meaning |
| --- | --- |
| Provider / title / territory | Apple Music / `Top Songs` / `country: us`. Never label this Billboard, all-service US popularity, or a global chart. |
| Ordering | Provider supplies an ordered `results` array. Inspected entries contain no explicit numeric rank field. Preserve array positions; do not re-sort or renumber after dropping malformed entries. Confirm ranking semantics before describing generated numbers as an official rank. |
| Feed timestamp | `Thu, 10 Sep 2026 19:30:38 +0000`. Label as **feed updated**, not a weekly chart date. An item's `releaseDate` is its release date, not the chart date. |
| Attribution | `Copyright © 2026 Apple Inc. All rights reserved.` No `rights` field was supplied. |
| Content links | Official `https://music.apple.com/us/album/.../<album-id>?i=<song-id>` links. The `i` query parameter identifies the song; stripping every query parameter would lose that identity. |
| Artwork references | Feed-supplied `artworkUrl100` URLs on `is1-ssl.mzstatic.com`; these references establish availability, not a general image-reuse licence. |
| Cache headers | `Cache-Control: max-age=0, private, must-revalidate`; weak ETag `W/"e19c86c9214bf120a3798e570a53e40b"`. These are observations, not constants to hard-code. |

## Exact acceptance blockers

1. **Scope of RSS reuse.** The public invitation does not expressly resolve
   redistribution in a desktop music player, normalized persistent/offline chart
   display, permitted retention, or downloaded cover-image caching. No applicable
   RSS-specific grant settling those points was found in the reviewed official
   resources. Obtain the governing RSS terms or written confirmation from
   [Apple's marketing support](https://appleservices-marketing.zendesk.com/hc/en-us).
2. **Do not borrow another product's licence.** The
   [Search API terms](https://performance-partners.apple.com/search-api) and
   [Enterprise Partner Feed terms](https://performance-partners.apple.com/epf)
   describe their own promotional-use grants and restrictions. Neither was
   verified as governing this RSS endpoint. The
   [Apple Music identity guidelines](https://marketing.services.apple/apple-music-identity-guidelines)
   explain approved badges, icons, and linking presentation; badge permission is
   not an album-art caching licence. Apple's
   [general website terms](https://www.apple.com/legal/internet-services/terms/site.html)
   reserve content rights while allowing more-specific service terms to control.
3. **Current homepage cache is incompatible without changes.** `private` allows
   a single-user HTTP cache; it does not mean the public feed contains secret
   data or that storage is entirely forbidden. But `max-age=0, must-revalidate`
   cannot be treated as six hours of freshness or blanket stale-if-offline
   permission. HTTP reuse needs successful validation, including conditional
   requests with the current ETag. See
   [RFC 9111, response cache directives](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.2.2).
   Separate application-level archival display would also need a verified
   provider retention/reuse policy.

Ask Apple specifically whether a distributed desktop application may display
this public feed's ordered metadata with explicit official song links, retain a
private normalized cache, show dated cached results offline, and download/cache
the supplied cover images; request the required branding, attribution, retention,
and revalidation rules. No external support message has been sent.

## Integration consequence

There is **no new provider class or initialization signature to wire**. Keep
online discovery default-off and existing chart destinations link-only. No Apple
host allowlist, image downloader, ranking card, or playback control was added.

The inspected `HomepageService` already provides cancellation-aware background
refresh, but its provider/cache allowlists accept only Bandcamp Daily and
ListenBrainz releases; sections support culture/releases, with shared six-hour
freshness and up-to-30-day cache retention. The desktop link validator also
removes all query parameters. Those are deliberate boundaries, not permission to
silently inject a chart through an existing source label.

After permission is settled, acceptance must cover bounded streamed JSON,
territory/kind/ID/timestamp validation, stable provider order, malformed/duplicate
rows without invented positions, exact official song-link identity and query
allowlisting, private-URL rejection, ETag/304 validation and failure behavior,
per-provider freshness/retention, cancellation and stale-generation rejection,
and safe cache restoration. Start with no artwork unless its reuse is confirmed.
Chart cards must explicitly open the official Apple destination; no automatic
first-search-result playback or relabeling as another provider's chart.
