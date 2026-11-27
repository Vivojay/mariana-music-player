# Podcasts, Podbean and audiobooks

## Listen to a Podbean show

In the Mariana CLI, its TUI command box, a paired native Console/Flow session or the portable player's Console, enter these commands one line at a time. `tracklists` is the show slug used by Mariana's existing 1001Tracklists vendor. The episode titles and count come from the current feed.

```text
podbean search 1001Tracklists
podbean open tracklists
podbean follow
podbean episodes
podbean play 1
podbean queue 2
podbean list
```

`open` accepts a show slug, its homepage such as `https://tracklists.podbean.com/`, or a public feed such as `https://feed.podbean.com/tracklists/feed.xml`. The list shows ten episodes per page in the publisher's order. If it reports multiple pages, enter `podbean episodes 2`. Episode 11 keeps number 11 on page two. Opening another show resets the numbering. `podbean play 1` selects that episode in the ordinary player. Repeating it on the paused episode resumes playback. `queue` adds a choice without starting it. [Podbean’s public feed format](https://help.podbean.com/support/solutions/articles/25000004906-validating-my-podcast-feed)

`podbean search WORDS` queries Apple’s podcast directory and filters its first 50 matches to recognized Podbean RSS addresses. Open a result using its printed slug. For a show missing from these results, use its public feed from the publisher. `podbean follow SHOW` saves a show address and `podbean unfollow SHOW` removes it. Following a known address works offline. Playback and browsing uncached feed content require network access. Native shelves use Mariana's local database. The portable player uses the current browser profile and origin. [Apple Search API](https://developer.apple.com/library/archive/documentation/AudioVideo/Conceptual/iTuneSearchAPI/)

## Search a LibriVox audiobook from Console

The native and portable command lines both support the following sequence. Pick a result or reuse a catalog ID as `id:NUMBER`.

```text
librivox author Shelley --limit 10 --offset 0
librivox show 1
librivox chapters 1
librivox play 1 2
```

Use `librivox search Frankenstein` for a title, `librivox genre Poetry` for a genre, or `librivox recent 7` for newly cataloged books. The portable player displays chapter lists ten at a time. `librivox chapters 1 2` shows its second page. `librivox queue 1 all` adds the book to the local queue. `librivox play 1 2` adds missing book chapters and plays the second chapter.

## Flow, podcasts and books

In portable Flow, open **Podcasts & audiobooks**. Choose **Podbean by title**, **Podbean by slug or URL**, **Apple Podcasts**, or **LibriVox**. Select **Save** to follow a show or book, then **Episodes** or **Chapters** to inspect its feed. Select a title to queue it or press **Play** for immediate playback. Use **Next** and **Previous** under the feed for additional pages. The shelf, queue, bookmarks and playhead are shared by Console and Flow at the same address.

| Workflow | Native player and paired surfaces | Portable browser and mobile web shells |
| --- | --- | --- |
| Existing podcast vendor and public RSS | `podbean vendors`, `pods`, `/rss FEED` and the discovery catalogs | Apple Podcasts and Podbean search, saved feeds, selective browsing, or `feed URL` to queue a feed |
| LibriVox | Search by title, author or genre, read metadata, choose chapters, navigate the current book, queue sections and download audio. See the [LibriVox commands](LIBRIVOX.md). | Title, author, genre and recent searches with limit and offset, catalog ID lookups, book and RSS details, local shelf, paginated chapter lists, whole-book queueing and chapter playback. Use a native session for richer reader metadata, book-specific navigation and the download manager. |
| Listening position | A selected, paused podcast resumes in place. Native long-form resume offers follow the existing playback policy for eligible finite and seekable media. | A queued item's position is saved locally on pause, periodically during playback and when leaving the page. Reselect that item to resume after opening the same origin. |
| Spoken-word controls | Native de-essing, transport and playback settings run through the common audio controller. | Speed and bookmarks apply to the normal queue. Voice processing in the portable player is available for local files. Online-hosted tracks depend on their publisher's access rules. |
| Account access | Public Podbean and LibriVox listening requires no provider sign-in. | Same public access. Saved shows belong to this browser profile. |

If the browser reports that the provider restricts browser requests, use the feed from the native player or a paired native session, or add a public episode audio URL directly. Keeping the same localhost address and port preserves access to a browser shelf. Live catalog and enclosure playback depend on upstream availability, cross-origin settings and codec support. LibriVox documents its public audiobook API and pagination. [LibriVox API](https://librivox.org/api/info)

## Remaining work

| Capability | Status and next acceptance condition |
| --- | --- |
| Private and premium Podbean feeds | Pending. Support authenticated membership, revocation and protected device storage before offering private playback. This public show picker accepts canonical show URLs and rejects tokenized feed URLs. [Private podcasts](https://help.podbean.com/support/solutions/articles/25000027946-setting-up-a-private-podcast) |
| Creator hosting, upload, publish and analytics | Pending. Podbean's publishing workflow uses a registered developer application, OAuth authorization, media upload and an explicit publish request. These credentials and provider grants belong to a separate creator integration. [Podbean publishing API](https://help.podbean.com/support/solutions/articles/25000008051-publishing-a-new-podcast-episode-via-podbean-api) |
| Official Podbean global search, social subscriptions and multi-device shelf/position sync | Pending. Present search coverage is the recognized subset of Apple directory results. Following is local. Provider search access, authenticated synchronization and conflict handling require separate implementation. |
| Full LibriVox standalone parity and offline files | Pending. Standalone browser support covers the listening flows above. Native-only catalog and offline management actions need corresponding portable implementations and device tests. |
| Live end-to-end acceptance | Automated tests exercise fixture directory and RSS responses, durable native follow/unfollow, real queue selection in the portable app with a simulated audio element, and error paths. Feed availability, audible output and account entitlement on physical phones and desktops still need acceptance with those devices and live services. |
