"""Local, bounded playback-action capture and hotspot aggregation.

Events contain opaque stable identities and positions only. Persistence and optional
log forwarding happen on a worker thread, never in playback control or PCM callbacks.
"""

from __future__ import annotations

import json
import math
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal, TypedDict

from .database import MarianaDatabase

PlaybackAction = Literal["play", "pause", "seek"]
PlaybackOrigin = Literal["cli", "desktop", "mini-player", "automatic", "recovery", "system"]
PlayKind = Literal["start", "resume"]
Scaling = Literal["linear", "log1p"]

USER_INTEREST_ORIGINS = frozenset({"cli", "desktop", "mini-player"})
VALID_ACTIONS = frozenset({"play", "pause", "seek"})
VALID_ORIGINS = frozenset({"cli", "desktop", "mini-player", "automatic", "recovery", "system"})


@dataclass(frozen=True, slots=True)
class PlaybackEvent:
    event_id: str
    occurred_at: float
    stable_id: str
    session_id: str
    action: PlaybackAction
    origin: PlaybackOrigin
    position_seconds: float
    play_kind: PlayKind | None = None
    seek_from_seconds: float | None = None
    seek_to_seconds: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class HotspotBin(TypedDict):
    start_seconds: float
    end_seconds: float
    play_starts: int
    play_resumes: int
    pauses: int
    seek_destinations: int
    total: int
    intensity: float
    scaling: Scaling


@dataclass(frozen=True, slots=True)
class _Request:
    operation: Literal["clear", "purge", "flush"]
    completed: threading.Event
    successful: threading.Event


