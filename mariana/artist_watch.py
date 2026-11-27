"""On-demand artist discovery and persistent, identity-scoped follows."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID

from .artist_catalogues import apple_country, apple_id, apple_rows


PREFIX = "artist.follow."
NEWS_FEEDS = (
    ("BrooklynVegan", "https://www.brooklynvegan.com/feed/"),
    ("Louder Than War", "https://louderthanwar.com/feed/"),
    ("GoldFlakePaint", "https://goldflakepaint.ghost.io/rss/"),
)
HELP = (
    "artist discover [genre] | artist emerging [genre] | artist search NAME",
    "artist follow ID | artist list | artist unfollow ID (MusicBrainz UUID or apple:NUMBER)",
    "artist releases [followed ID] | artist tracks [followed ID] | artist news [followed ID]",
    "artist refresh [followed ID] | artist inbox [all] | artist read ITEM_ID|all",
)


@dataclass(frozen=True)
class ArtistUpdate:
    summary: str
    url: str

    def display(self):
        return f"{self.summary} · {self.url}"


def _save_updates(database, updates):
    # Bound a single check and retain the most recently discovered 1,000 items.
    # A stable publisher URL or MusicBrainz entity URL is the deduplication key.
    first_seen = time.time()
    count = 0
    with database.transaction() as connection:
        for update in dict.fromkeys(updates):
            key = hashlib.sha256(update.url.encode()).hexdigest()[:16]
            cursor = connection.execute(
                "INSERT INTO artist_inbox(item_id,summary,url,first_seen) VALUES(?,?,?,?) "
                "ON CONFLICT(url) DO NOTHING", (key, update.summary, update.url, first_seen)
            )
            count += cursor.rowcount
            if count == 400:
                break
        connection.execute(
            "DELETE FROM artist_inbox WHERE item_id IN (SELECT item_id FROM artist_inbox "
            "ORDER BY first_seen DESC, rowid DESC LIMIT -1 OFFSET 1000)"
        )
    return count


def _inbox(database, args):
    if args and [a.casefold() for a in args] != ["all"]:
        raise ValueError("Usage: artist inbox [all]")
    rows = database.fetchall(
        "SELECT item_id,summary,url,is_read FROM artist_inbox WHERE is_read=0 OR ? "
        "ORDER BY first_seen DESC, rowid LIMIT 1000", (int(bool(args)),)
    )
    return [
        f"{'Read' if row['is_read'] else 'New'} · {row['item_id']} · {row['summary']} · {row['url']}"
        for row in rows
    ] or ["Your inbox has no matching updates. Run artist refresh to check your follows."]


def _mark_read(database, args):
    if len(args) != 1 or not (args[0].casefold() == "all" or re.fullmatch(r"[a-f0-9]{16}", args[0])):
        raise ValueError("Usage: artist read ITEM_ID|all")
    with database.transaction() as connection:
        changed = connection.execute(
            "UPDATE artist_inbox SET is_read=1 WHERE is_read=0 AND (item_id=? OR ?='all')",
            (args[0], args[0].casefold()),
        ).rowcount
    noun = "update" if changed == 1 else "updates"
    return [f"Marked {changed} {noun} as read."]


def _id(value):
    try:
        parsed = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return ""
    return parsed if parsed == value.lower() else ""


def _follow_id(value):
    identifier = _id(value) or apple_id(value)
    if identifier:
        return identifier
    try:
        link = urlsplit(value)
    except ValueError:
        return ""
    if link.scheme != "https":
        return ""
    if link.netloc.lower() == "musicbrainz.org":
        match = re.fullmatch(r"/artist/([^/]+)/?", link.path)
        return _id(match[1]) if match else ""
    if link.netloc.lower() == "music.apple.com":
        match = re.fullmatch(r"/[a-zA-Z]{2}/artist/(?:[^/]+/)?([1-9][0-9]{0,18})/?", link.path)
        return "apple:" + match[1] if match else ""
    return ""


def _text(value, maximum=200):
    if not isinstance(value, str):
        return ""
    return " ".join("".join(char if char.isprintable() else " " for char in value).split())[:maximum]


def _phrase(value):
    if not value or len(value) > 160:
        raise ValueError("Enter a search term between 1 and 160 characters")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def following(database):
    rows = database.fetchall(
        "SELECT key, value_json FROM app_state WHERE key GLOB ? ORDER BY key", (PREFIX + "*",)
    )
    return {row["key"][len(PREFIX):]: json.loads(row["value_json"]) for row in rows}


def _artists(records):
    seen = set()
    for row in records:
        identifier, name = _id(row.get("id")), _text(row.get("name"), 120)
        if identifier and name and identifier not in seen:
            seen.add(identifier)
            detail = " · ".join(filter(None, (_text(row.get("disambiguation")), _text(row.get("country")))))
            yield identifier, name, detail


def _apple_artists(records):
    seen = set()
    for row in records:
        identifier = apple_id(f"apple:{row.get('artistId')}")
        name = _text(row.get("artistName"), 120)
        if row.get("wrapperType") != "artist" or row.get("artistType", "Artist") != "Artist":
            continue
        if identifier and name and identifier not in seen:
            seen.add(identifier)
            yield identifier, name, f"Apple Music ({apple_country()})"


def _cached_artists(database, term, query_key, include_previous):
    saved = {key: (key, name, "Saved follow") for key, name in following(database).items()
             if term.casefold() in name.casefold()}
    if include_previous:
        for identifier, name, detail in database.get_state(query_key, []):
            label = f"Previous search · {detail}" if detail else "Previous search · MusicBrainz"
            saved.setdefault(identifier, (identifier, name, label))
    return list(saved.values())


def _remember_artists(database, key, artists):
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO app_state(key,value_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, json.dumps(artists[:25]), time.time()),
        )
        connection.execute(
            "DELETE FROM app_state WHERE key IN (SELECT key FROM app_state WHERE key GLOB 'artist.search.*' "
            "ORDER BY updated_at DESC, key LIMIT -1 OFFSET 64)"
        )


def _name_search(client, database, term):
    query = "artist:" + _phrase(term)
    notes = []
    try:
        artists = list(_artists(client.artist_catalogue_search("artist", query)))
    except ValueError as error:
        notes.append(str(error))
        artists = []
    if not artists:
        try:
            artists = list(_apple_artists(apple_rows("search", term=term, media="music", entity="musicArtist", limit=25)))
        except ValueError as error:
            notes.append(str(error))
    live = bool(artists)
    if database is not None:
        cache_key = "artist.search." + hashlib.sha256(term.casefold().encode()).hexdigest()
        if live:
            _remember_artists(database, cache_key, artists)
        else:
            artists = _cached_artists(database, term, cache_key, include_previous=bool(notes))
    results = [" · ".join(filter(None, (name, detail, key))) for key, name, detail in artists[:25]]
    if not results:
        if len(notes) < 2:
            results.append("No matches from the available catalogues. Try another spelling.")
        else:
            results.append("Both online catalogues are unavailable. Try artist list for saved follows.")
    if not live:
        results.append("Search Bandcamp · https://bandcamp.com/search?" + urlencode({"q": term, "item_type": "b"}))
    return results + notes


def _apple_music(entity, tracked, today, messages):
    entity_name = "song" if entity == "recording" else "album"
    identifiers = [key.split(":")[1] for key in tracked if apple_id(key)]
    updates = {}
    for offset in range(0, len(identifiers), 8):
        batch = identifiers[offset:offset + 8]
        try:
            candidates = apple_rows("lookup", id=",".join(batch), entity=entity_name, sort="recent", limit=100)
        except ValueError as error:
            messages.append(f"Apple Music {entity_name} lookup for artist batch {offset // 8 + 1}: {error}")
            continue
        for row in candidates:
            artist_number = str(row.get("artistId"))
            if artist_number not in batch:
                continue
            if entity_name == "song" and row.get("kind") == "song":
                title, number = _text(row.get("trackName")), str(row.get("trackId"))
            elif entity_name == "album" and row.get("wrapperType") == "collection":
                title, number = _text(row.get("collectionName")), str(row.get("collectionId"))
            else:
                continue
            try:
                released = date.fromisoformat(_text(row.get("releaseDate"), 10))
            except ValueError:
                continue
            if title and re.fullmatch(r"[1-9][0-9]{0,18}", number) and abs((released - today).days) <= 90:
                url = f"https://music.apple.com/{apple_country().lower()}/{entity_name}/{number}"
                updates[url] = (released.isoformat(), title, tracked["apple:" + artist_number], url)
    return updates.values()


def _credits(row):
    credits = row.get("artist-credit")
    if isinstance(credits, list):
        for credit in credits:
            if isinstance(credit, dict) and isinstance(credit.get("artist"), dict):
                yield from _artists([credit["artist"]])


def _date_window(today):
    return f"firstreleasedate:[{today - timedelta(days=90)} TO {today + timedelta(days=90)}]"


def _spotlight(client, genre, today):
    query = _date_window(today)
    if genre:
        query += " AND tag:" + _phrase(genre)
    artists = {}
    for row in client.artist_catalogue_search("release-group", query):
        title = _text(row.get("title"))
        if title:
            for identifier, name, _ in _credits(row):
                artists.setdefault(identifier, f"{name} · {title} · {identifier}")
    return list(artists.values())[:25]


def _new_music(client, entity, tracked, today, messages):
    rows = {}
    identifiers = [key for key in tracked if _id(key)]
    for offset in range(0, len(identifiers), 12):
        group = " OR ".join("arid:" + item for item in identifiers[offset:offset + 12])
        try:
            candidates = client.artist_catalogue_search(entity, f"({group}) AND {_date_window(today)}")
        except ValueError as error:
            messages.append(f"MusicBrainz {entity} search unavailable for artist batch {offset // 12 + 1}. {error}")
            continue
        for row in candidates:
            identifier, title = _id(row.get("id")), _text(row.get("title"))
            names = [name for key, name, _ in _credits(row) if key in tracked]
            released = _text(row.get("first-release-date"), 10)
            if identifier and title and names and released:
                rows[identifier] = (released, title, ", ".join(names), f"https://musicbrainz.org/{entity}/{identifier}")
    kind = "Track" if entity == "recording" else "Release"
    records = [*rows.values(), *_apple_music(entity, tracked, today, messages)]
    return [ArtistUpdate(" · ".join((kind, *row[:3])), row[3]) for row in sorted(records, reverse=True)]


def _mentions(payload, feed, names, publisher):
    import feedparser

    indexed_names = [re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I) for name in names]
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, re.I):
        raise ValueError("Unsupported RSS document")
    document = feedparser.parse(payload)
    if not document.version:
        raise ValueError("Invalid news feed")
    articles = {}
    for item in document.entries[:100]:
        title = _text(item.get("title"))
        if not title or not any(pattern.search(title) for pattern in indexed_names):
            continue
        try:
            raw_link = item.get("link")
            if not isinstance(raw_link, str) or len(raw_link) > 2048 or any(
                not char.isprintable() or char.isspace() for char in raw_link
            ):
                continue
            url = urlsplit(raw_link)
            target = url.hostname or ""
            if (url.scheme != "https" or target.removeprefix("www.") !=
                    urlsplit(feed).hostname.removeprefix("www.") or url.username is not None or
                    url.password is not None or url.port not in {None, 443}):
                continue
        except ValueError:
            continue
        link = urlunsplit(("https", target, url.path, "", ""))
        articles[link] = ArtistUpdate(f"{publisher} · {title}", link)
    return articles.values()


def _news(tracked, messages):
    from .artwork import ArtworkError, SafeArtworkFetcher

    updates = []
    fetcher = SafeArtworkFetcher(total_timeout=12, accept="application/rss+xml,application/atom+xml,application/xml",
                                 user_agent="Mariana-ArtistWatch/1 (+https://github.com/Vivojay/mariana-music-player)")
    try:
        for publisher, url in NEWS_FEEDS:
            try:
                result = fetcher.fetch(url, max_bytes=2_000_000, cancel=threading.Event())
                hits = _mentions(result.data, url, tracked.values(), publisher)
                updates.extend(hits)
                if not hits:
                    messages.append(f"{publisher} · No artist-name matches in the latest headlines.")
            except (ArtworkError, ValueError):
                messages.append(f"{publisher} · Feed unavailable.")
    finally:
        fetcher.close()
    return updates


def run_artist_command(arguments, database, client, *, today=None):
    action = arguments[0].casefold() if arguments else "help"
    args = arguments[1:]
    today = today or date.today()
    term = " ".join(args).strip()
    if action in {"help", "?"} and not args:
        return HELP
    if action == "search":
        return _name_search(client, database, term)
    if action == "emerging":
        query = f"type:group AND begin:[{today.year - 2}-01-01 TO {today}]"
        if term:
            query += " AND tag:" + _phrase(term)
        lines = [" · ".join(filter(None, (name, detail, identifier)))
                 for identifier, name, detail in _artists(client.artist_catalogue_search("artist", query))]
        return lines[:25] or ["No indexed artists matched."]
    if action == "discover":
        return _spotlight(client, term, today) or ["No credited artists matched this release window."]
    if action in {"follow", "unfollow"}:
        if len(args) != 1 or not (identifier := _follow_id(args[0])):
            raise ValueError(f"Usage: artist {action} ID (use a MusicBrainz UUID, apple:NUMBER or official artist URL)")
        if action == "unfollow":
            database.delete_state(PREFIX + identifier)
            return [f"Removed artist follow · {identifier}"]
        if apple_id(identifier):
            candidates = _apple_artists(apple_rows("lookup", id=identifier.split(":")[1]))
        else:
            candidates = _artists(client.artist_catalogue_search("artist", "arid:" + identifier))
        for key, name, _ in candidates:
            if key == identifier:
                database.set_state(PREFIX + key, name)
                return [f"Following {name} · {key}"]
        raise ValueError("The catalogue could not confirm that artist ID")
    if action == "inbox":
        return _inbox(database, args)
    if action == "read":
        return _mark_read(database, args)
    tracked = following(database)
    if action == "list" and not args:
        return [f"{name} · {key}" for key, name in sorted(tracked.items(), key=lambda item: item[1].casefold())] or ["No followed artists."]
    if action not in {"releases", "tracks", "news", "refresh"}:
        raise ValueError("Run artist help for the available commands")
    if args:
        identifier = _follow_id(args[0])
        if len(args) != 1 or identifier not in tracked:
            raise ValueError("Choose a followed MBID or apple:NUMBER from artist list")
        tracked = {identifier: tracked[identifier]}
    if not tracked:
        return ["Follow an artist from artist discover, artist emerging, or artist search first."]
    messages = []
    updates = []
    if action in {"news", "refresh"}:
        updates.extend(_news(tracked, messages))
    if action in {"releases", "refresh"}:
        updates.extend(_new_music(client, "release-group", tracked, today, messages))
    if action in {"tracks", "refresh"}:
        updates.extend(_new_music(client, "recording", tracked, today, messages))
    if action == "refresh":
        added = _save_updates(database, updates)
        return [f"{added} new items saved. Run artist inbox to read them.", *messages]
    return [item.display() for item in updates] + messages or [
        "No matching dated records returned in the 90-day recent/upcoming window."
    ]
