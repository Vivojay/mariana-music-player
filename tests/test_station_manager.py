import json
import threading
import time
from pathlib import Path

import pytest

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, StationState
from mariana.queueing import PersistentQueue, QueueError
from mariana.station import UNLIMITED_WINDOW, StationError, StationManager
from mariana.station_discovery import DiscoveredTrack


def youtube(name: str) -> MediaRef:
    return MediaRef(
        MediaSource.YOUTUBE,
        f"https://www.youtube.com/watch?v={name}",
        title=name,
        artist=f"artist-{name}",
        resolver_data={"is_music": True},
    )


class Discovery:
    def __init__(self, values=None, error=None):
        self.values = list(values or [])
        self.error = error
        self.calls = []

    def discover(self, seed, *, scope, limit, excluded):
        self.calls.append((seed, scope, limit, set(excluded)))
        if self.error:
            raise self.error
        return [
            DiscoveredTrack(media, float(index), [f"reason {index}"], "test")
            for index, media in enumerate(self.values)
            if media.stable_id not in excluded
        ][:limit]


def test_station_lifecycle_queue_snapshot_events_and_restart(tmp_path: Path):
    events = []
    discovery_started = threading.Event()
    release_discovery = threading.Event()

    class GatedDiscovery(Discovery):
        def discover(self, *args, **kwargs):
            discovery_started.set()
            assert release_discovery.wait(2), "station discovery gate timed out"
            return super().discover(*args, **kwargs)

    database_path = tmp_path / "station.db"
    seed, old = youtube("seed"), youtube("old")
    recommendations = [youtube(f"rec-{index}") for index in range(12)]
    with MarianaDatabase(database_path) as database:
        queue = PersistentQueue(database)
        queue.add(old)
        queue.jump(0)
        discovery = GatedDiscovery(recommendations)
        manager = StationManager(database, queue, discovery, on_update=events.append)
        session = manager.start(seed, scope="hybrid", limit=50)
        assert discovery_started.wait(1)
        assert session.state == StationState.LOADING
        release_discovery.set()
        ready = manager.wait_initial(10)
        assert ready.state == StationState.READY
        assert ready.ready_ahead == 10
        assert [item.media.title for item in queue.items()] == ["seed", *[f"rec-{i}" for i in range(10)]]
        assert manager.items(2)[0]["reasons"] == ["reason 0"]
        assert manager.payload()["next"][0]["title"] == "rec-0"
        assert events[-1]["ready_ahead"] == 10

        manager.mark_played(recommendations[0])
        assert manager.session().ready_ahead in {9, 10}
        manager.pause()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and manager.session().state != StationState.PAUSED:
            time.sleep(0.01)
        assert manager.session().state == StationState.PAUSED
        manager.close()

    with MarianaDatabase(database_path) as database:
        queue = PersistentQueue(database)
        restored = StationManager(database, queue, Discovery(recommendations))
        assert restored.session().state == StationState.PAUSED
        restored.resume()
        assert restored.wait_initial(10).state in {StationState.READY, StationState.PARTIAL}
        restored.stop()
        assert restored.session() is None
        assert [item.media.title for item in queue.items()] == ["old"]


def test_station_limits_partial_failure_and_validation(tmp_path: Path):
    with MarianaDatabase(tmp_path / "station.db") as database:
        queue = PersistentQueue(database)
        seed = youtube("seed")
        manager = StationManager(database, queue, Discovery([youtube("one")]))
        with pytest.raises(StationError, match="scope"):
            manager.start(seed, scope="wrong")
        with pytest.raises(StationError, match="at least"):
            manager.start(seed, limit=0)

        manager.start(seed, limit=2)
        assert manager.wait_initial(3).state == StationState.PARTIAL
        assert manager.session().generated_count == 2
        manager.more(2)
        assert manager.wait_initial(3).state == StationState.EXHAUSTED
        with pytest.raises(StationError, match="positive"):
            manager.more(0)
        manager.stop()

        failed = StationManager(database, queue, Discovery(error=TimeoutError("offline")))
        failed.start(seed)
        assert failed.wait_initial(3).state == StationState.FAILED
        assert failed.session().error_code == "timeouterror"
        failed.stop()


