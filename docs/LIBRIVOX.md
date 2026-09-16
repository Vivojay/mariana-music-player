# LibriVox integration

Mariana can browse and play the LibriVox public-domain audiobook catalog without
an account or API key. The integration is lazy: importing or starting Mariana
does not contact LibriVox. A catalog request occurs only after an explicit
`librivox` search, lookup, or action that needs project details.

## Supported catalog surface

The implementation uses LibriVox's released
[`audiobooks` API](https://librivox.org/api/info) with JSON responses and bounded
timeouts, redirects, result counts, and response sizes. It supports title,
author-surname, genre, and recent-addition queries. An expanded project lookup
supplies:

- catalog identity, title, authors, translators, language, genres, description,
  and duration;
- chapter/section titles, volunteer readers, languages, durations, and direct
  audio references;
- catalog, text-source, RSS, whole-book ZIP, Internet Archive, and cover-art
  links when LibriVox supplies them.

LibriVox also documents per-section audio, whole-book ZIP and RSS downloads, and
additional Internet Archive formats on its
[help page](https://librivox.org/pages/help/) and
[feed page](https://librivox.org/pages/librivox-feeds/). Mariana exposes only
the fields and destinations that the project record actually provides. It does
not fabricate missing editions, chapter files, cover images, narrators, or
durations.

## Commands

Run `librivox help` (aliases: `lv`, `libri`) for the in-application reference.

```text
librivox search "The Time Machine" --limit 10
librivox author Wells
librivox genre Poetry
librivox recent 30
librivox show 1
librivox chapters id:123
librivox play 1 2
librivox current
librivox chapters current
librivox goto 5
librivox next
librivox previous 2
librivox restart
librivox resume
librivox queue 1 all
librivox download 1 all --format mp3 --to "C:\Audiobooks"
librivox rss 1
librivox open 1 text
```

Bare numbers refer to the latest LibriVox result list. `id:<catalog-id>` is an
explicit catalog reference and is therefore safer in notes or repeated commands.
Detail responses must identify exactly the requested project before they can be
cached or selected. A different or ambiguous returned identity is rejected rather
than substituted. Malformed optional collections and invalid link fields are
discarded without inventing missing metadata or aborting otherwise usable items.
Commands that take a book reference also accept `current` while a LibriVox chapter
is active or selected in the persistent queue.
`play` defaults to chapter 1 and appends any missing sections of that book to the
persistent queue so chapter navigation and automatic continuation use Mariana's
existing queue authority. It does not clear or replace unrelated queue entries.
`queue` and `download` default to all chapters.
Downloads always use the existing confirmation and output-safety path. `--yes`
is the same explicit command-scoped bypass used by Mariana's other download
commands.

## Playback, queue, metadata, and favourites

Each chapter is projected into the existing finite, seekable, downloadable
online-media model. Playback still has one controller; LibriVox does not start a
second player. Queue operations append to the current persistent queue and normal
`media info`, favourite, block, play-region, history, and artwork behavior applies.

LibriVox publishes most audiobook sections as separate finite files. Mariana
therefore does not fabricate one continuous whole-book timeline. The ordinary
progress bar and `seek` command remain freely seekable within the current section.
Use `librivox goto`, `next`, `previous`, `first`, and `last` to move between section
files. Navigation never wraps. `librivox current` reports the chapter position;
`restart` returns to the section start; `resume` uses the persisted queue cursor
and the existing long-media resume offer where one is available.

The durable chapter identity is derived from the official RSS project identity,
LibriVox catalog ID, and section ID. The archive MP3 URL is retained as playback
transport, not as the favourite key. Consequently, a changed enclosure URL does
not change the chapter identity, while two chapters with the same title remain
distinct.

Persisted resolver hints contain only the stable book and section IDs plus the
existing durable-podcast identity marker. Descriptions and artwork URLs remain
transient catalog metadata; credentials, request headers, redirects, and resolved
playback URLs are not stored as identity data.

## Availability and rights

Catalog lookup and playback remain subject to LibriVox and Internet Archive
availability, network conditions, regional access, and individual project data.
Search is the released catalog's own prefix/matching behavior, not a full-text or
relevance-ranked search engine.

LibriVox states that its recordings and source texts are evaluated for public
domain status under United States law. Copyright terms differ by jurisdiction,
so users remain responsible for checking whether listening, downloading, or
redistributing a work is permitted where they are located. Mariana does not
bypass access controls or infer broader rights from the presence of a catalog
record.
