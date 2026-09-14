"""Bounded access to LibriVox's public-domain audiobook catalog API."""

from __future__ import annotations

import html
import ipaddress
import json
import math
import re
import time
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import requests

from .models import MediaCapabilities, MediaRef, MediaSource, podcast_episode_identity

API_ROOT = "https://librivox.org/api/feed"
API_INFO_URL = "https://librivox.org/api/info"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_DESCRIPTION_LENGTH = 12_000
USER_AGENT = "Mariana/0.7 (+https://github.com/Vivojay/mariana-music-player)"


class LibrivoxError(ValueError):
    """A safe, user-facing LibriVox catalog failure."""


class _Response(Protocol):
    url: str

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> Mapping[str, str]: ...

    def raise_for_status(self) -> None: ...

    def iter_content(self, chunk_size: int) -> Iterable[bytes]: ...

    def close(self) -> None: ...


class _Session(Protocol):
    max_redirects: int

    def get(self, url: str, **kwargs: Any) -> _Response: ...


class LibrivoxClientProtocol(Protocol):
    def search_title(self, query: str, *, limit: int, offset: int) -> list[LibrivoxBook]: ...

    def search_author(self, surname: str, *, limit: int, offset: int) -> list[LibrivoxBook]: ...

    def search_genre(self, genre: str, *, limit: int, offset: int) -> list[LibrivoxBook]: ...

    def recent(self, *, days: int, limit: int, offset: int) -> list[LibrivoxBook]: ...

    def book(self, catalog_id: str) -> LibrivoxBook: ...


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _clean_text(value: object, *, maximum: int = 500) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(str(value or ""))
    except (TypeError, ValueError):
        return ""
    text = html.unescape(" ".join(parser.parts))
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:maximum].rstrip()


def _public_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if re.search(r"[\x00-\x1f\x7f]", candidate):
        return None
    try:
        parsed = urlparse(candidate)
        # Accessing port validates malformed and out-of-range port values.
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password or port == 0:
        return None
    host = parsed.hostname.casefold().rstrip(".")
    if host == "localhost" or host.endswith(".local"):
        return None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            return None
    return candidate


def _catalog_id(value: object) -> str | None:
    identifier = str(value or "").strip()
    if not identifier.isascii() or not identifier.isdecimal():
        return None
    return identifier.lstrip("0") or None


def _positive_integer(value: object, *, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError, OverflowError):
        return default
    return number if number > 0 else default


