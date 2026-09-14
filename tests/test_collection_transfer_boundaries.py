import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

import mariana.collection_transfer as transfers
from mariana.collection_transfer import (
    CollectionTransferError,
    CollectionTransferService,
    parse_item_selection,
    parse_transfer_request,
)
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.playlists import PlaylistError, PlaylistStore
from mariana.preferences import MediaPreferences, PreferenceState


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[tuple[PlaylistStore, MediaPreferences, CollectionTransferService]]:
    with MarianaDatabase(tmp_path / "collections.db") as database:
        playlists = PlaylistStore(database)
        preferences = MediaPreferences(database)
        yield playlists, preferences, CollectionTransferService(playlists, preferences)


def track(name: str) -> MediaRef:
    return MediaRef(MediaSource.YOUTUBE, f"https://www.youtube.com/watch?v={name}", title=name)


def entries(store: PlaylistStore, name: str) -> list[str | None]:
    return [item.title for item in store.flattened_media(store.get(name).tree)]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["copy"], "Usage"),
        (["erase", "to", "favs", "from", "favs", "items", "all"], "copy or move"),
        (["copy", "at", "favs", "from", "favs", "items", "all"], "Expected 'to'"),
        (["copy", "to", "unknown", "from", "favs", "items", "all"], "collection must"),
        (["copy", "to", "favs", "via", "playlist", "Source", "items", "all"], "Expected 'from'"),
        (["copy", "to", "favs", "from", "playlist", "Source"], "requires 'items'"),
        (["copy", "to", "favs", "from", "playlist", "Source", "items"], "Missing item selection"),
        (["copy", "to", "playlist", "Target", "from", "playlist"], "requires a playlist name"),
        (["copy", "to", "playlist", "Target", "from", "playlist", "Source", "items", "all", "from"],
         "Missing collection"),
        (["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--other"], "Unknown transfer option"),
        (["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--yes", "--yes"], "only once"),
        (["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--dry-run", "--dry-run"], "only once"),
        (["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--yes", "--dry-run"], "unnecessary"),
        (["copy", "to", "favs", "from", "playlist", "Source", "items", "all", "--yes"], "destructive move"),
        (["copy", "to", "favourites", "from", "favorites", "items", "all"], "same collection"),
        (["copy", "to", "favs", "from", "playlist", "Source", "items", "1", "from", "playlist", "SOURCE", "items", "2"],
         "appears more than once"),
    ],
)
def test_invalid_transfer_grammar_is_rejected_before_planning(arguments: list[str], message: str):
    with pytest.raises(CollectionTransferError, match=message):
        parse_transfer_request(arguments)


@pytest.mark.parametrize("selection", ["", "   ", "1-5001"])
def test_empty_or_oversized_selection_is_bounded(selection: str):
    with pytest.raises(CollectionTransferError, match=r"empty|more than 5000"):
        parse_item_selection(selection)


def test_stores_from_different_databases_cannot_form_a_transfer(tmp_path: Path):
    with (
        MarianaDatabase(tmp_path / "first.db") as first,
        MarianaDatabase(tmp_path / "second.db") as second,
        pytest.raises(ValueError, match="share one database"),
    ):
        CollectionTransferService(PlaylistStore(first), MediaPreferences(second))


@pytest.mark.parametrize("source", [["playlist", "Empty"], ["favs"]])
def test_empty_source_leaves_destination_and_revisions_unchanged(stores, source: list[str]):
    playlists, _preferences, service = stores
    playlists.create("Empty")
    playlists.create("Target", tree=playlists.snapshot_from_media([track("existing")]))
    request = parse_transfer_request(["move", "to", "playlist", "Target", "from", *source, "items", "all", "--yes"])

    with pytest.raises(CollectionTransferError, match="empty"):
        service.plan(request)

    assert entries(playlists, "Target") == ["existing"]
    assert playlists.revisions("Target") == [1]


