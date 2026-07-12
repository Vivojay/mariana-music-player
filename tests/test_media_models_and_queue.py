from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, settings, strategies as st

from mariana.database import MarianaDatabase, SCHEMA_VERSION
from mariana.models import MediaCapabilities, MediaRef, MediaSource, TrackIdentity, IdentityStatus
from mariana.queueing import PersistentQueue, QueueError


def media(name: str) -> MediaRef:
    return MediaRef(MediaSource.LOCAL, f"C:/music/{name}.mp3", title=name)


def test_media_and_identity_contracts_round_trip():
    original = MediaRef(
        MediaSource.RADIO,
        "https://example.test/live",
        title="Station",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
        resolver_data={"endpoint": 2},
    )
    restored = MediaRef.from_dict(original.to_dict())
    assert restored == original
    assert MediaRef(MediaSource.RADIO, original.original_uri).stable_id == original.stable_id

    identity = TrackIdentity(
        IdentityStatus.IDENTIFIED,
        recording_mbid="recording",
        confidence=0.94,
        provenance=["acoustid", "musicbrainz"],
    )
    assert TrackIdentity.from_dict(identity.to_dict()) == identity
    assert MediaRef(MediaSource.YOUTUBE, "https://youtu.be/abc12345678?utm_source=x").stable_id == MediaRef(
        MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abc12345678"
    ).stable_id


def test_database_migration_state_backup_and_rollback(tmp_path: Path):
    path = tmp_path / "state" / "mariana.db"
    with MarianaDatabase(path) as database:
        assert database.fetchone("SELECT value FROM schema_meta WHERE key='schema_version'")[0] == str(
            SCHEMA_VERSION
        )
        database.set_state("window", {"x": 4})
        assert database.get_state("window") == {"x": 4}
        with pytest.raises(RuntimeError):
            with database.transaction() as connection:
                connection.execute(
                    "INSERT INTO app_state(key, value_json, updated_at) VALUES('bad', '{}', 0)"
                )
                raise RuntimeError("abort")
        assert database.get_state("bad") is None
        backup = database.backup(tmp_path / "backup.db")
    assert backup.is_file()


def test_legacy_play_counts_are_backed_up_and_imported_once(tmp_path: Path):
    user = tmp_path / "user.yml"
    user.write_text("default_user_data:\n  stats:\n    play_count:\n      local: 4\n      radio: 2\n      total: 6\n")
    with MarianaDatabase(tmp_path / "state.db") as database:
        assert database.migrate_legacy_play_counts(user) == {"local": 4, "radio": 2}
        assert user.with_suffix(".yml.pre-mariana-0.7.bak").is_file()
        user.write_text("default_user_data:\n  stats:\n    play_count:\n      local: 99\n")
        assert database.migrate_legacy_play_counts(user) == {"local": 4, "radio": 2}


def test_queue_full_lifecycle_and_restart(tmp_path: Path):
    path = tmp_path / "mariana.db"
    with MarianaDatabase(path) as database:
        queue = PersistentQueue(database)
        queue.add(media("a"))
        queue.add(media("c"))
        queue.add(media("b"), position=1, priority=10)
        assert [item.media.title for item in queue.items()] == ["a", "b", "c"]
        assert queue.jump(1).media.title == "b"
        queue.move(1, 2)
        assert [item.media.title for item in queue.items()] == ["a", "c", "b"]
        queue.swap(0, 2)
        assert [item.media.title for item in queue.items()] == ["b", "c", "a"]
        queue.set_repeat("all")
        queue.set_consume(True)
        queue.set_autofill(True)
        queue.save("trip")
        assert queue.undo()
        assert not queue.state()["autofill"]
        assert queue.redo()
        assert queue.state()["autofill"]
        queue.clear()
        queue.load("trip")
        assert [item.media.title for item in queue.items()] == ["b", "c", "a"]

    with MarianaDatabase(path) as database:
        queue = PersistentQueue(database)
        assert [item.media.title for item in queue.items()] == ["b", "c", "a"]


def test_queue_deduplication_validation_and_navigation(tmp_path: Path):
    with MarianaDatabase(tmp_path / "mariana.db") as database:
        queue = PersistentQueue(database)
        queue.add(media("a"))
        with pytest.raises(QueueError, match="already queued"):
            queue.add(media("a"))
        duplicate = queue.add(media("a"), allow_duplicate=True)
        assert duplicate.queue_id is not None
        with pytest.raises(QueueError, match="Unknown failure"):
            queue.add(media("b"), failure_policy="explode")
        with pytest.raises(QueueError, match="Unknown repeat"):
            queue.set_repeat("sometimes")
        with pytest.raises(QueueError, match="out of range"):
            queue.jump(99)
        queue.jump(1)
        assert queue.next() is None
        queue.set_repeat("all")
        assert queue.next().position == 0
        queue.set_repeat("one")
        assert queue.next().queue_id == queue.current().queue_id


def test_queue_identity_dedup_and_bounded_failure_policies(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        first = media("first")
        first.resolver_data["recording_mbid"] = "same-recording"
        queue.add(first)
        duplicate = media("copy")
        duplicate.resolver_data["recording_mbid"] = "same-recording"
        with pytest.raises(QueueError, match="identified copy"):
            queue.add(duplicate)
        retry = queue.add(media("retry"), failure_policy="retry")
        assert queue.mark_failure(retry.queue_id) == "retry"
        assert queue.mark_failure(retry.queue_id) == "retry"
        assert queue.mark_failure(retry.queue_id) == "stop"
        skipped = queue.add(media("skip"), failure_policy="skip")
        assert queue.mark_failure(skipped.queue_id) == "skip"
        with pytest.raises(QueueError, match="Unknown queue item"):
            queue.mark_failure(99999)


def test_queue_empty_invalid_consume_and_saved_queue_compatibility(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        assert queue.next() is None and queue.previous() is None
        assert not queue.undo() and not queue.redo()
        with pytest.raises(QueueError, match="out of range"):
            queue.remove(0)
        with pytest.raises(QueueError, match="out of range"):
            queue.move(0, 1)
        with pytest.raises(QueueError, match="out of range"):
            queue.swap(0, 1)
        with pytest.raises(QueueError, match="cannot be empty"):
            queue.save(" ")
        with pytest.raises(QueueError, match="Unknown saved"):
            queue.load("missing")

        queue.add(media("only"))
        queue.jump(0)
        queue.set_consume(True)
        assert queue.next() is None
        queue.add(media("a"))
        queue.add(media("b"))
        queue.jump(0)
        queue.set_repeat("all")
        assert queue.previous().media.title == "b"
        queue.save("append")
        before = len(queue.items())
        queue.load("append", replace=False)
        assert len(queue.items()) == before * 2


@given(st.permutations((0, 1, 2, 3, 4)))
@settings(deadline=None)
def test_queue_move_permutations_preserve_unique_order(permutation):
    with TemporaryDirectory() as directory:
        with MarianaDatabase(Path(directory) / "property.db") as database:
            queue = PersistentQueue(database)
            for index in range(5):
                queue.add(media(str(index)))
            for destination, wanted in enumerate(permutation):
                current = [int(item.media.title) for item in queue.items()]
                queue.move(current.index(wanted), destination)
            items = queue.items()
            assert [int(item.media.title) for item in items] == list(permutation)
            assert [item.position for item in items] == list(range(5))
