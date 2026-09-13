import math
import threading
import time
from dataclasses import FrozenInstanceError

import pytest

from mariana.database import MarianaDatabase
from mariana.playback_events import LocalPlaybackEvents, PlaybackEvent


def event(
    event_id: str,
    *,
    action: str = "play",
    origin: str = "cli",
    position: float = 0,
    occurred_at: float | None = None,
    play_kind: str | None = "start",
    stable_id: str = "media-1",
) -> PlaybackEvent:
    return PlaybackEvent(
        event_id=event_id,
        occurred_at=time.time() if occurred_at is None else occurred_at,
        stable_id=stable_id,
        session_id="session-1",
        action=action,  # type: ignore[arg-type]
        origin=origin,  # type: ignore[arg-type]
        position_seconds=position,
        play_kind=play_kind,  # type: ignore[arg-type]
        seek_from_seconds=2 if action == "seek" else None,
        seek_to_seconds=position if action == "seek" else None,
    )


def test_capture_is_immutable_deduplicated_and_independent_of_log_forwarding(tmp_path):
    logs: list[str] = []
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database, enabled=True, log_sink=logs.append)
        assert capture.capture(
            stable_id="opaque-media-id",
            session_id="opaque-session-id",
            action="seek",
            origin="desktop",
            position_seconds=12,
            seek_from_seconds=3,
            seek_to_seconds=12,
        )
        duplicate = event("same-event")
        attribute = "action"
        with pytest.raises(FrozenInstanceError):
            setattr(duplicate, attribute, "pause")
        assert capture.submit(duplicate)
        assert capture.submit(duplicate)
        assert capture.flush()
        rows = database.fetchall("SELECT * FROM playback_events ORDER BY occurred_at,event_id")
        assert len(rows) == 2
        seek_row = next(row for row in rows if row["action"] == "seek")
        assert seek_row["seek_from_seconds"] == 3
        assert seek_row["seek_to_seconds"] == 12
        assert seek_row["event_id"] and seek_row["occurred_at"] > 0
        assert seek_row["stable_id"] == "opaque-media-id"
        assert seek_row["session_id"] == "opaque-session-id"
        assert logs == []

        capture.configure(forward_to_log=True)
        assert capture.capture(
            stable_id="opaque-media-id",
            session_id="opaque-session-id",
            action="pause",
            origin="mini-player",
            position_seconds=14,
        )
        assert capture.flush()
        assert len(logs) == 1
        assert "playback-event" in logs[0]
        assert "opaque-media-id" in logs[0]
        assert "http" not in logs[0]
        assert capture.close()


def test_capture_validation_disable_and_shutdown_flush(tmp_path):
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database)
        assert not capture.capture(
            stable_id="media",
            session_id="session",
            action="play",
            origin="cli",
            position_seconds=0,
            play_kind="start",
        )
        capture.configure(enabled=True)
        assert not capture.capture(
            stable_id="media",
            session_id="session",
            action="seek",
            origin="cli",
            position_seconds=math.nan,
            seek_from_seconds=0,
            seek_to_seconds=1,
        )
        assert not capture.capture(
            stable_id="https://private.example/signed",
            session_id="session",
            action="pause",
            origin="cli",
            position_seconds=1,
        )
        assert not capture.capture(
            stable_id="media",
            session_id="session",
            action="seek",
            origin="cli",
            position_seconds=1,
        )
        assert capture.capture(
            stable_id="media",
            session_id="session",
            action="play",
            origin="cli",
            position_seconds=0,
            play_kind="start",
        )
        assert capture.close()
        stored = database.fetchone("SELECT COUNT(*) FROM playback_events")
        assert stored is not None and stored[0] == 1
        assert not capture.submit(event("after-close"))


def test_persistence_and_log_sink_failures_are_counted_and_isolated(tmp_path, monkeypatch):
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(
            database,
            enabled=True,
            forward_to_log=True,
            log_sink=lambda _message: (_ for _ in ()).throw(OSError("log unavailable")),
        )
        assert capture.flush()
        original_transaction = database.transaction

        def unavailable_transaction():
            raise OSError("storage unavailable")

        monkeypatch.setattr(database, "transaction", unavailable_transaction)
        assert capture.submit(event("storage-failure"))
        assert capture.flush()
        assert capture.status()["persistence_failures"] == 1

        monkeypatch.setattr(database, "transaction", original_transaction)
        assert capture.submit(event("log-failure"))
        assert capture.flush()
        assert capture.status()["log_forward_failures"] == 1
        assert capture.close()


def test_bounded_queue_reports_overflow_without_blocking_producer(tmp_path):
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database, enabled=True, capacity=2, batch_size=1)
        started = threading.Event()
        release = threading.Event()
        original_persist = capture._persist

        def blocked_persist(events):
            if events:
                started.set()
                release.wait(2)
            original_persist(events)

        capture._persist = blocked_persist
        assert capture.submit(event("one"))
        assert started.wait(1)
        assert capture.submit(event("two"))
        assert capture.submit(event("three"))
        assert not capture.submit(event("overflow"))
        assert capture.status()["dropped"] == 1
        release.set()
        assert capture.close()


def test_retention_clear_and_personal_hotspot_aggregation(tmp_path):
    now = time.time()
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database, enabled=True, retention_days=90)
        assert capture.submit(
            event("old", occurred_at=now - 3 * 86400, stable_id="old-media")
        )
        assert capture.submit(event("start", position=1))
        assert capture.submit(event("resume", position=4, play_kind="resume"))
        assert capture.submit(event("pause", action="pause", position=7, play_kind=None))
        assert capture.submit(event("seek", action="seek", position=12, play_kind=None))
        assert capture.submit(event("automatic", origin="recovery", position=12))
        assert capture.flush()

        rows = capture.aggregate("media-1", bin_seconds=10, scaling="linear")
        assert rows == [
            {
                "start_seconds": 0.0,
                "end_seconds": 10.0,
                "play_starts": 1,
                "play_resumes": 1,
                "pauses": 1,
                "seek_destinations": 0,
                "total": 3,
                "intensity": 1.0,
                "scaling": "linear",
            },
            {
                "start_seconds": 10.0,
                "end_seconds": 20.0,
                "play_starts": 0,
                "play_resumes": 0,
                "pauses": 0,
                "seek_destinations": 1,
                "total": 1,
                "intensity": 1 / 3,
                "scaling": "linear",
            },
        ]
        with_automatic = capture.aggregate(
            "media-1", bin_seconds=10, scaling="log1p", include_automatic=True
        )
        assert with_automatic[-1]["play_starts"] == 1
        assert with_automatic[-1]["intensity"] == math.log1p(2) / math.log1p(3)

        capture.configure(retention_days=1)
        assert capture.flush()
        old = database.fetchone(
            "SELECT COUNT(*) FROM playback_events WHERE event_id='old'"
        )
        assert old is not None and old[0] == 0
        assert capture.clear()
        assert capture.status()["stored"] == 0
        assert capture.close()