def test_favourite_without_stored_media_refuses_transfer(stores):
    playlists, preferences, service = stores
    preferences.set_rating("missing-metadata", 5)
    preferences.set("missing-metadata", PreferenceState.FAVORITE)
    playlists.create("Target")
    request = parse_transfer_request(["move", "to", "playlist", "Target", "from", "favs", "items", "all", "--yes"])

    with pytest.raises(CollectionTransferError, match="no longer has usable media metadata"):
        service.plan(request)

    assert preferences.rating("missing-metadata") == 5
    assert entries(playlists, "Target") == []
    assert playlists.revisions("Target") == [1]


def test_name_and_identity_aliases_cannot_move_playlist_into_itself(stores):
    playlists, _preferences, service = stores
    source = playlists.create("Source", tree=playlists.snapshot_from_media([track("one")]))
    request = parse_transfer_request(
        ["move", "to", "playlist", source.playlist_id, "from", "playlist", "Source", "items", "all", "--yes"]
    )

    with pytest.raises(CollectionTransferError, match="resolve to the same playlist"):
        service.plan(request)

    assert entries(playlists, "Source") == ["one"]
    assert playlists.revisions("Source") == [1]


def test_combined_sources_enforce_total_limit_before_any_write(stores, monkeypatch: pytest.MonkeyPatch):
    playlists, _preferences, service = stores
    for name in ("First", "Second"):
        playlists.create(name, tree=playlists.snapshot_from_media([track(f"{name}-1"), track(f"{name}-2")]))
    playlists.create("Target")
    monkeypatch.setattr(transfers, "MAX_TRANSFER_ITEMS", 3)
    request = parse_transfer_request(
        ["move", "to", "playlist", "Target", "from", "playlist", "First", "items", "all",
         "from", "playlist", "Second", "items", "all", "--yes"]
    )

    with pytest.raises(CollectionTransferError, match="more than 3"):
        service.plan(request)

    assert entries(playlists, "Target") == []
    assert entries(playlists, "First") == ["First-1", "First-2"]
    assert entries(playlists, "Second") == ["Second-1", "Second-2"]


def test_dry_run_plan_cannot_be_applied(stores):
    playlists, preferences, service = stores
    media = track("one")
    playlists.create("Source", tree=playlists.snapshot_from_media([media]))
    request = parse_transfer_request(["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--dry-run"])

    with pytest.raises(CollectionTransferError, match="dry-run"):
        service.apply(service.plan(request))

    assert entries(playlists, "Source") == ["one"]
    assert preferences.rating(media) == 0
    assert playlists.revisions("Source") == [1]


def test_deleted_and_recreated_destination_does_not_inherit_preview_approval(stores):
    playlists, _preferences, service = stores
    playlists.create("Source", tree=playlists.snapshot_from_media([track("one")]))
    playlists.create("Target")
    request = parse_transfer_request(
        ["move", "to", "playlist", "Target", "from", "playlist", "Source", "items", "all", "--yes"]
    )
    plan = service.plan(request)
    playlists.delete_bound(playlists.bind_mutation("Target"))
    playlists.create("Target", tree=playlists.snapshot_from_media([track("replacement")]))

    with pytest.raises(CollectionTransferError, match="no longer available"):
        service.apply(plan)

    assert entries(playlists, "Source") == ["one"]
    assert entries(playlists, "Target") == ["replacement"]
    assert playlists.revisions("Source") == [1]
    assert playlists.revisions("Target") == [1]


def test_favourite_removed_after_preview_rolls_back_destination_and_other_removals(stores):
    playlists, preferences, service = stores
    first, second = track("one"), track("two")
    preferences.set_rating(first, 5)
    preferences.set_rating(second, 4)
    preferences.set(first, PreferenceState.FAVORITE)
    preferences.set(second, PreferenceState.FAVORITE)
    playlists.create("Target")
    request = parse_transfer_request(["move", "to", "playlist", "Target", "from", "favs", "items", "all", "--yes"])
    plan = service.plan(request)
    preferences.set(second, PreferenceState.NEUTRAL)

    with pytest.raises(CollectionTransferError, match="Favourites changed after confirmation"):
        service.apply(plan)

    assert preferences.rating(first) == 5
    assert preferences.rating(second) == 4
    assert preferences.is_favorite(first)
    assert not preferences.is_favorite(second)
    assert entries(playlists, "Target") == []
    assert playlists.revisions("Target") == [1]


