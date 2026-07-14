"""Provider-neutral presence projection and asynchronous coordination."""

from __future__ import annotations

import math
import re
import threading
import time
import unicodedata
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState

_URL = re.compile(r"(?:[a-z][a-z0-9+.-]*://|www\.)", re.IGNORECASE)
_ABSOLUTE_PATH = re.compile(r"^(?:[a-z]:[\\/]|\\\\|/|~[\\/])", re.IGNORECASE)
_ACTIVE_STATES = {
    PlaybackState.RESOLVING,
    PlaybackState.BUFFERING,
    PlaybackState.PLAYING,
    PlaybackState.PAUSED,
    PlaybackState.SEEKING,
    PlaybackState.CROSSFADING,
}
_UNSET = object()


class PresencePrivacyMode(StrEnum):
    OFF = "off"
    APP = "app"
    TRACK = "track"
    SESSION = "session"


@dataclass(frozen=True, slots=True)
class PresenceProjection:
    """Sanitized activity data which is safe to hand to a presence provider."""

    details: str
    state: str | None = None
    start_timestamp: int | None = None
    end_timestamp: int | None = None
    activity_type: str = "listening"

    def __post_init__(self) -> None:
        if len(self.details) < 2 or sanitize_presence_text(self.details) != self.details:
            raise ValueError("presence details must be sanitized text between 2 and 128 characters")
        if self.state is not None and (len(self.state) < 2 or sanitize_presence_text(self.state) != self.state):
            raise ValueError("presence state must be sanitized text between 2 and 128 characters")
        if self.activity_type != "listening":
            raise ValueError("only listening presence is supported")
        if self.start_timestamp is not None and self.start_timestamp < 0:
            raise ValueError("presence start timestamp cannot be negative")
        if self.end_timestamp is not None and self.end_timestamp < 0:
            raise ValueError("presence end timestamp cannot be negative")
        if (
            self.start_timestamp is not None
            and self.end_timestamp is not None
            and self.end_timestamp < self.start_timestamp
        ):
            raise ValueError("presence end timestamp cannot precede its start")


class PresencePublisher(Protocol):
    def publish(self, projection: PresenceProjection) -> None: ...

    def clear(self, *, disconnect: bool = False) -> None: ...

    def refresh(self) -> None: ...

    def close(self, timeout: float = 1.0) -> None: ...


def sanitize_presence_text(value: object, *, maximum: int = 128) -> str | None:
    """Return compact display text, rejecting URLs and absolute/path-like values."""

    if not isinstance(value, str):
        return None
    cleaned = "".join(character for character in value if not unicodedata.category(character).startswith("C"))
    cleaned = " ".join(cleaned.split()).strip()
    if not cleaned or _URL.search(cleaned) or _ABSOLUTE_PATH.search(cleaned) or cleaned.casefold().startswith("file:"):
        return None
    if len(cleaned) > maximum:
        cleaned = cleaned[: maximum - 1].rstrip() + "…"
    return cleaned or None


def _safe_media_metadata(media: MediaRef) -> tuple[str, str | None, str | None, str]:
    source_labels = {
        MediaSource.LOCAL: "Local audio",
        MediaSource.YOUTUBE: "YouTube music",
        MediaSource.URL: "Online media",
        MediaSource.PODCAST: "Podcast",
        MediaSource.RADIO: "Internet radio",
        MediaSource.RECOMMENDATION: "Recommended music",
    }
    fallback = source_labels.get(media.source, "Media")
    # Direct local references normally have names derived from their paths. Only
    # metadata that came through the indexed library is eligible for presence.
    metadata_allowed = media.source != MediaSource.LOCAL or media.provenance.startswith("library")
    forbidden = {
        value.casefold()
        for value in (
            media.resolver_data.get("id"),
            media.resolver_data.get("video_id"),
            media.resolver_data.get("youtube_id"),
        )
        if isinstance(value, str) and len(value) >= 6
    }
    if media.source == MediaSource.YOUTUBE:
        parsed = urlparse(media.original_uri)
        video_id = parsed.path.strip("/") if parsed.netloc.casefold() == "youtu.be" else parse_qs(parsed.query).get("v", [None])[0]
        if isinstance(video_id, str) and len(video_id) >= 6:
            forbidden.add(video_id.casefold())

    def safe(value: object) -> str | None:
        cleaned = sanitize_presence_text(value)
        if cleaned and any(fragment in cleaned.casefold() for fragment in forbidden):
            return None
        return cleaned

    title = safe(media.title) if metadata_allowed else None
    artist = safe(media.artist) if metadata_allowed else None
    album = safe(media.album) if metadata_allowed else None
    title = title if title and len(title) >= 2 else None
    return title or fallback, artist, album, fallback


