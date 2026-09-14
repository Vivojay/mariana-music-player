from dataclasses import replace

import pytest

from mariana.collection_transfer import (
    CollectionTransferError,
    CollectionTransferService,
    parse_item_selection,
    parse_transfer_request,
)
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.playlists import PlaylistStore
from mariana.preferences import MediaPreferences, PreferenceState


@pytest.fixture
def stores(tmp_path):
    with MarianaDatabase(tmp_path / "collections.db") as database:
        playlists = PlaylistStore(database)
        source = MediaRef(MediaSource.LOCAL, "C:/music/original.flac", title="Original")
        playlists.create("Source", tree=playlists.snapshot_from_media([source]))
        playlists.create("Target")
        yield playlists, CollectionTransferService(playlists, MediaPreferences(database))


def request(operation="move"):
    return parse_transfer_request([
        operation, "to", "playlist", "Target", "from", "playlist", "Source", "items", "all",
    ])


def titles(playlists, name):
    return [media.title for media in playlists.flattened_media(playlists.get(name).tree)]


@pytest.mark.parametrize("changed_name", ["Source", "Target"])
def test_snapshot_and_approval_revision_cannot_come_from_different_reads(stores, monkeypatch, changed_name):
    playlists, service = stores
    original_get = playlists.get
    changed = False

    def get_then_edit(reference):
        nonlocal changed
        snapshot = original_get(reference)
        if snapshot.name == changed_name and not changed:
            changed = True
            playlists.add_media(changed_name, MediaRef(
                MediaSource.LOCAL, "C:/music/new.flac", title="Intervening edit",
            ))
        return snapshot

    monkeypatch.setattr(playlists, "get", get_then_edit)
    plan = service.plan(request())
    with pytest.raises(CollectionTransferError, match="changed after confirmation"):
        service.apply(plan)

    assert titles(playlists, "Source") == (["Original", "Intervening edit"] if changed_name == "Source" else ["Original"])
    assert titles(playlists, "Target") == (["Intervening edit"] if changed_name == "Target" else [])


def test_copy_revalidates_source_revision_without_mutating_it(stores):
    playlists, service = stores
    plan = service.plan(request("copy"))
    playlists.add_media("Source", MediaRef(MediaSource.LOCAL, "C:/music/new.flac", title="New"))

    with pytest.raises(CollectionTransferError, match="changed after confirmation"):
        service.apply(plan)

    assert titles(playlists, "Target") == []
    assert titles(playlists, "Source") == ["Original", "New"]
    assert playlists.revisions("Target") == [1]


def test_duplicate_source_name_and_id_cannot_copy_the_same_occurrence_twice(stores):
    playlists, service = stores
    source_id = playlists.get("Source").playlist_id
    duplicate = parse_transfer_request([
        "copy", "to", "playlist", "Target",
        "from", "playlist", "Source", "items", "1",
        "from", "playlist", source_id, "items", "1",
    ])

    with pytest.raises(CollectionTransferError, match="same source playlist"):
        service.plan(duplicate)

    assert titles(playlists, "Target") == []
    assert playlists.revisions("Source") == [1]


@pytest.mark.parametrize("indexes", [(0,), (-1,), (True,), (1, 1)])
def test_direct_structured_selection_cannot_bypass_positive_unique_indexes(stores, indexes):
    playlists, service = stores
    selected = request()
    selected = replace(selected, sources=(replace(selected.sources[0], indexes=indexes),))

    with pytest.raises(CollectionTransferError, match=r"positive|more than once"):
        service.plan(selected)

    assert titles(playlists, "Source") == ["Original"]
    assert titles(playlists, "Target") == []


def test_extreme_integer_selection_returns_a_domain_error():
    with pytest.raises(CollectionTransferError, match=r"selection|index|indexes"):
        parse_item_selection("9" * 5000)


def test_copy_favourite_revalidates_membership_before_destination_write(stores):
    playlists, service = stores
    media = playlists.flattened_media(playlists.get("Source").tree)[0]
    service.preferences.set(media, PreferenceState.FAVORITE)
    selected = parse_transfer_request([
        "copy", "to", "playlist", "Target", "from", "favs", "items", "all",
    ])
    plan = service.plan(selected)
    service.preferences.set(media, PreferenceState.NEUTRAL)

    with pytest.raises(CollectionTransferError, match="Favourites changed after confirmation"):
        service.apply(plan)

    assert titles(playlists, "Target") == []
    assert playlists.revisions("Target") == [1]


def test_result_reports_committed_revisions_without_rereading_mutable_playlists(stores, monkeypatch):
    playlists, service = stores
    plan = service.plan(request())
    monkeypatch.setattr(playlists, "get", lambda _: pytest.fail("Result must describe its own committed transaction"))

    result = service.apply(plan)

    assert dict(result.playlist_revisions) == {"Source": 2, "Target": 2}