def test_database_refusal_rolls_back_every_playlist_and_revision(stores):
    playlists, _preferences, service = stores
    playlists.create("Source", tree=playlists.snapshot_from_media([track("one")]))
    playlists.create("Target")
    request = parse_transfer_request(
        ["move", "to", "playlist", "Target", "from", "playlist", "Source", "items", "all", "--yes"]
    )
    plan = service.plan(request)
    with playlists.database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER refuse_target BEFORE UPDATE ON playlists WHEN OLD.name='Target' "
            "BEGIN SELECT RAISE(IGNORE); END"
        )

    with pytest.raises(CollectionTransferError, match="changed after confirmation"):
        service.apply(plan)

    assert entries(playlists, "Source") == ["one"]
    assert entries(playlists, "Target") == []
    assert playlists.revisions("Source") == [1]
    assert playlists.revisions("Target") == [1]


def test_preference_write_failure_rolls_back_source_removal(stores):
    playlists, preferences, service = stores
    media = track("one")
    playlists.create("Source", tree=playlists.snapshot_from_media([media]))
    request = parse_transfer_request(["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--yes"])
    plan = service.plan(request)
    with playlists.database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER refuse_rating BEFORE INSERT ON media_preferences "
            "BEGIN SELECT RAISE(ABORT, 'rating write refused'); END"
        )

    with pytest.raises(sqlite3.IntegrityError, match="rating write refused"):
        service.apply(plan)

    assert entries(playlists, "Source") == ["one"]
    assert playlists.revisions("Source") == [1]
    assert preferences.rating(media) == 0
    assert preferences.media(media.stable_id) is None


def test_favourite_transfer_uses_bound_identity_without_removing_block_policy(stores):
    playlists, preferences, _service = stores
    original, durable = track("unbound"), track("bound")
    preferences.set_blocked(durable)
    playlists.create("Source", tree=playlists.snapshot_from_media([original]))
    service = CollectionTransferService(playlists, preferences, favourite_binder=lambda _media: (durable, None))
    request = parse_transfer_request(["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--yes"])

    service.apply(service.plan(request))

    assert entries(playlists, "Source") == []
    assert preferences.rating(durable) == 0
    assert preferences.is_favorite(durable)
    assert preferences.rating(original) == 0
    assert preferences.is_blocked(durable)


def test_missing_binding_reason_has_safe_fallback_and_does_not_write(stores):
    playlists, preferences, _service = stores
    playlists.create("Source", tree=playlists.snapshot_from_media([track("one")]))
    service = CollectionTransferService(playlists, preferences, favourite_binder=lambda _media: (None, None))
    request = parse_transfer_request(["move", "to", "favs", "from", "playlist", "Source", "items", "all", "--yes"])

    with pytest.raises(CollectionTransferError, match="rating is unavailable"):
        service.plan(request)

    assert entries(playlists, "Source") == ["one"]
    assert preferences.rating(track("one")) == 0


@pytest.mark.parametrize(
    "tree",
    [
        {"groups": "invalid"},
        {"items": "invalid"},
        {"state": []},
        {"groups": [{"group_id": "cycle", "parent_id": "cycle"}]},
        {"items": [{"group_id": "missing", "media": track("one").to_dict()}]},
        {"groups": [{"group_id": "duplicate"}, {"group_id": "duplicate"}]},
    ],
)
def test_invalid_playlist_snapshot_cannot_replace_existing_collection(stores, tree):
    playlists, _preferences, _service = stores
    playlists.create("Keep", tree=playlists.snapshot_from_media([track("original")]))

    with pytest.raises(PlaylistError):
        playlists.save_snapshot("Keep", tree)

    assert entries(playlists, "Keep") == ["original"]
    assert playlists.revisions("Keep") == [1]