def project_presence(
    snapshot: PlaybackSnapshot,
    mode: PresencePrivacyMode | str,
    *,
    now: float | None = None,
) -> PresenceProjection | None:
    """Project one snapshot into the selected privacy mode without retaining it."""

    privacy = PresencePrivacyMode(mode)
    if privacy == PresencePrivacyMode.OFF:
        return None
    if privacy == PresencePrivacyMode.APP:
        return PresenceProjection("Using Mariana")
    if snapshot.state not in _ACTIVE_STATES or snapshot.media is None:
        return None

    title, artist, album, source_label = _safe_media_metadata(snapshot.media)
    if snapshot.media.source == MediaSource.RADIO:
        stream_title = sanitize_presence_text(snapshot.stream_title)
        title = stream_title if stream_title and len(stream_title) >= 2 else title
    paused = snapshot.state == PlaybackState.PAUSED
    if privacy == PresencePrivacyMode.TRACK:
        state_parts = ["Paused"] if paused else []
        if artist:
            state_parts.append(f"by {artist}")
        return PresenceProjection(title, " · ".join(state_parts) or None)

    state_parts = ["Paused"] if paused else []
    if artist:
        state_parts.append(f"by {artist}")
    if album:
        state_parts.append(f"on {album}")
    state_parts.append(source_label)
    start_timestamp = None
    end_timestamp = None
    duration = snapshot.duration
    if (
        not paused
        and snapshot.state in {PlaybackState.PLAYING, PlaybackState.SEEKING, PlaybackState.CROSSFADING}
        and duration is not None
        and math.isfinite(duration)
        and duration > 0
    ):
        wall_time = time.time() if now is None else now
        position = min(max(snapshot.position, 0.0), duration)
        start_timestamp = int(wall_time - position)
        end_timestamp = int(start_timestamp + duration)
    return PresenceProjection(
        title,
        sanitize_presence_text(" · ".join(state_parts)),
        start_timestamp,
        end_timestamp,
    )


class PresenceCoordinator:
    """Poll snapshots outside the audio callback and publish latest-only state."""

    def __init__(
        self,
        snapshot_provider: Callable[[], PlaybackSnapshot],
        publisher: PresencePublisher,
        *,
        mode: PresencePrivacyMode | str = PresencePrivacyMode.OFF,
        poll_seconds: float = 1.0,
    ) -> None:
        self._snapshot_provider = snapshot_provider
        self._publisher = publisher
        self._mode = PresencePrivacyMode(mode)
        self._poll_seconds = max(0.1, poll_seconds)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_projection: PresenceProjection | None | object = _UNSET

    @property
    def mode(self) -> PresencePrivacyMode:
        with self._lock:
            return self._mode

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="mariana-presence", daemon=True)
            self._thread.start()

    def set_mode(self, mode: PresencePrivacyMode | str) -> PresencePrivacyMode:
        selected = PresencePrivacyMode(mode)
        with self._lock:
            self._mode = selected
            self._last_projection = _UNSET
        if selected == PresencePrivacyMode.OFF:
            self._publisher.clear(disconnect=True)
        self._wake.set()
        return selected

    def refresh(self) -> None:
        with self._lock:
            self._last_projection = _UNSET
        self._publisher.refresh()
        self._wake.set()

    def _publish_current(self) -> None:
        mode = self.mode
        projection = project_presence(self._snapshot_provider(), mode)
        with self._lock:
            if projection == self._last_projection:
                return
            self._last_projection = projection
        if projection is None:
            self._publisher.clear(disconnect=mode == PresencePrivacyMode.OFF)
        else:
            self._publisher.publish(projection)

    def _run(self) -> None:
        while not self._stop.is_set():
            with suppress(Exception):
                self._publish_current()
            self._wake.wait(self._poll_seconds)
            self._wake.clear()

    def close(self, timeout: float = 1.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(max(0.0, min(timeout, 1.0)))
        self._publisher.close(timeout=max(0.0, min(timeout, 1.0)))
