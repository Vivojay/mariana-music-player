import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.models import (
    IdentityStatus,
    MediaCapabilities,
    MediaChapter,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    StationSession,
    StationState,
    TrackIdentity,
    display_width,
    truncate_display_cells,
)
from mariana.queueing import CUSTOM_ORIGIN, DEFAULT_LIBRARY_ORIGIN, PersistentQueue, QueueError


def media(name: str) -> MediaRef:
    return MediaRef(MediaSource.LOCAL, f"C:/music/{name}.mp3", title=name)


def test_media_and_identity_contracts_round_trip():
    original = MediaRef(
        MediaSource.RADIO,
        "https://example.test/live",
        title="Station",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
        resolver_data={"endpoint": 2},
        chapters=[MediaChapter("Intro", 0, 12.5), MediaChapter("Song", 12.5, 60)],
    )
    restored = MediaRef.from_dict(original.to_dict())
    assert restored == original
    assert MediaRef(MediaSource.RADIO, original.original_uri).stable_id == original.stable_id
    assert restored.chapter_at(12.5).title == "Song"
    assert restored.chapter_at(60) is None
    assert PlaybackSnapshot(PlaybackState.PLAYING, media=restored, current_chapter=restored.chapters[0])
    assert StationSession("session", restored, state=StationState.PAUSED).state == StationState.PAUSED
    assert display_width("A界") == 3
    assert truncate_display_cells("A界BC", 4) == "A界…"
    assert truncate_display_cells("short", 10) == "short"
    assert truncate_display_cells("anything", 1) == "…"
    assert truncate_display_cells("anything", 0) == ""

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
        with pytest.raises(RuntimeError), database.transaction() as connection:
            connection.execute(
                "INSERT INTO app_state(key, value_json, updated_at) VALUES('bad', '{}', 0)"
            )
            raise RuntimeError("abort")
        assert database.get_state("bad") is None
        backup = database.backup(tmp_path / "backup.db")
    assert backup.is_file()


def test_failed_schema_migration_restores_verified_backup(monkeypatch, tmp_path: Path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES('schema_version', '3');"
        "CREATE TABLE retained(value TEXT);"
        "INSERT INTO retained VALUES('safe');"
    )
    connection.close()
    monkeypatch.setattr(MarianaDatabase, "migrate", lambda _self: (_ for _ in ()).throw(RuntimeError("fail")))
    with pytest.raises(RuntimeError, match="fail"):
        MarianaDatabase(path)
    restored = sqlite3.connect(path)
    try:
        assert restored.execute("SELECT value FROM retained").fetchone()[0] == "safe"
        assert restored.execute("SELECT value FROM schema_meta").fetchone()[0] == "3"
    finally:
        restored.close()


def test_fresh_database_migration_failure_has_no_backup_to_restore(monkeypatch, tmp_path: Path):
    path = tmp_path / "fresh.db"
    monkeypatch.setattr(MarianaDatabase, "migrate", lambda _self: (_ for _ in ()).throw(RuntimeError("fail")))
    with pytest.raises(RuntimeError, match="fail"):
        MarianaDatabase(path)
    assert path.is_file()
    assert not path.with_suffix(f".db.pre-schema-{SCHEMA_VERSION}.bak").exists()


def test_legacy_library_roots_schema_adds_origin_column(tmp_path: Path):
    path = tmp_path / "legacy-roots.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE library_roots(id TEXT PRIMARY KEY)")
    connection.commit()
    connection.close()

    with MarianaDatabase(path) as database:
        columns = {row["name"] for row in database.fetchall("PRAGMA table_info(library_roots)")}
        assert "origin" in columns


def test_legacy_media_schema_adds_chapters_and_station_tables(tmp_path: Path):
    path = tmp_path / "legacy-media.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE media_items(stable_id TEXT PRIMARY KEY);"
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES('schema_version', '4');"
    )
    connection.close()

    with MarianaDatabase(path) as database:
        columns = {row["name"] for row in database.fetchall("PRAGMA table_info(media_items)")}
        tables = {row["name"] for row in database.fetchall("SELECT name FROM sqlite_master")}
        assert "chapters_json" in columns
        assert {"station_sessions", "station_items"} <= tables


def test_legacy_play_counts_are_backed_up_and_imported_once(tmp_path: Path):
    user = tmp_path / "user.yml"
    user.write_text("default_user_data:\n  stats:\n    play_count:\n      local: 4\n      radio: 2\n      total: 6\n")
    with MarianaDatabase(tmp_path / "state.db") as database:
        assert database.migrate_legacy_play_counts(user) == {"local": 4, "radio": 2}
        assert user.with_suffix(".yml.pre-mariana-0.7.bak").is_file()
        user.write_text("default_user_data:\n  stats:\n    play_count:\n      local: 99\n")
        assert database.migrate_legacy_play_counts(user) == {"local": 4, "radio": 2}


def test_database_backup_validation_and_existing_legacy_backup(tmp_path: Path):
    class BadBackup:
        def execute(self, _sql):
            return SimpleNamespace(fetchone=lambda: ("corrupt",))

    with pytest.raises(Exception, match="integrity"):
        MarianaDatabase._verify_backup(BadBackup())

    user = tmp_path / "user.yml"
    user.write_text(
        "default_user_data:\n  stats:\n    play_count:\n      local: -2\n      invalid: nope\n      total: 99\n"
    )
    backup = user.with_suffix(".yml.pre-mariana-0.7.bak")
    backup.write_text("preserve")
    with MarianaDatabase(tmp_path / "existing-backup.db") as database:
        assert database.execute("SELECT 1").fetchone()[0] == 1
        assert database.migrate_legacy_play_counts(user) == {"local": 0}
    assert backup.read_text() == "preserve"


