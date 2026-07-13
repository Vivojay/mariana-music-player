"""Small yt-dlp adapter used by Mariana's YouTube features."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from mariana.toolchain import find_javascript_runtime


class YouTubeError(RuntimeError):
    """Raised when yt-dlp cannot resolve a requested YouTube resource."""


def youtube_error_message(error: BaseException, browser_profile: str | None = None) -> str | None:
    """Return actionable guidance for recognizable YouTube/TLS failures."""
    detail = str(error).casefold()
    if "certificate_verify_failed" in detail or "self-signed certificate" in detail:
        return (
            "Secure YouTube connection failed because the certificate is not trusted by the operating system. "
            "Install the trusted root certificate and restart Mariana; TLS verification was not disabled."
        )
    if any(
        marker in detail
        for marker in (
            "sign in to confirm",
            "not a bot",
            "cookies-from-browser",
            "login required",
            "requires authorization",
            "requires a signed-in",
            "rejected browser profile",
        )
    ):
        if browser_profile:
            return (
                f'YouTube rejected browser profile "{browser_profile}". Sign in to YouTube in that browser, '
                "close it if its cookie database is locked, then run `youtube auth status` and retry."
            )
        return (
            "YouTube requires a signed-in browser session. Run `youtube auth set firefox` "
            "(recommended) or `youtube auth set edge:Default`, then retry. Mariana stores only the profile "
            "reference, never the cookies."
        )
    if "429" in detail or "rate limit" in detail or "too many requests" in detail:
        return (
            "YouTube temporarily rate-limited this connection. Wait before retrying; if YouTube also asks you "
            "to sign in, configure an explicit browser profile with `youtube auth set`."
        )
    return None


def _browser_profile(value: str | None) -> tuple[str, ...] | None:
    if not value:
        return None
    parts = tuple(part.strip() for part in value.split(":", 1))
    if not parts[0] or any(char in value for char in "\r\n\0"):
        raise YouTubeError("Invalid browser profile reference")
    return parts


def parse_browser_profile(value: str | None) -> tuple[str, ...] | None:
    """Validate a yt-dlp browser/profile reference without reading cookies."""
    return _browser_profile(value)


def integration_options(browser_profile: str | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 3,
    }
    if javascript := find_javascript_runtime():
        runtime, runtime_path = javascript
        options["js_runtimes"] = {runtime: {"path": runtime_path}}
    if profile := _browser_profile(browser_profile):
        options["cookiesfrombrowser"] = profile
    return options


def _options(**overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    browser_profile = overrides.pop("browser_profile", None)
    options.update(integration_options(browser_profile) if browser_profile else integration_options())
    options.update(overrides)
    return options


def _extract(query: str, **options: Any) -> Mapping[str, Any]:
    try:
        with YoutubeDL(cast(Any, _options(**options))) as ydl:
            info = ydl.extract_info(query, download=False)
            if not isinstance(info, Mapping):
                raise YouTubeError("yt-dlp returned an unsupported response")
            return info
    except DownloadError as exc:
        raise YouTubeError(str(exc)) from exc


def _webpage_url(entry: Mapping[str, Any]) -> str:
    if entry.get("webpage_url"):
        return str(entry["webpage_url"])
    video_id = entry.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return str(entry.get("url") or "")


def search(
    query: str,
    limit: int = 1,
    *,
    browser_profile: str | None = None,
) -> list[dict[str, Any]]:
    if not query.strip() or limit < 1:
        return []
    result = _extract(
        f"ytsearch{limit}:{query}",
        extract_flat="in_playlist",
        playlistend=limit,
        browser_profile=browser_profile,
    )
    entries = result.get("entries") or []
    return [
        {
            "id": entry.get("id"),
            "title": entry.get("title") or "[Untitled YouTube result]",
            "url": _webpage_url(entry),
            "duration": entry.get("duration"),
            "thumbnail": entry.get("thumbnail"),
        }
        for entry in entries
        if isinstance(entry, Mapping)
    ]


def media_info(
    url: str,
    detailed: bool = False,
    *,
    browser_profile: str | None = None,
) -> dict[str, Any]:
    info = _extract(url, browser_profile=browser_profile)
    stream_options = {"browser_profile": browser_profile} if browser_profile else {}
    normalized: dict[str, Any] = {
        "title": info.get("title") or "[Untitled YouTube media]",
        "duration": info.get("duration"),
        "streams": {
            "bestaudurl": stream_url(url, audio_only=True, **stream_options),
            "bestvidurl": stream_url(url, audio_only=False, **stream_options),
        },
    }
    if detailed:
        normalized.update(
            {
                "dislikes": info.get("dislike_count"),
                "likes": info.get("like_count"),
                "views": info.get("view_count"),
                "thumbnail": info.get("thumbnail"),
                "formats": list(info.get("formats") or []),
                "artist": info.get("artist") or info.get("uploader"),
                "track": info.get("track"),
                "album": info.get("album"),
                "categories": list(info.get("categories") or []),
                "is_live": bool(info.get("is_live") or info.get("live_status") == "is_live"),
            }
        )
    return normalized


def stream_url(
    url: str,
    *,
    audio_only: bool = True,
    browser_profile: str | None = None,
) -> str:
    format_selector = "bestaudio/best" if audio_only else "best[acodec!=none][vcodec!=none]/best"
    info = _extract(url, format=format_selector, browser_profile=browser_profile)
    direct_url = info.get("url")
    if not direct_url:
        requested = info.get("requested_formats") or []
        candidates = [item.get("url") for item in requested if isinstance(item, Mapping)]
        direct_url = next((candidate for candidate in candidates if candidate), None)
    if not direct_url:
        raise YouTubeError("yt-dlp could not resolve a playable stream URL")
    return str(direct_url)


def resolve_stream(
    url: str,
    *,
    audio_only: bool = True,
    browser_profile: str | None = None,
) -> dict[str, Any]:
    """Return transient stream information without persisting credentials."""
    format_selector = "bestaudio/best" if audio_only else "best[acodec!=none][vcodec!=none]/best"
    info = _extract(url, format=format_selector, browser_profile=browser_profile)
    direct_url = info.get("url")
    if not direct_url:
        requested = info.get("requested_formats") or []
        direct_url = next(
            (item.get("url") for item in requested if isinstance(item, Mapping) and item.get("url")),
            None,
        )
    if not direct_url:
        raise YouTubeError("yt-dlp could not resolve a playable stream URL")
    expires_at = None
    expiry = info.get("url_expiry") or info.get("expires")
    if isinstance(expiry, (int, float)) or (isinstance(expiry, str) and expiry.isdigit()):
        expires_at = float(expiry)
    if expires_at and expires_at < 10_000_000_000:
        expires_at = datetime.fromtimestamp(expires_at, tz=UTC).timestamp()
    return {
        "url": str(direct_url),
        "http_headers": {
            str(key): str(value)
            for key, value in (info.get("http_headers") or {}).items()
            if value is not None
        },
        "expires_at": expires_at,
        "is_live": bool(info.get("is_live") or info.get("live_status") == "is_live"),
        "title": info.get("title"),
        "artist": info.get("artist") or info.get("uploader"),
        "album": info.get("album"),
        "duration": info.get("duration"),
    }


def is_resolvable(url: str, *, browser_profile: str | None = None) -> bool:
    try:
        _extract(url, browser_profile=browser_profile)
    except YouTubeError:
        return False
    return True
