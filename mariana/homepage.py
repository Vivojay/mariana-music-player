"""Local-first homepage projection and bounded editorial feed refresh.

The service deliberately has no knowledge of the CLI, Electron, or Mariana's
database implementation.  Callers provide local summary and app-state cache
callbacks; projections contain display-safe values only.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
from calendar import timegm
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, NotRequired, Protocol, TypedDict
from urllib.parse import urlsplit, urlunsplit

import feedparser
import requests

from mariana.artwork import (
    ArtworkCancelled,
    ArtworkError,
    ArtworkFetcher,
    SafeArtworkFetcher,
    validate_artwork_image,
)
from mariana.entertainment_catalog import BY_ID, ENTRIES

HOMEPAGE_SCHEMA_VERSION = 2
HOMEPAGE_CACHE_STATE_KEY = "homepage.discovery.v2"
BANDCAMP_DAILY_FEED_URL = "https://daily.bandcamp.com/feed"
LISTENBRAINZ_FRESH_RELEASES_URL = "https://api.listenbrainz.org/1/explore/fresh-releases/"

DEFAULT_CACHE_TTL_SECONDS = 6 * 60 * 60
DEFAULT_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
DEFAULT_MAX_ITEMS = 12
MAX_LOCAL_ITEMS = 12
MAX_CACHE_BYTES = 64_000
MAX_FEED_BYTES = 1_000_000
HTTP_TIMEOUT = (4, 12)
MAX_HOMEPAGE_IMAGE_BYTES = 2 * 1024 * 1024
MAX_HOMEPAGE_IMAGE_DIMENSION = 4096
MAX_HOMEPAGE_IMAGE_PIXELS = 16_000_000
MAX_HOMEPAGE_IMAGE_CACHE_BYTES = 64 * 1024 * 1024
MAX_HOMEPAGE_IMAGE_CACHE_ENTRIES = 96
HOMEPAGE_IMAGE_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60

_PRIVATE_REFERENCE = re.compile(
    r"(?:https?|ftp|file)://\S+|(?:^|\s)[A-Za-z]:[\\/]|(?:^|\s)\\\\|"
    r"(?:^|\s)~?/[A-Za-z0-9._~-]+(?:[/\\][^\s]*)?|"
    r"\b(?:authorization|cookie|password|token|secret)\b\s*[:=]",
    re.IGNORECASE,
)
_READ_MORE = re.compile(r"\s*Read full story on (?:the )?Bandcamp Daily\.?\s*$", re.IGNORECASE)
_IMAGE_CACHE_NAME = re.compile(r"^[0-9a-f]{64}\.(?:jpg|png|webp)$")
_BANDCAMP_IMAGE_HOST = re.compile(r"^f[0-9]+\.bcbits\.com$", re.IGNORECASE)
_MBID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_LOCAL_KINDS = {"current", "favorite", "playlist", "queue", "recent", "recommendation", "library"}

HomepageState = Literal["offline", "loading", "ready", "stale", "partial", "error"]


class HomepageItemProjection(TypedDict):
    catalogue: NotRequired[dict[str, str]]
    id: str
    title: str
    summary: str | None
    source: str
    published_at: str | None
    link: str | None
    image_key: str | None
    image_mime: str | None


class HomepageSectionProjection(TypedDict):
    key: str
    title: str
    items: list[HomepageItemProjection]


# These are deliberately destinations, not scraped headlines or chart rankings.
# Merely projecting them performs no network requests, even when discovery is on.
_OFFICIAL_DESTINATIONS = (
    ("culture-links", "grammys", "GRAMMY news", "Recording Academy",
     "Awards, music interviews, and official announcements.", "https://www.grammy.com/news"),
    ("culture-links", "sxsw", "SXSW", "SXSW",
     "Music, film, and festival programming from the organiser.", "https://sxsw.com/"),
    ("culture-links", "pitchfork", "Pitchfork", "Pitchfork",
     "Music criticism, reviews, and artist interviews.", "https://pitchfork.com/"),
    ("culture-links", "playbill", "Playbill", "Playbill",
     "Theatre, Broadway, musicals, and stage news.", "https://playbill.com/"),
    ("culture-links", "sight-sound", "Sight and Sound", "BFI",
     "Film criticism, cinema history, and international perspectives.",
     "https://www.bfi.org.uk/sight-and-sound"),
    ("culture-links", "indian-express", "Indian Express entertainment", "Indian Express",
     "Indian cinema, regional films, music, and entertainment coverage.",
     "https://indianexpress.com/section/entertainment/"),
    ("culture-links", "comic-con", "Comic-Con", "Comic-Con International",
     "Official convention, comics, and arts programming.", "https://www.comic-con.org/"),
    ("chart-links", "billboard", "Billboard charts", "Billboard",
     "Open the official charts. Rankings and chart dates are not imported into Mariana.",
     "https://www.billboard.com/charts/"),
    ("chart-links", "official-charts", "UK Official Charts", "Official Charts Company",
     "UK singles, albums, and genre charts on the original site.",
     "https://www.officialcharts.com/charts/"),
    ("chart-links", "ifpi", "IFPI Global Charts", "IFPI",
     "Annual global rankings; not a weekly or real-time chart.",
     "https://www.ifpi.org/our-industry/global-charts/"),
    ("performance-links", "boiler-room", "Boiler Room", "Boiler Room",
     "DJ sets and club communities from around the world. Opens the official site.",
     "https://boilerroom.tv/"),
    ("performance-links", "book-club-radio", "Book Club Radio", "Book Club Radio",
     "Community-centred dance-floor sets from New York. Opens the official site.",
     "https://www.bookclub.radio/"),
    ("performance-links", "triple-j-like-a-version", "Like A Version", "triple j / ABC",
     "Studio performances: an original song and a cover. Opens the official episode catalogue.",
     "https://www.abc.net.au/triplej/programs/like-a-version"),
    ("performance-links", "kexp", "Live on KEXP", "KEXP",
     "Studio performances and global music discovery. Opens the official podcast page.",
     "https://www.kexp.org/podcasts/live-on-kexp/"),
    ("performance-links", "nts", "NTS Radio", "NTS",
     "Human-curated radio and international specialist shows. Opens the official site.",
     "https://www.nts.live/"),
    ("performance-links", "colors", "COLORS", "COLORS",
     "Emerging artists and intimate performances. Opens the official site.",
     "https://colorsxstudios.com/"),
    ("performance-links", "cercle", "Cercle", "Cercle",
     "Electronic performances connected to distinctive locations. Opens the official site.",
     "https://www.cercle.io/"),
    ("performance-links", "elevator-music-live", "Elevator Music Live", "Elevator Music Live",
     "DJ performances and community sessions. Opens the confirmed official link hub.",
     "https://linktr.ee/elevatormusiclive"),
    ("show-links", "vanderpump-rules", "Vanderpump Rules", "Bravo",
     "Official episodes, clips, and After Show catalogue. Full episodes may require an authorised provider.",
     "https://www.bravotv.com/vanderpump-rules"),
    ("show-links", "bravo", "BravoTV", "Bravo",
     "Official show, video, news, and schedule destination. Playback availability depends on the provider.",
     "https://www.bravotv.com/"),
    ("show-links", "hayu", "Hayu", "NBCUniversal",
     "Subscription reality-TV catalogue with regional availability; opens the official service.",
     "https://www.hayu.com/"),
)


def official_destination_sections() -> list[HomepageSectionProjection]:
    """Return fresh display-only records, without remote images or playback claims."""

    return [
        {
            "key": key,
            "title": title,
            "items": [
                {
                    "id": f"destination:{identifier}",
                    "title": name,
                    "source": source,
                    "summary": summary,
                    "published_at": None,
                    "link": link,
                    "image_key": None,
                    "image_mime": None,
                }
                for group, identifier, name, source, summary, link in _OFFICIAL_DESTINATIONS
                if group == key and link not in {entry.homepage for entry in ENTRIES}
            ],
        }
        for key, title in (
            ("culture-links", "Explore culture · official links"),
            ("chart-links", "Charts · official links"),
            ("performance-links", "Performance channels · official links"),
            ("show-links", "Shows · official links"),
        )
    ]


def catalogue_sections() -> list[HomepageSectionProjection]:
    """Bundled, offline source cards; selecting one uses the existing discovery worker."""
    return [{
        "key": f"catalogue-{index}", "title": category,
        "items": [{
            "id": f"catalogue:{entry.id}", "title": entry.title, "source": entry.publisher,
            "summary": f"{entry.summary} Language: {entry.language}; region: {entry.region}. Checked {entry.validated_at}.",
            "published_at": None, "link": entry.homepage, "image_key": None, "image_mime": None,
            "catalogue": {"language": entry.language, "region": entry.region, "category": entry.category,
                          "kind": entry.kind, "health": entry.health, "validated_at": entry.validated_at or "Not checked"},
        } for entry in ENTRIES if entry.category == category],
    } for index, category in enumerate(dict.fromkeys(entry.category for entry in ENTRIES))]


class HomepageProjection(TypedDict):
    schema_version: int
    show_on_startup: bool
    online_enabled: bool
    state: HomepageState
    refreshed_at: float | None
    safe_message: str | None
    sections: list[HomepageSectionProjection]


class HomepageProviderError(RuntimeError):
    """Raised when a configured homepage provider returns unusable content."""


class _RefreshCancelled(RuntimeError):
    pass


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.image_sources: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "img":
            return
        for key, value in attrs:
            if key.casefold() == "src" and value:
                self.image_sources.append(value)
                return


def _plain_text(value: object, *, maximum: int, reject_private: bool = True) -> str | None:
    if not isinstance(value, str):
        return None
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
        value = " ".join(parser.parts)
    except (ValueError, AssertionError):
        value = re.sub(r"<[^>]*>", " ", value)
    cleaned = html.unescape(value)
    cleaned = "".join(
        character for character in cleaned if not unicodedata.category(character).startswith("C")
    )
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned or (reject_private and _PRIVATE_REFERENCE.search(cleaned)):
        return None
    if len(cleaned) > maximum:
        cleaned = cleaned[: maximum - 1].rstrip() + "…"
    return cleaned or None


def _official_bandcamp_link(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2_048:
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "daily.bandcamp.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/")
    ):
        return None
    # Provider query strings and fragments are unnecessary for the canonical
    # story link and can contain tracking or transient values.
    return urlunsplit(("https", "daily.bandcamp.com", parsed.path, "", ""))


def _official_bandcamp_image(value: object) -> str | None:
    """Return a public Bandcamp CDN image reference supplied by the official feed."""

    if not isinstance(value, str) or len(value) > 2_048:
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or _BANDCAMP_IMAGE_HOST.fullmatch(hostname) is None
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/img/")
    ):
        return None
    return urlunsplit(("https", hostname.casefold(), parsed.path, "", ""))


def _official_musicbrainz_link(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2_048:
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    match = re.fullmatch(r"/release/([0-9a-f-]{36})", parsed.path, re.IGNORECASE)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "musicbrainz.org"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or match is None
        or _MBID.fullmatch(match.group(1)) is None
    ):
        return None
    return f"https://musicbrainz.org/release/{match.group(1).casefold()}"


def _official_cover_art_image(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 2_048:
        return None
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    match = re.fullmatch(r"/release/([0-9a-f-]{36})/front-500", parsed.path, re.IGNORECASE)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "coverartarchive.org"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or match is None
        or _MBID.fullmatch(match.group(1)) is None
    ):
        return None
    return f"https://coverartarchive.org/release/{match.group(1).casefold()}/front-500"


def _bandcamp_entry_image(entry: Mapping[str, Any]) -> str | None:
    """Select only an image reference embedded in Bandcamp's own feed metadata."""

    for markup in (entry.get("summary"), entry.get("description")):
        if not isinstance(markup, str):
            continue
        parser = _TextExtractor()
        with suppress(ValueError, AssertionError):
            parser.feed(markup)
            parser.close()
        for candidate in parser.image_sources:
            if image := _official_bandcamp_image(candidate):
                return image
    for media_field in ("media_thumbnail", "media_content"):
        values = entry.get(media_field)
        if not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if isinstance(value, Mapping) and (image := _official_bandcamp_image(value.get("url"))):
                return image
    return None


