"""Boundary regressions for looping and completed-track CLI controls."""

from types import SimpleNamespace
from typing import NoReturn, cast

import pytest

import main
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback import DecoderSession, PlaybackController


def _unexpected_output(**_kwargs) -> NoReturn:
    raise AssertionError("Changing loop policy must not open an audio output")


@pytest.fixture
def loop_runtime(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/private/current.mp3", title="Current", duration=60)
    successor = MediaRef(MediaSource.LOCAL, "C:/private/next.mp3", title="Next", duration=60)
    controller = PlaybackController(output_factory=_unexpected_output)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=20, duration=60)
    monkeypatch.setattr(controller, "snapshot", lambda: snapshot)
    monkeypatch.setattr(main.vas, "controller", controller)
    queue_state = {"repeat_mode": "off"}
    item = SimpleNamespace(queue_id=1, media=media)
    queue = SimpleNamespace(
        state=lambda: dict(queue_state), current=lambda: item,
        set_repeat=lambda mode: queue_state.update(repeat_mode=mode),
    )
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
    main._set_loop_override()
    yield media, successor, controller, queue_state
    main._set_loop_override()


@pytest.mark.parametrize("operation", ["once", "infinite", "off"])
def test_loop_policy_change_discards_incompatible_prefetch(loop_runtime, operation):
    media, successor, controller, queue_state = loop_runtime
    stopped = []
    if operation == "off":
        queue_state["repeat_mode"] = "one"
        main._set_loop_override("infinite", media)
    prepared = SimpleNamespace(media=media if operation == "off" else successor, stop=lambda: stopped.append(True))
    controller._next = cast(DecoderSession, prepared)

    main.loop_command([operation])

    assert controller._next is None
    assert stopped == [True]
    assert controller.snapshot().media is media and controller.snapshot().position == 20


def test_queue_repeat_change_discards_previous_prefetch(loop_runtime):
    _media, successor, controller, _queue_state = loop_runtime
    stopped = []
    controller._next = cast(DecoderSession, SimpleNamespace(media=successor, stop=lambda: stopped.append(True)))

    main.queue_command(["repeat", "one"])

    assert controller._next is None and stopped == [True]


def test_direct_loop_rechecks_blocked_media_before_replay(loop_runtime, monkeypatch):
    media, _successor, _controller, _queue_state = loop_runtime
    monkeypatch.setattr(main.QUEUE, "current", lambda: None)
    monkeypatch.setattr(main, "_is_media_blocked", lambda _media: True)
    played = []
    monkeypatch.setattr(main.vas.supervisor, "play", lambda *args, **_kwargs: played.append(args))
    for name in ("_set_current_media_state", "_record_queue_history", "_show_local_copy_hint", "_record_successful_start"):
        monkeypatch.setattr(main, name, lambda *_args: None)

    with pytest.raises(main.PlaybackBlockedError, match="Playback blocked"):
        main._replay_completed_media(media)

    assert played == []


@pytest.mark.parametrize("arguments", [["status"], ["once", "extra"], ["twice"]])
def test_loop_query_and_invalid_requests_preserve_prefetch_and_override(loop_runtime, arguments):
    media, successor, controller, queue_state = loop_runtime
    stopped = []
    prepared = SimpleNamespace(media=successor, stop=lambda: stopped.append(True))
    controller._next = cast(DecoderSession, prepared)
    main._set_loop_override("once", media)
    if arguments == ["status"]:
        main.loop_command(arguments)
    else:
        with pytest.raises(ValueError, match="Usage"):
            main.loop_command(arguments)
    assert controller._next is prepared and stopped == []
    assert main._loop_status()["mode"] == "once"
    assert queue_state["repeat_mode"] == "off"