def test_station_pause_cancels_stale_discovery(tmp_path: Path):
    started = threading.Event()
    release = threading.Event()

    class SlowDiscovery:
        def discover(self, *_args, **_kwargs):
            started.set()
            release.wait(2)
            return [DiscoveredTrack(youtube("late"), 1, ["late"], "test")]

    pauses = []
    resumes = []
    with MarianaDatabase(tmp_path / "station.db") as database:
        manager = StationManager(
            database,
            PersistentQueue(database),
            SlowDiscovery(),
            pause_playback=lambda: pauses.append(True),
            resume_playback=lambda: resumes.append(True),
        )
        manager.start(youtube("seed"))
        assert started.wait(1)
        manager.pause()
        release.set()
        time.sleep(0.05)
        assert manager.items() == []
        assert pauses == [True]
        manager.resume()
        assert resumes == [True]
        manager.stop()
        manager.close()


def test_station_cancelled_worker_replenishes_only_while_active(tmp_path: Path):
    started = threading.Event()
    release = threading.Event()

    class RestartingDiscovery:
        def __init__(self):
            self.calls = 0

        def discover(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                started.set()
                release.wait(2)
                return [DiscoveredTrack(youtube("stale"), 1, ["stale"], "test")]
            return [DiscoveredTrack(youtube("fresh"), 1, ["fresh"], "test")]

    with MarianaDatabase(tmp_path / "station.db") as database:
        discovery = RestartingDiscovery()
        manager = StationManager(database, PersistentQueue(database), discovery)
        manager.start(youtube("seed"))
        assert started.wait(1)
        manager.mark_played(youtube("seed"))
        release.set()
        deadline = time.monotonic() + 2
        while discovery.calls < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert discovery.calls == 2
        assert [item["media"].title for item in manager.items()] == ["fresh"]
        manager.stop()
        manager.close()


def test_station_generation_can_be_cancelled_without_pausing_playback(tmp_path: Path):
    started = threading.Event()
    release = threading.Event()

    class SlowDiscovery:
        def discover(self, *_args, **_kwargs):
            started.set()
            release.wait(2)
            return []

    with MarianaDatabase(tmp_path / "station.db") as database:
        manager = StationManager(database, PersistentQueue(database), SlowDiscovery())
        manager.start(youtube("seed"))
        assert started.wait(1)
        manager.cancel_generation()
        assert manager.session().state == StationState.PARTIAL
        assert manager.session().error_code == "cancelled"
        release.set()
        manager.stop()
        manager.close()


def test_station_stop_and_close_never_touch_a_closed_database(tmp_path: Path):
    started = threading.Event()
    release = threading.Event()

    class SlowDiscovery:
        def discover(self, *_args, **_kwargs):
            started.set()
            release.wait(2)
            return [DiscoveredTrack(youtube("late"), 1, ["late"], "test")]

    database = MarianaDatabase(tmp_path / "station.db")
    manager = StationManager(database, PersistentQueue(database), SlowDiscovery())
    manager.start(youtube("seed"))
    assert started.wait(1)
    manager.stop()
    manager.close()
    database.close()
    release.set()
    time.sleep(0.05)
    assert manager._worker is None or not manager._worker.is_alive()


def test_inactive_station_commands_are_safe(tmp_path: Path):
    with MarianaDatabase(tmp_path / "station.db") as database:
        manager = StationManager(database, PersistentQueue(database), Discovery())
        assert manager.items() == []
        assert manager.payload() == {"state": "stopped", "next": []}
        manager.mark_played(youtube("none"))
        manager.close()
        for operation in (manager.pause, manager.resume, manager.stop, manager.more):
            with pytest.raises(StationError, match="No station"):
                operation()


def test_station_internal_cancellation_duplicate_and_worker_guards(tmp_path: Path, monkeypatch):
    with MarianaDatabase(tmp_path / "station.db") as database:
        queue = PersistentQueue(database)
        manager = StationManager(database, queue, Discovery([]))
        manager._start_worker(1)
        manager._generate("missing", 1, threading.Event())

        manager.start(youtube("seed"), limit=None)
        manager.wait_initial(3)
        manager.close()
        session = manager.session()
        manager._generate(session.session_id, 0, threading.Event())
        assert manager.session().state == StationState.EXHAUSTED

        manager._set_state(session.session_id, StationState.PAUSED, "paused", None)
        manager._start_worker(1)
        fake_worker = type("Worker", (), {"is_alive": lambda self: True})()
        manager._worker = fake_worker
        manager._set_state(session.session_id, StationState.LOADING, "loading", None)
        manager._start_worker(1)

        item = DiscoveredTrack(youtube("duplicate"), 1, ["reason"], "test")
        manager._append(session.session_id, item)
        before = len(manager.items(100, include_played=True))
        manager._append(session.session_id, item)
        assert len(manager.items(100, include_played=True)) == before

        new_item = DiscoveredTrack(youtube("queue-duplicate"), 1, ["reason"], "test")
        monkeypatch.setattr(queue, "add", lambda _media: (_ for _ in ()).throw(QueueError("already queued")))
        manager._append(session.session_id, new_item)
        bad_item = DiscoveredTrack(youtube("queue-failure"), 1, ["reason"], "test")
        monkeypatch.setattr(queue, "add", lambda _media: (_ for _ in ()).throw(QueueError("database failed")))
        with pytest.raises(QueueError, match="database failed"):
            manager._append(session.session_id, bad_item)

        manager._worker = None
        manager.stop()


def test_unlimited_window_prunes_only_played_items(tmp_path: Path, monkeypatch):
    removed = []
    with MarianaDatabase(tmp_path / "station.db") as database:
        queue = PersistentQueue(database)
        manager = StationManager(database, queue, Discovery([]))
        manager.start(youtube("seed"), limit=None)
        manager.wait_initial(3)
        session = manager.session()
        with database.transaction() as connection:
            for index in range(1, UNLIMITED_WINDOW + 3):
                media = youtube(f"bulk-{index}")
                connection.execute(
                    "INSERT INTO station_items(session_id,position,stable_id,media_json,provider,played,created_at) "
                    "VALUES(?,?,?,?,?, ?,?)",
                    (
                        session.session_id,
                        index,
                        media.stable_id,
                        json.dumps(media.to_dict()),
                        "test",
                        int(index != 1),
                        time.time(),
                    ),
                )
        monkeypatch.setattr(queue, "remove_media", lambda stable_id: removed.append(stable_id))
        manager._prune_unlimited(session.session_id)
        assert removed
        count = database.fetchone(
            "SELECT COUNT(*) AS count FROM station_items WHERE session_id=?", (session.session_id,)
        )["count"]
        assert count <= UNLIMITED_WINDOW + 1
        manager.stop()


def test_station_replacement_timeout_paused_completion_and_callback_errors(tmp_path: Path):
    second_discovery_started = threading.Event()
    release_second_discovery = threading.Event()

    class PauseGatedDiscovery(Discovery):
        def discover(self, seed, **kwargs):
            if seed.title == "second":
                second_discovery_started.set()
                assert release_second_discovery.wait(2), "second station discovery gate timed out"
            return super().discover(seed, **kwargs)

    def fail():
        raise RuntimeError("device unavailable")

    with MarianaDatabase(tmp_path / "station.db") as database:
        manager = StationManager(
            database,
            PersistentQueue(database),
            PauseGatedDiscovery([]),
            pause_playback=fail,
            resume_playback=fail,
        )
        first = manager.start(youtube("first"))
        assert manager.wait_initial(0).session_id == first.session_id
        second = manager.start(youtube("second"))
        assert second.session_id != first.session_id
        assert second_discovery_started.wait(1), "second discovery never reached pause gate"
        worker = manager._worker
        assert worker is not None
        manager.pause()
        assert manager.session().state == StationState.PAUSED
        manager.mark_played(youtube("none"))
        release_second_discovery.set()
        worker.join(timeout=2)
        assert not worker.is_alive()
        assert manager.session().state == StationState.PAUSED
        manager.resume()
        manager.close()
        manager.stop()
