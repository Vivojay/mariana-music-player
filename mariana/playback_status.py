"""Safe, presentation-neutral projection of authoritative playback state."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any

from .models import MediaSource, PlaybackSnapshot, PlaybackState

SCHEMA_VERSION = 4
MAX_ERROR_LENGTH = 160
_GENERIC_ERROR = "Playback failed; see logs for details"
_SPACE_PATTERN = re.compile(r"\s+")
_URL_PATTERN = re.compile(r"(?i)(?:https?|ftp)://\S+|\bwww\.\S+")
_WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?:\b[a-z]:[\\/]|\\\\)[^\s]*")
_POSIX_PATH_PATTERN = re.compile(r"/(?:home|users|var|tmp|private|etc|opt)/[^\s]*", re.IGNORECASE)
_SECRET_PATTERN = re.compile(
    r"(?i)\b(?:authorization|cookie|password|token|secret|browser[_ -]?profile)\b\s*[:=]"
)
_COMMAND_PATTERN = re.compile(r"(?i)\b(?:ffmpeg|ffprobe|ffplay|yt-dlp)(?:\.exe)?\b.*(?:^|\s)-[a-z]")


@dataclass(frozen=True, slots=True)
class PlaybackChapterProjection:
    title: str
    start_time: float
    end_time: float
    index: int | None = None
    count: int | None = None


@dataclass(frozen=True, slots=True)
class FavoriteStatusProjection:
    """Sanitized preference state for the current playback item."""

    available: bool
    is_favorite: bool
    toggle_enabled: bool
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PlaybackStatusProjection:
    schema_version: int
    state: str
    display_state: str
    media_id: str | None
    title: str | None
    artist: str | None
    source: str | None
    position_seconds: float
    duration_seconds: float | None
    percent: float | None
    buffered_seconds: float
    finite: bool
    live: bool
    seekable: bool
    library_index: int | None
    queue_position: int | None
    queue_count: int
    favorite: FavoriteStatusProjection
    chapter: PlaybackChapterProjection | None
    replaygain_db: float
    live_leveling: bool
    safe_error: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe payload for local presentation surfaces."""
        return asdict(self)


_DISPLAY_STATES = {
    PlaybackState.RESOLVING: "Resolving",
    PlaybackState.BUFFERING: "Buffering",
    PlaybackState.PLAYING: "Playing",
    PlaybackState.PAUSED: "Paused",
    PlaybackState.SEEKING: "Seeking",
    PlaybackState.CROSSFADING: "Crossfading",
    PlaybackState.FAILED: "Failed",
    PlaybackState.STOPPING: "Stopping",
}

_SOURCE_FALLBACKS = {
    MediaSource.LOCAL: "Local media",
    MediaSource.YOUTUBE: "YouTube media",
    MediaSource.URL: "Online media",
    MediaSource.PODCAST: "Podcast episode",
    MediaSource.RADIO: "Live stream",
    MediaSource.RECOMMENDATION: "Recommended media",
}


def _indexed_local_display_title(media: object) -> object | None:
    """Return the dedicated local-library label, never arbitrary resolver data."""
    if getattr(media, "source", None) != MediaSource.LOCAL:
        return None
    if getattr(media, "provenance", "") != "library":
        return None
    resolver_data = getattr(media, "resolver_data", None)
    if not isinstance(resolver_data, dict):
        return None
    return resolver_data.get("library_display_title")


def _finite_nonnegative(value: object, *, default: float = 0.0) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return max(0.0, number) if math.isfinite(number) else default


def _finite_number(value: object, *, default: float = 0.0) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return default
    return number if math.isfinite(number) else default


def _positive_finite(value: object) -> float | None:
    number = _finite_nonnegative(value, default=-1.0)
    return number if number > 0 else None


def _contains_private_reference(value: str) -> bool:
    return bool(
        _URL_PATTERN.search(value)
        or _WINDOWS_PATH_PATTERN.search(value)
        or _POSIX_PATH_PATTERN.search(value)
        or _SECRET_PATTERN.search(value)
    )


def _clean_display_text(value: object, *, maximum: int) -> str | None:
    if value is None:
        return None
    text = _SPACE_PATTERN.sub(" ", str(value)).strip()
    if not text or _contains_private_reference(text):
        return None
    return text if len(text) <= maximum else f"{text[: maximum - 1].rstrip()}…"


