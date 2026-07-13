from pathlib import Path

import pytest

import main
from mariana.albums import AlbumCatalog, AlbumError
from mariana.database import MarianaDatabase
from mariana.queueing import PersistentQueue
from tests.test_albums import add_library_track


@pytest.fixture
def album_cli(monkeypatch, tmp_path: Path):
    database = MarianaDatabase(tmp_path / "album-cli.db")
    add_library_track(
        database,
        tmp_path,
        "first",
        title="First",
        artist="Artist",
        album="Test Album",
        album_artist="Artist",
        track="1/2",
        release_mbid="release-test",
    )
    add_library_track(
        database,
        tmp_path,
        "second",
        title="Second",
        artist="Artist",
        album="Test Album",
        album_artist="Artist",
        track="2/2",
        release_mbid="release-test",
    )
    catalog = AlbumCatalog(database)
    queue = PersistentQueue(database)
    output = []
    played = []
    monkeypatch.setattr(main, "ALBUMS", catalog)
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "_play_queue_item", played.append)
    yield catalog, queue, output, played
    database.close()


def test_album_search_show_tracks_play_queue_and_save(album_cli):
    catalog, queue, output, played = album_cli
    main.album_command(["search", "Artist Test Album", "--scope", "local", "--limit", "5"])
    assert catalog.resolve_reference("1").title == "Test Album"
    main.album_command(["show", "1"])
    main.album_command(["tracks", "1"])
    main.album_command(["play", "1", "--order", "shuffle", "--seed", "42"])
    assert played and queue.groups()[0].kind == "album" and queue.groups()[0].atomic
    assert queue.current() is not None

    main.album_command(["queue", "1", "--at", "end", "--tracks", "1"])
    assert len(queue.items()) == 3
    assert len([group for group in queue.groups() if group.kind == "album"]) == 2
    main.album_command(["save", "1", "Saved Album"])
    assert queue.playlists.get("Saved Album").description.startswith("Album snapshot")
    assert any("seed 42" in value for value in output)


def test_album_custom_order_partial_guards_and_flatten(album_cli):
    _catalog, queue, _output, _played = album_cli
    main.album_command(["search", "Test Album", "--scope", "local"])
    with pytest.raises(AlbumError, match="requires --tracks"):
        main.album_command(["play", "1", "--order", "custom"])
    main.album_command(["play", "1", "--order", "custom", "--tracks", "2,1"])
    assert [item.media.title for item in queue.items()] == ["Second", "First"]
    queue.clear()
    main.album_command(["queue", "1", "--flatten", "--tracks", "1-2"])
    assert queue.groups() == []
    assert [item.media.title for item in queue.items()] == ["First", "Second"]


def test_playlist_can_add_album_snapshot(album_cli):
    catalog, queue, _output, _played = album_cli
    catalog.search("Test Album", scope="local")
    queue.playlists.create("Mix")
    main.playlist_command(["add", "Mix", "album", "1"])
    playlist = queue.playlists.get("Mix")
    assert [media.title for media in queue.playlists.flattened_media(playlist.tree)] == ["First", "Second"]
    assert playlist.tree["groups"][0]["kind"] == "album"
