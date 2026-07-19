import json
import sqlite3
from pathlib import Path

import pytest

from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.models import MediaRef, MediaSource, QueueStrategy
from mariana.playlists import PlaylistError, PlaylistStore
from mariana.queueing import MAX_QUEUE_DEPTH, PersistentQueue, QueueError


def media(name: str) -> MediaRef:
    return MediaRef(MediaSource.LOCAL, f"C:/music/{name}.mp3", title=name, artist=f"artist-{name}")


def test_schema_six_migrates_flat_queue_and_named_queue(tmp_path: Path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES('schema_version','5');"
        "CREATE TABLE queue_items(id INTEGER PRIMARY KEY,stable_id TEXT,position INTEGER,priority INTEGER,"
        "added_at REAL,attempts INTEGER,failure_policy TEXT);"
        "INSERT INTO queue_items VALUES(1,'one',0,0,0,0,'skip');"
        "CREATE TABLE queue_state(singleton INTEGER PRIMARY KEY,current_id INTEGER,repeat_mode TEXT,"
        "shuffle_seed INTEGER,consume_mode INTEGER,autofill INTEGER,updated_at REAL);"
        "INSERT INTO queue_state VALUES(1,1,'off',NULL,0,0,0);"
        "CREATE TABLE named_queues(name TEXT PRIMARY KEY,items_json TEXT,updated_at REAL);"
        "INSERT INTO named_queues VALUES('Road Trip','[]',1);"
    )
    connection.close()

    with MarianaDatabase(path) as database:
        item_columns = {row["name"] for row in database.fetchall("PRAGMA table_info(queue_items)")}
        state_columns = {row["name"] for row in database.fetchall("PRAGMA table_info(queue_state)")}
        assert {"group_id", "sibling_position"} <= item_columns
        assert {"root_strategy", "root_seed"} <= state_columns
        assert database.fetchone("SELECT sibling_position FROM queue_items")[0] == 0
        assert PlaylistStore(database).get("road trip").tree == {"legacy_items": []}
        assert database.get_state("unused") is None
        assert database.fetchone("SELECT value FROM schema_meta WHERE key='schema_version'")[0] == str(SCHEMA_VERSION)
    assert path.with_suffix(f".db.pre-schema-{SCHEMA_VERSION}.bak").is_file()