def _bounded_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return min(10_000_000, max(0, number))


@dataclass(frozen=True, slots=True)
class HomepageConfiguration:
    show_on_startup: bool = True
    online_enabled: bool = False

    @classmethod
    def from_mapping(cls, value: object) -> HomepageConfiguration:
        section = value if isinstance(value, Mapping) else {}
        startup = section.get("show on startup", True)
        online = section.get("online content", False)
        return cls(
            show_on_startup=startup if type(startup) is bool else True,
            online_enabled=online if type(online) is bool else False,
        )


@dataclass(frozen=True, slots=True)
class HomepageLocalItem:
    kind: str
    title: str
    subtitle: str | None = None

    def to_projection_item(self) -> HomepageItemProjection:
        identity = f"{self.kind}\0{self.title}\0{self.subtitle or ''}"
        return {
            "id": f"local:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:20]}",
            "title": self.title,
            "summary": self.subtitle,
            "source": f"Mariana {self.kind}",
            "published_at": None,
            "link": None,
            "image_key": None,
            "image_mime": None,
        }


@dataclass(frozen=True, slots=True)
class HomepageLocalContent:
    library_count: int = 0
    favorite_count: int = 0
    playlist_count: int = 0
    queue_count: int = 0
    items: tuple[HomepageLocalItem, ...] = ()

    def to_section(self) -> HomepageSectionProjection:
        summaries = (
            ("library", "Library", self.library_count, "media items"),
            ("favorites", "Rated media", self.favorite_count, "one-to-five-star ratings"),
            ("playlists", "Playlists", self.playlist_count, "playlists"),
            ("queue", "Queue", self.queue_count, "queued items"),
        )
        items: list[HomepageItemProjection] = []
        for key, title, count, label in summaries:
            if count:
                items.append(
                    {
                        "id": f"local-summary:{key}",
                        "title": title,
                        "summary": f"{count} {label}",
                        "source": "Mariana",
                        "published_at": None,
                        "link": None,
                        "image_key": None,
                        "image_mime": None,
                    }
                )
        used_ids = {item["id"] for item in items}
        for local_item in self.items:
            projected = local_item.to_projection_item()
            base_id = projected["id"]
            suffix = 2
            while projected["id"] in used_ids:
                projected["id"] = f"{base_id}:{suffix}"
                suffix += 1
            used_ids.add(projected["id"])
            items.append(projected)
        return {"key": "local", "title": "Your Mariana", "items": items[:MAX_LOCAL_ITEMS]}


