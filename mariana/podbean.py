"""Browse and follow public Podbean shows and select individual episodes."""
from __future__ import annotations

import json
import re
import threading
from urllib.parse import urlencode

from .artwork import ArtworkError, SafeArtworkFetcher
from .podcast_feeds import MAX_PODCAST_BYTES, episode_media, parse_podcast_feed, plain_text

_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_RESERVED = {"www", "feed", "api", "help", "developers", "admin"}
_PAGE = 10
_KEY = "podbean.followed.v1"
HELP = ("podbean search WORDS | open SHOW | episodes [PAGE] | play NUMBER | queue NUMBER | "
        "follow [SHOW] | list | unfollow SHOW. Use a show name from its Podbean URL, its "
        "homepage, or its public RSS feed.")


def show_slug(value: str) -> str:
    value = value.strip().lower()
    for pattern in (rf"({_LABEL})", rf"(?:https?://)?({_LABEL})\.podbean\.com/?",
                    rf"https?://feed\.podbean\.com/({_LABEL})/feed\.xml"):
        match = re.fullmatch(pattern, value, flags=re.ASCII)
        if match and match[1] not in _RESERVED:
            return match[1]
    raise ValueError("Enter a Podbean show slug, show homepage, or public feed URL.")


def feed_url(slug):
    return f"https://feed.podbean.com/{slug}/feed.xml"


def fetch_public(url):
    fetcher = SafeArtworkFetcher(accept="application/rss+xml,application/xml,application/json,*/*;q=0.1",
                                 user_agent="Mariana-Podcasts/1")
    try:
        return fetcher.fetch(url, max_bytes=MAX_PODCAST_BYTES, cancel=threading.Event()).data
    except ArtworkError as error:
        raise ValueError("The public podcast provider could not be reached. Try again or open another show.") from error
    finally:
        fetcher.close()


def search_shows(term, fetch):
    if not 1 <= len(term) <= 180:
        raise ValueError("Enter 1 to 180 characters after podbean search.")
    url = "https://itunes.apple.com/search?" + urlencode(
        {"media": "podcast", "entity": "podcast", "limit": 50, "term": term})
    data = json.loads(fetch(url))
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("The podcast directory returned an unreadable response.")
    shows = {}
    for item in data["results"][:50]:
        if not isinstance(item, dict) or not isinstance(item.get("feedUrl"), str):
            continue
        try:
            slug = show_slug(item["feedUrl"]) if "://" in item["feedUrl"] else None
        except ValueError:
            continue
        if slug:
            shows.setdefault(slug, plain_text(item.get("collectionName"), 300) or slug)
    return shows


def _number(value, limit):
    if not re.fullmatch(r"[1-9][0-9]{0,5}", value) or int(value) > limit:
        raise ValueError(f"Choose a number between 1 and {limit}.")
    return int(value)


class PodbeanShelf:
    def __init__(self, database, fetch=fetch_public):
        self.database = database
        self.fetch = fetch
        self.slug = ""
        self.rows = []
        self.search_results = {}

    def _page(self, value):
        if not self.rows:
            raise ValueError("Open a Podbean show first.")
        pages = (len(self.rows) + _PAGE - 1) // _PAGE
        page = _number(value, pages)
        start = (page - 1) * _PAGE
        title = self.rows[0].get("programme") or self.slug
        return "\n".join([f"{title} · page {page}/{pages} · {len(self.rows)} episodes",
                          *(f"{i}. {row['title']}" for i, row in enumerate(self.rows[start:start + _PAGE], start + 1))])

    def command(self, args, use_episode):
        op = args[0].lower() if args else "help"
        values = args[1:]
        if op == "search":
            shows = search_shows(" ".join(values), self.fetch)
            self.search_results = shows
            return "\n".join(f"{slug} · {title}" for slug, title in shows.items()) or (
                "No Podbean feeds in these Apple Podcasts directory results. Use podbean open SHOW.")
        if op == "open" and len(values) == 1:
            self.slug, self.rows = "", []
            slug = show_slug(values[0])
            url = feed_url(slug)
            rows = parse_podcast_feed(self.fetch(url), url)
            self.slug, self.rows = slug, rows
            return self._page("1")
        if op == "episodes" and len(values) <= 1:
            return self._page(values[0] if values else "1")
        if op in {"play", "queue"} and len(values) == 1:
            if not self.rows:
                raise ValueError("Open a Podbean show first.")
            row = self.rows[_number(values[0], len(self.rows)) - 1]
            media = episode_media(row)
            if not media:
                raise ValueError("This episode has no playable enclosure.")
            use_episode(media, op == "play")
            return f"{'Selected' if op == 'play' else 'Queued'} · {row['title']}"
        shelf = self.database.get_state(_KEY, {})
        if op == "list" and not values:
            return "\n".join(f"{slug} · {title}" for slug, title in shelf.items()) or "No followed Podbean shows."
        if op == "follow" and len(values) <= 1:
            if not values and not self.slug:
                raise ValueError("Open a show first or provide its slug.")
            slug = show_slug(values[0]) if values else self.slug
            if slug not in shelf and len(shelf) >= 250:
                raise ValueError("Your shelf holds 250 shows. Unfollow one to add another.")
            shelf[slug] = (self.rows[0].get("programme") if self.slug == slug else shelf.get(slug)) or slug
            self.database.set_state(_KEY, shelf)
            return f"Following {slug}."
        if op == "unfollow" and len(values) == 1:
            slug = show_slug(values[0])
            if slug not in shelf:
                return f"{slug} is already absent from your shelf."
            del shelf[slug]
            self.database.set_state(_KEY, shelf)
            return f"Removed {slug}."
        if op in {"help", "?"} and not values:
            return HELP
        raise ValueError(HELP)
