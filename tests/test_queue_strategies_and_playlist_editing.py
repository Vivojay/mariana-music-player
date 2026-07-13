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
