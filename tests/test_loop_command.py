from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture(autouse=True)
def reset_loop_override():
    main._set_loop_override()
    yield
    main._set_loop_override()


def finite_media(name="Track"):
    return MediaRef(
        MediaSource.LOCAL,
        f"C:/{name}.mp3",
        title=name,
        capabilities=MediaCapabilities(finite=True, live=False, seekable=True, downloadable=True),
    )


class QueueState:
    def __init__(self, media=None):
        self.repeat_mode = "off"
        self.item = SimpleNamespace(queue_id=1, media=media) if media is not None else None
        self.changes = []

    def state(self):
        return {"repeat_mode": self.repeat_mode}

    def set_repeat(self, mode):
        self.repeat_mode = mode
        self.changes.append(mode)

    def current(self):
        return self.item


def prepare_command(monkeypatch, media, *, state=PlaybackState.PLAYING, queued=True):
    queue = QueueState(media if queued else None)
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(state, media=media))
    monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    return queue


def test_loop_command_supports_once_infinite_status_off_and_aliases(monkeypatch):
    media = finite_media()
    queue = prepare_command(monkeypatch, media)

    assert main.loop_command(["once"])["mode"] == "once"
    assert main.loop_command([])["remaining"] == 1

    assert main.loop_command(["on"])["mode"] == "infinite"
    assert queue.repeat_mode == "one"
    assert main.loop_command(["forever"])["mode"] == "infinite"

    assert main.loop_command(["1"])["mode"] == "once"
    assert queue.repeat_mode == "off"
    assert main.loop_command(["off"])["mode"] == "off"
    assert queue.changes == ["one", "one", "off"]


def test_loop_once_replays_exactly_once_before_disabled_autonext(monkeypatch):
    media = finite_media()
    queue = QueueState(media)
    replayed = []
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", False)
    monkeypatch.setattr(main, "_play_queue_item", replayed.append)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE, media=media))
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.RECOMMENDER, "retrain_if_due", lambda: None)
    monkeypatch.setattr(main.STATION, "mark_played", lambda *_args: None)
    main._set_loop_override("once", media)

    main._on_queue_item_complete(media)
    main._on_queue_item_complete(media)

    assert replayed == [queue.item]
    assert main._loop_status()["mode"] == "off"


def test_direct_media_infinite_loop_replays_without_queue_duplication(monkeypatch):
    media = finite_media("Direct")
    queue = QueueState()
    replayed = []
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", False)
    monkeypatch.setattr(main.vas.supervisor, "play", lambda item, **kwargs: replayed.append((item, kwargs)))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE, media=media))
    monkeypatch.setattr(main, "_set_current_media_state", lambda *_args: None)
    monkeypatch.setattr(main, "_record_queue_history", lambda *_args: None)
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda *_args: None)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.STATION, "mark_played", lambda *_args: None)
    main._set_loop_override("infinite", media)

    main._on_queue_item_complete(media)
    main._on_queue_item_complete(media)

    assert replayed == [
        (media, {"origin": "automatic"}),
        (media, {"origin": "automatic"}),
    ]
    assert queue.item is None


def test_persistent_infinite_mode_follows_a_new_direct_media_identity(monkeypatch):
    previous = finite_media("Previous")
    current = finite_media("Current")
    queue = QueueState()
    queue.repeat_mode = "one"
    replayed = []
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", False)
    monkeypatch.setattr(main.vas.supervisor, "play", lambda item, **_kwargs: replayed.append(item))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE, media=current))
    monkeypatch.setattr(main, "_set_current_media_state", lambda *_args: None)
    monkeypatch.setattr(main, "_record_queue_history", lambda *_args: None)
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda *_args: None)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.STATION, "mark_played", lambda *_args: None)
    main._set_loop_override("infinite", previous)

    main._on_queue_item_complete(current)

    assert replayed == [current]


def test_loop_refuses_live_missing_and_invalid_requests(monkeypatch):
    live = MediaRef(
        MediaSource.RADIO,
        "https://radio.example/live",
        title="Live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False, downloadable=False),
    )
    prepare_command(monkeypatch, live)
    with pytest.raises(ValueError, match="finite media"):
        main.loop_command(["once"])
    with pytest.raises(ValueError, match="Usage"):
        main.loop_command(["twice"])

    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE))
    with pytest.raises(ValueError, match="No current media"):
        main.loop_command(["infinite"])


def test_loop_command_is_exposed_in_public_catalog():
    row = next(entry for entry in main.serialize_command_catalog() if entry["canonical"] == "loop")
    assert row["availability"] == ("current-media",)
    assert tuple(form["tokens"] for form in row["forms"]) == (
        ("status",),
        ("once",),
        ("infinite",),
        ("off",),
        ("1",),
        ("on",),
        ("forever",),
    )


def test_queue_repeat_replaces_loop_override_only_after_validation(monkeypatch):
    media = finite_media()
    prepare_command(monkeypatch, media)
    main._set_loop_override("once", media)

    with pytest.raises(main.QueueError, match="Unknown repeat mode"):
        main.queue_command(["repeat", "sometimes"])
    assert main._loop_status()["mode"] == "once"

    main.queue_command(["repeat", "all"])
    status = main._loop_status()
    assert status["mode"] == "off"
    assert status["queue_repeat"] == "all"
