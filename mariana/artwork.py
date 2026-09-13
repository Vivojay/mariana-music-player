"""Bounded, privacy-safe current-media artwork retrieval and caching."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import ipaddress
import math
import os
import re
import socket
import tempfile
import threading
import time
import warnings
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse

import requests
from mutagen import File as MutagenFile  # pyright: ignore[reportMissingImports]
from mutagen import MutagenError  # pyright: ignore[reportMissingImports]
from mutagen.flac import Picture  # pyright: ignore[reportMissingImports]
from PIL import Image, UnidentifiedImageError

_ALLOWED_IMAGE_TYPES: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}
_MIME_ALIASES = {"image/jpg": "image/jpeg"}
_CACHE_NAME = re.compile(r"^[0-9a-f]{64}\.(?:jpg|png|webp)$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ADJACENT_STEMS = ("cover", "folder", "front", "albumart", "album")
_ADJACENT_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def _safe_projection_media_id(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    return candidate if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", candidate) else None


class ArtworkError(RuntimeError):
    """Base class for safe artwork-service failures."""


class ArtworkFetchError(ArtworkError):
    """Raised when a provider artwork reference cannot be fetched safely."""


class ArtworkValidationError(ArtworkError):
    """Raised when bytes are not an allowed, bounded still image."""


class ArtworkCancelled(ArtworkError):
    """Raised internally when superseded or shutdown work is cancelled."""


class ArtworkState(StrEnum):
    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    DISABLED = "disabled"


class ArtworkOrigin(StrEnum):
    CACHE = "cache"
    EMBEDDED = "embedded"
    ADJACENT = "adjacent"
    PROVIDER = "provider"


@dataclass(frozen=True, slots=True)
class ArtworkProjection:
    """Renderer-safe state with only a caller-approved public media ID."""

    schema_version: int
    media_id: str | None
    state: ArtworkState
    automatic_online: bool
    available: bool = False
    cache_key: str | None = None
    mime_type: str | None = None
    source: ArtworkOrigin | None = None
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "media_id": self.media_id,
            "state": self.state.value,
            "available": self.available,
            "automatic_online": self.automatic_online,
            "cache_key": self.cache_key,
            "mime_type": self.mime_type,
            "source": self.source.value if self.source is not None else None,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True, slots=True)
class CurrentArtwork:
    """Application-internal cache reference; never include it in public projections."""

    path: Path
    cache_key: str
    mime_type: str
    origin: ArtworkOrigin


@dataclass(frozen=True, slots=True)
class FetchedArtwork:
    data: bytes
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedArtwork:
    data: bytes
    mime_type: str
    extension: str


def validate_artwork_image(
    data: bytes,
    claimed_mime: str | None,
    *,
    max_encoded_bytes: int = 8 * 1024 * 1024,
    max_dimension: int = 8192,
    max_pixels: int = 40_000_000,
) -> ValidatedArtwork:
    """Validate bounded still-image bytes for trusted application caches."""

    if max_encoded_bytes <= 0 or max_dimension <= 0 or max_pixels <= 0:
        raise ValueError("Artwork validation limits must be positive")
    if not data or len(data) > max_encoded_bytes:
        raise ArtworkValidationError("Artwork exceeds the encoded size limit")
    normalized_claim = None
    if claimed_mime:
        normalized_claim = _MIME_ALIASES.get(claimed_mime.casefold(), claimed_mime.casefold())
        if normalized_claim not in {value[0] for value in _ALLOWED_IMAGE_TYPES.values()}:
            raise ArtworkValidationError("Artwork MIME type is not supported")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image_format = str(image.format or "").upper()
                if image_format not in _ALLOWED_IMAGE_TYPES:
                    raise ArtworkValidationError("Artwork image type is not supported")
                width, height = image.size
                if (
                    width <= 0
                    or height <= 0
                    or width > max_dimension
                    or height > max_dimension
                    or width * height > max_pixels
                ):
                    raise ArtworkValidationError("Artwork dimensions exceed the safety limit")
                if bool(getattr(image, "is_animated", False)):
                    raise ArtworkValidationError("Animated artwork is not supported")
                image.verify()
    except ArtworkValidationError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as error:
        raise ArtworkValidationError("Artwork image is malformed") from error
    mime_type, extension = _ALLOWED_IMAGE_TYPES[image_format]
    if normalized_claim is not None and normalized_claim != mime_type:
        raise ArtworkValidationError("Artwork MIME type does not match its contents")
    return ValidatedArtwork(data, mime_type, extension)


@dataclass(frozen=True, slots=True)
class _ArtworkRequest:
    media_identity: str
    projection_media_id: str | None
    local_path: Path | None
    trusted_provider_url: str | None


class ArtworkFetcher(Protocol):
    """Narrow fetch boundary for a resolver-supplied artwork reference."""

    def fetch(
        self,
        url: str,
        *,
        cancel: threading.Event,
        max_bytes: int,
    ) -> FetchedArtwork: ...


class SafeArtworkFetcher:
    """Fetch public HTTP(S) artwork while validating every redirect target."""

    def __init__(
        self,
        *,
        session: Any | None = None,
        timeout: tuple[float, float] = (3.0, 10.0),
        total_timeout: float = 20.0,
        max_redirects: int = 3,
        address_resolver: Callable[..., Iterable[tuple[Any, ...]]] = socket.getaddrinfo,
        peer_address: Callable[[Any], object] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        accept: str = "image/jpeg,image/png,image/webp",
        user_agent: str = "Mariana-Artwork/1",
    ) -> None:
        self._owns_session = session is None
        self._closed = False
        self._response_lock = threading.RLock()
        self._active_responses: dict[int, Any] = {}
        self.session = session or requests.Session()
        if self._owns_session:
            self.session.trust_env = False
        self.timeout = timeout
        self.total_timeout = max(0.1, float(total_timeout))
        self.max_redirects = max(0, int(max_redirects))
        self.address_resolver = address_resolver
        self.peer_address = peer_address or self._response_peer_address
        self.monotonic = monotonic
        self.accept = accept
        self.user_agent = user_agent

    def close(self) -> None:
        """Cancel active response reads and release the owned HTTP session."""

        with self._response_lock:
            if self._closed:
                return
            self._closed = True
            active_responses = tuple(self._active_responses.values())
        for response in active_responses:
            with contextlib.suppress(Exception):
                response.close()
        if self._owns_session:
            with contextlib.suppress(Exception):
                self.session.close()

    def fetch(
        self,
        url: str,
        *,
        cancel: threading.Event,
        max_bytes: int,
    ) -> FetchedArtwork:
        current = url
        deadline = self.monotonic() + self.total_timeout
        for redirect_index in range(self.max_redirects + 1):
            with self._response_lock:
                if self._closed:
                    raise ArtworkCancelled("Artwork request was cancelled")
            if cancel.is_set():
                raise ArtworkCancelled("Artwork request was cancelled")
            if self.monotonic() > deadline:
                raise ArtworkFetchError("Artwork request exceeded its time limit")
            self._validate_public_target(current)
            try:
                response = self.session.get(
                    current,
                    allow_redirects=False,
                    headers={"Accept": self.accept, "User-Agent": self.user_agent},
                    stream=True,
                    timeout=self.timeout,
                )
            except requests.RequestException as error:
                raise ArtworkFetchError("Artwork request failed") from error
            with self._response_lock:
                if self._closed:
                    response.close()
                    raise ArtworkCancelled("Artwork request was cancelled")
                self._active_responses[id(response)] = response
            try:
                if cancel.is_set():
                    raise ArtworkCancelled("Artwork request was cancelled")
                self._validate_public_address(self.peer_address(response))
                if self.monotonic() > deadline:
                    raise ArtworkFetchError("Artwork request exceeded its time limit")
                if response.status_code in _REDIRECT_STATUSES:
                    location = str(response.headers.get("Location") or "").strip()
                    if not location or redirect_index >= self.max_redirects:
                        raise ArtworkFetchError("Artwork redirect could not be followed safely")
                    current = urljoin(current, location)
                    continue
                try:
                    response.raise_for_status()
                except requests.RequestException as error:
                    raise ArtworkFetchError("Artwork provider rejected the request") from error

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > max_bytes:
                            raise ArtworkValidationError("Artwork exceeds the encoded size limit")
                    except ValueError as error:
                        raise ArtworkValidationError("Artwork has an invalid encoded size") from error

                payload = bytearray()
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if cancel.is_set():
                        raise ArtworkCancelled("Artwork request was cancelled")
                    if self.monotonic() > deadline:
                        raise ArtworkFetchError("Artwork request exceeded its time limit")
                    if not chunk:
                        continue
                    payload.extend(chunk)
                    if len(payload) > max_bytes:
                        raise ArtworkValidationError("Artwork exceeds the encoded size limit")
                content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip() or None
                return FetchedArtwork(bytes(payload), content_type)
            finally:
                with self._response_lock:
                    self._active_responses.pop(id(response), None)
                response.close()
        raise ArtworkFetchError("Artwork redirected too many times")

    def _validate_public_target(self, value: str) -> None:
        try:
            parsed = urlparse(value)
            port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
        except ValueError as error:
            raise ArtworkFetchError("Artwork reference is invalid") from error
        if (
            parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ArtworkFetchError("Artwork reference must be a public HTTP or HTTPS URL")
        try:
            answers = tuple(self.address_resolver(parsed.hostname, port, type=socket.SOCK_STREAM))
        except (OSError, ValueError) as error:
            raise ArtworkFetchError("Artwork provider address could not be resolved safely") from error
        if not answers:
            raise ArtworkFetchError("Artwork provider address could not be resolved safely")
        for answer in answers:
            try:
                raw_address = answer[4][0]
            except (IndexError, TypeError, ValueError) as error:
                raise ArtworkFetchError("Artwork provider returned an invalid address") from error
            self._validate_public_address(raw_address)

    @staticmethod
    def _validate_public_address(value: object) -> None:
        try:
            raw_address = str(value).split("%", 1)[0]
            address = ipaddress.ip_address(raw_address)
        except (TypeError, ValueError) as error:
            raise ArtworkFetchError("Artwork provider returned an invalid address") from error
        if not address.is_global:
            raise ArtworkFetchError("Artwork provider address is not public")

    @staticmethod
    def _response_peer_address(response: Any) -> object:
        raw = getattr(response, "raw", None)
        connection = getattr(raw, "connection", None) or getattr(raw, "_connection", None)
        sock = getattr(connection, "sock", None)
        if sock is None:
            original = getattr(raw, "_original_response", None)
            fp = getattr(original, "fp", None)
            sock = getattr(getattr(fp, "raw", None), "_sock", None)
        if sock is None:
            raise ArtworkFetchError("Artwork provider connection could not be verified")
        try:
            return sock.getpeername()[0]
        except (AttributeError, IndexError, OSError, TypeError) as error:
            raise ArtworkFetchError("Artwork provider connection could not be verified") from error


class ArtworkManager:
    """Resolve and cache artwork without making it part of playback authority."""

    def __init__(
        self,
        cache_dir: str | os.PathLike[str],
        *,
        automatic_online: bool = False,
        fetcher: ArtworkFetcher | None = None,
        max_encoded_bytes: int = 8 * 1024 * 1024,
        max_dimension: int = 8192,
        max_pixels: int = 40_000_000,
        cache_ttl_seconds: float = 30 * 24 * 60 * 60,
        max_cache_bytes: int = 256 * 1024 * 1024,
        max_cache_entries: int = 512,
        max_workers: int = 2,
        now: Callable[[], float] = time.time,
        on_update: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        if max_encoded_bytes <= 0 or max_dimension <= 0 or max_pixels <= 0:
            raise ValueError("Artwork validation limits must be positive")
        if cache_ttl_seconds <= 0 or max_cache_bytes <= 0 or max_cache_entries <= 0:
            raise ValueError("Artwork cache limits must be positive")
        self.cache_dir = Path(cache_dir).resolve(strict=False)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._automatic_online = bool(automatic_online)
        self._owns_fetcher = fetcher is None
        self._fetcher = fetcher or SafeArtworkFetcher()
        self._max_encoded_bytes = min(int(max_encoded_bytes), int(max_cache_bytes))
        self._max_dimension = int(max_dimension)
        self._max_pixels = int(max_pixels)
        self._cache_ttl_seconds = float(cache_ttl_seconds)
        self._max_cache_bytes = int(max_cache_bytes)
        self._max_cache_entries = int(max_cache_entries)
        self._now = now
        self._on_update = on_update
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="mariana-artwork",
        )
        self._closed = False
        self._revision = 0
        self._current_request: _ArtworkRequest | None = None
        self._current_cancel: threading.Event | None = None
        self._current_image: CurrentArtwork | None = None
        self._projection = ArtworkProjection(1, None, ArtworkState.IDLE, self._automatic_online)
        self._futures: set[Future[None]] = set()
        self._cleanup_cache(remove_temporary=True)

    @property
    def automatic_online(self) -> bool:
        with self._lock:
            return self._automatic_online

    def activate(
        self,
        media_identity: str,
        *,
        projection_media_id: str | None = None,
        local_path: str | os.PathLike[str] | None = None,
        trusted_provider_url: str | None = None,
    ) -> int:
        """Select current media and begin non-blocking artwork resolution."""

        identity = str(media_identity).strip()
        if not identity:
            raise ValueError("Artwork requires a stable current-media identity")
        request = _ArtworkRequest(
            media_identity=identity,
            projection_media_id=self._safe_projection_media_id(projection_media_id),
            local_path=Path(local_path).resolve(strict=False) if local_path is not None else None,
            trusted_provider_url=str(trusted_provider_url).strip() if trusted_provider_url else None,
        )
        return self._start(request, explicit_online=False)

    def clear(self) -> int:
        """Invalidate current artwork when playback no longer has current media."""

        with self._condition:
            self._require_open()
            if self._current_cancel is not None:
                self._current_cancel.set()
            self._revision += 1
            self._current_request = None
            self._current_cancel = None
            self._current_image = None
            self._projection = ArtworkProjection(1, None, ArtworkState.IDLE, self._automatic_online)
            projection = self._projection
            self._condition.notify_all()
            revision = self._revision
        self._emit_update(projection)
        return revision

    def set_automatic_online(self, enabled: bool) -> int | None:
        """Apply the network preference and reconsider only the current item."""

        with self._lock:
            self._require_open()
            enabled = bool(enabled)
            if enabled == self._automatic_online:
                return None
            self._automatic_online = enabled
            request = self._current_request
            if request is None:
                current = self._projection
                self._projection = ArtworkProjection(
                    current.schema_version,
                    current.media_id,
                    current.state,
                    enabled,
                    current.available,
                    current.cache_key,
                    current.mime_type,
                    current.source,
                    current.unavailable_reason,
                )
                projection = self._projection
            else:
                projection = None
        if projection is not None:
            self._emit_update(projection)
            return None
        assert request is not None
        return self._start(request, explicit_online=False)

    def fetch_current(self, expected_projection_media_id: str | None = None) -> int | None:
        """Explicitly fetch the still-current projected media, when bound by ID."""

        with self._condition:
            self._require_open()
            request = self._current_request
            if request is None or request.trusted_provider_url is None:
                return None
            if expected_projection_media_id is not None:
                expected = self._safe_projection_media_id(expected_projection_media_id)
                if expected is None or expected != request.projection_media_id:
                    return None
            # Keep target validation and rebinding in one critical section so
            # a track transition cannot turn an explicit fetch into a request
            # for stale media.  _start uses the same re-entrant lock.
            return self._start(request, explicit_online=True)

    def projection(self) -> ArtworkProjection:
        with self._lock:
            return self._projection

    def current_image(self, expected_cache_key: str | None = None) -> CurrentArtwork | None:
        """Return the current cache reference to trusted application code only."""

        with self._lock:
            image = self._current_image
            if image is None or (expected_cache_key is not None and image.cache_key != expected_cache_key):
                return None
            path = image.path
        try:
            if path.is_symlink() or path.resolve(strict=True).parent != self.cache_dir:
                return None
        except OSError:
            return None
        return image

    def wait_for_idle(self, timeout: float = 5.0) -> ArtworkProjection:
        """Wait for current resolution; intended for explicit CLI actions and tests."""

        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._projection.state == ArtworkState.LOADING:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            return self._projection

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            if self._current_cancel is not None:
                self._current_cancel.set()
            self._revision += 1
            self._current_request = None
            self._current_image = None
            self._projection = ArtworkProjection(
                1,
                None,
                ArtworkState.UNAVAILABLE,
                self._automatic_online,
                unavailable_reason="Artwork service is unavailable",
            )
            projection = self._projection
            self._condition.notify_all()
        if self._owns_fetcher:
            close = getattr(self._fetcher, "close", None)
            if callable(close):
                close()
        self._emit_update(projection)
        self._executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self) -> ArtworkManager:
        return self

    def __exit__(self, _error_type: object, _error: object, _traceback: object) -> None:
        self.close()

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("Artwork service is closed")

    def _start(self, request: _ArtworkRequest, *, explicit_online: bool) -> int:
        with self._condition:
            self._require_open()
            if self._current_cancel is not None:
                self._current_cancel.set()
            self._revision += 1
            revision = self._revision
            cancel = threading.Event()
            self._current_cancel = cancel
            self._current_request = request
            self._current_image = None
            self._projection = ArtworkProjection(
                1,
                request.projection_media_id,
                ArtworkState.LOADING,
                self._automatic_online,
            )
            projection = self._projection
            allow_online = explicit_online or self._automatic_online
            self._condition.notify_all()
        self._emit_update(projection)
        with self._condition:
            if not self._is_current(revision, request, cancel):
                return revision
            # A rapid sequence of track changes must not leave an unbounded
            # backlog behind the small worker pool.  Running fetches retain
            # their cooperative cancellation event; futures which have not
            # started are discarded in favour of the newest media request.
            for stale_future in tuple(self._futures):
                if stale_future.cancel():
                    self._futures.discard(stale_future)
            future = self._executor.submit(self._resolve, revision, request, cancel, allow_online)
            self._futures.add(future)
            future.add_done_callback(self._future_finished)
            self._condition.notify_all()
        return revision

    def _future_finished(self, future: Future[None]) -> None:
        with self._condition:
            self._futures.discard(future)
            self._condition.notify_all()

    def _resolve(
        self,
        revision: int,
        request: _ArtworkRequest,
        cancel: threading.Event,
        allow_online: bool,
    ) -> None:
        try:
            cache_key = self._cache_key(request.media_identity)
            local_candidate_seen = False
            if request.local_path is not None:
                for data, content_type, origin in self._local_candidates(request.local_path, cancel):
                    local_candidate_seen = True
                    try:
                        validated = self._validate_image(data, content_type)
                    except ArtworkValidationError:
                        continue
                    image = self._store(cache_key, validated, origin, cancel)
                    self._publish_image(revision, request, cancel, image)
                    return

            # Local tags and adjacent cover files can change without changing
            # the durable media identity, so they are inspected before an old
            # identity-cache entry.  Online media remain cache-first to avoid
            # unnecessary network requests.
            cached = self._read_cached(cache_key, cancel)
            if cached is not None:
                self._publish_image(revision, request, cancel, cached)
                return

            if request.trusted_provider_url is not None and allow_online:
                fetched = self._fetcher.fetch(
                    request.trusted_provider_url,
                    cancel=cancel,
                    max_bytes=self._max_encoded_bytes,
                )
                validated = self._validate_image(fetched.data, fetched.content_type)
                image = self._store(cache_key, validated, ArtworkOrigin.PROVIDER, cancel)
                self._publish_image(revision, request, cancel, image)
                return

            if request.trusted_provider_url is not None and not allow_online:
                reason = "Automatic online artwork is disabled"
                state = ArtworkState.DISABLED
            elif local_candidate_seen:
                reason = "Artwork is invalid or unsupported"
                state = ArtworkState.UNAVAILABLE
            else:
                reason = "No artwork is available for this media"
                state = ArtworkState.UNAVAILABLE
            self._publish_projection(
                revision,
                request,
                cancel,
                ArtworkProjection(
                    1,
                    request.projection_media_id,
                    state,
                    self.automatic_online,
                    unavailable_reason=reason,
                ),
            )
        except ArtworkCancelled:
            return
        except (ArtworkError, OSError, ValueError):
            self._publish_projection(
                revision,
                request,
                cancel,
                ArtworkProjection(
                    1,
                    request.projection_media_id,
                    ArtworkState.ERROR,
                    self.automatic_online,
                    unavailable_reason="Artwork could not be loaded safely",
                ),
            )
        except Exception:
            self._publish_projection(
                revision,
                request,
                cancel,
                ArtworkProjection(
                    1,
                    request.projection_media_id,
                    ArtworkState.ERROR,
                    self.automatic_online,
                    unavailable_reason="Artwork could not be loaded safely",
                ),
            )

    def _publish_image(
        self,
        revision: int,
        request: _ArtworkRequest,
        cancel: threading.Event,
        image: CurrentArtwork,
    ) -> None:
        projection = ArtworkProjection(
            1,
            request.projection_media_id,
            ArtworkState.READY,
            self.automatic_online,
            available=True,
            cache_key=image.cache_key,
            mime_type=image.mime_type,
            source=image.origin,
        )
        with self._condition:
            if not self._is_current(revision, request, cancel):
                return
            self._current_image = image
            self._projection = projection
            self._condition.notify_all()
        self._emit_update(projection)

    def _publish_projection(
        self,
        revision: int,
        request: _ArtworkRequest,
        cancel: threading.Event,
        projection: ArtworkProjection,
    ) -> None:
        with self._condition:
            if not self._is_current(revision, request, cancel):
                return
            self._current_image = None
            self._projection = projection
            self._condition.notify_all()
        self._emit_update(projection)

    def _emit_update(self, projection: ArtworkProjection) -> None:
        callback = self._on_update
        if callback is None:
            return
        with contextlib.suppress(Exception):
            callback(projection.to_dict())

    def _is_current(self, revision: int, request: _ArtworkRequest, cancel: threading.Event) -> bool:
        return (
            not self._closed
            and not cancel.is_set()
            and revision == self._revision
            and request is self._current_request
            and cancel is self._current_cancel
        )

    @staticmethod
    def _cache_key(media_identity: str) -> str:
        return hashlib.sha256(f"mariana-artwork-v1\0{media_identity}".encode()).hexdigest()

    @staticmethod
    def _safe_projection_media_id(value: str | None) -> str | None:
        return _safe_projection_media_id(value)

    def _read_cached(self, cache_key: str, cancel: threading.Event) -> CurrentArtwork | None:
        for image_format, (mime_type, extension) in _ALLOWED_IMAGE_TYPES.items():
            del image_format
            path = self.cache_dir / f"{cache_key}.{extension}"
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.is_symlink() or self._now() - stat.st_mtime > self._cache_ttl_seconds:
                self._safe_unlink(path)
                continue
            try:
                data = self._read_bounded(path, cancel)
                validated = self._validate_image(data, mime_type)
            except (ArtworkError, OSError):
                self._safe_unlink(path)
                continue
            if validated.extension != extension:
                self._safe_unlink(path)
                continue
            with contextlib.suppress(OSError):
                os.utime(path, None)
            return CurrentArtwork(path, path.name, validated.mime_type, ArtworkOrigin.CACHE)
        return None

    def _store(
        self,
        cache_key: str,
        artwork: ValidatedArtwork,
        origin: ArtworkOrigin,
        cancel: threading.Event,
    ) -> CurrentArtwork:
        if cancel.is_set():
            raise ArtworkCancelled("Artwork request was cancelled")
        destination = self.cache_dir / f"{cache_key}.{artwork.extension}"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.cache_dir,
                prefix=f".{cache_key}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(artwork.data)
                temporary.flush()
                os.fsync(temporary.fileno())
            with self._lock:
                if self._closed or cancel.is_set():
                    raise ArtworkCancelled("Artwork request was cancelled")
                for _mime, extension in _ALLOWED_IMAGE_TYPES.values():
                    other = self.cache_dir / f"{cache_key}.{extension}"
                    if other != destination:
                        self._safe_unlink(other)
                os.replace(temporary_path, destination)
                temporary_path = None
                # Replacement and eviction form one cache transaction.  A
                # superseded worker must not run a later cleanup pass which
                # can evict the current worker's just-published destination.
                # _cleanup_cache deliberately uses this same re-entrant lock.
                self._cleanup_cache(preserve=destination)
            return CurrentArtwork(destination, destination.name, artwork.mime_type, origin)
        finally:
            if temporary_path is not None:
                self._safe_unlink(temporary_path)

    def _local_candidates(
        self,
        local_path: Path,
        cancel: threading.Event,
    ) -> Iterable[tuple[bytes, str | None, ArtworkOrigin]]:
        for data, content_type in self._embedded_candidates(local_path, cancel):
            yield data, content_type, ArtworkOrigin.EMBEDDED
        for path in self._adjacent_paths(local_path):
            try:
                yield self._read_bounded(path, cancel), None, ArtworkOrigin.ADJACENT
            except (ArtworkError, OSError):
                continue

    def _embedded_candidates(
        self,
        local_path: Path,
        cancel: threading.Event,
    ) -> Iterable[tuple[bytes, str | None]]:
        if cancel.is_set():
            raise ArtworkCancelled("Artwork request was cancelled")
        try:
            media = MutagenFile(local_path, easy=False)
        except (MutagenError, OSError, TypeError, ValueError):
            return
        if media is None:
            return

        for picture in getattr(media, "pictures", ()) or ():
            data = getattr(picture, "data", None)
            if isinstance(data, bytes):
                yield data, self._optional_text(getattr(picture, "mime", None))

        tags = getattr(media, "tags", None) or {}
        items = tags.items() if isinstance(tags, Mapping) or hasattr(tags, "items") else ()
        for key, raw_value in items:
            if cancel.is_set():
                raise ArtworkCancelled("Artwork request was cancelled")
            lowered = str(key).casefold()
            values = raw_value if isinstance(raw_value, (list, tuple)) else (raw_value,)
            if lowered.startswith("apic"):
                for value in values:
                    data = getattr(value, "data", None)
                    if isinstance(data, bytes):
                        yield data, self._optional_text(getattr(value, "mime", None))
            elif lowered.startswith("covr"):
                for value in values:
                    if isinstance(value, bytes):
                        yield bytes(value), None
            elif lowered.startswith("metadata_block_picture"):
                for value in values:
                    if isinstance(value, bytes):
                        encoded = value
                    elif isinstance(value, str):
                        encoded = value.encode("ascii", errors="ignore")
                    else:
                        continue
                    if len(encoded) > math.ceil(self._max_encoded_bytes * 4 / 3) + 8:
                        continue
                    try:
                        picture = Picture(base64.b64decode(encoded, validate=True))
                    except (TypeError, ValueError):
                        continue
                    if isinstance(picture.data, bytes):
                        yield picture.data, self._optional_text(picture.mime)

    @staticmethod
    def _optional_text(value: object) -> str | None:
        return str(value).strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _adjacent_paths(local_path: Path) -> Iterable[Path]:
        directory = local_path.parent
        try:
            candidates = tuple(directory.iterdir())
        except OSError:
            return
        matches: list[Path] = []
        for candidate in candidates:
            if (
                candidate.stem.casefold() not in _ADJACENT_STEMS
                or candidate.suffix.casefold() not in _ADJACENT_SUFFIXES
            ):
                continue
            try:
                if candidate.is_file() and not candidate.is_symlink():
                    matches.append(candidate)
            except OSError:
                continue
        stem_order = {stem: index for index, stem in enumerate(_ADJACENT_STEMS)}
        suffix_order = {suffix: index for index, suffix in enumerate(_ADJACENT_SUFFIXES)}
        matches.sort(
            key=lambda path: (
                stem_order[path.stem.casefold()],
                suffix_order[path.suffix.casefold()],
                path.name.casefold(),
                path.name,
            )
        )
        yield from matches

    def _read_bounded(self, path: Path, cancel: threading.Event) -> bytes:
        if cancel.is_set():
            raise ArtworkCancelled("Artwork request was cancelled")
        if path.stat().st_size > self._max_encoded_bytes:
            raise ArtworkValidationError("Artwork exceeds the encoded size limit")
        with path.open("rb") as handle:
            data = handle.read(self._max_encoded_bytes + 1)
        if len(data) > self._max_encoded_bytes:
            raise ArtworkValidationError("Artwork exceeds the encoded size limit")
        return data

    def _validate_image(self, data: bytes, claimed_mime: str | None) -> ValidatedArtwork:
        return validate_artwork_image(
            data,
            claimed_mime,
            max_encoded_bytes=self._max_encoded_bytes,
            max_dimension=self._max_dimension,
            max_pixels=self._max_pixels,
        )

    def _cleanup_cache(self, preserve: Path | None = None, *, remove_temporary: bool = False) -> None:
        with self._lock:
            entries: list[tuple[float, int, Path]] = []
            now = self._now()
            try:
                paths = tuple(self.cache_dir.iterdir())
            except OSError:
                return
            for path in paths:
                if path.name.endswith(".tmp"):
                    if remove_temporary:
                        self._safe_unlink(path)
                    continue
                if not _CACHE_NAME.fullmatch(path.name) or path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if now - stat.st_mtime > self._cache_ttl_seconds:
                    self._safe_unlink(path)
                    continue
                entries.append((stat.st_mtime, stat.st_size, path))

            entries.sort(key=lambda entry: (entry[0], entry[2].name))
            total = sum(entry[1] for entry in entries)
            while len(entries) > self._max_cache_entries or total > self._max_cache_bytes:
                eviction_index = next(
                    (index for index, entry in enumerate(entries) if preserve is None or entry[2] != preserve),
                    None,
                )
                if eviction_index is None:
                    break
                _modified, size, path = entries.pop(eviction_index)
                self._safe_unlink(path)
                total -= size

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


class ArtworkUnavailableService:
    """Nonfatal artwork boundary used when the optional service cannot start."""

    def __init__(
        self,
        *,
        automatic_online: bool = False,
        on_update: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        self._automatic_online = bool(automatic_online)
        self._on_update = on_update
        self._lock = threading.RLock()
        self._revision = 0
        self._closed = False
        self._projection = self._unavailable_projection(None)

    @property
    def automatic_online(self) -> bool:
        with self._lock:
            return self._automatic_online

    def activate(
        self,
        media_identity: str,
        *,
        projection_media_id: str | None = None,
        local_path: str | os.PathLike[str] | None = None,
        trusted_provider_url: str | None = None,
    ) -> int:
        del local_path, trusted_provider_url
        if not str(media_identity).strip():
            raise ValueError("Artwork requires a stable current-media identity")
        return self._update(_safe_projection_media_id(projection_media_id))

    def clear(self) -> int:
        return self._update(None)

    def set_automatic_online(self, enabled: bool) -> int | None:
        with self._lock:
            self._require_open()
            enabled = bool(enabled)
            if enabled == self._automatic_online:
                return None
            self._automatic_online = enabled
            self._revision += 1
            self._projection = self._unavailable_projection(self._projection.media_id)
            revision = self._revision
            projection = self._projection
        self._emit_update(projection)
        return revision

    def fetch_current(self, expected_projection_media_id: str | None = None) -> None:
        del expected_projection_media_id
        with self._lock:
            self._require_open()
        return None

    def projection(self) -> ArtworkProjection:
        with self._lock:
            return self._projection

    def current_image(self, expected_cache_key: str | None = None) -> None:
        del expected_cache_key
        return None

    def wait_for_idle(self, timeout: float = 5.0) -> ArtworkProjection:
        del timeout
        return self.projection()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True

    def __enter__(self) -> ArtworkUnavailableService:
        return self

    def __exit__(self, _error_type: object, _error: object, _traceback: object) -> None:
        self.close()

    def _update(self, media_id: str | None) -> int:
        with self._lock:
            self._require_open()
            self._revision += 1
            self._projection = self._unavailable_projection(media_id)
            revision = self._revision
            projection = self._projection
        self._emit_update(projection)
        return revision

    def _unavailable_projection(self, media_id: str | None) -> ArtworkProjection:
        return ArtworkProjection(
            1,
            media_id,
            ArtworkState.ERROR,
            self._automatic_online,
            unavailable_reason="Artwork service is unavailable",
        )

    def _emit_update(self, projection: ArtworkProjection) -> None:
        if self._on_update is not None:
            with contextlib.suppress(Exception):
                self._on_update(projection.to_dict())

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("Artwork service is closed")


def create_artwork_manager(
    cache_dir: str | os.PathLike[str],
    **options: Any,
) -> ArtworkManager | ArtworkUnavailableService:
    """Create the optional artwork service without making app startup depend on it."""

    try:
        return ArtworkManager(cache_dir, **options)
    except Exception:
        return ArtworkUnavailableService(
            automatic_online=bool(options.get("automatic_online", False)),
            on_update=options.get("on_update"),
        )
