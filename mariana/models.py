"""Shared, serializable contracts for the Mariana media platform."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def canonical_uri(source: "MediaSource", value: str) -> str:
    value = value.strip()
    if source == MediaSource.LOCAL:
        return str(Path(value).expanduser().resolve()).casefold()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        host = parsed.netloc.casefold()
        query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"}
        ]
        if host in {"youtu.be", "www.youtube.com", "youtube.com", "m.youtube.com"}:
            video_id = parsed.path.strip("/") if host == "youtu.be" else dict(query).get("v")
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
        return urlunparse((parsed.scheme.casefold(), host, parsed.path, "", urlencode(query), ""))
    return value


class PlaybackState(StrEnum):
    IDLE = "idle"
    RESOLVING = "resolving"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    SEEKING = "seeking"
    CROSSFADING = "crossfading"
    FAILED = "failed"
    STOPPING = "stopping"


class MediaSource(StrEnum):
    LOCAL = "local"
    YOUTUBE = "youtube"
    URL = "url"
    PODCAST = "podcast"
    RADIO = "radio"
    RECOMMENDATION = "recommendation"


class IdentityStatus(StrEnum):
    IDENTIFIED = "identified"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"
    NO_LYRICS = "no_lyrics"
    INSUFFICIENT_AUDIO = "insufficient_audio"
    OFFLINE = "offline"
    UNAVAILABLE = "unavailable"


@dataclass(slots=True)
class MediaCapabilities:
    finite: bool = True
    live: bool = False
    seekable: bool = True
    fingerprintable: bool = True
    downloadable: bool = True
    metadata_available: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, value: str | None) -> "MediaCapabilities":
        return cls(**(json.loads(value) if value else {}))


@dataclass(slots=True)
class MediaRef:
    source: MediaSource
    original_uri: str
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None
    stable_id: str | None = None
    resolver_data: dict[str, Any] = field(default_factory=dict)
    provenance: str = "user"
    capabilities: MediaCapabilities = field(default_factory=MediaCapabilities)

    def __post_init__(self) -> None:
        if not self.stable_id:
            canonical = f"{self.source.value}\0{canonical_uri(self.source, self.original_uri)}"
            self.stable_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["source"] = self.source.value
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MediaRef":
        data = dict(value)
        data["source"] = MediaSource(data["source"])
        capabilities = data.get("capabilities")
        if isinstance(capabilities, dict):
            data["capabilities"] = MediaCapabilities(**capabilities)
        return cls(**data)


@dataclass(frozen=True, slots=True)
class PlaybackSnapshot:
    state: PlaybackState
    position: float = 0.0
    duration: float | None = None
    buffered_seconds: float = 0.0
    volume: float = 1.0
    muted: bool = False
    error: str | None = None
    media: MediaRef | None = None
    replaygain_db: float = 0.0
    live_leveling: bool = False


@dataclass(slots=True)
class TrackIdentity:
    status: IdentityStatus
    acoustid: str | None = None
    recording_mbid: str | None = None
    work_mbid: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None
    confidence: float = 0.0
    provenance: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["status"] = self.status.value
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TrackIdentity":
        data = dict(value)
        data["status"] = IdentityStatus(data["status"])
        return cls(**data)


@dataclass(slots=True)
class LyricsResult:
    status: IdentityStatus
    plain: str | None = None
    synced: str | None = None
    provider: str | None = None
    provider_id: str | None = None
    retrieved_at: float | None = None
    attribution: str | None = None
    identity_confidence: float = 0.0


@dataclass(slots=True)
class QueueItem:
    media: MediaRef
    queue_id: int | None = None
    position: int = 0
    priority: int = 0
    added_at: float = 0.0
    attempts: int = 0
    failure_policy: str = "skip"

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["media"] = self.media.to_dict()
        return result
