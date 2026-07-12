"""Broad behavior-level coverage for the preserved interactive command surface."""

from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import PreferenceState

REAL_EDIT_CURRENT_LYRICS = main.edit_current_lyrics


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
    monkeypatch.setattr(main, "refresh_settings", lambda: actions.append(("refresh-settings",)))
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
    monkeypatch.setattr(main, "library_command", lambda args: actions.append(("library", args)))
    monkeypatch.setattr(main, "radio_command", lambda args: actions.append(("radio", args)))
    monkeypatch.setattr(main, "recommendation_command", lambda args: actions.append(("recommend", args)))
    monkeypatch.setattr(main, "replaygain_command", lambda args: actions.append(("replaygain", args)))
    monkeypatch.setattr(main, "broadcast_command", lambda args: actions.append(("broadcast", args)))
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *args, **kwargs: actions.append(("event", args, kwargs)))
    monkeypatch.setattr(main.PREFERENCES, "set", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.PREFERENCES, "get", lambda *_args: PreferenceState.NEUTRAL)
    monkeypatch.setattr(main.PREFERENCES, "toggle", lambda _media, state: state)
    monkeypatch.setattr(main.PREFERENCES, "list", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "set_download_library_inclusion", lambda enabled: actions.append(("downloads-root", enabled)))
    monkeypatch.setattr(main, "edit_current_lyrics", lambda: actions.append(("lyrics-edit",)))
    monkeypatch.setattr(main, "recycle_library_media", lambda args: actions.append(("recycle", args)))
    monkeypatch.setattr(main, "reveal_path", lambda path: actions.append(("reveal", path)))
    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: ("Video", "https://youtube.test/watch?v=1"))
    monkeypatch.setattr(main, "play_vas_media", lambda *args, **kwargs: actions.append(("play-vas", args, kwargs)))
    monkeypatch.setattr(
        main,
        "url_is_valid",
        lambda value=None, url=None, **_kwargs: (value or url or "").startswith("https://"),
    )
    monkeypatch.setattr(main, "download_media", lambda *args, **kwargs: actions.append(("download-media", args, kwargs)) or tmp_path / "media.mp3")
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
        "all*",
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
        "reload include-downloads",
        "reload exclude downloads",
        "include downloads",
        "exclude dl",
        "history",
        "hist count",
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
        ".arand",
        "=rand",
        "=arand",
        "rand",
        "arand",
        "rand*",
        "arand*",
        "/rand",
        "/arand",
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
        "mute",
        "lyrics",
        "lyrics edit",
        "volume",
        "volumeh",
        "volume 101",
        "mvolume",
        "mvolume 25",
        "length",
        "library",
        "library status",
        "view library",
        "view lyrics",
        "music-downloads",
        "queue list",
        "radio list",
        "replaygain status",
        "broadcast status",
        "recommend 3",
        "recommend related 3",
        "fav",
        "fav !",
        "fav +",
        "bl -",
        "favs",
        "blacklist 2",
        "beta",
        "beta off",
        "check_dev",
        "rm 1",
        "del 2",
        "/rs",
        "/reddit-session",
        "/rpan",
        ".",
        ".*",
        "+",
        "-",
        ".+",
        ".-",
        "rfind Alpha 1",
        "lfind Alpha missing",
        ".find Alpha",
        "/find Alpha",
        "dl-yv invalid",
        "dl-ya invalid",
        "donwload-yv",
        "list bad-range",
        "list 1-2-3",
        "/rss https://example.test/feed extra",
        "pod",
        "pod vendors 1",
        ".podbeans",
        "pods 1 2",
        "recent bad-range",
        "recent 1-2-3",
        "recent 2-1",
        "prev 0",
        "prev invalid",
        "prev 999",
        "next 999",
        "fade in invalid",
        "fade in 1 2",
        "fade from invalid to 50 in 2",
        "fade from 20 to invalid in 2",
        "fade from 20 to 50 in invalid",
        "fade from 20 from 30 to 50",
        "fade from 20 to 50 in 1 in 2",
        "seek 1.5",
        "seek invalid",
        "seek -999",
        "download-yv invalid",
        "download-yv one two",
        "download-ya invalid",
        "download-ya one two",
        "download-ml",
        "999",
        "path 999",
        "sleep invalid",
        "replaygain invalid",
        "broadcast invalid",
        "tools invalid",
        "/ys \"query\" 0",
        "/ys \"query\" 999",
        "/ys \"query\" invalid",
        "/yl invalid",
        "/yl one two",
        "/ml invalid",
        "/ml one two",
        "/wra 99",
        "/wra one two",
    ],
)
def test_command_matrix_never_requires_external_side_effects(cli, command):
    main.process(command)


