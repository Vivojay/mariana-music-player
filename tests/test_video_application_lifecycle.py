"""Application ownership of committed video, captions, and resume services."""

import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


def test_controller_reconnect_detaches_old_observers_and_rejects_late_delivery(monkeypatch):
    previous, current, removed, video, resume = [], [], [], [], []

    def controller(name, callbacks):
        def subscribe(callback):
            callbacks.append(callback)
            return lambda: removed.append((name, callback))
        return SimpleNamespace(add_active_media_sink=subscribe)

    old_controller = controller("old", previous)
    new_controller = controller("new", current)
    monkeypatch.setattr(main, "_PRESENTATION_OBSERVER_REMOVERS", [])
    monkeypatch.setattr(main, "_PRESENTATION_OBSERVER_GENERATION", None)
    monkeypatch.setattr(main, "VIDEO", SimpleNamespace(activate=lambda *args: video.append(args)))
    monkeypatch.setattr(main, "PLAYBACK_RESUME", SimpleNamespace(activate=lambda *args: resume.append(args)))
    monkeypatch.setattr(main.vas, "controller", old_controller)
    media = MediaRef(MediaSource.LOCAL, "C:/fixture/movie.mp4")
    resolved = object()

    main._connect_video_controller()
    assert len(previous) == 2
    for callback in previous:
        callback(media, resolved)
    assert video == [(media, resolved)] and resume == [(media, resolved)]

    monkeypatch.setattr(main.vas, "controller", new_controller)
    main._connect_video_controller()
    assert len(current) == 2 and [name for name, _callback in removed] == ["old", "old"]
    for callback in previous:
        callback(media, resolved)
    assert len(video) == len(resume) == 1
    for callback in current:
        callback(None, None)
    assert video[-1] == resume[-1] == (None, None)
    main._disconnect_video_controller()
    assert main._PRESENTATION_OBSERVER_REMOVERS == []
    for callback in current:
        callback(media, resolved)
    assert len(video) == len(resume) == 2


def test_caption_persistence_preserves_other_settings_and_does_not_publish_a_failed_save(monkeypatch):
    original = {"captions": {"languages": ["eng"]}, "equalizer": {"enabled": True}, "custom": 17}
    monkeypatch.setattr(main, "SETTINGS", deepcopy(original))
    saved = []
    monkeypatch.setattr(main, "save_user_settings", lambda value, path: saved.append((deepcopy(value), path)))
    value = {"languages": ["hin", "eng"], "media": {}}
    main._persist_caption_configuration(value)
    assert {**original, "captions": value} == main.SETTINGS
    assert saved == [({**original, "captions": value}, main.RUNTIME_PATHS.settings)]

    def unavailable(*_args):
        raise OSError("private configuration path")

    before = deepcopy(main.SETTINGS)
    monkeypatch.setattr(main, "save_user_settings", unavailable)
    with pytest.raises(OSError):
        main._persist_caption_configuration({"languages": ["fra"]})
    assert before == main.SETTINGS


