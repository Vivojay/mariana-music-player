"""Small yt-dlp adapter used by Mariana's YouTube features."""

from __future__ import annotations

import math
import queue
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, cast

from beta import extractor_fallback
from mariana.chapters import normalize_chapters
from mariana.media_details import normalized_provider_metadata
from mariana.models import MediaSource, canonical_uri
from mariana.toolchain import find_javascript_runtime
from mariana.video_sources import VideoTracks


class YouTubeError(RuntimeError):
    """Raised when yt-dlp cannot resolve a requested YouTube resource."""


@lru_cache(maxsize=1)
def _extractor_runtime() -> tuple[type, type[BaseException]]:
    """Load the sizeable extractor runtime only when an online operation needs it."""
    from yt_dlp import YoutubeDL as extractor
    from yt_dlp.utils import DownloadError as extractor_error

    return extractor, extractor_error


def YoutubeDL(*args: Any, **kwargs: Any) -> Any:
    """Construct the extractor lazily while retaining the established test seam."""
    extractor, _error = _extractor_runtime()
    return extractor(*args, **kwargs)


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
            "age-restricted",
            "confirm your age",
            "private video",
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
    _, download_error = _extractor_runtime()
    try:
        with YoutubeDL(cast(Any, _options(**options))) as ydl:
            info = ydl.extract_info(query, download=False)
            if not isinstance(info, Mapping):
                raise YouTubeError("yt-dlp returned an unsupported response")
            return info
    except download_error as exc:
        raise YouTubeError(str(exc)) from exc


# A socket timeout alone cannot bound a provider making several requests, DNS
# or reading the browser profile. A stalled in-process lookup may finish late.
# Keep those workers bounded and discard the results once the caller has left.
_PYTHON_BUDGET = 10.
_LOOKUPS = threading.BoundedSemaphore(4)


def _timed_playback_lookup(url: str, options: dict) -> Mapping[str, Any]:
    if not _LOOKUPS.acquire(blocking=False):
        raise YouTubeError("Other playback lookups are still finishing. Try again shortly.")
    done = queue.Queue(maxsize=1)

    def lookup():
        try:
            done.put((True, _extract(url, **options)))
        except Exception as error:
            done.put((False, error))
        finally:
            _LOOKUPS.release()

    try:
        threading.Thread(target=lookup, name="mariana-playback-resolve", daemon=True).start()
    except RuntimeError:
        _LOOKUPS.release()
        raise
    try:
        ok, result = done.get(timeout=_PYTHON_BUDGET)
    except queue.Empty:
        raise TimeoutError("The playback metadata lookup timed out.") from None
    if not ok:
        raise result
    return result


def _playback_extract(url: str, *, format: str, browser_profile: str | None) -> Mapping[str, Any]:
    options = dict(format=format, browser_profile=browser_profile, socket_timeout=8,
                   retries=0, extractor_retries=0, geo_bypass=False)
    try:
        return _timed_playback_lookup(url, options)
    except (YouTubeError, OSError, ModuleNotFoundError) as error:
        if not extractor_fallback.retryable(error):
            raise
        alternate = extractor_fallback.external_info(url, format, browser_profile)
        if alternate is not None:
            return alternate
        if isinstance(error, ModuleNotFoundError):
            raise YouTubeError("Install yt-dlp in Mariana or configure MARIANA_YTDLP_BINARY. Anonymous public videos may also use MARIANA_YOUTUBE_DL_BINARY.") from error
    # Retry a transient failure once with a new extractor instance. Access and
    # rate limits are handled by the normal account/error flow on the first try.
    return _timed_playback_lookup(url, options)


_picture_hints: OrderedDict[tuple[str, str | None], tuple[float, VideoTracks]] = OrderedDict()
_hint_lock = threading.Lock()


def _picture_key(url: str, profile: str | None) -> tuple[str, str | None] | None:
    identity = canonical_uri(MediaSource.YOUTUBE, url)
    match = re.fullmatch(r"https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})", identity)
    return (match[1], profile) if match else None


