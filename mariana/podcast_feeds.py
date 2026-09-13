"""Shared public podcast parsing; article links are never playable episodes."""

from __future__ import annotations

import ipaddress
import math
import re
from calendar import timegm
from html.parser import HTMLParser
from urllib.parse import urlsplit

import feedparser

from .models import MediaCapabilities, MediaChapter, MediaRef, MediaSource, podcast_episode_identity

MAX_PODCAST_BYTES = 8 * 1024 * 1024
MAX_PODCAST_ENTRIES = 1500


class PodcastFeedError(ValueError):
    """A feed could not safely provide podcast episodes."""


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: object, maximum: int = 8000) -> str:
    parser = _Text()
    parser.feed(str(value or "")[: maximum * 3])
    text = " ".join(" ".join(parser.parts).split())
    # Feed text is untrusted terminal input as well as renderer input.
    return "".join(c for c in text if c.isprintable())[:maximum]


def public_reference(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 4096 or any(c.isspace() for c in value):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.port not in {None, 80, 443}):
            return None
        host = parts.hostname.casefold()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        return value
    except ValueError:
        return None


def _duration(value: object) -> float | None:
    try:
        components = str(value).split(":")
        if len(components) > 3:
            return None
        seconds = 0.0
        for component in components:
            seconds = seconds * 60 + float(component)
        return seconds if math.isfinite(seconds) and 0 < seconds <= 604800 else None
    except (TypeError, ValueError):
        return None


def _artwork(value: object) -> str | None:
    return public_reference(value.get("href")) if isinstance(value, dict) else None


def parse_podcast_feed(payload: bytes, feed_uri: str) -> list[dict]:
    """Return bounded legacy-compatible records in publisher order.

    Keep GUID identity separate from enclosure transport. Deduplicate only
    within this canonical feed, never by title or across unrelated publishers.
    Inline chapters are retained. Linked chapter JSON is not fetched implicitly.
    """
    if len(payload) > MAX_PODCAST_BYTES:
        raise PodcastFeedError("Podcast feed exceeds the 8 MiB limit")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", payload, re.I):
        raise PodcastFeedError("Podcast feed contains unsupported XML declarations")
    parsed = feedparser.parse(payload)
    if parsed.bozo:
        raise PodcastFeedError("Podcast feed is malformed")
    records: list[dict] = []
    seen: set[str] = set()
    feed = parsed.feed
    for entry in parsed.entries[:MAX_PODCAST_ENTRIES]:
        enclosure = next((e for e in entry.get("enclosures", [])
                          if public_reference(e.get("href")) and (
                              str(e.get("type", "")).startswith(("audio/", "video/"))
                              or re.search(r"\.(?:mp3|m4a|mp4|ogg|opus|webm|wav)(?:[?#]|$)",
                                           str(e.get("href", "")), re.I))
                          and not re.search(r"\.m3u8?(?:[?#]|$)", str(e.get("href", "")), re.I)
                          and "mpegurl" not in str(e.get("type", "")).casefold()), None)
        if enclosure is None:
            continue
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        try:
            timestamp = timegm(published) if published else 0
        except (ValueError, OverflowError, TypeError):
            timestamp = 0
        title = plain_text(entry.get("title"), 500) or "Untitled podcast episode"
        episode_url = public_reference(entry.get("link"))
        identity = podcast_episode_identity(
            feed_uri, guid=entry.get("id") or entry.get("guid"), episode_url=episode_url,
            enclosure_url=enclosure["href"], title=title,
            published_timestamp=timestamp, published=entry.get("published"),
        )
        key = identity[0] if identity else enclosure["href"]
        if key in seen:
            continue
        seen.add(key)
        raw_explicit = entry.get("itunes_explicit", feed.get("itunes_explicit"))
        explicit = None if raw_explicit is None else str(raw_explicit).casefold() in {"true", "yes", "explicit", "1"}
        chapters = []
        raw_chapters = entry.get("psc_chapters", {})
        if isinstance(raw_chapters, dict):
            for chapter in raw_chapters.get("chapters", [])[:200]:
                start = chapter.get("start")
                seconds = 0.0 if str(start) in {"0", "0.0", "00:00:00", "00:00:00.000"} else _duration(start)
                if seconds is not None:
                    chapters.append({"title": plain_text(chapter.get("title"), 200), "start_time": seconds})
        records.append({
            "title": title, "enclosure_url": enclosure["href"], "episode_url": episode_url,
            "episode_guid": entry.get("id") or entry.get("guid"),
            "stable_id": identity[0] if identity else None,
            "identity_kind": identity[1] if identity else None,
            "published_timestamp": timestamp,
            "published_date": plain_text(entry.get("published") or entry.get("updated"), 100),
            "itunes_explicit": explicit,
            "itunes_subtitle": plain_text(entry.get("summary") or entry.get("itunes_subtitle")),
            "itune_image": _artwork(entry.get("image")) or _artwork(feed.get("image")),
            "creator": plain_text(entry.get("author") or feed.get("author"), 240),
            "programme": plain_text(feed.get("title"), 240),
            "language": plain_text(entry.get("language") or feed.get("language"), 80),
            "duration": _duration(entry.get("itunes_duration")),
            "chapters": chapters,
        })
    if not records:
        raise PodcastFeedError("This feed has no supported playable media enclosures")
    return records


def episode_media(episode: dict) -> MediaRef | None:
    """Use one metadata/identity mapping for legacy RSS and discovery choices."""
    url = public_reference(episode.get("url") or episode.get("enclosure_url"))
    if url is None:
        return None
    metadata = {key: value for key, value in {
        "description": episode.get("caption", episode.get("itunes_subtitle")),
        "published": episode.get("pub_date", episode.get("published_date")),
        "explicit": episode.get("is_explicit", episode.get("itunes_explicit")),
        "artwork": episode.get("artwork", episode.get("itune_image")),
        "programme": episode.get("programme"), "language": episode.get("language"),
        "podcast_identity_kind": episode.get("identity_kind"),
    }.items() if value not in (None, "")}
    duration = _duration(episode.get("duration"))
    starts = episode.get("chapters") or []
    chapters = []
    for index, chapter in enumerate(starts):
        end = starts[index + 1]["start_time"] if index + 1 < len(starts) else duration
        if end is not None and 0 <= chapter["start_time"] < end:
            chapters.append(MediaChapter(chapter["title"], chapter["start_time"], end))
    return MediaRef(
        MediaSource.PODCAST, url, title=episode.get("title"),
        artist=episode.get("creator") or None, album=episode.get("programme") or None,
        duration=duration, stable_id=episode.get("stable_id") or "",
        resolver_data=metadata, provenance="podcast-feed", chapters=chapters,
        capabilities=MediaCapabilities(metadata_available=True),
    )