def test_loop_keeps_a_same_identity_copy_already_promoted_by_controller(loop_runtime, monkeypatch):
    media, _successor, controller, queue_state = loop_runtime
    monkeypatch.setattr(controller, "snapshot", PlaybackController.snapshot.__get__(controller, PlaybackController))
    completed = SimpleNamespace(media=media, position=60, stop=lambda: None)
    promoted = SimpleNamespace(media=media, position=.5, buffered_seconds=1.0, stop=lambda: None)
    controller._active = cast(DecoderSession, completed)
    controller._next = cast(DecoderSession, promoted)
    controller._state = PlaybackState.PLAYING
    controller.on_complete = main._on_queue_item_complete
    queue_state["repeat_mode"] = "one"
    main._set_loop_override("infinite", media)
    actions = []
    monkeypatch.setattr(main, "RECOMMENDER", SimpleNamespace(record_event=lambda *_args: None))
    monkeypatch.setattr(main, "STATION", SimpleNamespace(mark_played=lambda *_args: None))
    monkeypatch.setattr(main, "_is_media_blocked", lambda _media: False)
    monkeypatch.setattr(main, "_play_queue_item", lambda _item: actions.append("restarted"))
    monkeypatch.setattr(main, "_set_current_media_state", lambda _media: actions.append("state"))
    monkeypatch.setattr(main, "_record_queue_history", lambda _media: actions.append("history"))
    monkeypatch.setattr(main, "_record_successful_start", lambda _media: actions.append("start"))
    monkeypatch.setattr(main, "_prefetch_after", lambda _item: actions.append("prefetch"))

    class ImmediateThread:
        def __init__(self, target, args=(), **_kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(main.threading, "Thread", ImmediateThread)

    controller._promote_next(cast(DecoderSession, completed))

    assert controller._active is promoted and controller.snapshot().position == .5
    assert actions == ["state", "history", "start", "prefetch"]


def test_stale_direct_completion_does_not_replace_newer_active_media(loop_runtime, monkeypatch):
    media, previous, _controller, queue_state = loop_runtime
    main._set_loop_override("infinite", previous)
    queue_state["repeat_mode"] = "one"
    monkeypatch.setattr(main.QUEUE, "current", lambda: None)
    monkeypatch.setattr(main, "RECOMMENDER", SimpleNamespace(record_event=lambda *_args: None, retrain_if_due=lambda: None))
    monkeypatch.setattr(main, "STATION", SimpleNamespace(mark_played=lambda *_args: None))
    replayed = []
    monkeypatch.setattr(main, "_replay_completed_media", replayed.append)

    main._on_queue_item_complete(previous)

    assert main.vas.controller.snapshot().media is media
    assert replayed == []


@pytest.mark.parametrize("state", [PlaybackState.IDLE, PlaybackState.PAUSED])
def test_stale_completion_cannot_override_later_stop_or_pause(loop_runtime, monkeypatch, state):
    media, _successor, controller, queue_state = loop_runtime
    main._set_loop_override("infinite", media)
    queue_state["repeat_mode"] = "one"
    snapshot = PlaybackSnapshot(state, media=media if state == PlaybackState.PAUSED else None)
    monkeypatch.setattr(controller, "snapshot", lambda: snapshot)
    monkeypatch.setattr(main.QUEUE, "current", lambda: None)
    monkeypatch.setattr(main, "RECOMMENDER", SimpleNamespace(record_event=lambda *_args: None, retrain_if_due=lambda: None))
    monkeypatch.setattr(main, "STATION", SimpleNamespace(mark_played=lambda *_args: None))
    replayed = []
    monkeypatch.setattr(main, "_replay_completed_media", replayed.append)

    main._on_queue_item_complete(media)

    assert replayed == []


@pytest.mark.parametrize("legacy_duration", [None, 0, -1])
def test_restart_uses_authoritative_completed_media_when_legacy_duration_is_stale(loop_runtime, monkeypatch, legacy_duration):
    media, _successor, controller, _queue_state = loop_runtime
    monkeypatch.setattr(controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE, media=media, duration=60, position=60))
    monkeypatch.setattr(main, "currentsong_length", legacy_duration)
    monkeypatch.setattr(main, "PLAY_REGIONS", SimpleNamespace(get=lambda _media: None))
    monkeypatch.setattr(main, "_sync_legacy_playback_state", lambda: None)
    seeks = []
    monkeypatch.setattr(main, "song_seek", lambda *, timeval: seeks.append(timeval) or True)

    assert main.restart_command([]) == 0
    assert seeks == [0.0]


@pytest.mark.parametrize("operation", ["reset", "restart"])
def test_reset_and_restart_reject_live_media_even_if_seekable(loop_runtime, monkeypatch, operation):
    _media, _successor, controller, _queue_state = loop_runtime
    media = MediaRef(
        MediaSource.RADIO, "https://private.test/live", duration=60,
        capabilities=MediaCapabilities(finite=False, live=True, seekable=True),
    )
    monkeypatch.setattr(controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media, duration=60))
    monkeypatch.setattr(main, "currentsong_length", 60)
    monkeypatch.setattr(main, "PLAY_REGIONS", SimpleNamespace(get=lambda _media: None))
    monkeypatch.setattr(main, "_sync_legacy_playback_state", lambda: None)
    seeks = []
    monkeypatch.setattr(main, "song_seek", lambda *args, **kwargs: seeks.append((args, kwargs)) or True)

    if operation == "reset":
        assert main.reset_playback() is False
    else:
        with pytest.raises(ValueError, match="finite audio"):
            main.restart_command([])
    assert seeks == []


def test_loop_history_helpers_keep_safe_titles_and_survive_optional_write_failures(loop_runtime, monkeypatch, tmp_path):
    media = MediaRef(MediaSource.URL, "https://private.test/audio?token=secret")
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(logs=tmp_path))
    history = []
    events = []
    diagnostics = []
    monkeypatch.setattr(main, "SAY", lambda **kwargs: history.append(kwargs))
    monkeypatch.setattr(main.playback_diagnostics, "record", lambda *args: diagnostics.append(args))
    monkeypatch.setattr(main, "PREFERENCES", SimpleNamespace(remember=lambda _media: (_ for _ in ()).throw(OSError("secret"))))
    monkeypatch.setattr(main, "RECOMMENDER", SimpleNamespace(record_event=lambda *args: events.append(args)))

    main._record_queue_history(media)
    main._record_successful_start(media)

    assert history[0]["log_message"] == "Online media"
    assert history[0]["out_file"] == tmp_path / "history.log"
    assert events == [(media, "start")]
    assert diagnostics == [(2, "history.identity_write_failed")]
    assert "secret" not in str(history) + str(diagnostics)
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: (_ for _ in ()).throw(OSError("secret")))
    main._record_queue_history(media)
    assert diagnostics[-1] == (2, "history.write_failed")


def test_loop_reset_restart_catalog_and_playback_help_are_complete(loop_runtime, monkeypatch):
    printed = []
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: printed.append(str(value)))
    main.help_command(["playback"])
    rendered = "\n".join(printed)
    for command in ("loop once", "reset", ".reset", "restart"):
        assert command in rendered
    rows = {row["canonical"]: row for row in main.serialize_command_catalog()}
    for command in ("loop", "reset", ".reset", "restart"):
        assert rows[command]["risk"] == "state-changing"
    assert rows["restart"]["availability"] == ("finite-media",)