@pytest.mark.parametrize(
    "command",
    [
        "/rss https://example.test/feed.xml 1",
        "pod 1 1",
        "pods 1",
        "recent count",
        "recents 1",
        "recents 1-2",
        "recents 1 2",
        "last played",
        "reload",
        "refresh",
        "refresh all",
        "refresh lyrics",
        "vis",
        "prev",
        "next",
        ".prev",
        ".next",
        "now*",
        "play 1",
        "play 1 2",
        "fade in 1",
        "fade out 1",
        "fade 10 20 1",
        "m?",
        "ispl",
        "ispl?",
        "isl?",
        "seek 1",
        "seek :30",
        "download-yv https://youtube.test/watch?v=1",
        "download-ya https://youtube.test/watch?v=1",
        "download-ml https://example.test/audio mp3",
        "open .",
        "open lib",
        "open lyrics",
        "view lib",
        "view lyrics",
        "volume 25",
        "mvolume 25",
        "/ys query",
        "/ys query 1",
        "/yl https://youtube.test/watch?v=1",
        "/ml https://example.test/audio",
        "/wra",
        "/wra coffee",
        "like",
        "dislike",
        "vivojay fav",
    ],
)
def test_extended_command_matrix_never_performs_real_io(cli, command):
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


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("fade to 30 in 3", (0.7, 0.3, 3.0)),
        ("fade from 20 in 2", (0.2, 0.7, 2.0)),
        ("fade from 20 to 80", (0.2, 0.8, 5.0)),
        ("fade 10 20 1", (0.1, 0.2, 1.0)),
    ],
)
def test_fade_parser_and_dispatch_are_complete(cli, command, expected):
    main.cached_volume = 0.7
    assert main.parse_fade_arguments(command.split(), main.cached_volume) == expected
    main.process(command)
    assert cli.actions[-1] == (
        "fade",
        {
            "initvol": expected[0],
            "finalvol": expected[1],
            "fade_type": main.isplaying,
            "fade_duration": expected[2],
        },
    )


@pytest.mark.parametrize(
    "command",
    [
        "fade",
        "fade to",
        "fade to loud",
        "fade from 20 from 30 to 50",
        "fade to 101",
        "fade from -1 to 50",
        "fade to 50 in -1",
        "other to 50",
    ],
)
def test_fade_parser_rejects_partial_or_unsafe_values(command):
    with pytest.raises(ValueError):
        main.parse_fade_arguments(command.split(), 0.5)


def test_completion_callback_advances_persistent_queue_without_restarting_prefetched_media(monkeypatch):
    first = SimpleNamespace(queue_id=1, media=MediaRef(MediaSource.LOCAL, "C:/first.mp3"))
    second = SimpleNamespace(queue_id=2, media=MediaRef(MediaSource.LOCAL, "C:/second.mp3", title="Second"))
    queue = SimpleNamespace(
        current=lambda: first,
        next=lambda: second,
        state=lambda: {"autofill": 0, "repeat_mode": "off"},
        items=lambda: [first, second],
    )
    events = []
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda media, event, **_kwargs: events.append((media, event)))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=second.media),
    )
    monkeypatch.setattr(main, "_prefetch_after", lambda item: events.append((item.media, "prefetch")))
    monkeypatch.setattr(main, "_play_queue_item", lambda _item: pytest.fail("prefetched media must not restart"))
    main._on_queue_item_complete(first.media)
    assert [event for _media, event in events] == ["completion", "start", "prefetch"]
    assert main.currentsong == "Second"


