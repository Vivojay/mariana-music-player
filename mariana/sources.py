"""Capability-aware media source resolution.

Resolvers return transient playback data without mutating the persistent
``MediaRef``.  In particular, signed URLs and authentication headers must not
be written to SQLite or queue snapshots.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from .models import MediaCapabilities, MediaRef, MediaSource, canonical_uri

ALLOWED_SCHEMES = frozenset({"http", "https"})
SENSITIVE_QUERY_KEYS = re.compile(
    r"(?:token|sig(?:nature)?|key|auth|credential|password|expires?|policy|session)",
    re.IGNORECASE,
)


class FailureCode(StrEnum):
    AUTH_REQUIRED = "auth_required"
    RATE_LIMITED = "rate_limited"
    GEO_BLOCKED = "geo_blocked"
    DRM = "drm"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    EXPIRED = "expired"
    UNSUPPORTED_PROTOCOL = "unsupported_protocol"
    DECODE = "decode"
    OUTPUT_DEVICE = "output_device"
    CANCELLED = "cancelled"


class MediaFailure(RuntimeError):
    """A safe, typed source or playback failure."""

    def __init__(
        self,
        code: FailureCode,
        source: MediaSource,
        message: str,
        *,
        retryable: bool = False,
        cause: BaseException | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.source = source
        self.retryable = retryable
        self.cause = cause
        self.retry_after = retry_after


@dataclass(slots=True)
class ResolvedMedia:
    media: MediaRef
    playback_uri: str
    canonical_uri: str
    capabilities: MediaCapabilities
    headers: dict[str, str] = field(default_factory=dict)
    expires_at: float | None = None
    endpoints: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time() + 15


class SourceResolver(Protocol):
    def resolve(self, media: MediaRef, *, force: bool = False) -> ResolvedMedia: ...
    def refresh(self, media: MediaRef) -> ResolvedMedia: ...
    def probe(self, resolved: ResolvedMedia) -> ResolvedMedia: ...
    def classify_failure(self, error: BaseException, media: MediaRef) -> MediaFailure: ...


def redacted_uri(value: str) -> str:
    """Strip credentials and redact secret-like query values for diagnostics."""
    parsed = urlparse(value)
    if parsed.scheme not in ALLOWED_SCHEMES:
        return value
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    query = [
        (key, "[REDACTED]" if SENSITIVE_QUERY_KEYS.search(key) else item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunparse((parsed.scheme, host, parsed.path, "", urlencode(query), ""))


def sanitized_resolver_data(value: dict[str, Any]) -> dict[str, Any]:
    """Return only stable resolver hints suitable for persistence."""
    allowed = {
        "youtube",
        "underlying_source",
        "station_id",
        "station_slug",
        "recording_mbid",
        "fingerprint",
        "library_id",
        "content_id",
        "credential_ref",
        "credential_username",
    }
    return {key: item for key, item in value.items() if key in allowed}


class BaseResolver:
    def resolve(self, media: MediaRef, *, force: bool = False) -> ResolvedMedia:
        raise NotImplementedError

    def refresh(self, media: MediaRef) -> ResolvedMedia:
        return self.resolve(media, force=True)

    def probe(self, resolved: ResolvedMedia) -> ResolvedMedia:
        return resolved

    def classify_failure(self, error: BaseException, media: MediaRef) -> MediaFailure:
        if isinstance(error, MediaFailure):
            return error
        if isinstance(error, (requests.Timeout, TimeoutError)):
            return MediaFailure(FailureCode.TIMEOUT, media.source, "The media source timed out", retryable=True, cause=error)
        if isinstance(error, requests.RequestException):
            status = getattr(error.response, "status_code", None)
            if status in {401, 403}:
                return MediaFailure(
                    FailureCode.AUTH_REQUIRED,
                    media.source,
                    "The media source requires authorization or is unavailable in this region",
                    cause=error,
                )
            if status == 429:
                return MediaFailure(FailureCode.RATE_LIMITED, media.source, "The media source rate-limited Mariana", retryable=True, cause=error)
            return MediaFailure(FailureCode.UNAVAILABLE, media.source, "The media source is unavailable", retryable=True, cause=error)
        return MediaFailure(FailureCode.UNAVAILABLE, media.source, str(error) or "The media source is unavailable", cause=error)


class LocalResolver(BaseResolver):
    def resolve(self, media: MediaRef, *, force: bool = False) -> ResolvedMedia:
        del force
        path = Path(media.original_uri).expanduser()
        try:
            path = path.resolve(strict=True)
            stat = path.stat()
        except (OSError, RuntimeError) as error:
            raise MediaFailure(FailureCode.UNAVAILABLE, media.source, f"Local media is unavailable: {path}", cause=error) from error
        if not path.is_file():
            raise MediaFailure(FailureCode.UNAVAILABLE, media.source, f"Local media is not a file: {path}")
        capabilities = MediaCapabilities(
            finite=True,
            live=False,
            seekable=True,
            fingerprintable=True,
            downloadable=False,
            metadata_available=media.capabilities.metadata_available,
        )
        return ResolvedMedia(
            media,
            str(path),
            canonical_uri(MediaSource.LOCAL, str(path)),
            capabilities,
            metadata={"size": stat.st_size, "mtime_ns": stat.st_mtime_ns},
        )


class HttpResolver(BaseResolver):
    def __init__(self, session: requests.Session | None = None, timeout: tuple[float, float] = (5, 20)) -> None:
        self.session = session or requests.Session()
        self.session.max_redirects = 5
        self.timeout = timeout

    @staticmethod
    def _validate(media: MediaRef) -> str:
        parsed = urlparse(media.original_uri)
        if parsed.scheme.casefold() not in ALLOWED_SCHEMES or not parsed.hostname:
            raise MediaFailure(
                FailureCode.UNSUPPORTED_PROTOCOL,
                media.source,
                f"Unsupported or invalid media protocol: {parsed.scheme or '[missing]'}",
            )
        if parsed.username or parsed.password:
            raise MediaFailure(FailureCode.AUTH_REQUIRED, media.source, "Credentials embedded in media URLs are not accepted")
        return media.original_uri

    def resolve(self, media: MediaRef, *, force: bool = False) -> ResolvedMedia:
        del force
        url = self._validate(media)
        capabilities = MediaCapabilities(
            finite=media.capabilities.finite,
            live=media.capabilities.live,
            seekable=False,
            fingerprintable=True,
            downloadable=media.source != MediaSource.RADIO,
            metadata_available=media.capabilities.metadata_available,
        )
        resolved = ResolvedMedia(media, url, canonical_uri(media.source, url), capabilities, endpoints=[url])
        if reference := media.resolver_data.get("credential_ref"):
            resolved.metadata["credential_ref"] = str(reference)
            resolved.metadata["credential_username"] = str(
                media.resolver_data.get("credential_username") or "source"
            )
            return resolved
        try:
            return self.probe(resolved)
        except MediaFailure as error:
            if not error.retryable:
                raise
            resolved.metadata["probe_warning"] = str(error)
            return resolved

    def probe(self, resolved: ResolvedMedia) -> ResolvedMedia:
        request_headers = {"User-Agent": "Mariana/0.7", "Icy-MetaData": "1"}
        try:
            response = self.session.head(
                resolved.playback_uri,
                allow_redirects=True,
                timeout=self.timeout,
                headers=request_headers,
            )
            if response.status_code in {405, 501}:
                response = self.session.get(
                    resolved.playback_uri,
                    allow_redirects=True,
                    timeout=self.timeout,
                    headers={**request_headers, "Range": "bytes=0-0"},
                    stream=True,
                )
            response.raise_for_status()
        except requests.RequestException as error:
            raise self.classify_failure(error, resolved.media) from error
        resolved.playback_uri = response.url
        content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        accepts_ranges = response.headers.get("accept-ranges", "").casefold() == "bytes" or response.status_code == 206
        playlist_live = content_type in {"audio/x-mpegurl", "application/vnd.apple.mpegurl"}
        icy = bool(response.headers.get("icy-name") or response.headers.get("icy-metaint"))
        known_length = response.headers.get("content-length") not in {None, "", "0"}
        live = resolved.media.source == MediaSource.RADIO or icy or (playlist_live and resolved.media.capabilities.live)
        resolved.capabilities = MediaCapabilities(
            finite=not live,
            live=live,
            seekable=not live and (accepts_ranges or playlist_live),
            fingerprintable=True,
            downloadable=not live,
            metadata_available=icy or resolved.media.capabilities.metadata_available,
        )
        icy_metadata: dict[str, Any] = {
            name.removeprefix("icy-"): response.headers.get(f"icy-{name}")
            for name in ("name", "genre", "url", "br", "metaint")
            if response.headers.get(f"icy-{name}") is not None
        }
        if "br" in icy_metadata:
            with suppress(ValueError):
                icy_metadata["bitrate_kbps"] = int(str(icy_metadata["br"]))
        if "metaint" in icy_metadata:
            with suppress(ValueError):
                icy_metadata["metadata_interval"] = int(str(icy_metadata["metaint"]))
        resolved.metadata.update({
            "content_type": content_type,
            "content_length_known": known_length,
            "accepts_ranges": accepts_ranges,
            "icy": icy_metadata,
        })
        return resolved


class YouTubeResolver(BaseResolver):
    def __init__(self, browser_profile: str | None = None) -> None:
        self.browser_profile = browser_profile or None

    def resolve(self, media: MediaRef, *, force: bool = False) -> ResolvedMedia:
        del force
        from beta.youtube_media import resolve_stream

        try:
            payload = resolve_stream(media.original_uri, audio_only=True, browser_profile=self.browser_profile)
        except Exception as error:
            raise self.classify_failure(error, media) from error
        return ResolvedMedia(
            media,
            payload["url"],
            canonical_uri(MediaSource.YOUTUBE, media.original_uri),
            MediaCapabilities(
                finite=not payload.get("is_live", False),
                live=bool(payload.get("is_live")),
                seekable=not payload.get("is_live", False),
                fingerprintable=True,
                downloadable=not payload.get("is_live", False),
                metadata_available=True,
            ),
            headers=dict(payload.get("http_headers") or {}),
            expires_at=payload.get("expires_at"),
            metadata={key: payload.get(key) for key in ("title", "artist", "album", "duration")},
        )

    def classify_failure(self, error: BaseException, media: MediaRef) -> MediaFailure:
        text = str(error).casefold()
        if "drm" in text:
            return MediaFailure(FailureCode.DRM, media.source, "DRM-protected media is not supported", cause=error)
        if "geo" in text or "country" in text:
            return MediaFailure(FailureCode.GEO_BLOCKED, media.source, "This media is unavailable in the current region", cause=error)
        if any(
            marker in text
            for marker in (
                "sign in",
                "login",
                "private",
                "age",
                "not a bot",
                "cookies-from-browser",
                "requires authorization",
                "requires a signed-in",
            )
        ):
            from beta.youtube_media import youtube_error_message

            message = youtube_error_message(error, self.browser_profile) or "This YouTube media requires authorization"
            return MediaFailure(FailureCode.AUTH_REQUIRED, media.source, message, cause=error)
        if "429" in text or "rate" in text:
            return MediaFailure(FailureCode.RATE_LIMITED, media.source, "YouTube rate-limited Mariana", retryable=True, cause=error)
        return super().classify_failure(error, media)


class DelegatingResolver(BaseResolver):
    def __init__(self, registry: ResolverRegistry) -> None:
        self.registry = registry

    def resolve(self, media: MediaRef, *, force: bool = False) -> ResolvedMedia:
        underlying = media.resolver_data.get("underlying_source")
        if underlying:
            source = MediaSource(str(underlying))
        elif "youtube.com" in media.original_uri or "youtu.be" in media.original_uri:
            source = MediaSource.YOUTUBE
        elif Path(media.original_uri).is_file():
            source = MediaSource.LOCAL
        else:
            source = MediaSource.URL
        delegated = MediaRef(
            source,
            media.original_uri,
            title=media.title,
            artist=media.artist,
            album=media.album,
            duration=media.duration,
            stable_id=media.stable_id,
            provenance=media.provenance,
            capabilities=media.capabilities,
        )
        return self.registry.for_source(source).resolve(delegated, force=force)


class ResolverRegistry:
    def __init__(
        self,
        *,
        browser_profile: str | None = None,
        http_session: requests.Session | None = None,
        radio_endpoints: Callable[[MediaRef], list[str]] | None = None,
    ) -> None:
        http = HttpResolver(http_session)
        self._resolvers: dict[MediaSource, SourceResolver] = {
            MediaSource.LOCAL: LocalResolver(),
            MediaSource.URL: http,
            MediaSource.PODCAST: http,
            MediaSource.RADIO: http,
            MediaSource.YOUTUBE: YouTubeResolver(browser_profile),
        }
        self._resolvers[MediaSource.RECOMMENDATION] = DelegatingResolver(self)
        self.radio_endpoints = radio_endpoints

    def set_youtube_browser_profile(self, browser_profile: str | None) -> None:
        """Atomically replace the YouTube resolver for subsequent resolutions."""
        self._resolvers[MediaSource.YOUTUBE] = YouTubeResolver(browser_profile)

    def for_source(self, source: MediaSource) -> SourceResolver:
        try:
            return self._resolvers[source]
        except KeyError as error:
            raise MediaFailure(FailureCode.UNSUPPORTED_PROTOCOL, source, f"Unsupported media source: {source}") from error

    def resolve(self, media: MediaRef, *, force: bool = False) -> ResolvedMedia:
        resolved = self.for_source(media.source).resolve(media, force=force)
        if media.source == MediaSource.RADIO and self.radio_endpoints:
            endpoints = self.radio_endpoints(media)
            if endpoints:
                resolved.endpoints = endpoints
                resolved.playback_uri = endpoints[0]
        return resolved

    def classify_failure(self, error: BaseException, media: MediaRef) -> MediaFailure:
        return self.for_source(media.source).classify_failure(error, media)
