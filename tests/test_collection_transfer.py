from pathlib import Path

import pytest

from mariana.collection_transfer import (
    CollectionKind,
    CollectionTransferError,
    CollectionTransferService,
    TransferOperation,
    parse_item_selection,
    parse_transfer_request,
)
from mariana.command_catalog import COMMAND_CATALOG, CommandRisk
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.playlists import PlaylistStore
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue


def media(name: str) -> MediaRef:
    return MediaRef(
        MediaSource.LOCAL,
        f"C:/music/{name}.mp3",
        title=name,
        artist=f"artist-{name}",
        provenance="library",
    )


def titles(store: PlaylistStore, name: str) -> list[str | None]:
    return [item.title for item in store.flattened_media(store.get(name).tree)]


def test_transfer_parser_accepts_mixed_indexes_ranges_and_multiple_sources():
    request = parse_transfer_request(
        [
            "copy",
            "to",
            "playlist",
            "playlist7",
            "from",
            "playlist",
            "playlist1",
            "items",
            "1,2,6",
            "from",
            "playlist",
            "playlist4",
            "items",
            "3-4,9",
            "--dry-run",
        ]
    )

    assert request.operation == TransferOperation.COPY
    assert request.destination.kind == CollectionKind.PLAYLIST
    assert request.destination.name == "playlist7"
    assert request.sources[0].indexes == (1, 2, 6)
    assert request.sources[1].indexes == (3, 4, 9)
    assert request.dry_run
    assert parse_item_selection("all") is None


def test_command_catalog_distinguishes_copy_from_destructive_move():
    specs = {spec.canonical: spec for spec in COMMAND_CATALOG}

    assert specs["transfer copy"].risk == CommandRisk.STATE_CHANGING
    assert specs["transfer move"].risk == CommandRisk.DESTRUCTIVE
    assert specs["transfer move"].forms[0].flags == ("--dry-run", "--yes")


@pytest.mark.parametrize("selection", ["0", "3-1", "1,,2", "one", "1,1"])
def test_transfer_parser_rejects_ambiguous_or_invalid_selections(selection: str):
    with pytest.raises(CollectionTransferError):
        parse_item_selection(selection)


def test_add_media_many_preserves_order_in_one_revision(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        store = PlaylistStore(database)
        store.create("Mix")

        updated = store.add_media_many("Mix", [media("one"), media("two"), media("three")])

        assert updated.revision == 2
        assert titles(store, "Mix") == ["one", "two", "three"]
        assert store.revisions("Mix") == [2, 1]


def test_playlist_command_accepts_multiple_library_rows_as_one_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import main

    with MarianaDatabase(tmp_path / "state.db") as database:
        queue = PersistentQueue(database)
        queue.playlists.create("Mix")
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(
            main,
            "_sound_files",
            [str(tmp_path / "one.mp3"), str(tmp_path / "two.mp3"), str(tmp_path / "three.mp3")],
        )
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
        monkeypatch.setattr(main, "IPrint", lambda *args, **kwargs: None)

        main.playlist_command(["add", "Mix", "media", "1", "2", "3"])

        playlist = queue.playlists.get("Mix")
        assert playlist.revision == 2
        assert [Path(item.original_uri).name for item in queue.playlists.flattened_media(playlist.tree)] == [
            "one.mp3",
            "two.mp3",
            "three.mp3",
        ]


def test_transfer_command_previews_then_copies_without_terminal_injection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import main

    with MarianaDatabase(tmp_path / "state.db") as database:
        queue = PersistentQueue(database)
        preferences = MediaPreferences(database)
        queue.playlists.create(
            "Source",
            tree=queue.playlists.snapshot_from_media([media("one"), media("two")]),
        )
        queue.playlists.create("Target")
        output: list[str] = []
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "PREFERENCES", preferences)
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
        monkeypatch.setattr(
            main,
            "IPrint",
            lambda value, **kwargs: output.append(str(value)),
        )
        arguments = [
            "copy", "to", "playlist", "Target",
            "from", "playlist", "Source", "items", "2,1",
        ]

        preview = main.transfer_command([*arguments, "--dry-run"])
        assert preview is not None
        assert preview.selected_count == 2
        assert titles(queue.playlists, "Target") == []

        result = main.transfer_command(arguments)
        assert result is not None
        assert result.selected_count == 2
        assert titles(queue.playlists, "Target") == ["two", "one"]
        assert any("Copy complete" in message for message in output)