def test_process_reconciles_finished_playback_and_tolerates_snapshot_failure(cli, monkeypatch):
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    main.process("count")
    assert main.currentsong is None
    assert main.isplaying is False
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("closing")),
    )
    main.process("count")


def test_empty_library_and_recents_commands_are_safe(cli, monkeypatch):
    monkeypatch.setattr(main, "_sound_files", [])
    monkeypatch.setattr(main, "_sound_files_names_only", [])
    monkeypatch.setattr(main, "RECENTS_QUEUE", [])
    main.process("list")
    main.process("rand")
    main.process("last played")
    assert any("There are no audios" in message.get("display_message", "") for message in cli.messages)
    assert any("No recents" in message.get("display_message", "") for message in cli.messages)


def test_refresh_all_confirmation_reprompts_and_can_cancel(cli, monkeypatch):
    answers = iter(["invalid", "y"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))
    main.process("refresh all")
    assert ("refresh-settings",) in cli.actions
    assert ("reload", {"quick_load": False, "full": True}) in cli.actions

    before = list(cli.actions)
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    main.process("refresh all")
    assert cli.actions == before


def test_navigation_covers_play_print_and_unavailable_states(cli, monkeypatch):
    main.process("next")
    main.process(".prev")
    assert any(action[0] == "local" for action in cli.actions)
    monkeypatch.setattr(main, "songindex", -1)
    main.process("next")
    monkeypatch.setattr(main, "songindex", "N/A")
    main.process("prev")
    assert any("No audio" in message.get("display_message", "") for message in cli.messages)
    assert any("outside" in message.get("display_message", "") for message in cli.messages)


def test_seek_and_progress_failure_states_are_typed(cli, monkeypatch):
    monkeypatch.setattr(main, "currentsong_length", -1)
    main.process("seek 10")
    monkeypatch.setattr(main, "currentsong_length", 0)
    main.process("seek 10")
    monkeypatch.setattr(main, "currentsong", "stream")
    monkeypatch.setattr(main, "currentsong_length", None)
    monkeypatch.setattr(main, "get_currentsong_length", lambda: -1)
    main.process("progress")
    assert any("could not be loaded" in message.get("display_message", "") for message in cli.messages)
    assert any("No audio to seek" in message.get("display_message", "") for message in cli.messages)


def test_download_confirmation_and_rejection_paths(cli, monkeypatch):
    monkeypatch.setattr(main, "current_media_type", 0)
    monkeypatch.setattr(main, "currentsong", ("Video", "https://youtube.test/watch?v=1"))
    answers = iter(["invalid", "yes", "y"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))
    main.process("download-yv")
    main.process("download-ya")
    spawned = [action for action in cli.actions if action[0] == "spawn"]
    assert len(spawned) == 2
    assert all(action[1][0] == main.sys.executable for action in spawned)

    monkeypatch.setattr(main, "current_media_type", None)
    main.process("download-yv")
    main.process("download-ya")
    assert any("local storage" in message.get("display_message", "") for message in cli.messages)


@pytest.mark.parametrize(
    ("media_type", "song"),
    [
        (0, ("Video", "https://youtube.test/watch?v=1")),
        (1, "https://example.test/audio"),
        (2, "coffee"),
        (3, ("Session", "https://example.test/session")),
        (99, "invalid"),
    ],
)
def test_open_current_online_media_and_invalid_type(cli, monkeypatch, media_type, song):
    monkeypatch.setattr(main, "current_media_type", media_type)
    monkeypatch.setattr(main, "currentsong", song)
    monkeypatch.setattr(main, "get_current_progress", lambda: 12)
    monkeypatch.setattr(main.vas, "radio_stream_url", lambda station: f"https://radio.test/{station}")
    main.process("open")
    if media_type == 99:
        assert any("invalid type" in message.get("log_message", "") for message in cli.messages)
    else:
        assert any(action[0] == "browser" for action in cli.actions)


