"""Explicit-request, session-bound lyrics presentation on the source playback clock.

The resolver is the existing IdentificationService.lyrics boundary: local/embedded
lyrics precede its cache and provider lookup. Merely observing playback never
performs I/O or discloses metadata. One daemon worker and one replaceable pending
request bound work even when the source or user intent changes rapidly.
"""

from __future__ import annotations

import contextlib
import math
import re
import threading
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Protocol

from .lyrics_timeline import (
    MAX_SYNCED_LYRICS_CHARACTERS,
    LyricsTimeline,
    TimedLyricLine,
    timeline_from_result,
    validate_user_offset,
)
from .models import IdentityStatus, LyricsResult, MediaRef, PlaybackSnapshot, PlaybackState, TrackIdentity

MAX_PLAIN_CHARACTERS = 64_000
MAX_LINE_CHARACTERS = 2_000
SOURCE_SAMPLE_INTERVAL_SECONDS = 0.1
_MEDIA_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PRIVATE_REFERENCE = re.compile(r"https?://|file:|[A-Za-z]:[\\/]|/(?:home|Users|tmp)/|\\\\", re.IGNORECASE)
_UNSAFE_TEXT = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")


class LyricsResolver(Protocol):
    def lyrics(self, media: MediaRef, identity: TrackIdentity, refresh: bool = False) -> LyricsResult: ...


@dataclass(frozen=True, slots=True)
class _Request:
    generation: int
    media: MediaRef
    identity: TrackIdentity
    refresh: bool


