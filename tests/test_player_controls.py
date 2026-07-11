from types import SimpleNamespace

import pytest

import main
from mariana.models import PlaybackSnapshot, PlaybackState


def test_enqueue_builds_a_unique_local_playlist(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "_sound_files", ["one.mp3", "two.mp3"])
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda paths, _songindex, is_queue: captured.update(
            paths=paths, songindex=_songindex, is_queue=is_queue
        ),
    )
    main.enqueue(["1", "2", "2"])
    assert captured == {"paths": ["one.mp3", "two.mp3"], "songindex": None, "is_queue": True}


def test_seek_zero_resets_playback(monkeypatch):
    player = SimpleNamespace(time=None)
    player.set_time = lambda value: setattr(player, "time", value)
    monkeypatch.setattr(main.vas, "player", player)
    assert main.song_seek(0) is True
    assert player.time == 0


def test_ffmpeg_playback_wait_has_a_timeout(monkeypatch):
    states = SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.BUFFERING))
    monkeypatch.setattr(main.vas, "controller", states)
    with pytest.raises(TimeoutError, match="FFmpeg did not start"):
        main.vas.wait_until_playing(timeout=0.01, poll_interval=0)


def test_radio_aliases_use_official_playlists():
    assert main.vas.radio_stream_url("coffee").endswith("groovesalad.m3u")
    assert main.vas.radio_stream_url("chillout").endswith("groovesalad.m3u")
    with pytest.raises(ValueError, match="Unknown radio station"):
        main.vas.radio_stream_url("missing")


def test_audio_initialization_failure_is_actionable(monkeypatch):
    monkeypatch.setattr(main.sounddevice, "query_devices", lambda: [])
    with pytest.raises(RuntimeError, match="audio output device"):
        main.initialize_audio_output()
