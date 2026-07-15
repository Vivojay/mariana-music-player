import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import main
from mariana.albums import (
    AlbumCatalog,
    AlbumError,
    _artist_credit,
    _duration_seconds,
    _positive_number,
)
from mariana.database import MarianaDatabase
from mariana.download_jobs import DownloadJobError, DownloadManager, canonical_youtube_url
from mariana.models import (
    AlbumRef,
    AlbumTrack,
    DownloadState,
    MediaRef,
    MediaSource,
)
from mariana.playlists import MAX_PLAYLIST_DEPTH, PlaylistError, PlaylistStore, playlist_name
from mariana.queueing import PersistentQueue, QueueError
from recommendation_engine import RecommendationEngine


def media(name: str, *, artist: str | None = None) -> MediaRef:
    return MediaRef(
        MediaSource.LOCAL,
        f"C:/music/{name}.mp3",
        title=name,
        artist=artist,
    )


def youtube(video_id: str, title: str = "Track") -> MediaRef:
    return MediaRef(
        MediaSource.YOUTUBE,
        f"https://www.youtube.com/watch?v={video_id}",
        title=title,
        artist="Artist",
        resolver_data={"video_id": video_id, "secret": "remove-me"},
    )


def test_playlist_validation_legacy_conversion_and_revision_errors(tmp_path: Path):
    with pytest.raises(PlaylistError, match="160"):
        playlist_name("x" * 161)
    with pytest.raises(PlaylistError, match="corrupt"):
        PlaylistStore._decode_tree("{")
    with pytest.raises(PlaylistError, match="object"):
        PlaylistStore._normalized_tree(cast(Any, []))
    with pytest.raises(PlaylistError, match="lists"):
        PlaylistStore._normalized_tree({"groups": {}, "items": []})
    with pytest.raises(PlaylistError, match="state"):
        PlaylistStore._normalized_tree({"groups": [], "items": [], "state": []})

    legacy = PlaylistStore._normalized_tree(
        {
            "legacy_items": [
                media("direct").to_dict(),
                {"media": media("wrapped").to_dict(), "priority": 4},
                {"media": "invalid"},
            ]
        }
    )
    assert [item["media"]["title"] for item in legacy["items"]] == ["direct", "wrapped"]
    assert legacy["items"][1]["priority"] == 4

    with MarianaDatabase(tmp_path / "playlists.db") as database:
        store = PlaylistStore(database)
        first = store.create("First")
        store.create("Second")
        with pytest.raises(PlaylistError, match="already exists"):
            store.rename(first.playlist_id, "Second")
        assert store.restore("First", first.revision).playlist_id == first.playlist_id
        with pytest.raises(PlaylistError, match="Unknown playlist revision"):
            store.restore("First", 99)


def test_playlist_tree_depth_parent_move_remove_and_order_edges(tmp_path: Path):
    with MarianaDatabase(tmp_path / "playlists.db") as database:
        store = PlaylistStore(database)
        playlist = store.create("Tree")
        playlist = store.add_media(playlist.playlist_id, media("root", artist="A"))
        with pytest.raises(PlaylistError, match="parent must reference a group"):
            store.add_media(playlist.playlist_id, media("bad"), parent="1")
        with pytest.raises(PlaylistError, match="parent must reference a group"):
            store.add_snapshot(
                playlist.playlist_id,
                PlaylistStore.snapshot_from_media([media("bad")]),
                group_name="Bad",
                parent="1",
            )

        playlist = store.add_snapshot(
            playlist.playlist_id,
            PlaylistStore.snapshot_from_media([media("one", artist="A"), media("two", artist="B")]),
            group_name="Group",
            position=0,
        )
        with pytest.raises(PlaylistError, match="parent must reference a group"):
            store.move_node(playlist.playlist_id, "1", parent="2")
        playlist = store.move_node(playlist.playlist_id, "2", parent="1", position=0)
        assert [value.title for value in store.flattened_media(playlist.tree)] == ["root", "one", "two"]
        playlist = store.order(playlist.playlist_id, "artist-fair", group="1")
        playlist = store.order(playlist.playlist_id, "priority", group="1")
        with pytest.raises(PlaylistError, match="recommendation ranks"):
            store.order(playlist.playlist_id, "smart", group="1")
        ranks = {value.stable_id: index for index, value in enumerate(store.flattened_media(playlist.tree))}
        playlist = store.order(playlist.playlist_id, "smart", group="1", media_ranks=ranks)
        playlist = store.order(playlist.playlist_id, "sequential")
        playlist = store.order(playlist.playlist_id, "shuffle")
        assert isinstance(playlist.tree["state"]["root_seed"], int)
        playlist = store.remove_node(playlist.playlist_id, "1.1")
        playlist = store.remove_node(playlist.playlist_id, "1")
        assert store.flattened_media(playlist.tree) == []

        groups = []
        parent = None
        for index in range(MAX_PLAYLIST_DEPTH + 1):
            identifier = f"g{index}"
            groups.append({"group_id": identifier, "parent_id": parent, "sibling_position": 0})
            parent = identifier
        with pytest.raises(PlaylistError, match="nesting"):
            store.create("Too deep", tree={"groups": groups, "items": [], "state": {}})


