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


def test_video_open_requires_desktop(window_cli):
    main.DESKTOP_CONTROL.enabled = False
    with pytest.raises(VideoUnavailable):
        main.video_command(["open"])
    main.DESKTOP_CONTROL.emit.assert_not_called()


def test_video_close_emits_without_backend_round_trip(window_cli):
    assert main.video_command(["close"]) == {"open": False}
    main.DESKTOP_CONTROL.emit.assert_called_once_with("video-window", {"open": False})


def test_video_rejects_unknown_operations(window_cli):
    with pytest.raises(ValueError, match="Usage"):
        main.video_command(["pop"])
    with pytest.raises(ValueError, match="Usage"):
        main.video_command(["open", "extra"])