@dataclass(frozen=True, slots=True)
class HomepageArticle:
    article_id: str
    title: str
    excerpt: str
    source: str
    link: str
    published_at: str | None = None
    attribution: str | None = None
    category: str | None = None
    section: Literal["culture", "releases"] = "culture"
    image_url: str | None = None
    image_key: str | None = None
    image_mime: str | None = None

    def to_cache_dict(self) -> dict[str, str | None]:
        return {
            "article_id": self.article_id,
            "title": self.title,
            "excerpt": self.excerpt,
            "source": self.source,
            "link": self.link,
            "published_at": self.published_at,
            "attribution": self.attribution,
            "category": self.category,
            "section": self.section,
            "image_key": self.image_key,
            "image_mime": self.image_mime,
        }

    def to_projection_item(self) -> HomepageItemProjection:
        source = self.source
        if self.attribution:
            source = f"{source} · {self.attribution}"
        source = _plain_text(source, maximum=80) or self.source
        summary = self.excerpt
        release_link = _official_musicbrainz_link(self.link) if self.section == "releases" else None
        if release_link:
            release_id = release_link.rsplit("/", 1)[-1]
            # Display-only guidance uses the public edition identity, never a
            # provider-supplied title or executable action from a feed.
            summary += f" · Inspect this edition: album search reid:{release_id} --scope online"
        return {
            "id": f"{'release' if self.section == 'releases' else 'editorial'}:{self.article_id}",
            "title": self.title,
            "summary": summary,
            "source": source,
            "published_at": self.published_at,
            "link": self.link,
            "image_key": self.image_key,
            "image_mime": self.image_mime,
        }


class HomepageProvider(Protocol):
    source_name: str

    def fetch(self, cancelled: threading.Event) -> tuple[HomepageArticle, ...]: ...


@dataclass(frozen=True, slots=True)
class HomepageImageRef:
    cache_key: str
    mime_type: str


