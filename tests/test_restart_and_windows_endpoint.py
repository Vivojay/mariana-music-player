"""Regressions for completed-track playback controls."""

from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.mark.parametrize("source", [MediaSource.LOCAL, MediaSource.YOUTUBE])
@pytest.mark.parametrize("start", [0.0, 12.5])
def test_completed_restart_restores_cli_pause_toggle(monkeypatch, source, start):
    media = MediaRef(source, "C:/music/song.mp3" if source == MediaSource.LOCAL
                     else "https://www.youtube.com/watch?v=example", title="Song", duration=223)
    state = PlaybackSnapshot(PlaybackState.IDLE, media=media, position=223, duration=223)
    current = [state]
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: current[0])
    for name, value in {"currentsong": None, "currentsong_length": 223, "isplaying": False,
                        "songindex": -1, "current_media_type": None}.items():
        monkeypatch.setattr(main, name, value)
    monkeypatch.setattr(main, "PLAY_REGIONS", SimpleNamespace(
        get=lambda _media: SimpleNamespace(start_seconds=start)))
    monkeypatch.setattr(main, "_library_song_index", lambda _path: 7)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    actions = []

    def seek(milliseconds):
        actions.append(("seek", milliseconds))
        current[0] = PlaybackSnapshot(PlaybackState.PAUSED, media=media,
                                      position=milliseconds / 1000, duration=223)

    def toggle(*, action, origin):
        assert action == "pausetoggle" and origin == "cli"
        target = PlaybackState.PLAYING if current[0].state == PlaybackState.PAUSED else PlaybackState.PAUSED
        current[0] = PlaybackSnapshot(target, media=media, position=start, duration=223)
        actions.append(target)

    monkeypatch.setattr(main.vas.player, "set_time", seek)
    monkeypatch.setattr(main.vas.player, "audio_set_volume", lambda _value: None)
    monkeypatch.setattr(main.vas, "media_player", toggle)
    monkeypatch.setattr(main, "voltransition", lambda **_kwargs: None)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "visible", False)
    assert main.restart_command([]) == start
    assert current[0].state == PlaybackState.PAUSED
    assert main.currentsong == (media.original_uri if source == MediaSource.LOCAL else media.title)
    assert main.songindex == (7 if source == MediaSource.LOCAL else -1)
    main.playpausetoggle(softtoggle=False)
    assert current[0].state == PlaybackState.PLAYING and main.isplaying
    main.playpausetoggle(softtoggle=False)
    assert current[0].state == PlaybackState.PAUSED and not main.isplaying
    assert actions == [("seek", int(start * 1000)), PlaybackState.PLAYING, PlaybackState.PAUSED]