def test_hierarchical_groups_compile_to_stable_leaf_order_and_snapshot(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        queue.add(media("root-a"))
        queue.add(media("root-b"))
        album = queue.create_group("Album", position=1, kind="album", source_ref="album:test")
        queue.add(media("track-1"), group_id=album.group_id)
        queue.add(media("track-2"), group_id=album.group_id)
        disc = queue.create_group("Disc 2", parent=album.group_id)
        queue.add(media("track-3"), group_id=disc.group_id)

        assert [item.media.title for item in queue.items()] == [
            "root-a",
            "track-1",
            "track-2",
            "track-3",
            "root-b",
        ]
        tree = queue.tree()
        assert tree[1]["path"] == "2"
        assert tree[1]["children"][2]["path"] == "2.3"
        assert queue.resolve_node("2.3")["group"].name == "Disc 2"
        assert queue.resolve_node(album.group_id)["path"] == "2"

        queue.jump(2)
        snapshot = queue.export_snapshot()
        queue.clear()
        queue.restore_snapshot(snapshot)
        assert queue.current().media.title == "track-2"
        assert [group.name for group in queue.groups()] == ["Album", "Disc 2"]
        assert queue.groups()[0].strategy == QueueStrategy.CUSTOM


def test_group_moves_flatten_recursive_removal_and_depth_guards(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        parent = queue.create_group("Parent")
        child = queue.create_group("Child", parent=parent.group_id)
        queue.add(media("inside"), group_id=child.group_id)
        sibling = queue.create_group("Sibling")

        with pytest.raises(QueueError, match="cycle"):
            queue.move_group(parent.group_id, parent=child.group_id)
        moved = queue.move_group(child.group_id, parent=sibling.group_id)
        assert moved.parent_id == sibling.group_id
        queue.set_group_atomic(sibling.group_id, False)
        assert not queue.resolve_node(sibling.group_id)["group"].atomic
        queue.rename_group(sibling.group_id, "Renamed")
        assert queue.resolve_node(sibling.group_id)["group"].name == "Renamed"

        with pytest.raises(QueueError, match="not empty"):
            queue.remove_group(sibling.group_id)
        queue.remove_group(sibling.group_id, flatten=True)
        assert queue.resolve_node(child.group_id)["group"].parent_id is None
        queue.remove_group(child.group_id, recursive=True)
        assert queue.items() == []

        current = parent.group_id
        for index in range(1, MAX_QUEUE_DEPTH):
            current = queue.create_group(f"level-{index}", parent=current).group_id
        with pytest.raises(QueueError, match="cannot exceed"):
            queue.create_group("too-deep", parent=current)


def test_cross_group_flat_moves_are_refused_without_losing_state(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        first = queue.create_group("First")
        second = queue.create_group("Second")
        queue.add(media("one"), group_id=first.group_id)
        queue.add(media("two"), group_id=second.group_id)
        before = queue.export_snapshot()
        with pytest.raises(QueueError, match="Cross-group"):
            queue.move(0, 1)
        with pytest.raises(QueueError, match="Cross-group"):
            queue.swap(0, 1)
        assert queue.export_snapshot()["items"] == before["items"]


def test_playlist_crud_versions_and_queue_compatibility(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        store = queue.playlists
        created = store.create("Road Trip", description="Long drive")
        assert store.get(created.playlist_id).name == "Road Trip"
        with pytest.raises(PlaylistError, match="already exists"):
            store.create("road trip")
        with pytest.raises(PlaylistError, match="cannot be empty"):
            store.create(" ")

        queue.add(media("one"))
        group = queue.create_group("Set")
        queue.add(media("two"), group_id=group.group_id)
        queue.save("Road Trip")
        assert store.get("road trip").revision == 2
        assert store.revisions("Road Trip") == [2, 1]

        renamed = store.rename("Road Trip", "Night Drive")
        assert renamed.name == "Night Drive"
        queue.clear()
        queue.load("night drive")
        assert [item.media.title for item in queue.items()] == ["one", "two"]
        assert queue.groups()[0].name == "Set"
        restored = store.restore("Night Drive", 1)
        assert restored.revision == 3 and restored.tree["items"] == []
        assert store.clear("Night Drive").tree["items"] == []
        assert store.delete("Night Drive").name == "Night Drive"
        with pytest.raises(PlaylistError, match="Unknown playlist"):
            store.get("Night Drive")


def test_bound_playlist_delete_and_clear_refuse_changed_targets(tmp_path: Path):
    with MarianaDatabase(tmp_path / "playlist-mutation.db") as database:
        store = PlaylistStore(database)
        playlist = store.create(
            "Bound",
            tree=PlaylistStore.snapshot_from_media([media("one")]),
        )

        stale_clear = store.bind_mutation(playlist.playlist_id)
        store.save_snapshot("Bound", PlaylistStore.snapshot_from_media([media("two")]))
        with pytest.raises(PlaylistError, match="changed after confirmation"):
            store.clear_bound(stale_clear)
        assert [item.title for item in store.flattened_media(store.get("Bound").tree)] == ["two"]

        stale_delete = store.bind_mutation(playlist.playlist_id)
        store.rename("Bound", "Renamed")
        with pytest.raises(PlaylistError, match="changed after confirmation"):
            store.delete_bound(stale_delete)
        assert store.get("Renamed").playlist_id == playlist.playlist_id


def test_bound_playlist_mutation_refuses_missing_target(tmp_path: Path):
    with MarianaDatabase(tmp_path / "playlist-missing.db") as database:
        store = PlaylistStore(database)
        target = store.bind_mutation(store.create("Temporary").playlist_id)
        store.delete(target.playlist_id)

        with pytest.raises(PlaylistError, match="no longer available"):
            store.delete_bound(target)


def test_corrupt_playlist_payload_is_typed(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        store = PlaylistStore(database)
        playlist = store.create("Broken")
        with database.transaction() as connection:
            connection.execute(
                "UPDATE playlists SET tree_json=? WHERE playlist_id=?",
                (json.dumps(["not", "an", "object"]), playlist.playlist_id),
            )
        with pytest.raises(PlaylistError, match="object"):
            store.get("Broken")
