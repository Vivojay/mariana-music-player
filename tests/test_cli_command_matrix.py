"""Broad behavior-level coverage for the preserved interactive command surface."""

from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def cli(monkeypatch, tmp_path):
    songs = []
    for name in ("Alpha.mp3", "Beta.mp3", "Gamma.mp3"):
        path = tmp_path / name
        path.write_bytes(b"audio")
        songs.append(str(path))
    printed, messages, actions = [], [], []
    monkeypatch.setattr(main, "_sound_files", songs)
    monkeypatch.setattr(main, "_sound_files_names_only", ["Alpha", "Beta", "Gamma"])
    monkeypatch.setattr(main, "_sound_files_names_enumerated", [(1, "Alpha"), (2, "Beta"), (3, "Gamma")])
    monkeypatch.setattr(main, "paths", [str(tmp_path)])
    monkeypatch.setattr(main, "RECENTS_QUEUE", [(None, None, (1, songs[0])), (None, None, (2, songs[1]))])
    monkeypatch.setattr(main, "currentsong", songs[0])
    monkeypatch.setattr(main, "currentsong_length", 120)
    monkeypatch.setattr(main, "songindex", 2)
    monkeypatch.setattr(main, "current_media_type", None)
    monkeypatch.setattr(main, "isplaying", True)
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    monkeypatch.setattr(main, "reload_sounds", lambda **kwargs: actions.append(("reload", kwargs)))
    monkeypatch.setattr(main, "open_in_youtube", lambda value: actions.append(("youtube", value)))
    monkeypatch.setattr(main, "local_play_commands", lambda commandslist: actions.append(("local", commandslist)))
    monkeypatch.setattr(main, "stopsong", lambda: actions.append(("stop",)))
    monkeypatch.setattr(main, "lyrics_ops", lambda **kwargs: actions.append(("lyrics", kwargs)))
    monkeypatch.setattr(main, "purge_old_lyrics_if_exist", lambda: actions.append(("purge",)))
    monkeypatch.setattr(main, "fade_in_out", lambda **kwargs: actions.append(("fade", kwargs)))
    monkeypatch.setattr(main, "setmastervolume", lambda value=None: actions.append(("master", value)))
    monkeypatch.setattr(main, "get_master_volume", lambda: 42)
    monkeypatch.setattr(main, "get_current_progress", lambda: 30)
    monkeypatch.setattr(main, "song_seek", lambda value=None, **kwargs: actions.append(("seek", value, kwargs)) or True)
    monkeypatch.setattr(main, "get_latest_podbean_data", lambda **kwargs: [{"title": "Episode"}])
    monkeypatch.setattr(main, "display_and_choose_podbean", lambda **kwargs: actions.append(("podcast", kwargs)))
    monkeypatch.setattr(main, "queue_command", lambda args: actions.append(("queue", args)))
    monkeypatch.setattr(main, "radio_command", lambda args: actions.append(("radio", args)))
    monkeypatch.setattr(main, "recommendation_command", lambda args: actions.append(("recommend", args)))
    monkeypatch.setattr(main, "url_is_valid", lambda value: value.startswith("https://"))
    monkeypatch.setattr(main.sounddevice, "query_devices", lambda **_kwargs: {"name": "Test Device"})
    monkeypatch.setattr(main.os, "system", lambda command: actions.append(("system", command)) or 0)
    monkeypatch.setattr(main.sp, "Popen", lambda args, **kwargs: actions.append(("spawn", args, kwargs)))
    monkeypatch.setattr(main.webbrowser, "open", lambda url: actions.append(("browser", url)))
    monkeypatch.setattr(main.webbrowser, "_tryorder", [])
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=MediaRef(MediaSource.LOCAL, songs[0])))
    player = SimpleNamespace(
        audio_set_volume=lambda value: actions.append(("volume", value)),
        audio_set_mute=lambda value: actions.append(("mute", value)),
        get_length=lambda: 120_000,
        get_time=lambda: 30_000,
        set_time=lambda value: actions.append(("time", value)),
    )
    monkeypatch.setattr(main.vas, "player", player)
    monkeypatch.setattr(main.vas, "media_player", lambda **kwargs: actions.append(("media", kwargs)))
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    return SimpleNamespace(printed=printed, messages=messages, actions=actions, songs=songs, tmp_path=tmp_path)


@pytest.mark.parametrize(
    "command",
    [
        "all",
        "list",
        "list 2 o desc",
        "list 1 3",
        "list 1-3",
        "list 3-1",
        "list pattern",
        "/open",
        "/open 2",
        "/open missing.mp3",
        "last",
        "/rss https://example.test/feed",
        "/rss invalid",
        "/rss",
        "pod vendors all",
        "pod invalid",
        ".pods",
        "pods 2",
        ".pod 2 1001tracklists",
        "recent count",
        "recent",
        "recent 1 o desc",
        "recent 1-2",
        "recent pattern",
        "last played",
        "reload",
        "refresh",
        "refresh lyrics",
        "vis",
        "play 1",
        "output device",
        "input device",
        "fade in",
        "fade out 2",
        "fade from 20 to 80 in 2",
        "fade invalid",
        "m?",
        "isp?",
        "ispl?",
        "isl?",
        "seek -10",
        "seek 50",
        "progress",
        "progress*",
        "download",
        "download-yv",
        "download-ya",
        "download-ml",
        "t",
        ".rand",
        "=rand",
        "rand",
        "rand*",
        "/rand",
        "reset",
        ".1",
        ". 1",
        "clear",
        "p",
        "ph",
        "1",
        "0",
        "count",
        "weblinks",
        "open",
        "open lib",
        "open lyrics",
        "open 2",
        "sync",
        "path",
        "path 2",
        "path 0",
        "find Alpha 1",
        "find missing",
        "stop",
        "m",
        "lyrics",
        "volume",
        "volume 101",
        "mvolume",
        "mvolume 25",
        "length",
        "library",
        "view library",
        "view lyrics",
        "music-downloads",
        "queue list",
        "radio list",
        "recommend 3",
        "/rs",
    ],
)
def test_command_matrix_never_requires_external_side_effects(cli, command):
    main.process(command)


@pytest.mark.parametrize(
    ("media_type", "song"),
    [
        (None, "local.mp3"),
        (0, ("Video", "https://youtube.test/watch?v=1")),
        (1, "https://example.test/audio"),
        (2, "coffee"),
        (3, ("Session", "https://example.test/session")),
    ],
)
def test_now_and_open_render_every_media_type(cli, monkeypatch, media_type, song):
    monkeypatch.setattr(main, "current_media_type", media_type)
    monkeypatch.setattr(main, "currentsong", song)
    monkeypatch.setattr(main, "YOUTUBE_PLAY_TYPE", 0)
    main.process("now")
    main.process("now*")
    main.process("open")


def test_exit_confirmation_paths(cli, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_args: "y")
    assert main.process("exit") is False
    assert main.process("quit y") is False