def test_sync_path_and_family_error_boundaries(cli, monkeypatch):
    for media_type in range(4):
        monkeypatch.setattr(main, "current_media_type", media_type)
        main.process("sync")
    assert ("media", {"action": "resync"}) in cli.actions
    main.process("path invalid")
    assert any("positive integer" in message.get("display_message", "") for message in cli.messages)

    def fail(_arguments):
        raise ValueError("invalid request")

    for name in (
        "sleep_command",
        "replaygain_command",
        "broadcast_command",
        "tools_command",
        "library_command",
        "queue_command",
        "radio_command",
        "recommendation_command",
    ):
        monkeypatch.setattr(main, name, fail)
    for command in (
        "sleep 1m",
        "replaygain status",
        "broadcast status",
        "tools status",
        "library status",
        "queue list",
        "radio list",
        "recommend 1",
    ):
        main.process(command)
    assert sum("invalid request" in message.get("display_message", "") for message in cli.messages) == 8


def test_online_resolution_failures_do_not_escape_process(cli, monkeypatch):
    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(main, "play_vas_media", lambda **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(main, "url_is_valid", lambda value=None, url=None, **_kwargs: bool(value or url))
    main.process('/ys "query"')
    main.process('/ys "query" 1')
    main.process("/yl https://youtube.test/watch?v=1")
    main.process("vivojay fav")
    assert sum("Video Load Error" in message.get("display_message", "") for message in cli.messages) == 4


def test_like_without_active_media_and_update_failure_are_reported(cli, monkeypatch):
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE))
    main.process("like")
    assert "No active media" in cli.printed
    monkeypatch.setattr(main, "prepare_update", lambda: (_ for _ in ()).throw(OSError("disk full")))
    main.process("update prepare")
    assert any("disk full" in message.get("display_message", "") for message in cli.messages)


def test_legacy_aliases_route_to_modern_handlers(cli):
    main.process("mute")
    main.process("include downloads")
    main.process("exclude downloads")
    main.process("lyrics edit")
    main.process("/rpan")
    assert any(action[0] == "mute" for action in cli.actions)
    assert ("downloads-root", True) in cli.actions
    assert ("downloads-root", False) in cli.actions
    assert ("lyrics-edit",) in cli.actions
    assert main.REDDIT_RETIRED_MESSAGE in cli.printed


def test_durable_lyrics_edit_creates_sidecar_only_after_confirmation(cli, monkeypatch):
    song = cli.tmp_path / "editable.mp3"
    song.write_bytes(b"audio")
    media = MediaRef(MediaSource.LOCAL, str(song))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media))
    monkeypatch.setattr(main.vas.controller, "fingerprint_pcm", lambda: b"pcm")
    monkeypatch.setattr(main, "_preference_media", lambda value: value)
    monkeypatch.setattr(
        main.IDENTITY,
        "identify",
        lambda *_args, **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        main.IDENTITY,
        "lyrics",
        lambda *_args, **_kwargs: SimpleNamespace(synced="[00:01.00]Line", plain="Line"),
    )
    monkeypatch.setattr(main, "DEFAULT_EDITOR", None)
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    assert REAL_EDIT_CURRENT_LYRICS() is None
    assert not song.with_suffix(".lrc").exists()
    monkeypatch.setattr("builtins.input", lambda *_args: "y")
    assert REAL_EDIT_CURRENT_LYRICS() == song.with_suffix(".lrc")
    assert song.with_suffix(".lrc").read_text(encoding="utf-8") == "[00:01.00]Line\n"