def test_resume_final_flush_runs_with_parallel_shutdown_and_uses_captured_position(monkeypatch):
    owner_thread = threading.get_ident()
    media = MediaRef(MediaSource.LOCAL, "C:/fixture/movie.mp4", duration=4800)
    final_snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, duration=4800, position=240)
    current = [final_snapshot]
    closes, flushed = [], []
    playback_closed = threading.Event()

    def flush(snapshot):
        assert threading.get_ident() != owner_thread
        assert playback_closed.wait(3), "Persistence must not block the start of playback shutdown"
        flushed.append(snapshot)

    def close_playback():
        current[0] = PlaybackSnapshot(PlaybackState.IDLE)
        playback_closed.set()
        closes.append("playback")

    monkeypatch.setattr(main, "_disconnect_video_controller", lambda: closes.append("detach"))
    monkeypatch.setattr(main, "_close_artwork_controller", lambda: closes.append("artwork"))
    monkeypatch.setattr(main, "PLAYBACK_RESUME", SimpleNamespace(
        capture_now=flush, close=lambda: closes.append("resume"),
    ))
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(snapshot=lambda: current[0]))
    monkeypatch.setattr(main.vas, "supervisor", SimpleNamespace(close=close_playback))
    for name in ("VIDEO", "HOMEPAGE", "SLEEP_TIMER", "PRESENCE", "STATION", "DOWNLOADS", "BROADCASTER", "LIBRARY_SERVICE"):
        monkeypatch.setattr(main, name, SimpleNamespace(close=lambda name=name: closes.append(name)))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(
        emit=lambda *_args: None, close=lambda: closes.append("desktop"),
    ))
    monkeypatch.setattr(main, "RECOMMENDER", SimpleNamespace(record_event=lambda *_args, **_kwargs: None))
    monkeypatch.setattr(main, "APP_BOOT_END_TIME", main.time.time())
    monkeypatch.setattr(main, "currentsong", main.currentsong)
    monkeypatch.setattr(main, "isplaying", main.isplaying)
    monkeypatch.setattr(main, "USER_DATA", {"default_user_data": {"stats": {"times_spent": []}}})
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "purge_old_lyrics_if_exist", lambda: None)

    main.exitplayer()

    assert flushed == [final_snapshot] and flushed[0].position == 240
    assert current[0].state == PlaybackState.IDLE
    assert closes[0] == "detach" and "resume" in closes and "VIDEO" in closes
    assert "HOMEPAGE" in closes and "artwork" in closes


@pytest.mark.parametrize("command", [
    "play current --video", "/ys concert --video", "/yl https://youtu.be/abcdefghijk --video",
    "/ml https://example.org/movie.mp4 --video",
])
def test_terminal_only_video_request_is_rejected_before_playback_or_resolution(monkeypatch, command):
    calls, printed = [], []
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(enabled=False))
    monkeypatch.setattr(main, "play_vas_media", lambda *_args, **_kwargs: calls.append("play"))
    monkeypatch.setattr(main, "choose_media_url", lambda *_args, **_kwargs: calls.append("choose"))
    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: calls.append("search"))
    monkeypatch.setattr(main, "IPrint", lambda message, **_kwargs: printed.append(str(message)))
    main.process(command)
    assert calls == []
    assert any("requires the Mariana desktop" in line for line in printed)


@pytest.mark.parametrize(("command", "value", "relative"), [
    ("avsync set 250", 250, False), ("avsync shift -100", -100, True),
    ("avsync reset", 0, False),
])
def test_avsync_commands_only_change_picture_timing(monkeypatch, command, value, relative):
    media = MediaRef(MediaSource.LOCAL, "C:/fixture/movie.mp4")
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=25)
    calls, emitted = [], []
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: snapshot)
    monkeypatch.setattr(main, "VIDEO", SimpleNamespace(
        configure_audio_offset=lambda offset, **kwargs: (
            calls.append((offset, kwargs)) or {"audio_offset_ms": offset}
        ),
        host_status=lambda: {"audio_offset_ms": value},
    ))
    monkeypatch.setattr(main.DESKTOP_CONTROL, "emit", lambda *args: emitted.append(args))
    main.process(command)
    expected = {"expected_media": media}
    if command != "avsync reset":
        expected["relative"] = relative
    assert calls == [(value, expected)]
    assert emitted == [("video", {"audio_offset_ms": value})]
    assert snapshot.state == PlaybackState.PAUSED and snapshot.position == 25


@pytest.mark.parametrize("arguments", [
    ["set", "NaN"], ["set", "inf"], ["shift", "0.5"], ["set"], ["reset", "1"], ["set", "100000"],
])
def test_avsync_rejects_invalid_syntax_without_reaching_service(monkeypatch, arguments):
    monkeypatch.setattr(main, "VIDEO", SimpleNamespace(
        configure_audio_offset=lambda *_args, **_kwargs: pytest.fail("Invalid input reached the video service"),
    ))
    printed = []
    monkeypatch.setattr(main, "IPrint", lambda message, **_kwargs: printed.append(str(message)))
    main.avsync_command(arguments)
    assert len(printed) == 1 and "Usage: avsync" in printed[0]