def test_copy_combines_multiple_playlists_without_changing_sources(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        store = PlaylistStore(database)
        preferences = MediaPreferences(database)
        store.create("playlist1", tree=store.snapshot_from_media([media(f"a{index}") for index in range(1, 7)]))
        store.create("playlist4", tree=store.snapshot_from_media([media(f"b{index}") for index in range(1, 10)]))
        store.create("playlist7")
        request = parse_transfer_request(
            [
                "copy", "to", "playlist", "playlist7",
                "from", "playlist", "playlist1", "items", "1,2,6",
                "from", "playlist", "playlist4", "items", "3,9",
            ]
        )

        plan = CollectionTransferService(store, preferences).plan(request)
        result = CollectionTransferService(store, preferences).apply(plan)

        assert result.selected_count == 5
        assert titles(store, "playlist7") == ["a1", "a2", "a6", "b3", "b9"]
        assert store.get("playlist7").revision == 2
        assert store.get("playlist1").revision == 1
        assert store.get("playlist4").revision == 1


def test_move_from_playlists_to_favourites_is_atomic_and_persistent(tmp_path: Path):
    path = tmp_path / "state.db"
    request = parse_transfer_request(
        [
            "move", "to", "favs",
            "from", "playlist", "first", "items", "1,3",
            "from", "playlist", "second", "items", "2",
            "--yes",
        ]
    )
    with MarianaDatabase(path) as database:
        store = PlaylistStore(database)
        preferences = MediaPreferences(database)
        store.create("first", tree=store.snapshot_from_media([media("one"), media("two"), media("three")]))
        store.create("second", tree=store.snapshot_from_media([media("four"), media("five")]))
        preferences.set_rating(media("one"), 3)
        service = CollectionTransferService(store, preferences)

        result = service.apply(service.plan(request))

        assert result.selected_count == 3
        assert titles(store, "first") == ["two"]
        assert titles(store, "second") == ["four"]
        assert preferences.rating(media("one")) == 3
        assert preferences.rating(media("three")) == 0
        assert preferences.rating(media("five")) == 0
        assert {entry.label for entry in preferences.list(PreferenceState.FAVORITE)} == {
            "one",
            "three",
            "five",
        }
    with MarianaDatabase(path) as database:
        assert {
            entry.label
            for entry in MediaPreferences(database).list(PreferenceState.FAVORITE)
        } == {"one", "three", "five"}


def test_move_from_favourites_to_playlist_clears_only_the_heart(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        store = PlaylistStore(database)
        preferences = MediaPreferences(database)
        first = media("one")
        second = media("two")
        preferences.set_rating(first, 5)
        preferences.set_rating(second, 4)
        preferences.set(first, PreferenceState.FAVORITE)
        preferences.set(second, PreferenceState.FAVORITE)
        preferences.set_blocked(first, True)
        store.create("Later")
        request = parse_transfer_request(
            ["move", "to", "playlist", "Later", "from", "favs", "items", "all", "--yes"]
        )
        service = CollectionTransferService(store, preferences)

        service.apply(service.plan(request))

        assert set(titles(store, "Later")) == {"one", "two"}
        assert preferences.list(PreferenceState.FAVORITE) == []
        assert preferences.rating(first) == 5
        assert preferences.rating(second) == 4
        assert preferences.is_blocked(first)


def test_plan_rejects_invalid_rows_and_apply_rejects_stale_playlist_revisions(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        store = PlaylistStore(database)
        preferences = MediaPreferences(database)
        store.create("Source", tree=store.snapshot_from_media([media("one")]))
        store.create("Target")
        invalid = parse_transfer_request(
            ["copy", "to", "playlist", "Target", "from", "playlist", "Source", "items", "2"]
        )
        service = CollectionTransferService(store, preferences)
        with pytest.raises(CollectionTransferError, match="has no item 2"):
            service.plan(invalid)
        assert titles(store, "Target") == []

        valid = parse_transfer_request(
            ["move", "to", "playlist", "Target", "from", "playlist", "Source", "items", "1", "--yes"]
        )
        plan = service.plan(valid)
        store.add_media("Source", media("new"))
        with pytest.raises(CollectionTransferError, match="changed after confirmation"):
            service.apply(plan)
        assert titles(store, "Target") == []
        assert titles(store, "Source") == ["one", "new"]


def test_favourite_binding_can_reject_undurable_media_before_any_write(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        store = PlaylistStore(database)
        preferences = MediaPreferences(database)
        stream = MediaRef(MediaSource.URL, "https://temporary.test/audio", title="Transient")
        store.create("Source", tree=store.snapshot_from_media([stream]))
        request = parse_transfer_request(
            ["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--yes"]
        )
        service = CollectionTransferService(
            store,
            preferences,
            favourite_binder=lambda value: (None, "no durable identity"),
        )

        with pytest.raises(CollectionTransferError, match="no durable identity"):
            service.plan(request)

        assert titles(store, "Source") == ["Transient"]
        assert preferences.list(PreferenceState.FAVORITE) == []