def _remember_available_picture(url, profile, info):
    key = _picture_key(url, profile)
    if (key is None or info.get("id") != key[0] or info.get("has_drm") or info.get("is_live")
            or info.get("live_status") in {"is_live", "is_upcoming"}):
        return
    # yt-dlp sorts formats from least to most preferable for this extraction.
    # Keep only the chosen metadata. No video bytes are fetched during audio playback.
    formats = info.get("formats")
    if not isinstance(formats, list):
        return
    for row in reversed(formats):
        if (not isinstance(row, Mapping) or row.get("protocol") != "https" or row.get("has_drm")
                or row.get("ext") not in {"mp4", "webm"} or row.get("acodec") != "none"
                or not str(row.get("vcodec", "")).startswith(("avc1", "av01", "vp9", "vp09"))
                or not str(row.get("url", "")).startswith("https://")):
            continue
        try:
            tracks = replace(_selected_video_tracks(info, [row], native=True), from_audio_selection=True)
        except (TypeError, ValueError, OverflowError):
            return  # Unexpected optional picture metadata cannot block audio.
        with _hint_lock:
            _picture_hints[key] = (time.monotonic() + 120, tracks)
            _picture_hints.move_to_end(key)
            while len(_picture_hints) > 8:
                _picture_hints.popitem(last=False)
        return


def _take_available_picture(url, profile):
    key = _picture_key(url, profile)
    with _hint_lock:
        now = time.monotonic()
        for stale in [entry for entry, (deadline, _) in _picture_hints.items() if deadline <= now]:
            del _picture_hints[stale]
        hint = _picture_hints.pop(key, None) if key else None
    if hint:
        tracks = hint[1]
        if tracks.expires_at is None or tracks.expires_at > time.time() + 30:
            return tracks
    return None


def _webpage_url(entry: Mapping[str, Any]) -> str:
    if entry.get("webpage_url"):
        return str(entry["webpage_url"])
    video_id = entry.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return str(entry.get("url") or "")


def _published_value(info: Mapping[str, Any]) -> str | None:
    """Normalize extractor publication facts without exposing provider URLs."""
    for key in ("release_timestamp", "timestamp"):
        value = info.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            timestamp = float(value)
            if math.isfinite(timestamp) and timestamp >= 0:
                return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        except (OverflowError, OSError, ValueError):
            pass
    for key in ("release_date", "upload_date"):
        raw = info.get(key)
        if type(raw) is int and 10_000_000 <= raw <= 99_999_999:
            value = str(raw)
        elif isinstance(raw, str):
            value = raw.strip()
        else:
            continue
        if len(value) == 8 and value.isdigit():
            try:
                return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
            except ValueError:
                pass
    return None


def provider_metadata(info: Mapping[str, Any]) -> dict[str, str | int]:
    """Return source-aware public facts from an extractor response."""
    return normalized_provider_metadata(
        {
            "provider": info.get("extractor_key") or info.get("extractor"),
            "provider_media_id": info.get("id") or info.get("display_id"),
            "publisher": info.get("channel") or info.get("uploader") or info.get("creator"),
            "publisher_id": info.get("channel_id") or info.get("uploader_id"),
            "published": _published_value(info),
            "views": info.get("view_count"),
            "likes": info.get("like_count"),
            "dislikes": info.get("dislike_count"),
            "comments": info.get("comment_count"),
            "reposts": info.get("repost_count"),
            "followers": info.get("channel_follower_count"),
            "concurrent_viewers": info.get("concurrent_view_count"),
        }
    )


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