def _duration_seconds(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return None
        return number if math.isfinite(number) and number > 0 else None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if ":" not in text:
            number = float(text)
        else:
            pieces = [float(piece) for piece in text.split(":")]
            if len(pieces) > 3 or any(piece < 0 for piece in pieces):
                return None
            number = 0.0
            for piece in pieces:
                number = number * 60 + piece
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _names(values: object, *, reader: bool = False) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    result: list[str] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        if reader:
            name = _clean_text(item.get("display_name"), maximum=160)
        else:
            name = _clean_text(
                " ".join(str(item.get(key) or "") for key in ("first_name", "last_name")),
                maximum=160,
            )
        if name and name not in result:
            result.append(name)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class LibrivoxSection:
    section_id: str
    number: int
    title: str
    listen_url: str
    duration_seconds: float | None = None
    language: str | None = None
    readers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LibrivoxBook:
    catalog_id: str
    title: str
    description: str = ""
    authors: tuple[str, ...] = ()
    translators: tuple[str, ...] = ()
    language: str | None = None
    copyright_year: str | None = None
    section_count: int = 0
    total_time: str | None = None
    total_seconds: float | None = None
    rss_url: str | None = None
    zip_url: str | None = None
    catalog_url: str | None = None
    text_url: str | None = None
    archive_url: str | None = None
    artwork_url: str | None = None
    genres: tuple[str, ...] = ()
    sections: tuple[LibrivoxSection, ...] = ()

    @property
    def author_label(self) -> str:
        return ", ".join(self.authors) or "Unknown author"


def _section(raw: object, fallback_number: int) -> LibrivoxSection | None:
    if not isinstance(raw, dict):
        return None
    section_id = str(raw.get("id") or "").strip()
    listen_url = _public_url(raw.get("listen_url"))
    if not section_id or listen_url is None:
        return None
    number = _positive_integer(raw.get("section_number"), default=fallback_number)
    return LibrivoxSection(
        section_id=section_id,
        number=number,
        title=_clean_text(raw.get("title"), maximum=300) or f"Section {number}",
        listen_url=listen_url,
        duration_seconds=_duration_seconds(raw.get("playtime")),
        language=_clean_text(raw.get("language"), maximum=80) or None,
        readers=_names(raw.get("readers"), reader=True),
    )


def parse_book(raw: object) -> LibrivoxBook | None:
    """Parse one allowlisted API record into immutable catalog data."""
    if not isinstance(raw, dict):
        return None
    catalog_id = _catalog_id(raw.get("id"))
    title = _clean_text(raw.get("title"), maximum=300)
    if catalog_id is None or not title:
        return None
    sections = raw.get("sections")
    genre_records = raw.get("genres")
    parsed_sections = [
        section
        for index, item in enumerate(sections if isinstance(sections, list) else (), start=1)
        if (section := _section(item, index)) is not None
    ]
    parsed_sections.sort(key=lambda item: (item.number, item.section_id))
    genres = tuple(
        name
        for item in (genre_records if isinstance(genre_records, list) else ())
        if isinstance(item, dict) and (name := _clean_text(item.get("name"), maximum=160))
    )
    total_time = _clean_text(raw.get("totaltime"), maximum=40) or None
    return LibrivoxBook(
        catalog_id=catalog_id,
        title=title,
        description=_clean_text(raw.get("description"), maximum=MAX_DESCRIPTION_LENGTH),
        authors=_names(raw.get("authors")),
        translators=_names(raw.get("translators")),
        language=_clean_text(raw.get("language"), maximum=80) or None,
        copyright_year=_clean_text(raw.get("copyright_year"), maximum=20) or None,
        section_count=_positive_integer(raw.get("num_sections"), default=len(parsed_sections)),
        total_time=total_time,
        total_seconds=_duration_seconds(raw.get("totaltimesecs")) or _duration_seconds(total_time),
        rss_url=_public_url(raw.get("url_rss")),
        zip_url=_public_url(raw.get("url_zip_file")),
        catalog_url=_public_url(raw.get("url_librivox")) or _public_url(raw.get("url_project")),
        text_url=_public_url(raw.get("url_text_source")),
        archive_url=_public_url(raw.get("url_iarchive")),
        artwork_url=(
            _public_url(raw.get("coverart_jpg"))
            or _public_url(raw.get("coverart_thumbnail"))
        ),
        genres=genres,
        sections=tuple(parsed_sections),
    )


class LibrivoxClient:
    """Small synchronous client used only after an explicit catalog command."""

    def __init__(
        self,
        session: _Session | None = None,
        *,
        timeout: tuple[float, float] = (5, 20),
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> None:
        self.session = session or requests.Session()
        self.session.max_redirects = 5
        self.timeout = timeout
        self.max_response_bytes = min(MAX_RESPONSE_BYTES, max(1024, int(max_response_bytes)))

    @staticmethod
    def _catalog_url(value: object) -> str | None:
        candidate = _public_url(value)
        if candidate is None:
            return None
        parsed = urlparse(candidate)
        if (parsed.scheme != "https" or parsed.hostname not in {"librivox.org", "www.librivox.org"}
                or parsed.port not in (None, 443)):
            return None
        return candidate

    def _catalog_response(self, endpoint: str, parameters: dict[str, str | int]) -> _Response:
        target = f"{API_ROOT}/{endpoint}"
        params: dict[str, str | int] | None = {**parameters, "format": "json"}
        for redirects in range(6):
            response = self.session.get(
                target, params=params,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=self.timeout, stream=True, allow_redirects=False,
            )
            if not 300 <= response.status_code < 400:
                return response
            try:
                location = response.headers.get("Location", "")
                following = self._catalog_url(urljoin(target, location)) if location else None
                if following is None:
                    raise LibrivoxError("LibriVox redirected outside its official catalog host")
                if redirects == 5:
                    raise LibrivoxError("LibriVox exceeded the catalog redirect limit")
                target, params = following, None
            finally:
                response.close()
        raise LibrivoxError("LibriVox exceeded the catalog redirect limit")

    def _request(
        self,
        endpoint: str,
        parameters: dict[str, str | int],
    ) -> list[LibrivoxBook]:
        try:
            response = self._catalog_response(endpoint, parameters)
        except requests.Timeout as error:
            raise LibrivoxError("LibriVox did not respond before the catalog timeout") from error
        except requests.RequestException as error:
            raise LibrivoxError("The LibriVox catalog is currently unavailable") from error
        payload = bytearray()
        try:
            response.raise_for_status()
            if self._catalog_url(getattr(response, "url", None)) is None:
                raise LibrivoxError("LibriVox redirected outside its official catalog host")
            for chunk in response.iter_content(64 * 1024):
                if not chunk:
                    continue
                payload.extend(chunk)
                if len(payload) > self.max_response_bytes:
                    raise LibrivoxError(
                        "The LibriVox catalog response exceeded Mariana's safety limit"
                    )
        except requests.Timeout as error:
            raise LibrivoxError("LibriVox did not respond before the catalog timeout") from error
        except requests.RequestException as error:
            raise LibrivoxError("The LibriVox catalog is currently unavailable") from error
        finally:
            response.close()
        try:
            document = json.loads(bytes(payload).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LibrivoxError("LibriVox returned invalid catalog data") from error
        if document in (False, None, []):
            return []
        if not isinstance(document, dict):
            raise LibrivoxError("LibriVox returned an unexpected catalog response")
        books = document.get("books")
        if not isinstance(books, list):
            return []
        return [book for raw in books if (book := parse_book(raw)) is not None]

    @staticmethod
    def _limit(value: int) -> int:
        if isinstance(value, bool) or value not in range(1, MAX_LIMIT + 1):
            raise LibrivoxError(f"LibriVox result count must be between 1 and {MAX_LIMIT}")
        return value

    @staticmethod
    def _offset(value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise LibrivoxError("LibriVox result offset must be a non-negative whole number")
        return value

    def search_title(self, query: str, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[LibrivoxBook]:
        query = _clean_text(query, maximum=200)
        if not query:
            raise LibrivoxError("LibriVox title search requires text")
        return self._request(
            "audiobooks",
            {
                "title": f"^{query}",
                "limit": self._limit(limit),
                "offset": self._offset(offset),
                "coverart": 1,
            },
        )

    def search_author(self, surname: str, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[LibrivoxBook]:
        surname = _clean_text(surname, maximum=200)
        if not surname:
            raise LibrivoxError("LibriVox author search requires a surname")
        return self._request(
            "audiobooks",
            {
                "author": surname,
                "limit": self._limit(limit),
                "offset": self._offset(offset),
                "coverart": 1,
            },
        )

    def search_genre(self, genre: str, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[LibrivoxBook]:
        genre = _clean_text(genre, maximum=200)
        if not genre:
            raise LibrivoxError("LibriVox genre search requires a genre")
        return self._request(
            "audiobooks",
            {
                "genre": genre,
                "limit": self._limit(limit),
                "offset": self._offset(offset),
                "coverart": 1,
            },
        )

    def recent(self, *, days: int = 30, limit: int = DEFAULT_LIMIT, offset: int = 0) -> list[LibrivoxBook]:
        if isinstance(days, bool) or days not in range(1, 3661):
            raise LibrivoxError("LibriVox recent days must be between 1 and 3660")
        since = int(time.time()) - days * 86_400
        return self._request(
            "audiobooks",
            {
                "since": since,
                "limit": self._limit(limit),
                "offset": self._offset(offset),
                "coverart": 1,
            },
        )

    def book(self, catalog_id: str) -> LibrivoxBook:
        identifier = _catalog_id(catalog_id)
        if identifier is None:
            raise LibrivoxError("A positive LibriVox catalog ID is required")
        books = self._request(
            "audiobooks",
            {"id": identifier, "extended": 1, "coverart": 1, "limit": 1},
        )
        if not books:
            raise LibrivoxError(f"LibriVox audiobook {identifier} was not found")
        if len(books) != 1 or books[0].catalog_id != identifier:
            raise LibrivoxError("LibriVox detail response did not match the requested catalog ID")
        return books[0]


class LibrivoxCatalog:
    """Bounded last-result state and durable chapter projections for the CLI."""

    def __init__(
        self,
        client: LibrivoxClientProtocol | None = None,
        *,
        detail_cache_size: int = 16,
    ) -> None:
        self.client = client or LibrivoxClient()
        self.results: tuple[LibrivoxBook, ...] = ()
        self._details: OrderedDict[str, LibrivoxBook] = OrderedDict()
        self.detail_cache_size = max(1, min(64, int(detail_cache_size)))

    @property
    def result_count(self) -> int:
        return len(self.results)

    def search(
        self,
        kind: str,
        query: str = "",
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        days: int = 30,
    ) -> tuple[LibrivoxBook, ...]:
        operations = {
            "title": lambda: self.client.search_title(query, limit=limit, offset=offset),
            "author": lambda: self.client.search_author(query, limit=limit, offset=offset),
            "genre": lambda: self.client.search_genre(query, limit=limit, offset=offset),
            "recent": lambda: self.client.recent(days=days, limit=limit, offset=offset),
        }
        try:
            books = operations[kind]()
        except KeyError as error:
            raise LibrivoxError(f"Unsupported LibriVox search type: {kind}") from error
        self.results = tuple(books)
        return self.results

    def _remember(self, book: LibrivoxBook) -> LibrivoxBook:
        self._details[book.catalog_id] = book
        self._details.move_to_end(book.catalog_id)
        while len(self._details) > self.detail_cache_size:
            self._details.popitem(last=False)
        return book

    def resolve(self, reference: str) -> LibrivoxBook:
        value = reference.strip().casefold()
        if value.startswith("id:"):
            catalog_id = value[3:]
        else:
            if not value.isdigit():
                raise LibrivoxError("Use a last-result number or an explicit id:<catalog-id>")
            index = int(value)
            if index not in range(1, len(self.results) + 1):
                raise LibrivoxError(
                    "LibriVox result number is unavailable; run a search or use id:<catalog-id>"
                )
            catalog_id = self.results[index - 1].catalog_id
        catalog_id = _catalog_id(catalog_id)
        if catalog_id is None:
            raise LibrivoxError("A positive LibriVox catalog ID is required")
        cached = self._details.get(catalog_id)
        if cached is not None:
            self._details.move_to_end(catalog_id)
            return cached
        book = self.client.book(catalog_id)
        if book.catalog_id != catalog_id:
            raise LibrivoxError("LibriVox detail response did not match the requested catalog ID")
        return self._remember(book)

    @staticmethod
    def select_sections(book: LibrivoxBook, selector: str | None) -> tuple[LibrivoxSection, ...]:
        if not book.sections:
            raise LibrivoxError("This LibriVox audiobook has no playable sections")
        if selector is None or selector.casefold() == "all":
            return book.sections
        if not selector.isdigit() or int(selector) not in range(1, len(book.sections) + 1):
            raise LibrivoxError(f"Chapter must be all or between 1 and {len(book.sections)}")
        return (book.sections[int(selector) - 1],)

    @staticmethod
    def media(book: LibrivoxBook, section: LibrivoxSection) -> MediaRef:
        feed_uri = book.rss_url or f"https://librivox.org/rss/{book.catalog_id}"
        identity = podcast_episode_identity(
            feed_uri,
            guid=f"librivox:{book.catalog_id}:{section.section_id}",
            episode_url=book.catalog_url,
            enclosure_url=section.listen_url,
            title=section.title,
        )
        if identity is None:  # The generated official feed URI is always valid.
            raise LibrivoxError("Could not establish a durable LibriVox chapter identity")
        stable_id, identity_kind = identity
        chapter_title = section.title
        title = chapter_title if chapter_title.casefold().startswith(book.title.casefold()) else f"{book.title} — {chapter_title}"
        creator = ", ".join(section.readers) or book.author_label
        resolver_data: dict[str, Any] = {
            "podcast_identity_kind": identity_kind,
            "librivox_book_id": book.catalog_id,
            "librivox_section_id": section.section_id,
            "librivox_section_number": section.number,
            "librivox_section_count": len(book.sections),
            "provider_metadata": {
                "provider": "LibriVox",
                "provider_media_id": section.section_id,
                "publisher": "LibriVox",
                "publisher_id": book.catalog_id,
            },
        }
        if book.description:
            resolver_data["description"] = book.description
        if book.artwork_url:
            resolver_data["artwork"] = book.artwork_url
        return MediaRef(
            MediaSource.PODCAST,
            section.listen_url,
            title=title,
            artist=creator,
            album=book.title,
            duration=section.duration_seconds,
            stable_id=stable_id,
            resolver_data=resolver_data,
            provenance="podcast-feed",
            capabilities=MediaCapabilities(
                finite=True,
                live=False,
                seekable=True,
                fingerprintable=True,
                downloadable=True,
                metadata_available=True,
            ),
        )
