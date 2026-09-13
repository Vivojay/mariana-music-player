import threading

from mariana.database import MarianaDatabase
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback_resume import PlaybackResumeStore, PlaybackResumeTracker


def long_media(
    stable_id: str = "durable-media-id",
    *,
    duration: float = 3600,
    live: bool = False,
    seekable: bool = True,
) -> MediaRef:
    return MediaRef(
        MediaSource.LOCAL,
        "ignored-local-path.mp3",
        stable_id=stable_id,
        duration=duration,
        capabilities=MediaCapabilities(finite=not live, live=live, seekable=seekable),
    )


def snapshot(media: MediaRef, position: float, state: PlaybackState = PlaybackState.PLAYING) -> PlaybackSnapshot:
    return PlaybackSnapshot(state=state, position=position, duration=media.duration, media=media)


def test_resume_position_persists_without_paths_and_is_cleared_near_completion(tmp_path):
    database_path = tmp_path / "resume.db"
    media = long_media()
    with MarianaDatabase(database_path) as database:
        store = PlaybackResumeStore(database)
        assert store.remember(snapshot(media, 725.25))
        row = database.fetchone("SELECT * FROM playback_resume_positions")
        assert row is not None
        assert dict(row) == {
            "stable_id": "durable-media-id",
            "position_seconds": 725.25,
            "duration_seconds": 3600.0,
            "updated_at": row["updated_at"],
        }
        assert "ignored-local-path" not in repr(dict(row))

    with MarianaDatabase(database_path) as database:
        row = database.fetchone(
            "SELECT position_seconds FROM playback_resume_positions WHERE stable_id=?",
            (media.stable_id,),
        )
        assert row is not None and row["position_seconds"] == 725.25
        store = PlaybackResumeStore(database)
        assert not store.remember(snapshot(media, 3550))
        assert database.fetchone("SELECT stable_id FROM playback_resume_positions") is None


def test_resume_store_rejects_short_live_nonseekable_and_early_positions(tmp_path):
    with MarianaDatabase(tmp_path / "resume.db") as database:
        store = PlaybackResumeStore(database)
        assert not store.remember(snapshot(long_media(duration=1199), 300))
        assert not store.remember(snapshot(long_media(live=True), 300))
        assert not store.remember(snapshot(long_media(seekable=False), 300))
        assert not store.remember(snapshot(long_media(), 59.9))
        assert database.fetchone("SELECT stable_id FROM playback_resume_positions") is None


def test_tracker_offers_saved_position_only_for_same_media_start(tmp_path):
    media = long_media()
    current = [snapshot(media, 0)]
    received: list[dict[str, object]] = []
    offered = threading.Event()

    def receive(payload: dict[str, object]) -> None:
        received.append(payload)
        offered.set()

    with MarianaDatabase(tmp_path / "resume.db") as database:
        store = PlaybackResumeStore(database)
        assert store.remember(snapshot(media, 754))
        tracker = PlaybackResumeTracker(database, lambda: current[0], receive, poll_interval=0.05)
        tracker.activate(current[0].media)
        assert offered.wait(1)
        assert received == [{
            "media_id": "durable-media-id",
            "position_seconds": 754.0,
            "duration_seconds": 3600.0,
            "schema_version": 1,
        }]

        offered.clear()
        other = long_media("other-media-id")
        current[0] = snapshot(other, 0)
        tracker.activate(current[0].media)
        assert not offered.wait(0.15)

        current[0] = snapshot(long_media(), 80)
        tracker.activate(current[0].media)
        assert not offered.wait(0.15)
        assert tracker.close()


def test_tracker_sampling_is_bounded_and_capture_failures_are_nonfatal(tmp_path):
    media = long_media()
    current = [snapshot(media, 420)]
    provider_fails = [False]

    def current_snapshot() -> PlaybackSnapshot:
        if provider_fails[0]:
            raise RuntimeError("snapshot unavailable")
        return current[0]

    with MarianaDatabase(tmp_path / "resume.db") as database:
        tracker = PlaybackResumeTracker(database, current_snapshot, lambda payload: None, poll_interval=10)
        assert tracker.capture_now()
        current[0] = snapshot(media, 425)
        assert not tracker.capture_now(force=False)
        provider_fails[0] = True
        assert not tracker.capture_now()
        assert tracker.status()["failures"] >= 1
        assert tracker.close()
