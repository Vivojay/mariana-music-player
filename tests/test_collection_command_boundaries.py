from types import SimpleNamespace

import pytest

import main
from mariana.collection_transfer import CollectionTransferError
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.playlists import PlaylistError
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue
from mariana.tags import TagError


@pytest.fixture
def collection(tmp_path, monkeypatch):
    with MarianaDatabase(tmp_path / "collections.db") as database:
        queue = PersistentQueue(database)
        item = MediaRef(MediaSource.LOCAL, str(tmp_path / "song.flac"), title="Song", provenance="library")
        queue.playlists.create("Source", tree=queue.playlists.snapshot_from_media([item]))
        queue.playlists.create("Target")
        output, notifications = [], []
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "PREFERENCES", MediaPreferences(database))
        monkeypatch.setattr(main, "IPrint", lambda value="", **_: output.append(str(value)))
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: notifications.append("queue"))
        yield SimpleNamespace(queue=queue, item=item, output=output, notifications=notifications)


def move_arguments():
    return ["move", "to", "playlist", "Target", "from", "playlist", "Source", "items", "1"]


def test_transfer_cancel_preserves_every_collection_and_queue(collection, monkeypatch):
    prompts = []
    queue_before = collection.queue.state()
    monkeypatch.setattr(main, "_confirm_action", lambda message, **_: prompts.append(message) or False)

    assert main.transfer_command(move_arguments()) is None

    assert len(prompts) == 1
    assert collection.queue.playlists.revisions("Source") == [1]
    assert collection.queue.playlists.revisions("Target") == [1]
    assert collection.notifications == []
    assert collection.queue.state() == queue_before


def test_transfer_rechecks_destination_after_confirmation_without_overwriting_edits(collection, monkeypatch):
    def edit_then_approve(_message, **_kwargs):
        collection.queue.playlists.add_media("Target", collection.item)
        return True

    monkeypatch.setattr(main, "_confirm_action", edit_then_approve)
    with pytest.raises(CollectionTransferError, match="changed after confirmation"):
        main.transfer_command(move_arguments())

    assert collection.queue.playlists.revisions("Source") == [1]
    assert collection.queue.playlists.revisions("Target") == [2, 1]
    assert collection.notifications == []


def test_transfer_to_favourites_enforces_existing_durable_identity_policy(collection, monkeypatch):
    stream = MediaRef(MediaSource.URL, "https://example.invalid/audio?token=private", title="Stream")
    collection.queue.playlists.add_media("Source", stream)
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: pytest.fail("Invalid source prompted"))

    with pytest.raises(CollectionTransferError, match=r"no durable (?:favourite|rating) identity"):
        main.transfer_command(["move", "to", "favs", "from", "playlist", "Source", "items", "2"])

    assert main.PREFERENCES.list(PreferenceState.FAVORITE) == []
    assert collection.queue.playlists.revisions("Source") == [2, 1]
    assert collection.notifications == []


def test_multi_item_playlist_add_validates_all_references_before_one_write(collection, monkeypatch):
    def resolve(reference):
        if reference == "missing":
            raise ValueError("Unavailable reference")
        return collection.item

    monkeypatch.setattr(main, "_media_from_argument", resolve)
    with pytest.raises(ValueError, match="Unavailable reference"):
        main.playlist_command(["add", "Target", "media", "known", "missing"])

    assert collection.queue.playlists.revisions("Target") == [1]
    assert collection.notifications == []


@pytest.mark.parametrize("kind", ["album", "playlist"])
def test_playlist_non_media_add_still_requires_one_reference(collection, kind):
    with pytest.raises(PlaylistError):
        main.playlist_command(["add", "Target", kind, "Source", "unexpected"])
    assert collection.queue.playlists.revisions("Target") == [1]


@pytest.mark.parametrize("operation", ["play", "queue"])
@pytest.mark.parametrize("index", ["9" * 5000, "²"], ids=["excessive-digits", "non-decimal-digit"])
def test_extreme_tag_result_index_returns_domain_error_before_resolving(monkeypatch, operation, index):
    monkeypatch.setattr(main, "TagCommandService", lambda *_args, **_kwargs: SimpleNamespace(
        resolve_result=lambda _: pytest.fail("Invalid index reached result resolver"),
    ))
    with pytest.raises(TagError, match="Usage"):
        main.tag_command([operation, index])


@pytest.mark.parametrize("topic", ["tag", "tags", "transfer", "playlists"])
def test_collection_help_topics_expose_discoverable_commands(monkeypatch, topic):
    output = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_: output.append(str(value)))
    main.help_command([topic])
    text = "\n".join(output)
    if topic in {"tag", "tags"}:
        assert "tag help" in text and "tag find" in text and "tag play" in text
    else:
        assert "transfer copy" in text and "transfer move" in text and "--dry-run" in text


@pytest.mark.parametrize(
    ("command", "handler", "arguments"),
    [
        ('tag create "Late night"', "tag_command", ["create", "Late night"]),
        ('transfer copy to playlist "My set" from favs items 1', "transfer_command",
         ["copy", "to", "playlist", "My set", "from", "favs", "items", "1"]),
    ],
)
def test_commands_dispatch_tokens_once_without_replaying_command_text(monkeypatch, command, handler, arguments):
    calls = []
    monkeypatch.setattr(main, handler, lambda values: calls.append(values))
    monkeypatch.setattr(main, "isplaying", False)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
    monkeypatch.setattr(main.os, "system", lambda _: pytest.fail("Command text reached shell"))

    main.process(command)

    assert calls == [arguments]
