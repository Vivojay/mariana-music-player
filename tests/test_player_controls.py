import importlib

import pytest

import main


def test_enqueue_builds_a_unique_vlc_playlist(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "_sound_files", ["one.mp3", "two.mp3"])
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda paths, _songindex, is_queue: captured.update(
            paths=paths,
            songindex=_songindex,
            is_queue=is_queue,
        ),
    )

    main.enqueue(["1", "2", "2"])

    assert captured == {
        "paths": ["one.mp3", "two.mp3"],
        "songindex": None,
        "is_queue": True,
    }


class FakePlayer:
    def __init__(self):
        self.time = None

    def set_time(self, value):
        self.time = value


class FakeListPlayer:
    def __init__(self, player):
        self.player = player

    def get_media_player(self):
        return self.player


def test_seek_zero_resets_playback(monkeypatch):
    player = FakePlayer()
    monkeypatch.setattr(main.vas, "vlc_media_player", FakeListPlayer(player))

    assert main.song_seek(0) is True
    assert player.time == 0


def test_vlc_playback_wait_has_a_timeout(monkeypatch):
    vlc_stream = importlib.import_module("beta.vlc-async-stream")
    player = type("NeverPlaying", (), {"is_playing": lambda self: False})()
    list_player = type("ListPlayer", (), {"get_media_player": lambda self: player})()
    monkeypatch.setattr(vlc_stream, "VLC_AVAILABLE", True)
    monkeypatch.setattr(vlc_stream, "vlc", object())
    monkeypatch.setattr(vlc_stream, "vlc_media_player", list_player)

    with pytest.raises(TimeoutError, match="did not start playback"):
        vlc_stream.wait_until_playing(timeout=0.01, poll_interval=0)


def test_radio_aliases_use_permanent_playlists():
    vlc_stream = importlib.import_module("beta.vlc-async-stream")
    assert vlc_stream.radio_stream_url("coffee").endswith("gsclassic.m3u")
    assert vlc_stream.radio_stream_url("chillout").endswith("groovesalad.m3u")
    assert vlc_stream.radio_stream_url("lounge").endswith("illstreet.m3u")
    with pytest.raises(ValueError, match="Unknown radio station"):
        vlc_stream.radio_stream_url("missing")


def test_audio_initialization_failure_is_actionable(monkeypatch):
    monkeypatch.setattr(
        main.pygame.mixer,
        "init",
        lambda: (_ for _ in ()).throw(main.pygame.error("no device")),
    )
    with pytest.raises(RuntimeError, match="audio output device"):
        main.initialize_audio_output()