def test_queue_full_lifecycle_and_restart(tmp_path: Path):
    path = tmp_path / "mariana.db"
    with MarianaDatabase(path) as database:
        queue = PersistentQueue(database)
        queue.add(media("a"))
        chaptered = media("c")
        chaptered.chapters = [MediaChapter("Verse", 1, 2)]
        queue.add(chaptered)
        queue.add(media("b"), position=1, priority=10)
        assert [item.media.title for item in queue.items()] == ["a", "b", "c"]
        assert queue.jump(1).media.title == "b"
        queue.move(1, 2)
        assert [item.media.title for item in queue.items()] == ["a", "c", "b"]
        queue.swap(0, 2)
        assert [item.media.title for item in queue.items()] == ["b", "c", "a"]
        assert queue.items()[1].media.chapters[0].title == "Verse"

        snapshot = queue.export_snapshot()
        queue.clear()
        with pytest.raises(QueueError, match="object"):
            queue.restore_snapshot([])
        queue.restore_snapshot(snapshot)
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


def test_default_queue_tracks_library_order_until_explicitly_customized(tmp_path: Path):
    with MarianaDatabase(tmp_path / "default-queue.db") as database:
        queue = PersistentQueue(database)
        first, second, third = media("first"), media("second"), media("third")

        assert queue.sync_library_defaults([first, second])
        assert queue.origin() == DEFAULT_LIBRARY_ORIGIN
        assert [item.media.title for item in queue.items()] == ["first", "second"]
        queue.jump(1)

        assert queue.sync_library_defaults([first, second, third])
        assert queue.current().media.title == "second"
        assert [item.media.title for item in queue.items()] == ["first", "second", "third"]
        assert not queue.sync_library_defaults([first, second, third])

        queue.move(2, 0)
        assert queue.origin() == CUSTOM_ORIGIN
        assert not queue.sync_library_defaults([first, second])
        assert [item.media.title for item in queue.items()] == ["third", "first", "second"]

        assert queue.sync_library_defaults([first, second], force=True)
        assert queue.origin() == DEFAULT_LIBRARY_ORIGIN
        assert [item.media.title for item in queue.items()] == ["first", "second"]

        queue.clear()
        assert queue.origin() == CUSTOM_ORIGIN
        assert not queue.sync_library_defaults([first, second, third])
        assert queue.items() == []


def test_pre_origin_and_corrupt_origin_queues_are_preserved_as_custom(tmp_path: Path):
    with MarianaDatabase(tmp_path / "legacy-queue.db") as database:
        queue = PersistentQueue(database)
        queue.add(media("existing"))
        with database.transaction() as connection:
            connection.execute("DELETE FROM app_state WHERE key='queue_origin'")
        assert not queue.sync_library_defaults([media("replacement")])
        assert queue.origin() == CUSTOM_ORIGIN
        assert [item.media.title for item in queue.items()] == ["existing"]

        with database.transaction() as connection:
            connection.execute(
                "UPDATE app_state SET value_json='not-json' WHERE key='queue_origin'"
            )
        assert not queue.sync_library_defaults([media("replacement")])
        assert queue.origin() == CUSTOM_ORIGIN


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


def test_queue_extend_handles_duplicates_empty_inputs_and_unexpected_errors(tmp_path: Path, monkeypatch):
    with MarianaDatabase(tmp_path / "queue-extend.db") as database:
        queue = PersistentQueue(database)
        item = media("only")
        assert len(queue.extend([item, item])) == 1
        assert queue.extend([]) == []

        monkeypatch.setattr(queue, "add", lambda *_args, **_kwargs: (_ for _ in ()).throw(QueueError("broken")))
        with pytest.raises(QueueError, match="broken"):
            queue.extend([media("bad")])


def test_queue_consume_and_previous_nonwrapping_branches(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue-consume.db") as database:
        queue = PersistentQueue(database)
        queue.add(media("first"))
        queue.add(media("second"))
        queue.jump(0)
        queue.set_consume(True)
        assert queue.next().media.title == "second"
        assert [item.media.title for item in queue.items()] == ["second"]

        queue.set_consume(False)
        queue.add(media("third"))
        queue.jump(1)
        assert queue.previous().media.title == "second"

        queue.clear()
        queue.add(media("last"))
        queue.jump(0)
        queue.set_repeat("all")
        queue.set_consume(True)
        assert queue.next() is None


def test_queue_move_permutations_preserve_unique_order(tmp_path: Path):
    with MarianaDatabase(tmp_path / "property.db") as database:
        queue = PersistentQueue(database)

        @given(st.permutations((0, 1, 2, 3, 4)))
        @settings(deadline=None)
        def verify_permutation(permutation):
            queue.clear()
            for index in range(5):
                queue.add(media(str(index)))
            for destination, wanted in enumerate(permutation):
                current = [int(item.media.title) for item in queue.items()]
                queue.move(current.index(wanted), destination)
            items = queue.items()
            assert [int(item.media.title) for item in items] == list(permutation)
            assert [item.position for item in items] == list(range(5))

        verify_permutation()