def test_m3u_import_keeps_missing_references_and_does_not_change_blocked_policy(stores, tmp_path: Path):
    playlists, preferences, _service = stores
    missing = tmp_path / "missing.wav"
    blocked = MediaRef(MediaSource.LOCAL, str(missing), title="Missing original")
    preferences.set_blocked(blocked)
    source = tmp_path / "source.m3u8"
    source.write_text(
        "\ufeff#EXTM3U\n#EXTINF:10,Missing original\nmissing.wav\n"
        "#EXTINF:-1,Online\nhttps://example.test/audio.mp3\n",
        encoding="utf-8",
    )

    imported = playlists.import_m3u("Imported", source)
    items = playlists.flattened_media(imported.tree)

    assert [item.title for item in items] == ["Missing original", "Online"]
    assert items[0].original_uri == str(missing)
    assert items[0].source == MediaSource.LOCAL
    assert items[1].source == MediaSource.URL
    assert preferences.is_blocked(items[0])
    assert not missing.exists()
    assert playlists.revisions("Imported") == [1]


@pytest.mark.parametrize("source_name", ["missing.m3u8", "unsupported.json"])
def test_invalid_import_source_cannot_modify_existing_playlist(stores, tmp_path: Path, source_name: str):
    playlists, _preferences, _service = stores
    playlists.create("Keep", tree=playlists.snapshot_from_media([track("original")]))
    source = tmp_path / source_name
    if source.suffix == ".json":
        source.write_text("{}", encoding="utf-8")

    with pytest.raises(PlaylistError, match=r"existing \.m3u or \.m3u8"):
        playlists.import_m3u("Keep", source)

    assert entries(playlists, "Keep") == ["original"]
    assert playlists.revisions("Keep") == [1]


def test_import_never_overwrites_existing_playlist_name(stores, tmp_path: Path):
    playlists, _preferences, _service = stores
    playlists.create("Keep", tree=playlists.snapshot_from_media([track("original")]))
    source = tmp_path / "source.m3u"
    source.write_text("replacement.wav\n", encoding="utf-8")

    with pytest.raises(PlaylistError, match="already exists"):
        playlists.import_m3u("KEEP", source)

    assert entries(playlists, "Keep") == ["original"]
    assert playlists.revisions("Keep") == [1]


def test_playlist_export_refuses_unapproved_overwrite_and_cleans_staging(stores, tmp_path: Path):
    playlists, _preferences, _service = stores
    playlists.create("Source", tree=playlists.snapshot_from_media([track("one")]))
    output = tmp_path / "export.m3u8"
    output.write_text("existing export", encoding="utf-8")

    with pytest.raises(PlaylistError, match="overwrite approval is required"):
        playlists.export_m3u("Source", output)
    assert output.read_text(encoding="utf-8") == "existing export"
    target = playlists.bind_export("Source", output)
    replacement = tmp_path / "replacement.m3u8"
    replacement.write_text("another owner", encoding="utf-8")
    replacement.replace(output)

    with pytest.raises(PlaylistError, match="changed after approval"):
        playlists.export_bound(target)

    assert output.read_text(encoding="utf-8") == "another owner"
    assert not list(tmp_path.glob(".export.m3u8.*.tmp"))
    assert entries(playlists, "Source") == ["one"]


def test_playlist_export_approval_is_bound_to_parent_identity(stores, tmp_path: Path):
    playlists, _preferences, _service = stores
    playlists.create("Source", tree=playlists.snapshot_from_media([track("one")]))
    parent = tmp_path / "exports"
    target = playlists.bind_export("Source", parent / "export.m3u8")
    parent.rename(tmp_path / "previous")
    parent.mkdir()
    (parent / "keep.txt").write_text("unrelated", encoding="utf-8")

    with pytest.raises(PlaylistError, match="changed after approval"):
        playlists.export_bound(target)

    assert (parent / "keep.txt").read_text(encoding="utf-8") == "unrelated"
    assert not (parent / "export.m3u8").exists()
    assert not list(parent.glob("*.tmp"))
    assert playlists.revisions("Source") == [1]