def test_playlist_m3u_boundaries_and_atomic_export(tmp_path: Path):
    with MarianaDatabase(tmp_path / "playlists.db") as database:
        store = PlaylistStore(database)
        with pytest.raises(PlaylistError, match="existing"):
            store.import_m3u("Bad", tmp_path / "missing.txt")
        source = tmp_path / "mixed.m3u"
        source.write_text(
            "\ufeff#EXTM3U\n#EXTINF:12,Remote title\nhttps://example.test/a.mp3\n"
            "https://youtu.be/abc123\nrelative.mp3\n",
            encoding="utf-8",
        )
        playlist = store.import_m3u("Mixed", source)
        values = store.flattened_media(playlist.tree)
        assert [value.source for value in values] == [MediaSource.URL, MediaSource.YOUTUBE, MediaSource.LOCAL]
        assert values[0].title == "Remote title"
        with pytest.raises(PlaylistError, match="must end"):
            store.export_m3u("Mixed", tmp_path / "bad.txt")
        exported = store.export_m3u("Mixed", tmp_path / "nested" / "mixed.m3u8")
        assert exported.is_file() and not exported.with_suffix(".m3u8.tmp").exists()


def test_queue_hierarchy_rejects_item_parents_and_corrupt_snapshots(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        item = queue.add(media("one"))
        for action in (
            lambda: queue.create_group("Bad", parent="1"),
            lambda: queue.rename_group("1", "Bad"),
            lambda: queue.set_group_atomic("1", True),
            lambda: queue.move_group("1"),
            lambda: queue.remove_group("1", recursive=True),
            lambda: queue.apply_strategy("shuffle", group="1"),
        ):
            with pytest.raises(QueueError):
                action()
        with pytest.raises(QueueError, match="cannot be empty"):
            queue.resolve_node("")
        with pytest.raises(QueueError, match="Unknown queue"):
            queue.resolve_node("99")
        group = queue.create_group("Group")
        with pytest.raises(QueueError, match="contain itself"):
            queue.move_group(group.group_id, parent=group.group_id)
        before = queue.export_snapshot()
        corrupt = {
            "groups": [{"group_id": "orphan", "parent_id": "missing"}],
            "items": [],
            "state": {},
        }
        with pytest.raises(QueueError, match="orphaned"):
            queue.restore_snapshot(corrupt)
        assert queue.export_snapshot()["items"] == before["items"]
        with pytest.raises(QueueError, match="object"):
            queue.import_snapshot(cast(Any, []), name="Bad", kind="playlist")
        with pytest.raises(QueueError, match="next, end"):
            queue.root_insert_position("middle")
        queue.jump(0)
        assert queue.root_insert_position("next") == 1
        assert queue.current() is not None and item.queue_id is not None


class MetadataClient:
    def __init__(self, payload: dict[str, Any] | None = None):
        self.payload = payload

    def search_releases(
        self, query: str, *, limit: int = 10, offset: int = 0, refresh: bool = False
    ) -> list[dict[str, Any]]:
        del query, limit, offset, refresh
        return []

    def release(self, mbid: str, refresh: bool = False) -> dict[str, Any] | None:
        del mbid, refresh
        return self.payload


def test_album_helpers_search_corruption_fetch_and_selector_errors(tmp_path: Path):
    assert _positive_number("2/3", 1) == 2
    assert _positive_number("bad", 7) == 7
    assert _positive_number(0, 7) == 7
    assert _duration_seconds("1500") == 1.5
    assert _duration_seconds("bad") is None
    assert _artist_credit({"artist-credit": ["A", {"artist": {"name": "B"}, "joinphrase": " & "}]}) == "AB &"

    with MarianaDatabase(tmp_path / "albums.db") as database:
        catalog = AlbumCatalog(database, musicbrainz=MetadataClient())
        with pytest.raises(AlbumError, match="scope"):
            catalog.search("Album", scope="space")
        with pytest.raises(AlbumError, match="query"):
            catalog.search(" ")
        with pytest.raises(AlbumError, match="positive"):
            catalog.search("Album", limit=0)
        with pytest.raises(AlbumError, match="Unknown album"):
            catalog.get("missing")

        album = catalog._persist(AlbumRef("no-id", "Tags only"))
        with pytest.raises(AlbumError, match="no release identity"):
            catalog.fetch(album.album_id)
        catalog._persist(AlbumRef("has-id", "Remote", release_mbid="release"))
        with pytest.raises(AlbumError, match="could not retrieve"):
            catalog.fetch("has-id", refresh=True)
        with database.transaction() as connection:
            connection.execute("UPDATE albums SET album_json='{' WHERE album_id='has-id'")
        with pytest.raises(AlbumError, match="corrupt"):
            catalog.get("has-id")

    tracks = [AlbumTrack("One", position=1, disc_number=1, track_number=1)]
    album = AlbumRef("selectors", "Selectors", tracks=tracks)
    for selector, message in (("", None), ("x", "Invalid"), ("a.b", "Invalid"), ("1,", "empty"), ("1-2", "does not exist")):
        if message is None:
            assert AlbumCatalog.select_tracks(album, selector) == tracks
        else:
            with pytest.raises(AlbumError, match=message):
                AlbumCatalog.select_tracks(album, selector)
    with pytest.raises(AlbumError, match="Unknown album order"):
        AlbumCatalog.order_tracks(tracks, "random")
    with pytest.raises(AlbumError, match="recommendation engine"):
        AlbumCatalog.order_tracks(tracks, "smart")


@pytest.mark.parametrize(
    ("search_results", "details"),
    [
        ([], {}),
        ([{"id": "x"}], {}),
        ([{"id": "x", "url": "https://www.youtube.com/watch?v=abc"}], {"track": "Wrong", "artist": "Artist"}),
        ([{"id": "x", "url": "https://www.youtube.com/watch?v=abc"}], {"track": "Song", "artist": "Wrong"}),
        ([{"id": "x", "url": "https://www.youtube.com/watch?v=abc"}], {"track": "Song", "artist": "Artist", "duration": 999}),
        ([{"id": "x", "url": "https://www.youtube.com/watch?v=abc"}], {"categories": ["Music"], "is_live": True}),
    ],
)
def test_album_youtube_verification_rejects_unsafe_candidates(tmp_path: Path, search_results, details):
    with MarianaDatabase(tmp_path / "album.db") as database:
        catalog = AlbumCatalog(
            database,
            musicbrainz=MetadataClient(),
            youtube_search=lambda *_args, **_kwargs: search_results,
            youtube_info=lambda *_args, **_kwargs: details,
        )
        album = AlbumRef("album", "Album", album_artist="Artist")
        track = AlbumTrack("Song", artist="Artist", duration=180)
        assert catalog._youtube_media(album, track) is None


class NoOutputDownloader:
    def __init__(self, options: dict[str, Any]):
        self.options = options

    def __enter__(self) -> "NoOutputDownloader":
        return self

    def __exit__(self, *_args: Any) -> bool:
        return False

    def extract_info(self, _url: str, *, download: bool) -> dict[str, Any]:
        assert download
        return {"id": "abc", "title": "Track"}


def test_download_creation_controls_options_progress_and_timeout(tmp_path: Path):
    updates = []
    with MarianaDatabase(tmp_path / "downloads.db") as database:
        manager = DownloadManager(
            database,
            ffmpeg_bin="~/ffmpeg/bin",
            browser_profile="chrome:Default",
            on_update=updates.append,
            autostart=False,
        )
        try:
            for kwargs, message in (
                ({"media_items": [youtube("abc")], "kind": "batch", "destination": tmp_path}, "kind"),
                ({"media_items": [], "destination": tmp_path}, "no media"),
                ({"media_items": [youtube("abc")], "metadata": [], "destination": tmp_path}, "align"),
            ):
                with pytest.raises(DownloadJobError, match=message):
                    manager.create(**kwargs)
            job = manager.create([youtube("abc")], destination=tmp_path)
            assert manager.status(job.job_id)[0]["items"][0]["media"]["resolver_data"] == {
                "video_id": "abc",
                "youtube": True,
            }
            item = manager.items(job.job_id)[0]
            with database.transaction() as connection:
                connection.execute("UPDATE download_jobs SET state='running' WHERE job_id=?", (job.job_id,))
            manager._progress_hook(item, {"downloaded_bytes": 5, "total_bytes_estimate": 10})
            assert manager.items(job.job_id)[0].progress == 0.5
            options = manager._options(item, tmp_path / "staging", "best")
            assert options["noplaylist"] and options["ffmpeg_location"].endswith("ffmpeg/bin")
            assert options["cookiesfrombrowser"]
            with pytest.raises(TimeoutError):
                manager.wait(job.job_id, timeout=0)
            assert updates
        finally:
            manager.close()


def test_download_idempotent_controls_missing_output_and_callback_isolation(tmp_path: Path):
    with MarianaDatabase(tmp_path / "downloads.db") as database:
        manager = DownloadManager(
            database,
            downloader_factory=NoOutputDownloader,
            on_update=lambda _payload: (_ for _ in ()).throw(RuntimeError("UI unavailable")),
        )
        job = manager.create([youtube("abc")], destination=tmp_path)
        failed = manager.wait(job.job_id)
        assert failed.state == DownloadState.FAILED
        assert "without producing" in (failed.error or "")
        manager.close()

        controls = DownloadManager(database, autostart=False)
        try:
            controls.pause(job.job_id)
            assert controls.pause(job.job_id).state == DownloadState.PAUSED
            controls.resume(job.job_id)
            assert controls.resume(job.job_id).state == DownloadState.QUEUED
            controls.cancel(job.job_id)
            assert controls.cancel(job.job_id).state == DownloadState.CANCELLED
            with database.transaction() as connection:
                connection.execute("UPDATE download_jobs SET state='completed' WHERE job_id=?", (job.job_id,))
            with pytest.raises(DownloadJobError, match="cannot be paused"):
                controls.pause(job.job_id)
            with pytest.raises(DownloadJobError, match="cannot be resumed"):
                controls.resume(job.job_id)
        finally:
            controls.close()


def test_playlist_structural_validation_and_nested_snapshot_branches(tmp_path: Path):
    duplicate = {
        "groups": [
            {"group_id": "same", "parent_id": None, "sibling_position": 0},
            {"group_id": "same", "parent_id": None, "sibling_position": 1},
        ],
        "items": [],
        "state": {},
    }
    with pytest.raises(PlaylistError, match="unique"):
        PlaylistStore._tree_nodes(duplicate)
    with pytest.raises(PlaylistError, match="malformed"):
        PlaylistStore._tree_nodes({"groups": [None], "items": [], "state": {}})

    with MarianaDatabase(tmp_path / "playlist-structure.db") as database:
        store = PlaylistStore(database)
        playlist = store.create("Nested")
        playlist = store.add_snapshot(
            playlist.playlist_id,
            {
                "groups": [
                    {"group_id": "parent", "parent_id": None, "name": "Parent", "sibling_position": 0},
                    {"group_id": "child", "parent_id": "parent", "name": "Child", "sibling_position": 0},
                ],
                "items": [
                    {
                        "stable_id": media("nested").stable_id,
                        "media": media("nested").to_dict(),
                        "group_id": "child",
                        "sibling_position": 0,
                    },
                    {"stable_id": "invalid", "media": None, "group_id": None, "sibling_position": 1},
                ],
                "state": {},
            },
            group_name="Wrapper",
        )
        nodes = store.nodes(playlist.playlist_id)
        nested_id = nodes[0]["children"][0]["children"][0]["id"]
        assert store._resolve(playlist.tree, nested_id)["type"] == "group"
        assert store.flattened_media(playlist.tree)[0].title == "nested"
        with pytest.raises(PlaylistError, match="Unknown playlist path"):
            store._resolve(playlist.tree, "9.9")
        with pytest.raises(PlaylistError, match="Unknown playlist node"):
            store._resolve(playlist.tree, "missing-id")
        with pytest.raises(PlaylistError, match="scope must reference a group"):
            store.order(playlist.playlist_id, "shuffle", group="1.1.1.1")
        playlist = store.add_media(playlist.playlist_id, media("inside"), parent="1")
        assert any(value.title == "inside" for value in store.flattened_media(playlist.tree))


def test_queue_private_guards_nested_next_uri_removal_and_legacy_load(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue-branches.db") as database:
        queue = PersistentQueue(database)
        with database.transaction() as connection:
            with pytest.raises(QueueError, match="nesting"):
                queue._flatten_ids(connection, depth=9)
            assert queue._node_media(connection, "group", "missing") == []
            assert queue._node_priority(connection, "group", "missing") == 0
            with pytest.raises(QueueError, match="parent is missing"):
                queue._group_depth(connection, "missing")

        with pytest.raises(QueueError, match="name cannot be empty"):
            queue.create_group(" ")
        outer = queue.create_group("Outer")
        inner = queue.create_group("Inner", parent=outer.group_id)
        inside = queue.add(media("inside"), group_id=inner.group_id)
        queue.jump(0)
        assert queue.root_insert_position("next") == 1
        assert queue.root_insert_position(999) == 1
        assert queue.root_insert_position(-4) == 0
        with pytest.raises(QueueError, match="name cannot be empty"):
            queue.rename_group(outer.group_id, " ")
        with pytest.raises(QueueError, match="Unknown queue group"):
            queue.add(media("unknown"), group_id="missing")

        removed = queue.remove_media("not-the-id", inside.media.original_uri)
        assert [item.queue_id for item in removed] == [inside.queue_id]
        assert queue.current() is None
        assert queue.remove_media("missing") == []

        legacy = queue.playlists.create("Legacy")
        legacy_tree = {
            "legacy_items": [
                media("raw").to_dict(),
                {"media": media("wrapped").to_dict(), "priority": 9, "failure_policy": "stop"},
            ]
        }
        with database.transaction() as connection:
            connection.execute(
                "UPDATE playlists SET tree_json=? WHERE playlist_id=?",
                (json.dumps(legacy_tree), legacy.playlist_id),
            )
        assert [item.media.title for item in queue.load("Legacy", replace=False)] == ["raw", "wrapped"]


def test_queue_strategy_recursion_dedupe_and_failure_policy_branches(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue-strategy.db") as database:
        queue = PersistentQueue(database)
        open_group = queue.create_group("Open", atomic=False)
        queue.add(media("a1", artist="A"), group_id=open_group.group_id)
        queue.add(media("a2", artist="A"), group_id=open_group.group_id)
        queue.add(media("a3", artist="A"), group_id=open_group.group_id)
        queue.add(media("a4", artist="A"), group_id=open_group.group_id)
        empty = queue.create_group("Empty")
        with pytest.raises(QueueError, match="recommendation engine"):
            queue.apply_strategy("smart")
        recommender = RecommendationEngine(database, exploration=0, blocked=lambda _stable_id: True)
        queue.apply_strategy("smart", seed=4, recommender=recommender)
        queue.apply_strategy("artist-fair", group=open_group.group_id)
        queue.apply_strategy("priority", group=open_group.group_id)
        queue.apply_strategy("sequential", group=empty.group_id)
        assert queue.shuffle() >= 0
        with pytest.raises(QueueError, match="Unknown queue strategy"):
            queue.apply_strategy("chaos")

        first = media("uri")
        queue.add(first)
        queue.add(first, allow_duplicate=True)
        assert queue.dedupe("uri") == 1
        assert queue.dedupe("uri") == 0
        stopped = queue.add(media("stop"), failure_policy="stop")
        assert queue.mark_failure(cast(int, stopped.queue_id)) == "stop"


def test_queue_recursive_removal_rehomes_cursor_and_import_validation(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue-remove.db") as database:
        queue = PersistentQueue(database)
        queue.add(media("survivor"))
        group = queue.create_group("Delete")
        queue.add(media("gone"), group_id=group.group_id)
        queue.jump(1)
        queue.remove_group(group.group_id, recursive=True)
        current = queue.current()
        assert current is not None and current.media.title == "survivor"

        corrupt = {
            "groups": [{"group_id": "child", "parent_id": "missing"}],
            "items": [],
            "state": {},
        }
        with pytest.raises(QueueError, match="orphaned"):
            queue.import_snapshot(corrupt, name="Corrupt", kind="playlist")
        valid = {
            "groups": [{"group_id": "root", "parent_id": None, "name": "Root"}],
            "items": [
                {"stable_id": "ignored", "media": None, "group_id": "root"},
                {
                    "stable_id": media("imported").stable_id,
                    "media": media("imported").to_dict(),
                    "group_id": "root",
                },
            ],
            "state": {},
        }
        assert [item.media.title for item in queue.import_snapshot(valid, name="Valid", kind="playlist")] == ["imported"]


def test_album_remote_parsing_search_deduplication_and_cached_fetch(tmp_path: Path):
    payload = {
        "id": "release",
        "title": "Album",
        "artist-credit": [{"name": "Artist"}],
        "media": [
            None,
            {
                "position": "bad",
                "tracks": [
                    None,
                    {"position": "bad", "recording": {}},
                    {
                        "number": "2",
                        "length": "2000",
                        "artist-credit": [{"name": "Track Artist"}],
                        "recording": {"id": "recording", "title": "Song"},
                    },
                ],
            },
        ],
    }

    class RepeatingMetadata(MetadataClient):
        def search_releases(self, query: str, *, limit: int = 10, offset: int = 0, refresh: bool = False):
            del query, limit, offset, refresh
            return [payload, payload, {**payload, "id": "second", "title": "Second"}]

    with MarianaDatabase(tmp_path / "album-remote.db") as database:
        catalog = AlbumCatalog(
            database,
            musicbrainz=RepeatingMetadata(payload),
            youtube_search=lambda *_args, **_kwargs: [],
        )
        results = catalog.search("Album", scope="online", limit=2)
        assert [album.release_mbid for album in results] == ["release", "second"]
        album = catalog.fetch(results[0].album_id, scope="local")
        assert album.tracks[0].title == "Song" and album.tracks[0].duration == 2
        assert catalog.fetch(album.album_id) == album
        with pytest.raises(AlbumError, match="scope"):
            catalog.fetch(album.album_id, refresh=True, scope="space")

        empty = AlbumRef("empty-release", "Empty", release_mbid="empty")
        catalog._persist(empty)
        catalog.musicbrainz = MetadataClient({"id": "empty", "title": "Empty", "media": []})
        with pytest.raises(AlbumError, match="no recording list"):
            catalog.fetch(empty.album_id)


def test_download_remaining_control_and_progress_branches(tmp_path: Path):
    with pytest.raises(DownloadJobError, match="canonical"):
        canonical_youtube_url("https://www.youtube.com/watch?v=x")
    with MarianaDatabase(tmp_path / "downloads-extra.db") as database:
        manager = DownloadManager(database, autostart=False)
        try:
            job = manager.create([youtube("valid")], destination=tmp_path)
            item = manager.items(job.job_id)[0]
            with database.transaction() as connection:
                connection.execute("UPDATE download_jobs SET state='running' WHERE job_id=?", (job.job_id,))
            manager._progress_hook(item, {"downloaded_bytes": 1})
            manager._progress_hook(item, {"downloaded_bytes": 1})
            with database.transaction() as connection:
                connection.execute("UPDATE download_jobs SET state='completed' WHERE job_id=?", (job.job_id,))
            with pytest.raises(DownloadJobError, match="cannot be cancelled"):
                manager.cancel(job.job_id)
        finally:
            manager.close()


def test_queue_remaining_defensive_and_navigation_branches(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue-final-branches.db") as database:
        queue = PersistentQueue(database)
        assert queue.root_insert_position("next") == 0
        queue.add(media("first"))
        queue.add(media("second"))
        queue.jump(0)
        previous = queue.previous()
        assert previous is not None and previous.media.title == "first"
        with pytest.raises(QueueError, match="Unknown queue node"):
            queue.resolve_node("missing-node")

        group = queue.create_group("Nested")
        child = queue.create_group("Child", parent=group.group_id)
        queue.add(media("nested"), group_id=child.group_id)
        active = queue.jump(2)
        active_id = cast(int, active.queue_id)
        with database.transaction() as connection:
            assert queue._active_child(connection, None) == ("group", group.group_id)
            connection.execute(
                "UPDATE queue_items SET group_id='missing-group' WHERE id=?",
                (active_id,),
            )
            assert queue._active_child(connection, None) is None
            connection.execute(
                "UPDATE queue_items SET group_id=? WHERE id=?",
                (child.group_id, active_id),
            )
            connection.execute(
                "UPDATE queue_groups SET parent_id=? WHERE group_id=?",
                (child.group_id, group.group_id),
            )
            with pytest.raises(QueueError, match="cycle"):
                queue._group_depth(connection, group.group_id)
            connection.execute(
                "UPDATE queue_groups SET parent_id=NULL WHERE group_id=?",
                (group.group_id,),
            )

        with pytest.raises(QueueError, match="parent must reference"):
            queue.move_group(group.group_id, parent="item:1")
        with database.transaction() as connection:
            queue._renumber(connection, [cast(int, item.queue_id) for item in queue.items()])

        snapshot = queue.export_snapshot()
        snapshot["items"][0].pop("media")
        queue.restore_snapshot(snapshot)
        assert len(queue.items()) == 3

        legacy = queue.playlists.create("Legacy replace")
        with database.transaction() as connection:
            connection.execute(
                "UPDATE playlists SET tree_json=? WHERE playlist_id=?",
                (json.dumps({"legacy_items": [media("replacement").to_dict()]}), legacy.playlist_id),
            )
        assert [item.media.title for item in queue.load("Legacy replace", replace=True)] == ["replacement"]

        invalid = queue.playlists.create("Invalid append")
        tree = PlaylistStore.snapshot_from_media([media("append")])
        tree["items"].insert(0, {"stable_id": "invalid", "media": None})
        with database.transaction() as connection:
            connection.execute(
                "UPDATE playlists SET tree_json=? WHERE playlist_id=?",
                (json.dumps(tree), invalid.playlist_id),
            )
        assert [item.media.title for item in queue.load("Invalid append", replace=False)] == ["append"]


def test_queue_move_depth_tree_depth_and_smart_fallback_guards(tmp_path: Path):
    with MarianaDatabase(tmp_path / "queue-depth.db") as database:
        queue = PersistentQueue(database)
        parent = queue.create_group("Level 0")
        current = parent
        for index in range(1, 7):
            current = queue.create_group(f"Level {index}", parent=current.group_id)
        source = queue.create_group("Source")
        queue.create_group("Source child", parent=source.group_id)
        with pytest.raises(QueueError, match="nesting"):
            queue.move_group(source.group_id, parent=current.group_id)

        with database.transaction() as connection:
            now = 1.0
            connection.execute(
                "INSERT INTO queue_groups(group_id,parent_id,name,kind,sibling_position,metadata_json,created_at,updated_at) "
                "VALUES('too-deep',?,'Too deep','manual',0,'{}',?,?)",
                (current.group_id, now, now),
            )
            connection.execute(
                "INSERT INTO queue_groups(group_id,parent_id,name,kind,sibling_position,metadata_json,created_at,updated_at) "
                "VALUES('too-deeper','too-deep','Too deeper','manual',0,'{}',?,?)",
                (now, now),
            )
        with pytest.raises(QueueError, match="nesting"):
            queue.tree()

    with MarianaDatabase(tmp_path / "queue-invalid-strategy.db") as database:
        queue = PersistentQueue(database)
        queue.add(media("one"))
        queue.add(media("two"))
        with database.transaction() as connection, pytest.raises(QueueError, match="Unknown queue strategy"):
            queue._ordered_children(connection, None, cast(Any, "invalid"), None)


def test_album_and_download_last_branch_boundaries(tmp_path: Path):
    assert _artist_credit({"artist-credit": [42]}) is None
    assert _artist_credit({"artist-credit": [{"artist": {}, "joinphrase": " & "}]}) == "&"
    with MarianaDatabase(tmp_path / "albums-last.db") as database:
        catalog = AlbumCatalog(database, musicbrainz=MetadataClient())
        catalog._local_rows = cast(Any, lambda: [(None, {}, None)])
        assert catalog.local_albums() == []

    with MarianaDatabase(tmp_path / "downloads-last.db") as database:
        manager = DownloadManager(database, autostart=False)
        try:
            job = manager.create([youtube("completed")], destination=tmp_path)
            with database.transaction() as connection:
                connection.execute(
                    "UPDATE download_items SET state='completed',progress=1 WHERE job_id=?",
                    (job.job_id,),
                )
            manager._run_job(job.job_id)
            assert manager.job(job.job_id).state == DownloadState.COMPLETED
        finally:
            manager.close()


def test_playlist_command_covers_crud_tree_import_and_queue_paths(monkeypatch, tmp_path: Path):
    output: list[str] = []
    played: list[Any] = []
    with MarianaDatabase(tmp_path / "playlist-command.db") as database:
        queue = PersistentQueue(database)
        album = AlbumRef(
            "album-id",
            "Album",
            album_artist="Artist",
            tracks=[AlbumTrack("Album song", artist="Artist", media=media("album-song"))],
        )
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "ALBUMS", SimpleNamespace(fetch=lambda _value: album))
        monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
        monkeypatch.setattr(main, "_print_queue_tree", lambda nodes, **_kwargs: output.append(str(nodes)))
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
        monkeypatch.setattr(main, "_play_queue_item", played.append)
        monkeypatch.setattr(main, "_media_from_argument", lambda value: media(value))

        main.playlist_command([])
        with pytest.raises(PlaylistError, match="Usage"):
            main.playlist_command(["create"])
        main.playlist_command(["create", "Empty", "--description", "No tracks"])
        main.playlist_command(["show", "Empty"])
        main.playlist_command(["show", "Empty", "--tree"])
        main.playlist_command(["rename", "Empty", "Working"])
        main.playlist_command(["add", "Working", "media", "one", "--at", "1"])
        queue.playlists.create("Source", tree=PlaylistStore.snapshot_from_media([media("source")]))
        main.playlist_command(["add", "Working", "playlist", "Source"])
        main.playlist_command(["add", "Working", "album", "album-id"])
        with pytest.raises(PlaylistError, match="must be media"):
            main.playlist_command(["add", "Working", "invalid", "one"])
        main.playlist_command(["show", "Working"])
        main.playlist_command(["show", "Working", "--tree"])
        main.playlist_command(["move", "Working", "1", "--parent", "root", "--at", "2"])
        main.playlist_command(["order", "Working", "shuffle", "--seed", "42"])
        main.playlist_command(["order", "Working", "smart"])
        main.playlist_command(["remove", "Working", "1"])
        main.playlist_command(["queue", "Working", "--at", "next"])
        main.playlist_command(["queue", "Working", "--at", "end", "--flatten"])
        main.playlist_command(["play", "Working"])
        assert played
        main.playlist_command(["create", "Blank"])
        main.playlist_command(["play", "Blank"])
        for invalid, message in (
            (["delete"], "Usage"),
            (["add", "Working", "media"], "Usage"),
            (["move", "Working", "--parent", "root"], "Usage"),
            (["order", "Working"], "Usage"),
            (["queue"], "Usage"),
        ):
            with pytest.raises(PlaylistError, match=message):
                main.playlist_command(invalid)

        source = tmp_path / "import.m3u"
        source.write_text("#EXTM3U\nhttps://example.test/song.mp3\n", encoding="utf-8")
        main.playlist_command(["import", "Imported", str(source)])
        main.playlist_command(["export", "Imported", str(tmp_path / "out.m3u8")])
        main.playlist_command(["clear", "Imported", "--yes"])

        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
        main.playlist_command(["delete", "Imported"])
        assert queue.playlists.get("Imported")
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
        main.playlist_command(["delete", "Imported"])
        main.playlist_command(["delete", "Source", "--yes"])
        with pytest.raises(PlaylistError, match="Invalid playlist command"):
            main.playlist_command(["unknown"])
        with pytest.raises(PlaylistError, match="Usage"):
            main.playlist_command(["show"])
        assert any("Created playlist" in value for value in output)


@pytest.mark.parametrize("token", ["y", "yes", "--yes"])
def test_playlist_delete_and_clear_confirmation_bypass_tokens(monkeypatch, tmp_path: Path, token):
    with MarianaDatabase(tmp_path / "playlist-confirmation.db") as database:
        queue = PersistentQueue(database)
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(
            "builtins.input",
            lambda *_args: pytest.fail("playlist confirmation bypass prompted"),
        )
        queue.playlists.create(
            "Clear me",
            tree=PlaylistStore.snapshot_from_media([media("clear")]),
        )
        main.playlist_command(["clear", "Clear me", token])
        assert queue.playlists.flattened_media(queue.playlists.get("Clear me").tree) == []

        queue.playlists.create("Delete me")
        main.playlist_command(["delete", "Delete me", token])
        with pytest.raises(PlaylistError, match="Unknown playlist"):
            queue.playlists.get("Delete me")


def test_playlist_name_yes_is_not_consumed_as_confirmation(monkeypatch, tmp_path: Path):
    with MarianaDatabase(tmp_path / "playlist-name-yes.db") as database:
        queue = PersistentQueue(database)
        queue.playlists.create("yes")
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("builtins.input", lambda *_args: "n")
        main.playlist_command(["delete", "yes"])
        assert queue.playlists.get("yes").name == "yes"

        main.playlist_command(["delete", "yes", "--yes"])
        with pytest.raises(PlaylistError, match="Unknown playlist"):
            queue.playlists.get("yes")


def test_playlist_clear_rejection_preserves_contents_and_validates_usage(monkeypatch, tmp_path: Path):
    with MarianaDatabase(tmp_path / "playlist-clear-rejection.db") as database:
        queue = PersistentQueue(database)
        queue.playlists.create(
            "Keep me",
            tree=PlaylistStore.snapshot_from_media([media("kept")]),
        )
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
        monkeypatch.setattr("builtins.input", lambda *_args: "n")
        main.playlist_command(["clear", "Keep me"])
        assert len(queue.playlists.flattened_media(queue.playlists.get("Keep me").tree)) == 1
        with pytest.raises(PlaylistError, match="Usage"):
            main.playlist_command(["clear"])
