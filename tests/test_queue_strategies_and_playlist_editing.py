from pathlib import Path

import pytest

import main
from beta import youtube_media
from mariana.command_parser import CommandSyntaxError, split_command
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, QueueStrategy
from mariana.playlists import PlaylistError, PlaylistStore
from mariana.queueing import PersistentQueue
from recommendation_engine import RecommendationEngine


def media(name: str, *, artist: str | None = None) -> MediaRef:
    return MediaRef(
        MediaSource.LOCAL,
        f"C:/music/{name}.mp3",
        title=name,
        artist=artist or f"artist-{name}",
    )


def titles(queue: PersistentQueue) -> list[str | None]:
    return [item.media.title for item in queue.items()]


def test_command_parser_preserves_windows_paths_and_quoted_names():
    assert split_command('playlist create "Road Trip" --description "A long drive"') == [
        "playlist",
        "create",
        "Road Trip",
        "--description",
        "A long drive",
    ]
    assert split_command('playlist export "Road Trip" "C:\\Music Library\\lists\\trip.m3u8"')[-1] == (
        "C:\\Music Library\\lists\\trip.m3u8"
    )
    assert split_command('queue group create ""')[-1] == ""
    assert split_command('playlist create "Say ""Hello"""')[-1] == 'Say "Hello"'
    with pytest.raises(CommandSyntaxError, match="Missing closing"):
        split_command('playlist create "unfinished')


def test_export_approval_is_invalidated_by_playlist_edit_without_writing_target(tmp_path):
    with MarianaDatabase(tmp_path / 'playlist.db') as database:
        store = PlaylistStore(database)
        store.create('Export', tree=store.snapshot_from_media([media('one')]))
        destination = tmp_path / 'selection.m3u8'
        target = store.bind_export('Export', destination)
        store.add_media_many('Export', [media('two')])
        with pytest.raises(PlaylistError, match='changed after export approval'):
            store.export_bound(target)
        assert not destination.exists()
        assert not list(tmp_path.glob('.*.tmp'))
        assert [item.title for item in store.flattened_media(store.get('Export').tree)] == ['one', 'two']


def test_empty_playlist_batch_and_current_revision_restore_do_not_create_revisions(tmp_path):
    with MarianaDatabase(tmp_path / 'playlist.db') as database:
        store = PlaylistStore(database)
        original = store.create('Keep', tree=store.snapshot_from_media([media('one')]))
        with pytest.raises(PlaylistError, match='At least one media item'):
            store.add_media_many('Keep', [])
        assert store.restore('Keep', original.revision) == original
        assert store.revisions('Keep') == [original.revision]
        assert store.get('Keep').tree == original.tree