def playlist_entries(
    url: str,
    *,
    browser_profile: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return a canonical, metadata-only snapshot of a YouTube playlist."""

    if limit is not None and limit < 1:
        raise YouTubeError("YouTube playlist limit must be positive")
    options: dict[str, Any] = {
        "noplaylist": False,
        "extract_flat": "in_playlist",
        "browser_profile": browser_profile,
    }
    if limit is not None:
        options["playlistend"] = limit
    result = _extract(url, **options)
    entries = []
    for index, entry in enumerate(result.get("entries") or [], 1):
        if not isinstance(entry, Mapping):
            continue
        canonical_url = _webpage_url(entry)
        video_id = str(entry.get("id") or "").strip()
        if not video_id or not canonical_url.startswith(("https://www.youtube.com/", "https://youtu.be/")):
            continue
        entries.append(
            {
                "id": video_id,
                "title": str(entry.get("title") or "[Untitled YouTube media]"),
                "url": canonical_url,
                "duration": entry.get("duration"),
                "artist": entry.get("artist") or entry.get("uploader"),
                "playlist_index": entry.get("playlist_index") or index,
            }
        )
    if not entries:
        raise YouTubeError("The YouTube playlist contains no usable videos")
    return {
        "id": result.get("id"),
        "title": result.get("title") or "Imported YouTube playlist",
        "url": result.get("webpage_url") or url,
        "entries": entries,
    }


def media_info(
    url: str,
    detailed: bool = False,
    *,
    browser_profile: str | None = None,
) -> dict[str, Any]:
    info = _playback_extract(url, format="bestvideo*+bestaudio/best", browser_profile=browser_profile)
    _remember_available_picture(url, browser_profile, info)
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
                "chapters": normalize_chapters(info.get("chapters"), info.get("duration")),
                **provider_metadata(info),
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
    info = _playback_extract(url, format=format_selector, browser_profile=browser_profile)
    _remember_available_picture(url, browser_profile, info)
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
    info = _playback_extract(url, format=format_selector, browser_profile=browser_profile)
    _remember_available_picture(url, browser_profile, info)
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
        "categories": list(info.get("categories") or []),
        "track": info.get("track"),
        "thumbnail": info.get("thumbnail"),
        "chapters": normalize_chapters(info.get("chapters"), info.get("duration")),
        "provider_metadata": provider_metadata(info),
    }


def resolve_video_tracks(
    url: str, *, browser_profile: str | None = None, native: bool = False,
) -> VideoTracks:
    """Select finite HTTP file tracks without collapsing separate audio/video."""
    if native and (hint := _take_available_picture(url, browser_profile)) is not None:
        return hint
    info = _playback_extract(
        url,
        format=(
            'bestvideo[protocol=https][vcodec~="^(avc1|av01|vp0?9)"]'
            if native else
            "bestvideo[height<=720][protocol=https]+bestaudio[protocol=https]/best[height<=720][protocol=https]"
        ),
        browser_profile=browser_profile,
    )
    return _selected_video_tracks(info, info.get("requested_formats") or [info], native=native)


def _selected_video_tracks(info, selected, *, native: bool) -> VideoTracks:
    from mariana.provider_captions import provider_caption_tracks
    from mariana.video_sources import VideoSourceError, VideoTrack

    if info.get("is_live") or info.get("live_status") == "is_live" or info.get("has_drm"):
        raise VideoSourceError("Live or protected video is not supported by this transport")
    rows = [row for row in selected if isinstance(row, Mapping)]
    picture = next((row for row in rows if row.get("vcodec") not in {None, "none"}), None)
    audio = next((row for row in rows if row.get("acodec") not in {None, "none"}), None)
    if picture is None or (not native and audio is None):
        raise VideoSourceError("This source has no supported audiovisual file")

    def track(row: Mapping[str, Any]) -> VideoTrack:
        uri = str(row.get("url") or "")
        if not uri.startswith(("https://", "http://")) or row.get("protocol") not in {None, "http", "https"}:
            raise VideoSourceError("This source requires an unsupported video transport")
        headers = {str(key): str(value) for key, value in (info.get("http_headers") or {}).items()}
        headers.update({str(key): str(value) for key, value in (row.get("http_headers") or {}).items()})
        codec = row.get("vcodec") if row.get("vcodec") not in {None, "none"} else row.get("acodec")
        return VideoTrack(
            uri, headers, str(codec or ""), str(row.get("format_id") or ""),
            str(row.get("ext") or ""),
            int(row["width"]) if isinstance(row.get("width"), (int, float)) else None,
            int(row["height"]) if isinstance(row.get("height"), (int, float)) else None,
            float(row["fps"]) if isinstance(row.get("fps"), (int, float)) else None,
        )

    duration = info.get("duration")
    expiry = info.get("url_expiry") or info.get("expires")
    return VideoTracks(
        track(picture), track(audio) if audio is not None else None,
        float(duration) if isinstance(duration, (int, float)) else None,
        float(expiry) if isinstance(expiry, (int, float)) else None,
        provider_caption_tracks(info),
    )


def is_resolvable(url: str, *, browser_profile: str | None = None) -> bool:
    try:
        info = _playback_extract(url, format="bestaudio/best", browser_profile=browser_profile)
        _remember_available_picture(url, browser_profile, info)
    except (YouTubeError, ValueError, OSError):
        return False
    return True