class HomepageImageCache:
    """Bounded cache for public provider images; projections receive keys only."""

    def __init__(
        self,
        cache_dir: str | os.PathLike[str],
        *,
        fetcher: ArtworkFetcher | None = None,
        max_encoded_bytes: int = MAX_HOMEPAGE_IMAGE_BYTES,
        max_cache_bytes: int = MAX_HOMEPAGE_IMAGE_CACHE_BYTES,
        max_cache_entries: int = MAX_HOMEPAGE_IMAGE_CACHE_ENTRIES,
        cache_ttl_seconds: float = HOMEPAGE_IMAGE_CACHE_TTL_SECONDS,
        now: Callable[[], float] = time.time,
    ) -> None:
        if max_encoded_bytes <= 0 or max_cache_bytes <= 0 or max_cache_entries <= 0:
            raise ValueError("Homepage image cache limits must be positive")
        if cache_ttl_seconds <= 0:
            raise ValueError("Homepage image cache lifetime must be positive")
        self.cache_dir = Path(cache_dir).resolve(strict=False)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._owns_fetcher = fetcher is None
        self._fetcher = fetcher or SafeArtworkFetcher(timeout=(3.0, 6.0), total_timeout=8.0)
        self._max_encoded_bytes = min(int(max_encoded_bytes), int(max_cache_bytes))
        self._max_cache_bytes = int(max_cache_bytes)
        self._max_cache_entries = int(max_cache_entries)
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._now = now
        self._lock = threading.RLock()
        self._closed = False
        self._cleanup(remove_temporary=True)

    @staticmethod
    def _identity_key(identity: str) -> str:
        return hashlib.sha256(f"mariana-homepage-image-v1\0{identity}".encode()).hexdigest()

    def resolve(
        self,
        identity: str,
        image_url: str,
        cancelled: threading.Event,
    ) -> HomepageImageRef:
        """Return a validated cache entry for one provider-bound public image."""

        if cancelled.is_set():
            raise ArtworkCancelled("Homepage image request was cancelled")
        identity = str(identity).strip()
        if not identity:
            raise ValueError("Homepage image requires a stable identity")
        cache_stem = self._identity_key(identity)
        with self._lock:
            if self._closed:
                raise ArtworkCancelled("Homepage image cache is closed")
            if cached := self._read_cached(cache_stem, cancelled):
                return cached
        fetched = self._fetcher.fetch(
            image_url,
            cancel=cancelled,
            max_bytes=self._max_encoded_bytes,
        )
        validated = validate_artwork_image(
            fetched.data,
            fetched.content_type,
            max_encoded_bytes=self._max_encoded_bytes,
            max_dimension=MAX_HOMEPAGE_IMAGE_DIMENSION,
            max_pixels=MAX_HOMEPAGE_IMAGE_PIXELS,
        )
        destination = self.cache_dir / f"{cache_stem}.{validated.extension}"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.cache_dir,
                prefix=f".{cache_stem}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(validated.data)
                temporary.flush()
                os.fsync(temporary.fileno())
            with self._lock:
                if self._closed or cancelled.is_set():
                    raise ArtworkCancelled("Homepage image request was cancelled")
                for extension in ("jpg", "png", "webp"):
                    other = self.cache_dir / f"{cache_stem}.{extension}"
                    if other != destination:
                        self._safe_unlink(other)
                os.replace(temporary_path, destination)
                temporary_path = None
                self._cleanup(preserve=destination)
            return HomepageImageRef(destination.name, validated.mime_type)
        finally:
            if temporary_path is not None:
                self._safe_unlink(temporary_path)

    def _read_cached(
        self,
        cache_stem: str,
        cancelled: threading.Event,
    ) -> HomepageImageRef | None:
        for mime_type, extension in (
            ("image/jpeg", "jpg"),
            ("image/png", "png"),
            ("image/webp", "webp"),
        ):
            path = self.cache_dir / f"{cache_stem}.{extension}"
            try:
                stat = path.stat()
                if path.is_symlink() or self._now() - stat.st_mtime > self._cache_ttl_seconds:
                    self._safe_unlink(path)
                    continue
                if stat.st_size < 1 or stat.st_size > self._max_encoded_bytes:
                    self._safe_unlink(path)
                    continue
                if cancelled.is_set():
                    raise ArtworkCancelled("Homepage image request was cancelled")
                data = path.read_bytes()
                validated = validate_artwork_image(
                    data,
                    mime_type,
                    max_encoded_bytes=self._max_encoded_bytes,
                    max_dimension=MAX_HOMEPAGE_IMAGE_DIMENSION,
                    max_pixels=MAX_HOMEPAGE_IMAGE_PIXELS,
                )
                if validated.extension != extension:
                    self._safe_unlink(path)
                    continue
                with suppress(OSError):
                    os.utime(path, None)
                return HomepageImageRef(path.name, validated.mime_type)
            except ArtworkCancelled:
                raise
            except (ArtworkError, OSError, ValueError):
                self._safe_unlink(path)
        return None

    def _cleanup(self, preserve: Path | None = None, *, remove_temporary: bool = False) -> None:
        with self._lock:
            entries: list[tuple[float, int, Path]] = []
            try:
                paths = tuple(self.cache_dir.iterdir())
            except OSError:
                return
            for path in paths:
                if path.name.endswith(".tmp"):
                    if remove_temporary:
                        self._safe_unlink(path)
                    continue
                if _IMAGE_CACHE_NAME.fullmatch(path.name) is None or path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if self._now() - stat.st_mtime > self._cache_ttl_seconds:
                    self._safe_unlink(path)
                    continue
                entries.append((stat.st_mtime, stat.st_size, path))
            entries.sort(key=lambda entry: (entry[0], entry[2].name))
            total = sum(entry[1] for entry in entries)
            while len(entries) > self._max_cache_entries or total > self._max_cache_bytes:
                index = next(
                    (i for i, entry in enumerate(entries) if preserve is None or entry[2] != preserve),
                    None,
                )
                if index is None:
                    break
                _modified, size, path = entries.pop(index)
                self._safe_unlink(path)
                total -= size

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._owns_fetcher:
            close = getattr(self._fetcher, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        with suppress(OSError):
            path.unlink(missing_ok=True)


class BandcampDailyProvider:
    """Fetch short, attributed entries from Bandcamp Daily's official RSS feed."""

    source_name = "Bandcamp Daily"

    def __init__(
        self,
        *,
        request_get: Callable[..., Any] | None = None,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_bytes: int = MAX_FEED_BYTES,
        total_timeout: float = 20.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session: requests.Session | None = None
        if request_get is None:
            # Editorial discovery is public, unauthenticated traffic.  Do not
            # let ambient proxy or .netrc credentials cross this boundary.
            self._session = requests.Session()
            self._session.trust_env = False
            self._request_get = self._session.get
        else:
            self._request_get = request_get
        self.max_items = min(DEFAULT_MAX_ITEMS, max(1, int(max_items)))
        self.max_bytes = min(MAX_FEED_BYTES, max(1, int(max_bytes)))
        self.total_timeout = max(0.1, float(total_timeout))
        self.monotonic = monotonic

    def close(self) -> None:
        """Release only the network session owned by this provider."""

        session, self._session = self._session, None
        if session is not None:
            session.close()

    @staticmethod
    def _published(entry: Mapping[str, Any]) -> tuple[float, str | None]:
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed:
            try:
                timestamp = float(timegm(parsed))
                return timestamp, datetime.fromtimestamp(timestamp, UTC).isoformat()
            except (OverflowError, TypeError, ValueError):
                pass
        raw = entry.get("published") or entry.get("updated")
        if isinstance(raw, str):
            try:
                value = parsedate_to_datetime(raw)
                if value.tzinfo is None:
                    value = value.replace(tzinfo=UTC)
                value = value.astimezone(UTC)
                return value.timestamp(), value.isoformat()
            except (TypeError, ValueError, OverflowError):
                pass
        return 0.0, None

    def _response_bytes(self, cancelled: threading.Event) -> bytes:
        if cancelled.is_set():
            raise _RefreshCancelled
        deadline = self.monotonic() + self.total_timeout
        response = self._request_get(
            BANDCAMP_DAILY_FEED_URL,
            headers={"User-Agent": "Mariana/0.7 (+https://github.com/Vivojay/mariana-music-player)"},
            timeout=HTTP_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
        try:
            if self.monotonic() > deadline:
                raise HomepageProviderError("Bandcamp Daily feed exceeded its time limit")
            if int(getattr(response, "status_code", 200)) in {301, 302, 303, 307, 308}:
                raise HomepageProviderError("Bandcamp Daily feed redirects are not followed")
            if _official_bandcamp_link(getattr(response, "url", BANDCAMP_DAILY_FEED_URL)) is None:
                raise HomepageProviderError("Bandcamp Daily redirected outside its official feed host")
            response.raise_for_status()
            content_length = (getattr(response, "headers", {}) or {}).get("Content-Length")
            try:
                declared_size = int(content_length) if content_length is not None else None
            except (TypeError, ValueError, OverflowError):
                declared_size = None
            if declared_size is not None and declared_size > self.max_bytes:
                raise HomepageProviderError("Bandcamp Daily feed exceeds the homepage size limit")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=16_384):
                if cancelled.is_set():
                    raise _RefreshCancelled
                if self.monotonic() > deadline:
                    raise HomepageProviderError("Bandcamp Daily feed exceeded its time limit")
                if not isinstance(chunk, bytes) or not chunk:
                    continue
                size += len(chunk)
                if size > self.max_bytes:
                    raise HomepageProviderError("Bandcamp Daily feed exceeds the homepage size limit")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def fetch(self, cancelled: threading.Event) -> tuple[HomepageArticle, ...]:
        payload = self._response_bytes(cancelled)
        if cancelled.is_set():
            raise _RefreshCancelled
        feed = feedparser.parse(payload)
        if getattr(feed, "bozo", False) and not getattr(feed, "entries", ()):
            raise HomepageProviderError("Bandcamp Daily returned an invalid feed")
        articles: list[tuple[float, HomepageArticle]] = []
        seen: set[str] = set()
        for raw_entry in getattr(feed, "entries", ()):
            if cancelled.is_set():
                raise _RefreshCancelled
            if not isinstance(raw_entry, Mapping):
                continue
            link = _official_bandcamp_link(raw_entry.get("link"))
            title = _plain_text(raw_entry.get("title"), maximum=180)
            description = _plain_text(
                raw_entry.get("summary") or raw_entry.get("description"),
                maximum=320,
                reject_private=False,
            )
            if description:
                description = _READ_MORE.sub("", description).strip()
                description = _plain_text(description, maximum=240)
            if not link or not title or not description or link in seen:
                continue
            seen.add(link)
            published_sort, published_at = self._published(raw_entry)
            attribution = _plain_text(
                raw_entry.get("author") or raw_entry.get("dc_creator"), maximum=120
            )
            categories = raw_entry.get("tags") or ()
            category = None
            if categories and isinstance(categories, (list, tuple)):
                first = categories[0]
                if isinstance(first, Mapping):
                    category = _plain_text(first.get("term"), maximum=64)
            category = category or _plain_text(raw_entry.get("category"), maximum=64)
            articles.append(
                (
                    published_sort,
                    HomepageArticle(
                        article_id=hashlib.sha256(link.encode("utf-8")).hexdigest()[:20],
                        title=title,
                        excerpt=description,
                        source=self.source_name,
                        link=link,
                        published_at=published_at,
                        attribution=attribution,
                        category=category,
                        image_url=_bandcamp_entry_image(raw_entry),
                    ),
                )
            )
        articles.sort(key=lambda item: (-item[0], item[1].title.casefold(), item[1].link))
        return tuple(article for _, article in articles[: self.max_items])


class ListenBrainzFreshReleasesProvider:
    """Fetch recent release metadata with stable MusicBrainz identities."""

    source_name = "ListenBrainz fresh releases"

    def __init__(
        self,
        *,
        request_get: Callable[..., Any] | None = None,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_bytes: int = MAX_FEED_BYTES,
        total_timeout: float = 20.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session: requests.Session | None = None
        if request_get is None:
            self._session = requests.Session()
            self._session.trust_env = False
            self._request_get = self._session.get
        else:
            self._request_get = request_get
        self.max_items = min(DEFAULT_MAX_ITEMS, max(1, int(max_items)))
        self.max_bytes = min(MAX_FEED_BYTES, max(1, int(max_bytes)))
        self.total_timeout = min(20.0, max(0.1, float(total_timeout)))
        self.monotonic = monotonic

    def close(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            session.close()

    def fetch(self, cancelled: threading.Event) -> tuple[HomepageArticle, ...]:
        if cancelled.is_set():
            raise _RefreshCancelled
        deadline = self.monotonic() + self.total_timeout
        response = self._request_get(
            LISTENBRAINZ_FRESH_RELEASES_URL,
            params={"days": 14},
            headers={"User-Agent": "Mariana/0.7 (+https://github.com/Vivojay/mariana-music-player)"},
            timeout=HTTP_TIMEOUT,
            stream=True,
            allow_redirects=False,
        )
        try:
            if self.monotonic() > deadline:
                raise HomepageProviderError("ListenBrainz exceeded its time limit")
            if int(getattr(response, "status_code", 200)) in {301, 302, 303, 307, 308}:
                raise HomepageProviderError("ListenBrainz redirects are not followed")
            response_url = urlsplit(
                str(getattr(response, "url", LISTENBRAINZ_FRESH_RELEASES_URL))
            )
            if response_url.scheme != "https" or response_url.hostname != "api.listenbrainz.org":
                raise HomepageProviderError("ListenBrainz redirected outside its official API")
            response.raise_for_status()
            content_length = (getattr(response, "headers", {}) or {}).get("Content-Length")
            try:
                declared_size = int(content_length) if content_length is not None else None
            except (TypeError, ValueError, OverflowError):
                declared_size = None
            if declared_size is not None and declared_size > self.max_bytes:
                raise HomepageProviderError("ListenBrainz response exceeds the homepage size limit")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=16_384):
                if cancelled.is_set():
                    raise _RefreshCancelled
                if self.monotonic() > deadline:
                    raise HomepageProviderError("ListenBrainz exceeded its time limit")
                if not isinstance(chunk, bytes) or not chunk:
                    continue
                size += len(chunk)
                if size > self.max_bytes:
                    raise HomepageProviderError("ListenBrainz response exceeds the homepage size limit")
                chunks.append(chunk)
            try:
                document = json.loads(b"".join(chunks))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise HomepageProviderError("ListenBrainz returned invalid release data") from error
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
        payload = document.get("payload") if isinstance(document, Mapping) else None
        values = payload.get("releases") if isinstance(payload, Mapping) else None
        if not isinstance(values, list):
            raise HomepageProviderError("ListenBrainz returned invalid release data")
        releases: list[HomepageArticle] = []
        seen: set[str] = set()
        for value in values:
            if cancelled.is_set():
                raise _RefreshCancelled
            if not isinstance(value, Mapping):
                continue
            release_mbid = value.get("release_mbid")
            if not isinstance(release_mbid, str) or _MBID.fullmatch(release_mbid) is None:
                continue
            release_mbid = release_mbid.casefold()
            if release_mbid in seen:
                continue
            title = _plain_text(value.get("release_name"), maximum=180)
            artist = _plain_text(value.get("artist_credit_name"), maximum=120)
            release_date = _plain_text(value.get("release_date"), maximum=10)
            release_type = _plain_text(value.get("release_group_primary_type"), maximum=40)
            if (
                not title
                or not artist
                or not release_date
                or re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date) is None
            ):
                continue
            seen.add(release_mbid)
            link = f"https://musicbrainz.org/release/{release_mbid}"
            caa_mbid = value.get("caa_release_mbid") or release_mbid
            image_url = (
                f"https://coverartarchive.org/release/{str(caa_mbid).casefold()}/front-500"
                if isinstance(caa_mbid, str) and _MBID.fullmatch(caa_mbid)
                else None
            )
            summary_parts = [part for part in (release_type, f"Released {release_date}") if part]
            releases.append(
                HomepageArticle(
                    article_id=hashlib.sha256(link.encode("utf-8")).hexdigest()[:20],
                    title=title,
                    excerpt=" · ".join(summary_parts),
                    source=self.source_name,
                    link=link,
                    published_at=release_date,
                    attribution=artist,
                    category=release_type,
                    section="releases",
                    image_url=image_url,
                )
            )
        releases.sort(key=lambda item: (item.published_at or "", item.title.casefold()), reverse=True)
        return tuple(releases[: self.max_items])


def _local_content(value: object) -> HomepageLocalContent:
    if isinstance(value, HomepageLocalContent):
        raw: Mapping[str, object] = {
            "library_count": value.library_count,
            "favorite_count": value.favorite_count,
            "playlist_count": value.playlist_count,
            "queue_count": value.queue_count,
            "items": value.items,
        }
    elif isinstance(value, Mapping):
        raw = value
    else:
        raw = {}
    items: list[HomepageLocalItem] = []
    raw_items = raw.get("items", ())
    if isinstance(raw_items, (list, tuple)):
        for candidate in raw_items[:MAX_LOCAL_ITEMS]:
            if isinstance(candidate, HomepageLocalItem):
                kind, title, subtitle = candidate.kind, candidate.title, candidate.subtitle
            elif isinstance(candidate, Mapping):
                kind = candidate.get("kind")
                title = candidate.get("title")
                subtitle = candidate.get("subtitle")
            else:
                continue
            if kind not in _LOCAL_KINDS:
                continue
            safe_title = _plain_text(title, maximum=160)
            safe_subtitle = _plain_text(subtitle, maximum=160) if subtitle is not None else None
            if safe_title:
                items.append(HomepageLocalItem(kind, safe_title, safe_subtitle))
    return HomepageLocalContent(
        library_count=_bounded_count(raw.get("library_count")),
        favorite_count=_bounded_count(raw.get("favorite_count")),
        playlist_count=_bounded_count(raw.get("playlist_count")),
        queue_count=_bounded_count(raw.get("queue_count")),
        items=tuple(items),
    )


def _article_from_cache(value: object) -> HomepageArticle | None:
    if not isinstance(value, Mapping) or set(value) != {
        "article_id",
        "title",
        "excerpt",
        "source",
        "link",
        "published_at",
        "attribution",
        "category",
        "section",
        "image_key",
        "image_mime",
    }:
        return None
    source = _plain_text(value.get("source"), maximum=64)
    section = value.get("section")
    if section not in {"culture", "releases"}:
        return None
    link = (
        _official_bandcamp_link(value.get("link"))
        if source == BandcampDailyProvider.source_name and section == "culture"
        else _official_musicbrainz_link(value.get("link"))
        if source == ListenBrainzFreshReleasesProvider.source_name and section == "releases"
        else None
    )
    article_id = value.get("article_id")
    title = _plain_text(value.get("title"), maximum=180)
    excerpt = _plain_text(value.get("excerpt"), maximum=240)
    published_at = _plain_text(value.get("published_at"), maximum=40)
    attribution = _plain_text(value.get("attribution"), maximum=120)
    category = _plain_text(value.get("category"), maximum=64)
    image_key = value.get("image_key")
    image_mime = value.get("image_mime")
    if image_key is not None and (
        not isinstance(image_key, str) or _IMAGE_CACHE_NAME.fullmatch(image_key) is None
    ):
        return None
    if image_mime not in {None, "image/jpeg", "image/png", "image/webp"}:
        return None
    if (image_key is None) != (image_mime is None):
        return None
    if isinstance(image_key, str) and isinstance(image_mime, str):
        expected_mime = (
            "image/jpeg"
            if image_key.endswith(".jpg")
            else "image/png"
            if image_key.endswith(".png")
            else "image/webp"
        )
        if image_mime != expected_mime:
            return None
    expected_id = hashlib.sha256(link.encode("utf-8")).hexdigest()[:20] if link else None
    if (
        not isinstance(article_id, str)
        or not re.fullmatch(r"[0-9a-f]{20}", article_id)
        or article_id != expected_id
        or not link
        or not title
        or not excerpt
        or source not in {
            BandcampDailyProvider.source_name,
            ListenBrainzFreshReleasesProvider.source_name,
        }
    ):
        return None
    return HomepageArticle(
        article_id,
        title,
        excerpt,
        source,
        link,
        published_at,
        attribution,
        category,
        section=section,
        image_key=image_key,
        image_mime=image_mime,
    )


def _safe_provider_article(value: object) -> HomepageArticle | None:
    """Revalidate provider output at the service/cache projection boundary."""

    if not isinstance(value, HomepageArticle):
        return None
    if value.source == BandcampDailyProvider.source_name and value.section == "culture":
        link = _official_bandcamp_link(value.link)
        image_url = _official_bandcamp_image(value.image_url)
    elif value.source == ListenBrainzFreshReleasesProvider.source_name and value.section == "releases":
        link = _official_musicbrainz_link(value.link)
        image_url = _official_cover_art_image(value.image_url)
    else:
        return None
    title = _plain_text(value.title, maximum=180)
    excerpt = _plain_text(value.excerpt, maximum=240)
    published_at = _plain_text(value.published_at, maximum=40)
    attribution = _plain_text(value.attribution, maximum=120)
    category = _plain_text(value.category, maximum=64)
    image_key = value.image_key
    image_mime = value.image_mime
    if image_key is not None or image_mime is not None:
        # Provider output cannot nominate application-owned cache keys. Those
        # are attached only after validated bytes are written by the service.
        image_key = None
        image_mime = None
    if not link or not title or not excerpt:
        return None
    return HomepageArticle(
        hashlib.sha256(link.encode("utf-8")).hexdigest()[:20],
        title,
        excerpt,
        value.source,
        link,
        published_at,
        attribution,
        category,
        section=value.section,
        image_url=image_url,
        image_key=image_key,
        image_mime=image_mime,
    )


@dataclass
class HomepageService:
    """Project local state immediately and refresh opted-in editorial data off-thread."""

    configuration: HomepageConfiguration = field(default_factory=HomepageConfiguration)
    local_loader: Callable[[], object] = field(default=dict)
    cache_load: Callable[[], object] = field(default=lambda: None)
    cache_save: Callable[[dict[str, object]], None] = field(default=lambda _value: None)
    provider: HomepageProvider = field(default_factory=BandcampDailyProvider)
    additional_providers: tuple[HomepageProvider, ...] = ()
    image_cache: HomepageImageCache | None = None
    on_update: Callable[[HomepageProjection], None] | None = None
    now: Callable[[], float] = time.time
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS
    cache_max_age_seconds: float = DEFAULT_CACHE_MAX_AGE_SECONDS

    def __post_init__(self) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._generation = 0
        self._workers: set[threading.Thread] = set()
        self._cancel_events: set[threading.Event] = set()
        self._articles: tuple[HomepageArticle, ...] = ()
        self._fetched_at: float | None = None
        self._online_state: HomepageState = "offline"
        self._safe_error: str | None = None
        self._load_cached_content()

    def _provider_tuple(self) -> tuple[HomepageProvider, ...]:
        return (self.provider, *self.additional_providers)

    def _provider_sources(self) -> list[str]:
        return [provider.source_name for provider in self._provider_tuple()]

    def _load_cached_content(self) -> None:
        try:
            raw = self.cache_load()
            encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        # The cache is an optional startup accelerator.  Storage callbacks can
        # fail for reasons beyond malformed JSON (for example, an unavailable
        # user-state database), and must never prevent Mariana from starting
        # with an empty homepage cache.
        except Exception:
            return
        if not isinstance(raw, Mapping) or len(encoded) > MAX_CACHE_BYTES:
            return
        if set(raw) != {"schema_version", "sources", "fetched_at", "items"}:
            return
        fetched_at = raw.get("fetched_at")
        if (
            raw.get("schema_version") != HOMEPAGE_SCHEMA_VERSION
            or raw.get("sources") != self._provider_sources()
            or isinstance(fetched_at, bool)
            or not isinstance(fetched_at, (int, float))
        ):
            return
        try:
            fetched_at = float(fetched_at)
        except OverflowError:
            return
        if not math.isfinite(fetched_at) or fetched_at < 0:
            return
        age = self.now() - float(fetched_at)
        if age < -300 or age > max(0.0, self.cache_max_age_seconds):
            return
        raw_items = raw.get("items")
        if not isinstance(raw_items, list):
            return
        articles = tuple(
            article
            for value in raw_items[: DEFAULT_MAX_ITEMS * len(self._provider_tuple())]
            if (article := _article_from_cache(value)) is not None
        )
        if not articles:
            return
        self._articles = articles
        self._fetched_at = float(fetched_at)
        if self.configuration.online_enabled:
            self._online_state = "ready" if age <= self.cache_ttl_seconds else "stale"

    def _local_section(self) -> tuple[HomepageSectionProjection, str | None]:
        try:
            return _local_content(self.local_loader()).to_section(), None
        except Exception:
            return (
                {"key": "local", "title": "Your Mariana", "items": []},
                "Local homepage information is temporarily unavailable",
            )

    def snapshot(self) -> HomepageProjection:
        """Return the complete allowlisted, JSON-safe renderer projection."""

        with self._lock:
            fetched_at = self._fetched_at
            online_state = self._online_state
            online_error = self._safe_error
            articles = self._articles
            startup = self.configuration.show_on_startup
            online_enabled = self.configuration.online_enabled
        local_section, local_error = self._local_section()
        editorial_section: HomepageSectionProjection = {
            "key": "culture",
            "title": "Music, art, and culture",
            "items": [
                article.to_projection_item() for article in articles if article.section == "culture"
            ],
        }
        release_section: HomepageSectionProjection = {
            "key": "releases",
            "title": "New releases",
            "items": [
                article.to_projection_item() for article in articles if article.section == "releases"
            ],
        }
        if not online_enabled:
            state: HomepageState = "offline"
            message = local_error or "Online discovery is off"
        elif local_error and online_state in {"ready", "stale", "loading"}:
            state = "partial"
            message = local_error
        elif local_error and online_state in {"offline", "error"} and not articles:
            state = "error"
            message = local_error
        else:
            state = online_state
            message = online_error or local_error
        return {
            "schema_version": HOMEPAGE_SCHEMA_VERSION,
            "show_on_startup": startup,
            "online_enabled": online_enabled,
            "state": state,
            "refreshed_at": fetched_at,
            "safe_message": message,
            "sections": [
                local_section, editorial_section, release_section, *catalogue_sections(), *official_destination_sections(),
            ],
        }

    def release_target(self, item_id: str) -> tuple[str, str] | None:
        """Bind an eligible current card without trusting a renderer-supplied URL."""
        with self._lock:
            if self._closed or not self.configuration.online_enabled:
                return None
            if item_id.startswith("catalogue:"):
                entry = BY_ID.get(item_id.removeprefix("catalogue:"))
                return entry.binding() if entry and entry.native else None
            for article in self._articles:
                if article.section != "releases" or f"release:{article.article_id}" != item_id:
                    continue
                link = _official_musicbrainz_link(article.link)
                if link:
                    identity = json.dumps([link, article.title, article.published_at], ensure_ascii=False)
                    return link.rsplit("/", 1)[-1], hashlib.sha256(identity.encode()).hexdigest()
        return None

    def configure(
        self,
        *,
        show_on_startup: bool | None = None,
        online_enabled: bool | None = None,
    ) -> HomepageProjection:
        if show_on_startup is not None and type(show_on_startup) is not bool:
            raise ValueError("Homepage startup setting must be true or false")
        if online_enabled is not None and type(online_enabled) is not bool:
            raise ValueError("Homepage online setting must be true or false")
        with self._lock:
            if self._closed:
                return self.snapshot()
            startup = (
                self.configuration.show_on_startup
                if show_on_startup is None
                else show_on_startup
            )
            online = self.configuration.online_enabled if online_enabled is None else online_enabled
            if self.configuration.online_enabled and not online:
                self._generation += 1
                for event in self._cancel_events:
                    event.set()
            self.configuration = HomepageConfiguration(startup, online)
            if not online:
                self._online_state = "offline"
                self._safe_error = None
            elif self._fetched_at is None:
                self._online_state = "offline"
            else:
                age = self.now() - self._fetched_at
                self._online_state = "ready" if age <= self.cache_ttl_seconds else "stale"
        projection = self.snapshot()
        self._notify(projection)
        return projection

    def _notify(self, projection: HomepageProjection | None = None) -> None:
        if self.on_update is None:
            return
        with suppress(Exception):
            self.on_update(projection or self.snapshot())

    def refresh_async(self) -> bool:
        """Start a fresh provider request without blocking the caller."""

        with self._lock:
            if self._closed or not self.configuration.online_enabled:
                return False
            # A slow provider must never create an unbounded pile of refresh
            # workers. The current projection already reports ``loading``;
            # callers can retry after that bounded request settles.
            if any(worker.is_alive() for worker in self._workers):
                return False
            self._generation += 1
            generation = self._generation
            for event in self._cancel_events:
                event.set()
            cancelled = threading.Event()
            self._cancel_events.add(cancelled)
            self._online_state = "loading"
            self._safe_error = None
            worker = threading.Thread(
                target=self._refresh_worker,
                args=(generation, cancelled),
                name=f"mariana-homepage-{generation}",
                daemon=True,
            )
            self._workers.add(worker)
            worker.start()
        self._notify()
        return True

    def _refresh_worker(self, generation: int, cancelled: threading.Event) -> None:
        try:
            if cancelled.is_set():
                raise _RefreshCancelled
            collected: list[HomepageArticle] = []
            provider_failed = False
            failures_were_offline = True
            for provider in self._provider_tuple():
                try:
                    fetched = provider.fetch(cancelled)
                except _RefreshCancelled:
                    raise
                except requests.RequestException:
                    provider_failed = True
                    continue
                except Exception:
                    provider_failed = True
                    failures_were_offline = False
                    continue
                usable = tuple(
                    article
                    for value in fetched[:DEFAULT_MAX_ITEMS]
                    if (article := _safe_provider_article(value)) is not None
                )
                if not usable:
                    provider_failed = True
                    failures_were_offline = False
                    continue
                collected.extend(usable)
            articles = tuple(collected)
            if not articles:
                self._finish_failure(
                    generation,
                    cancelled,
                    "Online discovery is temporarily unavailable"
                    if failures_were_offline
                    else "Online discovery could not be refreshed",
                    offline=failures_were_offline,
                )
                return
            cache = {
                "schema_version": HOMEPAGE_SCHEMA_VERSION,
                "sources": self._provider_sources(),
                "fetched_at": self.now(),
                "items": [article.to_cache_dict() for article in articles],
            }
            if len(json.dumps(cache, ensure_ascii=False).encode("utf-8")) > MAX_CACHE_BYTES:
                raise HomepageProviderError("Homepage cache exceeds its size limit")
            with self._lock:
                if self._closed or cancelled.is_set() or generation != self._generation:
                    return
                self._articles = articles
                self._fetched_at = float(cache["fetched_at"])
                try:
                    self.cache_save(cache)
                except Exception:
                    self._online_state = "partial"
                    self._safe_error = "Fresh discovery is shown but could not be cached"
                else:
                    self._online_state = "partial" if provider_failed else "ready"
                    self._safe_error = (
                        "Some discovery sources are temporarily unavailable"
                        if provider_failed
                        else None
                    )
            self._notify()
            image_cache = self.image_cache
            if image_cache is None:
                return
            enriched: list[HomepageArticle] = []
            changed = False
            for index, article in enumerate(articles):
                if cancelled.is_set():
                    raise _RefreshCancelled
                image = None
                if article.image_url:
                    try:
                        image = image_cache.resolve(article.article_id, article.image_url, cancelled)
                    except ArtworkCancelled:
                        raise _RefreshCancelled from None
                    except (ArtworkError, OSError, ValueError):
                        image = None
                if image is None:
                    enriched.append(article)
                    continue
                changed = True
                enriched.append(
                    replace(
                        article,
                        image_key=image.cache_key,
                        image_mime=image.mime_type,
                    )
                )
                # A slow later image must not hold back an already validated cover.
                # Generation checks also prevent disabled/closed workers publishing.
                with self._lock:
                    if self._closed or cancelled.is_set() or generation != self._generation:
                        return
                    self._articles = (*enriched, *articles[index + 1 :])
                self._notify()
            if not changed:
                return
            image_cache_payload = {
                **cache,
                "items": [article.to_cache_dict() for article in enriched],
            }
            if len(json.dumps(image_cache_payload, ensure_ascii=False).encode("utf-8")) > MAX_CACHE_BYTES:
                return
            with self._lock:
                if self._closed or cancelled.is_set() or generation != self._generation:
                    return
                self._articles = tuple(enriched)
                with suppress(Exception):
                    self.cache_save(image_cache_payload)
            self._notify()
        except _RefreshCancelled:
            return
        except requests.RequestException:
            self._finish_failure(
                generation,
                cancelled,
                "Online discovery is temporarily unavailable",
                offline=True,
            )
        except Exception:
            self._finish_failure(
                generation,
                cancelled,
                "Online discovery could not be refreshed",
                offline=False,
            )
        finally:
            with self._lock:
                self._cancel_events.discard(cancelled)
                self._workers.discard(threading.current_thread())

    def _finish_failure(
        self,
        generation: int,
        cancelled: threading.Event,
        safe_error: str,
        *,
        offline: bool,
    ) -> None:
        with self._lock:
            if self._closed or cancelled.is_set() or generation != self._generation:
                return
            if self._articles:
                self._online_state = "partial"
            else:
                self._online_state = "offline" if offline else "error"
            self._safe_error = safe_error
        self._notify()

    def wait(self, timeout: float = 1.0) -> bool:
        """Wait for current refresh workers; primarily useful to deterministic callers/tests."""

        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            with self._lock:
                workers = tuple(self._workers)
            if not workers:
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            for worker in workers:
                worker.join(timeout=max(0.0, remaining))

    def close(self, timeout: float = 1.0) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._generation += 1
            for event in self._cancel_events:
                event.set()
            workers = tuple(self._workers)
        deadline = time.monotonic() + max(0.0, timeout)
        for worker in workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        for provider in self._provider_tuple():
            close = getattr(provider, "close", None)
            if callable(close):
                with suppress(Exception):
                    close()
        if self.image_cache is not None:
            with suppress(Exception):
                self.image_cache.close()


def create_homepage_image_cache(
    cache_dir: str | os.PathLike[str],
) -> HomepageImageCache | None:
    """Create the optional visual cache without making homepage startup fragile."""

    try:
        return HomepageImageCache(cache_dir)
    except (OSError, ValueError):
        return None
