"""Private, durable resume positions for long finite media.

The tracker samples authoritative playback state on its own worker. Database I/O and
desktop notification therefore never run in the audio callback or serial playback
control handler.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass
from typing import Protocol

from .database import MarianaDatabase
from .models import MediaRef, PlaybackSnapshot, PlaybackState

LONG_MEDIA_MIN_SECONDS = 20 * 60
MIN_RESUME_SECONDS = 60
END_MARGIN_SECONDS = 60
RESUME_RETENTION_DAYS = 365
MAX_RESUME_RECORDS = 500


class _SnapshotProvider(Protocol):
    def __call__(self) -> PlaybackSnapshot: ...


class _OfferSink(Protocol):
    def __call__(self, payload: dict[str, object]) -> object: ...


@dataclass(frozen=True, slots=True)
class ResumeOffer:
    media_id: str
    position_seconds: float
    duration_seconds: float
    schema_version: int = 1

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _Activation:
    stable_id: str
    duration_seconds: float
    finite: bool
    live: bool
    seekable: bool


def _valid_identity(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and "://" not in value
        and "/" not in value
        and "\\" not in value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _finite_seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _eligible_position(position: float, duration: float) -> bool:
    return (
        duration >= LONG_MEDIA_MIN_SECONDS
        and position >= MIN_RESUME_SECONDS
        and position < duration - END_MARGIN_SECONDS
    )


class PlaybackResumeStore:
    """Store only opaque media identity and timing data."""

    def __init__(self, database: MarianaDatabase) -> None:
        self.database = database

    def remember(self, snapshot: PlaybackSnapshot) -> bool:
        media = snapshot.media
        position = _finite_seconds(snapshot.position)
        duration = _finite_seconds(snapshot.duration)
        if (
            media is None
            or not _valid_identity(media.stable_id)
            or not media.capabilities.finite
            or media.capabilities.live
            or not media.capabilities.seekable
            or duration is None
            or duration < LONG_MEDIA_MIN_SECONDS
            or position is None
        ):
            return False
        effective_end = _finite_seconds(snapshot.region_end_seconds) or duration
        if position >= effective_end - END_MARGIN_SECONDS:
            self.clear(media.stable_id)
            return False
        if position < MIN_RESUME_SECONDS:
            return False
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO playback_resume_positions("
                "stable_id,position_seconds,duration_seconds,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(stable_id) DO UPDATE SET "
                "position_seconds=excluded.position_seconds,"
                "duration_seconds=excluded.duration_seconds,updated_at=excluded.updated_at",
                (media.stable_id, position, duration, time.time()),
            )
        return True

    def offer_for(self, activation: _Activation) -> ResumeOffer | None:
        if (
            not _valid_identity(activation.stable_id)
            or not activation.finite
            or activation.live
            or not activation.seekable
            or activation.duration_seconds < LONG_MEDIA_MIN_SECONDS
        ):
            return None
        row = self.database.fetchone(
            "SELECT position_seconds,duration_seconds,updated_at "
            "FROM playback_resume_positions WHERE stable_id=?",
            (activation.stable_id,),
        )
        if row is None:
            return None
        position = _finite_seconds(row["position_seconds"])
        stored_duration = _finite_seconds(row["duration_seconds"])
        updated_at = _finite_seconds(row["updated_at"])
        expired = updated_at is None or updated_at < time.time() - RESUME_RETENTION_DAYS * 86400
        duration_tolerance = max(10.0, activation.duration_seconds * 0.01)
        incompatible = (
            position is None
            or stored_duration is None
            or abs(stored_duration - activation.duration_seconds) > duration_tolerance
            or not _eligible_position(position, activation.duration_seconds)
        )
        if expired or incompatible:
            self.clear(activation.stable_id)
            return None
        assert position is not None
        return ResumeOffer(
            media_id=activation.stable_id,
            position_seconds=position,
            duration_seconds=activation.duration_seconds,
        )

    def clear(self, stable_id: str) -> None:
        if not _valid_identity(stable_id):
            return
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM playback_resume_positions WHERE stable_id=?", (stable_id,))

    def prune(self) -> None:
        cutoff = time.time() - RESUME_RETENTION_DAYS * 86400
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM playback_resume_positions WHERE updated_at < ?", (cutoff,))
            connection.execute(
                "DELETE FROM playback_resume_positions WHERE stable_id IN ("
                "SELECT stable_id FROM playback_resume_positions ORDER BY updated_at DESC LIMIT -1 OFFSET ?)",
                (MAX_RESUME_RECORDS,),
            )


class PlaybackResumeTracker:
    """Sample progress and asynchronously offer a saved position on activation."""

    def __init__(
        self,
        database: MarianaDatabase,
        snapshot: _SnapshotProvider,
        on_offer: _OfferSink,
        *,
        poll_interval: float = 5.0,
    ) -> None:
        self.store = PlaybackResumeStore(database)
        self._snapshot = snapshot
        self._on_offer = on_offer
        self._poll_interval = max(0.05, float(poll_interval))
        self._wake = threading.Event()
        self._closing = threading.Event()
        self._activation_lock = threading.Lock()
        self._pending_activation: _Activation | None = None
        self._last_write: tuple[str, float, PlaybackState, float] | None = None
        self._failures = 0
        self._worker = threading.Thread(target=self._run, name="mariana-playback-resume", daemon=True)
        self._worker.start()

    def activate(self, media: MediaRef | None, _resolved: object = None) -> None:
        """Queue only the latest active identity; never block playback startup."""
        activation = None
        duration = _finite_seconds(media.duration) if media is not None else None
        if media is not None and duration is not None:
            activation = _Activation(
                stable_id=media.stable_id,
                duration_seconds=duration,
                finite=media.capabilities.finite,
                live=media.capabilities.live,
                seekable=media.capabilities.seekable,
            )
        with self._activation_lock:
            self._pending_activation = activation
        self._wake.set()

    def capture_now(self, snapshot: PlaybackSnapshot | None = None, *, force: bool = True) -> bool:
        """Persist one authoritative sample; failures remain nonfatal."""
        try:
            current = snapshot or self._snapshot()
            media = current.media
            position = _finite_seconds(current.position)
            if media is None or position is None:
                return False
            previous = self._last_write
            now = time.monotonic()
            should_write = force or previous is None or previous[0] != media.stable_id
            if previous is not None and previous[0] == media.stable_id:
                should_write = should_write or abs(position - previous[1]) >= 15
                should_write = should_write or current.state != previous[2]
                should_write = should_write or now - previous[3] >= 30
            if not should_write:
                return False
            stored = self.store.remember(current)
            if stored:
                self._last_write = (media.stable_id, position, current.state, now)
            return stored
        except Exception:
            self._failures += 1
            return False

    def status(self) -> dict[str, int]:
        return {"failures": self._failures}

    def _take_activation(self) -> _Activation | None:
        with self._activation_lock:
            activation = self._pending_activation
            self._pending_activation = None
        return activation

    def _offer_pending(self) -> None:
        activation = self._take_activation()
        if activation is None:
            return
        try:
            current = self._snapshot()
            current_id = current.media.stable_id if current.media else None
            current_position = _finite_seconds(current.position)
            starting_position = _finite_seconds(current.region_start_seconds) or 0.0
            if (
                current_id != activation.stable_id
                or current_position is None
                or current_position >= starting_position + MIN_RESUME_SECONDS
            ):
                return
            offer = self.store.offer_for(activation)
            region_start = _finite_seconds(current.region_start_seconds)
            region_end = _finite_seconds(current.region_end_seconds)
            if offer is None:
                return
            if region_start is not None and offer.position_seconds < region_start:
                return
            if region_end is not None and offer.position_seconds >= region_end - END_MARGIN_SECONDS:
                return
            self._on_offer(offer.to_dict())
        except Exception:
            self._failures += 1

    def _run(self) -> None:
        try:
            try:
                self.store.prune()
            except Exception:
                self._failures += 1
            while not self._closing.is_set():
                self._wake.wait(self._poll_interval)
                self._wake.clear()
                self._offer_pending()
                self.capture_now(force=False)
        finally:
            self.capture_now(force=True)

    def close(self, timeout: float = 1.0) -> bool:
        self._closing.set()
        self._wake.set()
        if self._worker is not threading.current_thread():
            self._worker.join(max(0.0, timeout))
        return not self._worker.is_alive()
