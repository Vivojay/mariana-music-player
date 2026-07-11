"""Small yt-dlp adapter used by Mariana's YouTube features."""

from __future__ import annotations

from collections.abc import Mapping
import shutil
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


class YouTubeError(RuntimeError):
    """Raised when yt-dlp cannot resolve a requested YouTube resource."""


def integration_options() -> dict[str, Any]:
    options: dict[str, Any] = {
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 3,
    }
    for runtime, executable in (("deno", "deno"), ("node", "node"), ("quickjs", "qjs")):
        if runtime_path := shutil.which(executable):
            options["js_runtimes"] = {runtime: {"path": runtime_path}}
            break
    return options


def _options(**overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    options.update(integration_options())
    options.update(overrides)
    return options


def _extract(query: str, **options: Any) -> Mapping[str, Any]:
    try:
        with YoutubeDL(_options(**options)) as ydl:
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


def search(query: str, limit: int = 1) -> list[dict[str, Any]]:
    if not query.strip() or limit < 1:
        return []
    result = _extract(
        f"ytsearch{limit}:{query}",
        extract_flat="in_playlist",
        playlistend=limit,
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


def media_info(url: str, detailed: bool = False) -> dict[str, Any]:
    info = _extract(url)
    normalized: dict[str, Any] = {
        "title": info.get("title") or "[Untitled YouTube media]",
        "duration": info.get("duration"),
        "streams": {
            "bestaudurl": stream_url(url, audio_only=True),
            "bestvidurl": stream_url(url, audio_only=False),
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
            }
        )
    return normalized


def stream_url(url: str, *, audio_only: bool = True) -> str:
    format_selector = "bestaudio/best" if audio_only else "best[acodec!=none][vcodec!=none]/best"
    info = _extract(url, format=format_selector)
    direct_url = info.get("url")
    if not direct_url:
        requested = info.get("requested_formats") or []
        candidates = [item.get("url") for item in requested if isinstance(item, Mapping)]
        direct_url = next((candidate for candidate in candidates if candidate), None)
    if not direct_url:
        raise YouTubeError("yt-dlp could not resolve a playable stream URL")
    return str(direct_url)


def is_resolvable(url: str) -> bool:
    try:
        _extract(url)
    except YouTubeError:
        return False
    return True
