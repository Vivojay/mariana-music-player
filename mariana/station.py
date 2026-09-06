"""Persistent station sessions and cancellable queue replenishment."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import Any, cast

from .database import MarianaDatabase
from .models import MediaRef, StationSession, StationState
from .queueing import PersistentQueue, QueueError
from .station_discovery import (
    VALID_STATION_SCOPES,
    DiscoveredTrack,
    StationDiscovery,
    validate_station_seed,
)

READY_AHEAD_TARGET = 10
UNLIMITED_WINDOW = 500


class StationError(RuntimeError):
    pass


class StationManager:
    def __init__(
        self,
        database: MarianaDatabase,
        queue: PersistentQueue,
        discovery: StationDiscovery,
        *,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        pause_playback: Callable[[], None] | None = None,
        resume_playback: Callable[[], None] | None = None,
    ) -> None:
        self.database = database
        self.queue = queue
        self.discovery = discovery
        self.on_update = on_update or (lambda _payload: None)
        self.pause_playback = pause_playback or (lambda: None)
        self.resume_playback = resume_playback or (lambda: None)
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._pending_target = 0
        self._closed = False
        self._restore_paused()

    def _restore_paused(self) -> None:
        row = self.database.fetchone("SELECT session_id FROM station_sessions WHERE active=1")
        if row:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE station_sessions SET state=?, progress_message=?, updated_at=? WHERE session_id=?",
                    (StationState.PAUSED.value, "restored after restart", time.time(), row["session_id"]),
                )

    def _row_to_session(self, row) -> StationSession:
        return StationSession(
            session_id=row["session_id"],
            seed=MediaRef.from_dict(json.loads(row["seed_json"])),
            scope=row["scope"],
            limit=row["generation_limit"],
            state=StationState(row["state"]),
            generated_count=row["generated_count"],
            ready_ahead=row["ready_ahead"],
            progress_message=row["progress_message"],
            error_code=row["error_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def session(self) -> StationSession | None:
        row = self.database.fetchone(
            "SELECT * FROM station_sessions WHERE active=1 ORDER BY created_at DESC LIMIT 1"
        )
        return self._row_to_session(row) if row else None

    def items(self, count: int = 10, *, include_played: bool = False) -> list[dict[str, Any]]:
        session = self.session()
        if not session:
            return []
        clause = "" if include_played else "AND played=0"
        rows = self.database.fetchall(
            f"SELECT * FROM station_items WHERE session_id=? {clause} ORDER BY position LIMIT ?",
            (session.session_id, max(0, count)),
        )
        return [
            {
                "position": row["position"],
                "media": MediaRef.from_dict(json.loads(row["media_json"])),
                "score": row["score"],
                "reasons": json.loads(row["reasons_json"]),
                "provider": row["provider"],
                "played": bool(row["played"]),
            }
            for row in rows
        ]

    def payload(self) -> dict[str, Any]:
        session = self.session()
        if not session:
            return {"state": StationState.STOPPED.value, "next": []}
        return {
            "session_id": session.session_id,
            "state": session.state.value,
            "scope": session.scope,
            "limit": session.limit,
            "generated_count": session.generated_count,
            "ready_ahead": session.ready_ahead,
            "progress": session.progress_message,
            "error_code": session.error_code,
            "seed": {
                "id": session.seed.stable_id,
                "title": session.seed.title,
                "artist": session.seed.artist,
            },
            "next": [
                {
                    "id": item["media"].stable_id,
                    "title": item["media"].title or item["media"].original_uri,
                    "artist": item["media"].artist,
                    "reasons": item["reasons"],
                }
                for item in self.items(10)
            ],
        }

    def _emit(self) -> None:
        self.on_update(self.payload())
        with self._condition:
            self._condition.notify_all()

    def start(self, seed: MediaRef, *, scope: str = "hybrid", limit: int | None = 50) -> StationSession:
        if scope not in VALID_STATION_SCOPES:
            raise StationError(f"Unknown station scope: {scope}")
        verified = validate_station_seed(self.database, seed)
        if limit is not None and limit < 1:
            raise StationError("Station limit must be at least one track")
        if self.session():
            self.stop()
        snapshot = self.queue.export_snapshot()
        session_id = uuid.uuid4().hex
        now = time.time()
        with self.database.transaction() as connection:
            connection.execute("UPDATE station_sessions SET active=0 WHERE active=1")
            connection.execute(
                "INSERT INTO station_sessions(session_id,seed_json,scope,generation_limit,state,"
                "generated_count,ready_ahead,progress_message,queue_snapshot_json,created_at,updated_at) "
                "VALUES(?,?,?,?,?,1,0,?,?,?,?)",
                (
                    session_id,
                    json.dumps(verified.to_dict(), ensure_ascii=False),
                    scope,
                    limit,
                    StationState.LOADING.value,
                    "validating 0/10",
                    json.dumps(snapshot, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO station_items(session_id,position,stable_id,media_json,score,reasons_json,provider,"
                "status,played,created_at) VALUES(?,0,?,?,0,?,'seed','ready',1,?)",
                (
                    session_id,
                    verified.stable_id,
                    json.dumps(verified.to_dict(), ensure_ascii=False),
                    json.dumps(["station seed"]),
                    now,
                ),
            )
        self.queue.clear()
        self.queue.add(verified)
        self.queue.jump(0)
        self._start_worker(READY_AHEAD_TARGET)
        self._emit()
        return self.session()  # type: ignore[return-value]

    def _start_worker(self, target: int) -> None:
        with self._lock:
            if self._closed:
                return
            session = self.session()
            if not session or session.state == StationState.PAUSED:
                return
            if self._worker and self._worker.is_alive():
                self._pending_target = max(self._pending_target, max(1, target))
                return
            self._pending_target = 0
            self._cancel = threading.Event()
            self._worker = threading.Thread(
                target=self._run_generation,
                args=(session.session_id, max(1, target), self._cancel),
                name="mariana-station-discovery",
                daemon=True,
            )
            self._worker.start()

    def _run_generation(self, session_id: str, target: int, cancel: threading.Event) -> None:
        try:
            self._generate(session_id, target, cancel)
        finally:
            restart_target = 0
            with self._lock:
                if self._worker is threading.current_thread():
                    self._worker = None
                    if not self._closed:
                        restart_target = self._pending_target
                    self._pending_target = 0
            if restart_target:
                self._start_worker(restart_target)

    def _generated_ids(self, session_id: str) -> set[str]:
        rows = self.database.fetchall(
            "SELECT stable_id FROM station_items WHERE session_id=? ORDER BY position DESC LIMIT ?",
            (session_id, UNLIMITED_WINDOW),
        )
        return {str(row["stable_id"]) for row in rows}

    def _generate(self, session_id: str, target: int, cancel: threading.Event) -> None:
        session = self.session()
        if not session or session.session_id != session_id:
            return

        remaining = target
        if session.limit is not None:
            remaining = min(remaining, max(0, session.limit - session.generated_count))

        if remaining <= 0:
            with self._lock:
                if cancel.is_set() or not self._is_current(session_id):
                    return
                self._set_state(
                    session_id,
                    StationState.EXHAUSTED,
                    "station limit reached",
                    None,
                )
            return

        try:
            results = self.discovery.discover(
                session.seed,
                scope=session.scope,
                limit=remaining,
                excluded=self._generated_ids(session_id),
            )

            for result in results:
                with self._lock:
                    if cancel.is_set() or not self._is_current(session_id):
                        return
                    self._append(session_id, result)

            with self._lock:
                if cancel.is_set() or not self._is_current(session_id):
                    return

                ready = self._ready_count(session_id)
                if ready >= READY_AHEAD_TARGET:
                    state, message, code = (
                        StationState.READY,
                        f"ready {ready}/10",
                        None,
                    )
                elif ready:
                    state, message, code = (
                        StationState.PARTIAL,
                        f"only {ready}/10 playable tracks available",
                        "catalog_shortage",
                    )
                else:
                    state, message, code = (
                        StationState.EXHAUSTED,
                        "no additional playable recommendations",
                        "catalog_exhausted",
                    )

                self._set_state(session_id, state, message, code)

        except Exception as error:
            with self._lock:
                if cancel.is_set() or not self._is_current(session_id):
                    return

                ready = self._ready_count(session_id)
                state = StationState.PARTIAL if ready else StationState.FAILED
                self._set_state(
                    session_id,
                    state,
                    "station discovery failed",
                    type(error).__name__.casefold(),
                )

    def _is_current(self, session_id: str) -> bool:
        session = self.session()
        return bool(session and session.session_id == session_id and session.state != StationState.PAUSED)

    def _ready_count(self, session_id: str) -> int:
        row = self.database.fetchone(
            "SELECT COUNT(*) AS count FROM station_items WHERE session_id=? AND played=0 AND status='ready'",
            (session_id,),
        )
        return int(row["count"] if row else 0)

    def _append(self, session_id: str, item: DiscoveredTrack) -> None:
        with self.database.transaction() as connection:
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS position FROM station_items WHERE session_id=?",
                (session_id,),
            ).fetchone()["position"]
            connection.execute(
                "INSERT OR IGNORE INTO station_items(session_id,position,stable_id,media_json,score,reasons_json,"
                "provider,status,played,created_at) VALUES(?,?,?,?,?,?,?,'ready',0,?)",
                (
                    session_id,
                    position,
                    item.media.stable_id,
                    json.dumps(item.media.to_dict(), ensure_ascii=False),
                    item.score,
                    json.dumps(item.reasons, ensure_ascii=False),
                    item.provider,
                    time.time(),
                ),
            )
            changed = connection.execute("SELECT changes()").fetchone()[0]
            if changed:
                connection.execute(
                    "UPDATE station_sessions SET generated_count=generated_count+1, ready_ahead=ready_ahead+1,"
                    "progress_message=?,updated_at=? WHERE session_id=?",
                    (f"validating {self._ready_count(session_id)}/10", time.time(), session_id),
                )
        if changed:
            try:
                self.queue.add(item.media)
            except QueueError as error:
                if "already queued" not in str(error):
                    raise
            self._prune_unlimited(session_id)
            self._emit()

    def _prune_unlimited(self, session_id: str) -> None:
        session = self.session()
        if not session or session.limit is not None:
            return
        rows = self.database.fetchall(
            "SELECT position,stable_id FROM station_items WHERE session_id=? ORDER BY position DESC",
            (session_id,),
        )
        for row in rows[UNLIMITED_WINDOW:]:
            played = self.database.fetchone(
                "SELECT played FROM station_items WHERE session_id=? AND position=?",
                (session_id, row["position"]),
            )
            if played and played["played"]:
                with self.database.transaction() as connection:
                    connection.execute(
                        "DELETE FROM station_items WHERE session_id=? AND position=?",
                        (session_id, row["position"]),
                    )
                self.queue.remove_media(str(row["stable_id"]))

    def _set_state(self, session_id: str, state: StationState, message: str, error_code: str | None) -> None:
        ready = self._ready_count(session_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE station_sessions SET state=?,ready_ahead=?,progress_message=?,error_code=?,updated_at=? "
                "WHERE session_id=? AND active=1",
                (state.value, ready, message, error_code, time.time(), session_id),
            )
        self._emit()

    def wait_initial(self, timeout: float = 5.0) -> StationSession | None:
        deadline = time.monotonic() + max(0, timeout)
        with self._condition:
            while time.monotonic() < deadline:
                session = self.session()
                if not session or session.state in {
                    StationState.READY,
                    StationState.PARTIAL,
                    StationState.EXHAUSTED,
                    StationState.FAILED,
                }:
                    return session
                self._condition.wait(min(0.1, deadline - time.monotonic()))
        return self.session()

    def mark_played(self, media: MediaRef) -> None:
        session = self.session()
        if not session:
            return
        self._cancel.set()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE station_items SET played=1 WHERE session_id=? AND stable_id=?",
                (session.session_id, media.stable_id),
            )
        ready = self._ready_count(session.session_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE station_sessions SET ready_ahead=?,updated_at=? WHERE session_id=?",
                (ready, time.time(), session.session_id),
            )
        if ready < READY_AHEAD_TARGET and session.state != StationState.PAUSED:
            self._start_worker(READY_AHEAD_TARGET - ready)
        self._emit()

    def more(self, count: int = 10) -> None:
        if count < 1:
            raise StationError("Station count must be positive")
        session = self.session()
        if not session:
            raise StationError("No station session is active")
        self._set_state(session.session_id, StationState.LOADING, "loading more recommendations", None)
        self._start_worker(count)

    def cancel_generation(self) -> None:
        """Cancel only discovery while retaining playback and validated items."""
        session = self.session()
        if not session:
            raise StationError("No station session is active")
        with self._lock:
            self._pending_target = 0
            self._cancel.set()
        ready = self._ready_count(session.session_id)
        state = StationState.READY if ready >= READY_AHEAD_TARGET else StationState.PARTIAL
        self._set_state(session.session_id, state, "station generation cancelled", "cancelled")

    def pause(self) -> None:
        session = self.session()
        if not session:
            raise StationError("No station session is active")
        with self._lock:
            self._pending_target = 0
            self._cancel.set()
        with suppress(Exception):
            self.pause_playback()
        self._set_state(session.session_id, StationState.PAUSED, "paused", None)

    def resume(self) -> None:
        session = self.session()
        if not session:
            raise StationError("No station session is active")
        self._set_state(session.session_id, StationState.LOADING, "resuming", None)
        with suppress(Exception):
            self.resume_playback()
        self._start_worker(max(1, READY_AHEAD_TARGET - self._ready_count(session.session_id)))

    def stop(self) -> None:
        session = self.session()
        if not session:
            raise StationError("No station session is active")
        with self._lock:
            self._pending_target = 0
            self._cancel.set()
        row = self.database.fetchone(
            "SELECT queue_snapshot_json FROM station_sessions WHERE session_id=?", (session.session_id,)
        )
        snapshot = json.loads(cast(Any, row)["queue_snapshot_json"])
        self.queue.restore_snapshot(snapshot)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE station_sessions SET state=?,active=0,updated_at=? WHERE session_id=?",
                (StationState.STOPPED.value, time.time(), session.session_id),
            )
        self.on_update({"state": StationState.STOPPED.value, "next": []})
        with self._condition:
            self._condition.notify_all()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending_target = 0
            self._cancel.set()
            worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join(timeout=1)
