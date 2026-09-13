import pytest

import main
from mariana.command_catalog import COMMAND_CATALOG, CommandRisk
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.playlists import PlaylistError
from mariana.queueing import PersistentQueue


def track(name):
    return MediaRef(MediaSource.LOCAL, f"C:/music/{name}.mp3", title=name)


@pytest.fixture
def collection(tmp_path, monkeypatch):
    with MarianaDatabase(tmp_path / "history.db") as database:
        queue = PersistentQueue(database)
        store = queue.playlists
        store.create("Set", description="Keep this description", tree=store.snapshot_from_media([track("first")]))
        store.add_media("Set", track("second"))
        output = []
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
        yield store, output


def test_history_commands_expose_read_and_restore_risks():
    specs = {spec.canonical: spec for spec in COMMAND_CATALOG}
    assert specs["playlist history"].risk is CommandRisk.READ_ONLY
    assert specs["playlist history"].forms[0].argument_kinds == ("playlist-name",)
    assert specs["playlist restore"].risk is CommandRisk.DESTRUCTIVE
    assert specs["playlist restore"].forms[0].argument_kinds == ("playlist-name", "revision")
    assert specs["playlist restore"].forms[0].flags == ("--yes",)


@pytest.mark.parametrize(
    "arguments",
    [
        ["restore"],
        ["restore", "Set"],
        ["restore", "Set", "0"],
        ["restore", "Set", "-1"],
        ["restore", "Set", "1.5"],
        ["restore", "Set", "²"],
        ["restore", "Set", "1" * 5000],
        ["restore", "Set", "1", "extra"],
    ],
)
def test_invalid_restore_syntax_never_requests_confirmation_or_writes(collection, monkeypatch, arguments):
    store, _ = collection
    before = store.get("Set")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Invalid input must be rejected before confirmation")

    monkeypatch.setattr(main, "_confirm_action", unexpected)
    with pytest.raises(PlaylistError, match="Usage: playlist restore"):
        main.playlist_command(arguments)
    assert store.get("Set") == before
    assert store.revisions("Set") == [2, 1]


def test_unknown_revision_is_rejected_before_confirmation(collection, monkeypatch):
    store, _ = collection

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Unknown revisions must not request approval")

    monkeypatch.setattr(main, "_confirm_action", unexpected)
    with pytest.raises(PlaylistError, match="Unknown playlist revision: 999"):
        main.playlist_command(["restore", "Set", "999"])
    assert store.revisions("Set") == [2, 1]


def test_declining_restore_preserves_current_tree_and_history(collection, monkeypatch):
    store, output = collection
    before = store.get("Set")
    prompts = []

    def decline(question, **kwargs):
        prompts.append((question, kwargs))
        return False

    monkeypatch.setattr(main, "_confirm_action", decline)
    main.playlist_command(["restore", "Set", "1"])

    assert len(prompts) == 1
    assert prompts[0][1]["assume_yes"] is False
    assert store.get("Set") == before
    assert store.revisions("Set") == [2, 1]
    assert not any("Restored playlist" in line for line in output)


def test_explicit_restore_retains_description_and_previous_tree(collection, monkeypatch):
    store, output = collection
    approval = []

    def approve(_question, **kwargs):
        approval.append(kwargs["assume_yes"])
        return True

    monkeypatch.setattr(main, "_confirm_action", approve)
    main.playlist_command(["restore", "Set", "1", "--yes"])
    main.playlist_command(["history", "Set"])

    restored = store.get("Set")
    assert approval == [True]
    assert restored.revision == 3
    assert restored.description == "Keep this description"
    assert [item.title for item in store.flattened_media(restored.tree)] == ["first"]
    assert "available revisions: 3, 2, 1" in output[-1]
    assert [item.title for item in store.flattened_media(store.restore("Set", 2).tree)] == ["first", "second"]


@pytest.mark.parametrize("revision", [True, False, 0, -1, 1.0, "1", None, float("nan"), float("inf")])
def test_storage_rejects_non_integer_revisions_without_changes(collection, revision):
    store, _ = collection
    before = store.get("Set")
    with pytest.raises(PlaylistError, match="positive integer"):
        store.restore("Set", revision)
    assert store.get("Set") == before
    assert store.revisions("Set") == [2, 1]


def test_multiple_media_insertions_preserve_order_in_one_revision(collection):
    store, _ = collection
    before = store.get("Set")
    updated = store.add_media_many("Set", [track("middle one"), track("middle two")], position=1)

    assert updated.revision == before.revision + 1
    assert [item.title for item in store.flattened_media(updated.tree)] == [
        "first", "middle one", "middle two", "second",
    ]
    restored = store.restore("Set", before.revision)
    assert [item.title for item in store.flattened_media(restored.tree)] == ["first", "second"]