def _text(value: object, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    return _UNSAFE_TEXT.sub("", value[:maximum]).replace("\r\n", "\n").strip() or None


def _source(result: LyricsResult) -> tuple[str | None, str | None]:
    provider = _text(result.provider, 80)
    if provider and (_PRIVATE_REFERENCE.search(provider) or "\n" in provider or "\t" in provider):
        provider = None
    if provider == "local-sidecar":
        return provider, "Lyrics from the local LRC sidecar"
    if provider == "embedded":
        return provider, "Lyrics from embedded file metadata"
    if provider == "LRCLIB":
        return provider, "Lyrics provided by LRCLIB"
    attribution = _text(result.attribution, 240)
    if attribution and _PRIVATE_REFERENCE.search(attribution):
        attribution = None
    return provider, attribution or (f"Lyrics provided by {provider}" if provider else None)


def _line(line: TimedLyricLine | None) -> dict[str, object] | None:
    return {"start_ms": line.start_ms, "text": _text(line.text, MAX_LINE_CHARACTERS) or ""} if line else None


def _position(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    return max(0.0, min(float(value), 1e9))


def _identity_key(identity: TrackIdentity | None) -> tuple[object, ...] | None:
    if identity is None:
        return None
    return (identity.status, identity.recording_mbid, identity.title, identity.artist, identity.album, identity.duration)


class LyricsPresentationService:
    """Thread-safe, bounded projection; callers own playback and provider lifetime.

    ``on_change`` receives only allowlisted dictionaries, serialized in revision
    order. It should be fast (e.g. enqueue a desktop event). ``session_id`` is an
    internal playback token and is never included in the projection. ``close``
    invalidates work immediately without waiting for an in-flight source/provider
    call; the existing resolver's own timeouts bound its I/O. Optional ``snapshot``
    sampling reuses this worker only while timed lyrics are visible and calls the
    authoritative source outside the lyrics condition.
    """

    def __init__(
        self,
        identification: LyricsResolver,
        *,
        on_change: Callable[[dict[str, object]], None] | None = None,
        snapshot: Callable[[], PlaybackSnapshot] | None = None,
    ):
        self._identification = identification
        self._on_change = on_change
        self._snapshot = snapshot
        self._condition = threading.Condition(threading.RLock())
        self._closed = False
        self._worker: threading.Thread | None = None
        self._pending: _Request | None = None
        self._working = False
        self._generation = 0
        self._observation_revision = 0
        self._session_revision = 0
        self._session_id: object = None
        self._media: MediaRef | None = None
        self._identity: TrackIdentity | None = None
        self._position = 0.0
        self._timeline: LyricsTimeline | None = None
        self._plain: str | None = None
        self._provider: str | None = None
        self._attribution: str | None = None
        self._state = "idle"
        self._reason: str | None = "Request lyrics for the current media"
        self._visible = False
        self._offset = 0
        self._revision = 0
        self._last: dict[str, object] | None = None

    def update_playback(
        self,
        snapshot: PlaybackSnapshot,
        *,
        session_id: object = None,
        identity: TrackIdentity | None = None,
    ) -> dict[str, object]:
        """Consume an authoritative source snapshot without starting any lookup.

        Pass the source playback-session token to distinguish repeat plays of the
        same media. Supplying changed track identity also invalidates old lyrics.
        Pauses and seeks only reselect the cursor; neither starts new work.
        """
        with self._condition:
            if self._closed:
                return self._project_locked()
            self._observation_revision += 1
            if session_id is None:
                session_id = getattr(snapshot, "session_id", None)
            media = snapshot.media if snapshot.state not in {PlaybackState.IDLE, PlaybackState.STOPPING} else None
            old_id = self._media.stable_id if self._media else None
            new_id = media.stable_id if media else None
            changed = old_id != new_id or session_id != self._session_id
            if not changed and identity is not None:
                changed = _identity_key(identity) != _identity_key(self._identity)
            if changed:
                self._invalidate_locked()
                self._session_revision += 1
                self._offset = 0
                self._identity = deepcopy(identity)
            elif identity is not None:
                self._identity = deepcopy(identity)
            self._media = media
            self._session_id = session_id
            self._position = _position(snapshot.position)
            if media is None:
                self._reason = "No media is active"
            self._condition.notify_all()
            return self._emit_locked()

    def request(
        self,
        *,
        media_id: str,
        refresh: bool = False,
        identity: TrackIdentity | None = None,
    ) -> dict[str, object]:
        """Explicitly show/load lyrics through the existing resolver, asynchronously.

        Optional identity should come from the application's existing identity
        cache. Without it, use the current media's declared metadata; there is no
        automatic fingerprinting or inference from private filenames/URLs.
        """
        with self._condition:
            self._require_current_locked(media_id)
            if not isinstance(refresh, bool):
                raise ValueError("Lyrics refresh must be a boolean")
            identity_changed = identity is not None and _identity_key(identity) != _identity_key(self._identity)
            if identity_changed:
                self._invalidate_locked()
                self._session_revision += 1
                self._offset = 0
                self._identity = deepcopy(identity)
            self._visible = True
            if not refresh and self._state in {"loading", "timed", "plain"}:
                self._condition.notify_all()
                return self._emit_locked()
            self._generation += 1
            media = self._media
            assert media is not None
            # Copy only resolver input fields: large/private resolver_data is not
            # needed by IdentificationService.lyrics and must not be retained.
            request_media = replace(media, resolver_data={}, chapters=[], capabilities=replace(media.capabilities))
            request_identity = deepcopy(self._identity) if self._identity else TrackIdentity(
                IdentityStatus.IDENTIFIED if media.title and media.artist else IdentityStatus.NO_MATCH,
                title=media.title,
                artist=media.artist,
                album=media.album,
                duration=media.duration,
            )
            self._pending = _Request(self._generation, request_media, request_identity, refresh)
            self._clear_result_locked()
            self._state = "loading"
            self._reason = "Loading lyrics; local and cached results are preferred"
            projection = self._emit_locked()
            if self._worker is None:
                self._worker = threading.Thread(target=self._run, name="mariana-lyrics", daemon=True)
                self._worker.start()
            self._condition.notify_all()
            return projection

    def set_offset(self, media_id: str, offset_ms: int) -> dict[str, object]:
        offset = validate_user_offset(offset_ms)
        with self._condition:
            self._require_current_locked(media_id)
            self._offset = offset
            return self._emit_locked()

    def hide(self) -> dict[str, object]:
        with self._condition:
            self._visible = False
            self._observation_revision += 1
            # Hidden work must not reopen the panel. Drop its ability to publish.
            if self._state == "loading":
                self._invalidate_locked()
            self._condition.notify_all()
            return self._emit_locked()

    def projection(self) -> dict[str, object]:
        with self._condition:
            return deepcopy(self._project_locked())

    def wait_for_idle(self, timeout: float = 1.0) -> bool:
        """Bounded synchronization for tests and non-UI callers, never polling."""
        with self._condition:
            return self._condition.wait_for(lambda: not self._working and self._pending is None, timeout)

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            self._invalidate_locked()
            self._visible = False
            self._reason = "Lyrics service is closed"
            self._condition.notify_all()

    def _require_current_locked(self, media_id: str) -> None:
        if self._closed:
            raise RuntimeError("Lyrics service is closed")
        if not self._media or media_id != self._media.stable_id or not _MEDIA_ID.fullmatch(media_id):
            raise ValueError("Playback changed; request lyrics for the current media")

    def _clear_result_locked(self) -> None:
        self._timeline = None
        self._plain = None
        self._provider = None
        self._attribution = None

    def _invalidate_locked(self) -> None:
        self._generation += 1
        self._pending = None
        self._clear_result_locked()
        self._state = "idle"
        self._reason = "Request lyrics for the current media"

    def _run(self) -> None:
        while True:
            with self._condition:
                observation = None
                while not self._closed and self._pending is None:
                    if not self._can_sample_locked():
                        self._condition.wait()
                        continue
                    notified = self._condition.wait(SOURCE_SAMPLE_INTERVAL_SECONDS)
                    if not notified and self._can_sample_locked() and self._pending is None:
                        observation = (self._generation, self._observation_revision)
                        break
                if self._closed:
                    return
                request = self._pending
                self._pending = None
                self._working = True
            if observation is not None and request is None:
                self._sample_source(observation)
                continue
            assert request is not None
            try:
                result = self._identification.lyrics(request.media, request.identity, refresh=request.refresh)
                if not isinstance(result, LyricsResult):
                    raise ValueError("Malformed lyrics result")
                # Never send an over-sized or incorrectly typed provider payload
                # into the parser. The parser separately bounds cue counts.
                synced = result.synced if isinstance(result.synced, str) else None
                if synced is not None and len(synced) > MAX_SYNCED_LYRICS_CHARACTERS:
                    synced = None
                result = replace(result, synced=synced)
                try:
                    timeline = timeline_from_result(
                        request.media.stable_id, result, duration_seconds=request.media.duration,
                    )
                except (TypeError, ValueError, OverflowError):
                    # For example, a malformed offset can exceed Python's
                    # integer-digit limit before the LRC parser can validate it.
                    timeline = None
                plain = _text(result.plain, MAX_PLAIN_CHARACTERS) if result.status == IdentityStatus.IDENTIFIED else None
                provider, attribution = _source(result)
                state = "timed" if timeline else "plain" if plain else "unavailable"
                reason = None if timeline else (
                    "Synchronized timing is unavailable; showing plain lyrics" if plain else
                    "Lyrics provider is offline; no cached lyrics were available" if result.status == IdentityStatus.OFFLINE else
                    "No usable lyrics are available for this media"
                )
            except Exception:
                timeline, plain, provider, attribution = None, None, None, None
                state, reason = "error", "Lyrics could not be loaded safely"
            with self._condition:
                self._working = False
                if not self._closed and request.generation == self._generation:
                    self._timeline, self._plain = timeline, plain
                    self._provider, self._attribution = provider, attribution
                    self._state, self._reason = state, reason
                    self._emit_locked()
                self._condition.notify_all()

    def _can_sample_locked(self) -> bool:
        return self._snapshot is not None and self._visible and self._state == "timed" and not self._closed

    def _sample_source(self, observation: tuple[int, int]) -> None:
        # Never call the source while holding the lyrics condition. A slow or
        # re-entrant source must not block hide, media updates, or shutdown.
        snapshot_provider = self._snapshot
        sampled = None
        if snapshot_provider is not None:
            with contextlib.suppress(Exception):
                candidate = snapshot_provider()
                if isinstance(candidate, PlaybackSnapshot):
                    sampled = candidate
        with self._condition:
            self._working = False
            if (
                sampled is not None
                and self._can_sample_locked()
                and observation == (self._generation, self._observation_revision)
            ):
                # The revision also protects seeks/pauses supplied by an explicit
                # observer while this source read was in flight. This RLock keeps
                # checking the observation and applying it one atomic operation.
                self.update_playback(sampled)
            self._condition.notify_all()

    def _project_locked(self) -> dict[str, object]:
        media_id = self._media.stable_id if self._media and _MEDIA_ID.fullmatch(self._media.stable_id) else None
        cursor = self._timeline.cursor(self._position, user_offset_ms=self._offset) if self._timeline else None
        return {
            "schema_version": 1,
            "revision": self._revision,
            "session_revision": self._session_revision,
            "media_id": media_id,
            "state": self._state,
            "visible": self._visible,
            "available": self._state in {"timed", "plain"},
            "position_ms": round(self._position * 1_000),
            "offset_ms": self._offset,
            "source_offset_ms": self._timeline.source_offset_ms if self._timeline else 0,
            "active_index": cursor.active_index if cursor else None,
            "line_count": len(self._timeline.lines) if self._timeline else 0,
            "previous": _line(cursor.previous) if cursor else None,
            "active": _line(cursor.active) if cursor else None,
            "following": _line(cursor.following) if cursor else None,
            "plain": self._plain if self._state == "plain" else None,
            "provider": self._provider,
            "attribution": self._attribution,
            "unavailable_reason": self._reason,
        }

    def _emit_locked(self) -> dict[str, object]:
        projection = self._project_locked()
        if projection != self._last:
            self._revision += 1
            projection["revision"] = self._revision
            self._last = deepcopy(projection)
            if not self._closed and self._on_change:
                with contextlib.suppress(Exception):
                    self._on_change(deepcopy(projection))
        return deepcopy(projection)