class LocalPlaybackEvents:
    """Best-effort event capture with bounded memory and shutdown latency."""

    def __init__(
        self,
        database: MarianaDatabase,
        *,
        enabled: bool = False,
        retention_days: int = 90,
        forward_to_log: bool = False,
        log_sink: Callable[[str], None] | None = None,
        capacity: int = 512,
        batch_size: int = 32,
        flush_interval: float = 0.25,
    ) -> None:
        self.database = database
        self._enabled = bool(enabled)
        self._retention_days = self._validate_retention(retention_days)
        self._forward_to_log = bool(forward_to_log)
        self._log_sink = log_sink
        self._queue: queue.Queue[PlaybackEvent | _Request] = queue.Queue(maxsize=max(1, int(capacity)))
        self._batch_size = max(1, int(batch_size))
        self._flush_interval = max(0.01, float(flush_interval))
        self._closing = threading.Event()
        self._lock = threading.Lock()
        self._dropped = 0
        self._persist_failures = 0
        self._forward_failures = 0
        self._next_purge = time.monotonic() + 3600
        self._worker = threading.Thread(target=self._run, name="mariana-playback-events", daemon=True)
        self._worker.start()
        self._request("purge", timeout=0)

    @staticmethod
    def _validate_retention(days: int) -> int:
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
            raise ValueError("Playback-event retention must be between 1 and 3650 days")
        return days

    @staticmethod
    def _valid_identity(value: object) -> bool:
        return (
            isinstance(value, str)
            and 0 < len(value) <= 128
            and "://" not in value
            and "/" not in value
            and "\\" not in value
            and not any(ord(character) < 32 or ord(character) == 127 for character in value)
        )

    @classmethod
    def _valid_event(cls, event: PlaybackEvent) -> bool:
        if not isinstance(event, PlaybackEvent):
            return False

        def finite_position(value: object) -> bool:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return False
            try:
                return math.isfinite(float(value)) and value >= 0
            except OverflowError:
                return False

        values = (event.position_seconds, event.seek_from_seconds, event.seek_to_seconds)
        if (
            not cls._valid_identity(event.event_id)
            or not finite_position(event.occurred_at)
            or event.occurred_at <= 0
            or not cls._valid_identity(event.stable_id)
            or not cls._valid_identity(event.session_id)
            or not isinstance(event.action, str)
            or event.action not in VALID_ACTIONS
            or not isinstance(event.origin, str)
            or event.origin not in VALID_ORIGINS
            or not finite_position(event.position_seconds)
            or any(
                value is not None
                and not finite_position(value)
                for value in values
            )
        ):
            return False
        if event.action == "play":
            return (
                event.play_kind in ("start", "resume")
                and event.seek_from_seconds is None
                and event.seek_to_seconds is None
            )
        if event.action == "pause":
            return (
                event.play_kind is None
                and event.seek_from_seconds is None
                and event.seek_to_seconds is None
            )
        return (
            event.play_kind is None
            and event.seek_from_seconds is not None
            and event.seek_to_seconds == event.position_seconds
        )

    def configure(
        self,
        *,
        enabled: bool | None = None,
        retention_days: int | None = None,
        forward_to_log: bool | None = None,
    ) -> None:
        if enabled is not None and type(enabled) is not bool:
            raise ValueError("Playback-event capture setting must be true or false")
        if forward_to_log is not None and type(forward_to_log) is not bool:
            raise ValueError("Playback-event log forwarding must be true or false")
        validated_retention = (
            self._validate_retention(retention_days) if retention_days is not None else None
        )
        with self._lock:
            if enabled is not None:
                self._enabled = enabled
            if validated_retention is not None:
                self._retention_days = validated_retention
            if forward_to_log is not None:
                self._forward_to_log = forward_to_log
        if retention_days is not None:
            self._request("purge", timeout=0)

    def capture(
        self,
        *,
        stable_id: str,
        session_id: str,
        action: PlaybackAction,
        origin: PlaybackOrigin,
        position_seconds: float,
        play_kind: PlayKind | None = None,
        seek_from_seconds: float | None = None,
        seek_to_seconds: float | None = None,
    ) -> bool:
        with self._lock:
            enabled = self._enabled
        if not enabled:
            return False
        try:
            position = float(position_seconds)
            seek_from = float(seek_from_seconds) if seek_from_seconds is not None else None
            seek_to = float(seek_to_seconds) if seek_to_seconds is not None else None
        except (TypeError, ValueError, OverflowError):
            return False
        event = PlaybackEvent(
            event_id=uuid.uuid4().hex,
            occurred_at=time.time(),
            stable_id=stable_id,
            session_id=session_id,
            action=action,
            origin=origin,
            position_seconds=position,
            play_kind=play_kind if action == "play" else None,
            seek_from_seconds=seek_from,
            seek_to_seconds=seek_to,
        )
        return self.submit(event)

    def submit(self, event: PlaybackEvent) -> bool:
        if not self._valid_event(event):
            return False
        # Consent changes, enqueue, and close share one short memory-only boundary.
        with self._lock:
            if not self._enabled or self._closing.is_set():
                return False
            try:
                self._queue.put_nowait(event)
                return True
            except queue.Full:
                self._dropped += 1
                return False

    def _request(self, operation: Literal["clear", "purge", "flush"], *, timeout: float) -> bool:
        completed = threading.Event()
        successful = threading.Event()
        deadline = time.monotonic() + max(0.0, timeout)
        try:
            if timeout > 0:
                self._queue.put(_Request(operation, completed, successful), timeout=timeout)
            else:
                self._queue.put_nowait(_Request(operation, completed, successful))
        except queue.Full:
            return False
        if timeout <= 0:
            return True  # Accepted for asynchronous execution, not yet completed.
        return completed.wait(max(0.0, deadline - time.monotonic())) and successful.is_set()

    def flush(self, timeout: float = 2.0) -> bool:
        return self._request("flush", timeout=max(0.0, timeout))

    def clear(self, timeout: float = 2.0) -> bool:
        return self._request("clear", timeout=max(0.0, timeout))

    def status(self) -> dict[str, object]:
        with self._lock:
            enabled = self._enabled
            retention = self._retention_days
            forwarding = self._forward_to_log
            dropped = self._dropped
            failures = self._persist_failures
            forward_failures = self._forward_failures
        row = self.database.fetchone("SELECT COUNT(*) AS count FROM playback_events")
        return {
            "enabled": enabled,
            "retention_days": retention,
            "forward_to_log": forwarding,
            "pending": self._queue.qsize(),
            "capacity": self._queue.maxsize,
            "stored": int(row["count"]) if row else 0,
            "dropped": dropped,
            "persistence_failures": failures,
            "log_forward_failures": forward_failures,
        }

    def aggregate(
        self,
        stable_id: str,
        *,
        bin_seconds: float = 10.0,
        scaling: Scaling = "linear",
        include_automatic: bool = False,
        flush_pending: bool = True,
    ) -> list[HotspotBin]:
        if not isinstance(stable_id, str) or not stable_id:
            raise ValueError("A stable media identity is required")
        if not isinstance(bin_seconds, (int, float)) or not math.isfinite(float(bin_seconds)) or bin_seconds <= 0:
            raise ValueError("Hotspot bin width must be a positive finite number")
        if scaling not in {"linear", "log1p"}:
            raise ValueError("Hotspot scaling must be linear or log1p")
        # Interactive CLI inspection asks for an up-to-the-moment view. Renderer
        # projections deliberately tolerate the worker's sub-second persistence
        # delay so a UI read never turns the serial control handler into a writer.
        if flush_pending:
            self.flush()
        parameters: list[object] = [stable_id]
        origin_filter = ""
        if not include_automatic:
            origin_filter = " AND origin IN (?, ?, ?)"
            parameters.extend(sorted(USER_INTEREST_ORIGINS))
        rows = self.database.fetchall(
            "SELECT action,play_kind,position_seconds FROM playback_events "
            f"WHERE stable_id=?{origin_filter} ORDER BY occurred_at,event_id",
            tuple(parameters),
        )
        bins: dict[int, dict[str, int]] = {}
        width = float(bin_seconds)
        for row in rows:
            raw_index = float(row["position_seconds"]) // width
            if not math.isfinite(raw_index):
                raise ValueError("Hotspot bin width is too small for stored positions")
            index = max(0, int(raw_index))
            counts = bins.setdefault(index, {"play_starts": 0, "play_resumes": 0, "pauses": 0, "seek_destinations": 0})
            if row["action"] == "play":
                counts["play_starts" if row["play_kind"] == "start" else "play_resumes"] += 1
            elif row["action"] == "pause":
                counts["pauses"] += 1
            elif row["action"] == "seek":
                counts["seek_destinations"] += 1
        maximum = max((sum(counts.values()) for counts in bins.values()), default=0)
        denominator = math.log1p(maximum) if scaling == "log1p" else float(maximum)
        result: list[HotspotBin] = []
        for index, counts in sorted(bins.items()):
            total = sum(counts.values())
            intensity = (math.log1p(total) if scaling == "log1p" else float(total)) / denominator if denominator else 0.0
            result.append({
                "start_seconds": index * width,
                "end_seconds": (index + 1) * width,
                "play_starts": counts["play_starts"],
                "play_resumes": counts["play_resumes"],
                "pauses": counts["pauses"],
                "seek_destinations": counts["seek_destinations"],
                "total": total,
                "intensity": intensity,
                "scaling": scaling,
            })
        return result

    def _persist(self, events: list[PlaybackEvent]) -> None:
        if not events:
            return
        stored: list[PlaybackEvent] = []
        try:
            with self.database.transaction() as connection:
                for event in events:
                    cursor = connection.execute(
                        "INSERT OR IGNORE INTO playback_events("
                        "event_id,occurred_at,stable_id,session_id,action,origin,position_seconds,"
                        "play_kind,seek_from_seconds,seek_to_seconds) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            event.event_id, event.occurred_at, event.stable_id, event.session_id,
                            event.action, event.origin, event.position_seconds, event.play_kind,
                            event.seek_from_seconds, event.seek_to_seconds,
                        ),
                    )
                    if cursor.rowcount:
                        stored.append(event)
        except Exception:
            with self._lock:
                self._persist_failures += len(events)
            return
        with self._lock:
            forward = self._forward_to_log
        if forward and self._log_sink:
            for event in stored:
                try:
                    self._log_sink("playback-event " + json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":")))
                except Exception:
                    with self._lock:
                        self._forward_failures += 1

    def _purge(self) -> None:
        with self._lock:
            cutoff = time.time() - self._retention_days * 86400
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM playback_events WHERE occurred_at < ?", (cutoff,))
        self._next_purge = time.monotonic() + 3600

    def _run(self) -> None:
        batch: list[PlaybackEvent] = []
        deadline = time.monotonic() + self._flush_interval
        while not self._closing.is_set() or not self._queue.empty():
            timeout = max(0.0, deadline - time.monotonic())
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                item = None
            if isinstance(item, PlaybackEvent):
                batch.append(item)
            elif isinstance(item, _Request):
                self._persist(batch)
                batch.clear()
                try:
                    if item.operation == "clear":
                        with self.database.transaction() as connection:
                            connection.execute("DELETE FROM playback_events")
                    elif item.operation == "purge":
                        self._purge()
                    item.successful.set()
                except Exception:
                    with self._lock:
                        self._persist_failures += 1
                finally:
                    item.completed.set()
            if len(batch) >= self._batch_size or time.monotonic() >= deadline:
                self._persist(batch)
                batch.clear()
                deadline = time.monotonic() + self._flush_interval
            if time.monotonic() >= self._next_purge:
                try:
                    self._purge()
                except Exception:
                    with self._lock:
                        self._persist_failures += 1
                    self._next_purge = time.monotonic() + 3600
        self._persist(batch)

    def close(self, timeout: float = 2.0) -> bool:
        with self._lock:
            self._closing.set()
        self._worker.join(max(0.0, timeout))
        return not self._worker.is_alive()