def _safe_error(value: object) -> str | None:
    text = _clean_display_text(value, maximum=MAX_ERROR_LENGTH)
    if text is None:
        return _GENERIC_ERROR if value else None
    if _COMMAND_PATTERN.search(text):
        return _GENERIC_ERROR
    return text


def _display_state(snapshot: PlaybackSnapshot, position: float, duration: float | None) -> str:
    if snapshot.state != PlaybackState.IDLE:
        return _DISPLAY_STATES[snapshot.state]
    completed = snapshot.media is not None and (
        position > 0 or (duration is not None and position >= max(0.0, duration - 0.25))
    )
    return "Finished" if completed else "Stopped"


def _chapter(snapshot: PlaybackSnapshot) -> PlaybackChapterProjection | None:
    chapter = snapshot.current_chapter
    if chapter is None:
        return None
    title = _clean_display_text(chapter.title, maximum=160)
    start = _finite_nonnegative(chapter.start_time)
    end = _finite_nonnegative(chapter.end_time)
    if title is None or end <= start:
        return None
    index = count = None
    if snapshot.media and snapshot.media.chapters:
        count = len(snapshot.media.chapters)
        try:
            index = snapshot.media.chapters.index(chapter) + 1
        except ValueError:
            count = None
    return PlaybackChapterProjection(title, start, end, index, count)


def project_playback_status(
    snapshot: PlaybackSnapshot,
    *,
    library_index: int | None = None,
    queue_position: int | None = None,
    queue_count: int = 0,
    favorite: FavoriteStatusProjection | None = None,
) -> PlaybackStatusProjection:
    """Build a safe status projection without resolving or mutating media."""
    media = snapshot.media
    favorite_status = favorite or FavoriteStatusProjection(
        available=False,
        is_favorite=False,
        toggle_enabled=False,
        unavailable_reason="Favourite state unavailable",
    )
    if media is None:
        favorite_status = FavoriteStatusProjection(
            available=False,
            is_favorite=False,
            toggle_enabled=False,
            unavailable_reason="No active media",
        )
    capabilities = media.capabilities if media else None
    finite = bool(capabilities and capabilities.finite)
    live = bool(capabilities and capabilities.live)
    seekable = bool(capabilities and capabilities.seekable and not live)
    position = _finite_nonnegative(snapshot.position)
    duration = _positive_finite(snapshot.duration) if finite and not live else None
    percent = min(100.0, max(0.0, position / duration * 100.0)) if duration else None
    count = max(0, int(queue_count))
    normalized_queue_position = (
        int(queue_position)
        if media is not None
        and queue_position is not None
        and 1 <= int(queue_position) <= count
        else None
    )
    normalized_library_index = (
        int(library_index)
        if media is not None
        and media.source == MediaSource.LOCAL
        and media.provenance == "library"
        and library_index is not None
        and int(library_index) > 0
        else None
    )

    title = None
    artist = None
    source = None
    media_id = None
    if media is not None:
        source = media.source.value
        media_id = media.stable_id
        preferred_title = snapshot.stream_title if live else media.title
        title = _clean_display_text(preferred_title, maximum=160)
        if title is None and live:
            title = _clean_display_text(media.title, maximum=160)
        if title is None and not live:
            title = _clean_display_text(_indexed_local_display_title(media), maximum=160)
        title = title or _SOURCE_FALLBACKS[media.source]
        artist = _clean_display_text(media.artist, maximum=120)

    return PlaybackStatusProjection(
        schema_version=SCHEMA_VERSION,
        state=snapshot.state.value,
        display_state=_display_state(snapshot, position, duration),
        media_id=media_id,
        title=title,
        artist=artist,
        source=source,
        position_seconds=position,
        duration_seconds=duration,
        percent=percent,
        buffered_seconds=_finite_nonnegative(snapshot.buffered_seconds),
        finite=finite,
        live=live,
        seekable=seekable,
        library_index=normalized_library_index,
        queue_position=normalized_queue_position,
        queue_count=count,
        favorite=favorite_status,
        chapter=_chapter(snapshot),
        replaygain_db=_finite_number(snapshot.replaygain_db),
        live_leveling=bool(snapshot.live_leveling),
        safe_error=_safe_error(snapshot.error),
    )