def test_seeded_shuffle_cursor_priority_and_undo(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        for name in ("one", "two", "three", "four"):
            queue.add(media(name))
        current = queue.jump(1)
        baseline = queue.export_snapshot()

        assert queue.apply_strategy(QueueStrategy.SHUFFLE, seed=41) == 41
        shuffled = titles(queue)
        assert queue.current().queue_id == current.queue_id
        assert shuffled[:2] == ["one", "two"]
        assert queue.undo()
        queue.apply_strategy("shuffle", seed=41)
        assert titles(queue) == shuffled

        queue.restore_snapshot(baseline)
        with database.transaction() as connection:
            connection.execute("UPDATE queue_state SET current_id=NULL WHERE singleton=1")
        queue.set_priority("1", 2)
        queue.set_priority("2", 9)
        queue.apply_strategy("priority")
        assert titles(queue)[:2] == ["two", "one"]


def test_atomic_groups_artist_fair_smart_and_dedupe(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        group = queue.create_group("Album")
        queue.add(media("album-1", artist="A"), group_id=group.group_id)
        queue.add(media("album-2", artist="A"), group_id=group.group_id)
        for name, artist in (("a-1", "A"), ("a-2", "A"), ("b-1", "B"), ("b-2", "B")):
            queue.add(media(name, artist=artist))

        queue.apply_strategy("artist-fair")
        assert titles(queue) == ["album-1", "album-2", "b-1", "a-1", "b-2", "a-2"]
        assert titles(queue)[:2] == ["album-1", "album-2"]

        blocked = media("blocked", artist="Z")
        queue.add(blocked, position=0)
        recommender = RecommendationEngine(database, exploration=0, blocked=lambda value: value == blocked.stable_id)
        queue.apply_strategy("smart", seed=7, recommender=recommender)
        assert titles(queue)[-1] == "blocked"

        duplicate = media("duplicate")
        first = queue.add(duplicate)
        second = queue.add(duplicate, allow_duplicate=True)
        queue.jump(next(index for index, item in enumerate(queue.items()) if item.queue_id == second.queue_id))
        assert queue.dedupe("identity") == 1
        assert queue.current().queue_id == first.queue_id
        with pytest.raises(Exception, match="identity or uri"):
            queue.dedupe("title")


def test_playlist_tree_edits_order_import_export_and_queue_import(tmp_path: Path):
    source = tmp_path / "source.m3u8"
    source.write_text(
        "#EXTM3U\n#EXTINF:10,Remote\nhttps://example.test/a.mp3\n"
        "#EXTINF:20,Local\nrelative.mp3\n",
        encoding="utf-8",
    )
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        store = PlaylistStore(database)
        imported = store.import_m3u("Imported", source)
        assert imported.revision == 1
        assert [item.title for item in store.flattened_media(imported.tree)] == ["Remote", "Local"]

        playlist = store.create("Nested")
        playlist = store.add_media(playlist.playlist_id, media("one"))
        snapshot = PlaylistStore.snapshot_from_media([media("two"), media("three")])
        playlist = store.add_snapshot(
            playlist.playlist_id,
            snapshot,
            group_name="Album",
            position=0,
            kind="album",
        )
        assert [item.title for item in store.flattened_media(playlist.tree)] == ["two", "three", "one"]
        playlist = store.move_node(playlist.playlist_id, "2", parent="1", position=1)
        assert [item.title for item in store.flattened_media(playlist.tree)] == ["two", "one", "three"]
        playlist = store.order(playlist.playlist_id, "shuffle", group="1", seed=12)
        assert playlist.tree["groups"][0]["shuffle_seed"] == 12
        playlist = store.remove_node(playlist.playlist_id, "1.1")
        assert len(store.flattened_media(playlist.tree)) == 2

        destination = store.export_m3u(playlist.playlist_id, tmp_path / "export.m3u8")
        assert destination.read_text(encoding="utf-8").startswith("#EXTM3U\n")
        imported_items = queue.import_snapshot(
            playlist.tree,
            name=playlist.name,
            kind="playlist",
            source_ref=playlist.playlist_id,
        )
        assert len(imported_items) == 2
        assert queue.groups()[0].name == "Nested"


def test_playlist_cycles_invalid_strategy_and_flattened_queue_import(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        store = queue.playlists
        playlist = store.create("Tree")
        playlist = store.add_snapshot(
            playlist.playlist_id,
            PlaylistStore.snapshot_from_media([media("one")]),
            group_name="Parent",
        )
        playlist = store.add_snapshot(
            playlist.playlist_id,
            PlaylistStore.snapshot_from_media([media("two")]),
            group_name="Child",
            parent="1",
        )
        with pytest.raises(PlaylistError, match="cycle"):
            store.move_node(playlist.playlist_id, "1", parent="1.2")
        with pytest.raises(PlaylistError, match="Unknown playlist strategy"):
            store.order(playlist.playlist_id, "randomish")
        corrupt = PlaylistStore.snapshot_from_media([])
        corrupt["groups"].append(
            {
                "group_id": "orphan",
                "parent_id": "missing",
                "name": "Orphan",
                "sibling_position": 0,
            }
        )
        with pytest.raises(PlaylistError, match="orphaned"):
            store.create("Corrupt", tree=corrupt)
        queue.import_snapshot(playlist.tree, name="flat", kind="playlist", flatten=True)
        assert queue.groups() == []
        assert titles(queue) == ["one", "two"]


def test_youtube_playlist_snapshot_normalization(monkeypatch):
    monkeypatch.setattr(
        youtube_media,
        "_extract",
        lambda *_args, **_kwargs: {
            "id": "PL1",
            "title": "Example",
            "webpage_url": "https://www.youtube.com/playlist?list=PL1",
            "entries": [
                {"id": "abc", "title": "One", "uploader": "Artist", "duration": 12},
                None,
                {"title": "Missing ID"},
            ],
        },
    )
    result = youtube_media.playlist_entries("https://www.youtube.com/playlist?list=PL1")
    assert result["title"] == "Example"
    assert result["entries"] == [
        {
            "id": "abc",
            "title": "One",
            "url": "https://www.youtube.com/watch?v=abc",
            "duration": 12,
            "artist": "Artist",
            "playlist_index": 1,
        }
    ]
    with pytest.raises(youtube_media.YouTubeError, match="positive"):
        youtube_media.playlist_entries("https://example.test", limit=0)


def test_queue_and_playlist_cli_paths(monkeypatch, tmp_path: Path):
    output = []
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
        monkeypatch.setattr(main, "_play_queue_item", lambda _item: None)
        monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
        track = tmp_path / "Track One.mp3"
        track.touch()

        main.queue_command(["group", "create", "Set One"])
        main.queue_command(["tree"])
        main.queue_command(["priority", "1", "4"])
        main.queue_command(["order", "priority"])
        main.queue_command(["group", "atomic", "1", "off"])
        main.playlist_command(["create", "Road Trip", "--description", "Drive"])
        main.playlist_command(["add", "Road Trip", "media", str(track)])
        main.playlist_command(["show", "Road Trip", "--tree"])
        main.playlist_command(["queue", "Road Trip", "--at", "end"])
        main.playlist_command(["export", "Road Trip", str(tmp_path / "road.m3u8")])
        assert queue.playlists.get("Road Trip").description == "Drive"
        assert any("Created playlist" in value for value in output)


@pytest.mark.parametrize("operation", ["add", "group", "remove", "move", "order", "restore"])
def test_playlist_edits_reject_concurrent_writer_without_losing_either_revision(tmp_path, monkeypatch, operation):
    path = tmp_path / "shared.db"
    with MarianaDatabase(path) as first, MarianaDatabase(path) as second:
        store, other = PlaylistStore(first), PlaylistStore(second)
        playlist = store.create("Shared", tree=store.snapshot_from_media([media("one"), media("two")]))
        playlist = store.add_media(playlist.playlist_id, media("three"))
        original_save = store._save_revision

        def concurrent_save(expected, tree, **kwargs):
            other.add_media(playlist.playlist_id, media("other writer"))
            return original_save(expected, tree, **kwargs)

        monkeypatch.setattr(store, "_save_revision", concurrent_save)
        actions = {
            "add": lambda: store.add_media(playlist.playlist_id, media("stale addition")),
            "group": lambda: store.add_snapshot(playlist.playlist_id, store.snapshot_from_media([media("nested")]),
                                                 group_name="Nested"),
            "remove": lambda: store.remove_node(playlist.playlist_id, "1"),
            "move": lambda: store.move_node(playlist.playlist_id, "1", position=2),
            "order": lambda: store.order(playlist.playlist_id, "shuffle", seed=3),
            "restore": lambda: store.restore(playlist.playlist_id, 1),
        }
        with pytest.raises(PlaylistError, match="changed after confirmation"):
            actions[operation]()
        latest = store.get(playlist.playlist_id)
        assert latest.revision == 3
        assert [item.title for item in store.flattened_media(latest.tree)] == ["one", "two", "three", "other writer"]
        assert store.revisions(playlist.playlist_id) == [3, 2, 1]


def test_playlist_rename_away_and_back_invalidates_old_edits(tmp_path):
    with MarianaDatabase(tmp_path / "rename.db") as database:
        store = PlaylistStore(database)
        original = store.create("Original", tree=store.snapshot_from_media([media("one")]))
        store.rename("Original", "Temporary")
        latest = store.rename("Temporary", "Original")
        assert latest.revision == original.revision + 2
        with pytest.raises(PlaylistError, match="changed after confirmation"):
            store.save_snapshot("Original", store.snapshot_from_media([media("stale")]), expected=original)
        assert store.get("Original").tree == original.tree


def test_playlist_history_restore_survives_restart_and_preserves_previous_tree(tmp_path):
    path = tmp_path / "versions.db"
    with MarianaDatabase(path) as database:
        store = PlaylistStore(database)
        original = store.create("Collection", tree=store.snapshot_from_media([media("one")]))
        store.add_media(original.playlist_id, media("two"))
    with MarianaDatabase(path) as database:
        store = PlaylistStore(database)
        restored = store.restore("Collection", 1)
        assert restored.revision == 3
        assert [item.title for item in store.flattened_media(restored.tree)] == ["one"]
        recovered = store.restore("Collection", 2)
        assert recovered.revision == 4
        assert [item.title for item in store.flattened_media(recovered.tree)] == ["one", "two"]
        assert store.revisions("Collection") == [4, 3, 2, 1]


def test_playlist_restore_command_binds_revision_before_confirmation(tmp_path, monkeypatch):
    output = []
    with MarianaDatabase(tmp_path / "restore.db") as database:
        queue = PersistentQueue(database)
        store = queue.playlists
        store.create("Set", tree=store.snapshot_from_media([media("one")]))
        store.add_media("Set", media("two"))
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)

        def confirm(_question, **_kwargs):
            store.add_media("Set", media("newer edit"))
            return True

        monkeypatch.setattr(main, "_confirm_action", confirm)
        with pytest.raises(PlaylistError, match="changed after confirmation"):
            main.playlist_command(["restore", "Set", "1"])
        monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: True)
        main.playlist_command(["restore", "Set", "1", "--yes"])
        main.playlist_command(["history", "Set"])
        assert store.get("Set").revision == 4
        assert [item.title for item in store.flattened_media(store.get("Set").tree)] == ["one"]
        assert "available revisions: 4, 3, 2, 1" in output[-1]


def test_nested_queue_and_playlist_survive_repeated_ordering_and_reopen(tmp_path):
    path = tmp_path / "restarts.db"
    with MarianaDatabase(path) as database:
        queue = PersistentQueue(database)
        queue.add(media("active"))
        active_id = queue.jump(0).queue_id
        for album in range(5):
            group = queue.create_group(f"Album {album}", kind="album")
            for track in range(6):
                queue.add(media(f"{album}-{track}"), group_id=group.group_id)
        queue.save("Archive")
    for seed in range(25):
        with MarianaDatabase(path) as database:
            queue = PersistentQueue(database)
            before = titles(queue)
            assert queue.current().queue_id == active_id
            queue.apply_strategy("shuffle", seed=seed)
            ordered = titles(queue)
            assert queue.current().queue_id == active_id
            assert sorted(ordered) == sorted(before)
            for album in range(5):
                start = ordered.index(f"{album}-0")
                assert ordered[start:start + 6] == [f"{album}-{track}" for track in range(6)]
            queue.save("Archive")
    with MarianaDatabase(path) as database:
        queue = PersistentQueue(database)
        assert queue.current().queue_id == active_id
        assert titles(queue) == ordered
        assert len(queue.groups()) == 5
        assert queue.playlists.get("Archive").revision == 26
        assert len(queue.playlists.revisions("Archive")) == 26
