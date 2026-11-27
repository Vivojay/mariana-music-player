from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.video import VideoUnavailable


@pytest.fixture
def window_cli(monkeypatch):
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(enabled=True, emit=Mock()))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    media = MediaRef(MediaSource.LOCAL, "movie.mp4", title="Movie", duration=120)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: snapshot)
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    return snapshot


def test_video_status_reports_current_state(window_cli):
    state = main.video_command(["status"])
    assert state["state"] in {"off", "preparing", "ready"}


def test_video_open_uses_desktop_surface_only(window_cli, monkeypatch):
    monkeypatch.setattr(main.VIDEO, "request", lambda _mode, **_kwargs: {"state": "preparing"})
    state = main.video_command(["open"])
    assert state == {"state": "preparing"}
    main.DESKTOP_CONTROL.emit.assert_called_once_with("video-window", {"open": True})


def test_cli_open_close_uses_child_and_retains_controller_position(window_cli, monkeypatch):
    main.DESKTOP_CONTROL.enabled = False
    host = Mock(is_open=False)
    service = Mock()
    service.request.return_value = {"state": "preparing"}
    monkeypatch.setattr(main, "CLI_VIDEO", host)
    monkeypatch.setattr(main, "VIDEO", service)
    monkeypatch.setattr(main, "_cli_video_allowed", lambda: True)
    assert main.video_command(["open"]) == {"state": "preparing"}
    host.open.assert_called_once_with()
    service.request.assert_called_once_with("video", expected_media=window_cli.media)
    assert main.video_command(["close"]) == {"open": False}
    host.close.assert_called_once_with()
    service.request.assert_called_with("audio")
    main.DESKTOP_CONTROL.emit.assert_not_called()


def test_cli_restricted_and_live_media_leave_no_window(window_cli, monkeypatch):
    main.DESKTOP_CONTROL.enabled = False
    host = Mock(is_open=False)
    monkeypatch.setattr(main, "CLI_VIDEO", host)
    monkeypatch.setattr(main, "_cli_video_allowed", lambda: False)
    with pytest.raises(VideoUnavailable, match="restricted"):
        main.video_command(["open"])
    host.open.assert_not_called()
    monkeypatch.setattr(main, "_cli_video_allowed", lambda: True)
    monkeypatch.setattr(main.VIDEO, "request", Mock(side_effect=VideoUnavailable("Live video is not supported")))
    with pytest.raises(VideoUnavailable, match="Live video"):
        main.video_command(["open"])
    host.close.assert_called_once_with()


def test_video_close_emits_without_backend_round_trip(window_cli):
    assert main.video_command(["close"]) == {"open": False}
    main.DESKTOP_CONTROL.emit.assert_called_once_with("video-window", {"open": False})


def test_video_rejects_unknown_operations(window_cli):
    with pytest.raises(ValueError, match="Usage"):
        main.video_command(["pop"])
    with pytest.raises(ValueError, match="Usage"):
        main.video_command(["open", "extra"])
