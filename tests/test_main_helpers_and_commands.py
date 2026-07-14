import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from hypothesis import given
from hypothesis import strategies as st

import main
from mariana import output_devices
from mariana.models import (
    MediaChapter,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    StationSession,
    StationState,
)
from mariana.sources import FailureCode, MediaFailure


def test_ordered_set_flatten_and_search_helpers(monkeypatch):
    assert main.OrderedSet([1, 2, 1, 3, 2]) == [1, 2, 3]
    assert list(main.flatten([1, [2, (3, 4)], "text"])) == [1, 2, 3, 4, "text"]

    monkeypatch.setattr(main, "_sound_files_names_enumerated", [(1, "Blue Moon"), (2, "Blue Sky"), (3, "Red Moon")])
    assert main.searchsongs(["blue", "moon", "blue"]) == [(1, "Blue Moon")]


def test_startup_progress_keeps_text_and_bar_in_sync(capsys):
    main._boot_progress(31, "ready")
    output = capsys.readouterr().out
    assert "Loaded 31/31" in output
    assert "[########################]" in output
    assert "100%" in output and output.endswith("\r")


def test_audio_file_generator_is_recursive_and_extension_exact(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "one.mp3").touch()
    (nested / "two.mp3").touch()
    (nested / "three.MP3").touch()
    assert {Path(path).name for path in main.audio_file_gen(tmp_path, ".mp3")} == {"one.mp3", "two.mp3"}


def test_remove_adjacent_mutates_in_place():
    values = [1, 1, 2, 2, 2, 3, 1, 1]
    assert main.remove_adjacent(values) is None
    assert values == [1, 2, 3, 1]


@given(seconds=st.integers(min_value=0, max_value=86_399))
def test_convert_round_trips_seconds_within_a_day(seconds):
    rendered = main.convert(seconds)
    hours, minutes, remaining = map(int, rendered.split(":"))
    assert hours * 3600 + minutes * 60 + remaining == seconds


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("-1.25", True), ("nan", True), ("text", False)],
)
def test_isdecimal(value, expected):
    assert main.isdecimal(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1:02", 0), ("10", 0), ("1.5", 1), ("bad", 2), ("-1", 3)],
)
def test_validate_time_codes(value, expected):
    assert main.validate_time(value) == expected


def test_time_parser_handles_colon_numeric_zero_and_out_of_range(monkeypatch):
    monkeypatch.setattr(main, "currentsong_length", 120)
    assert main.timeinput_to_timeobj("1:02") == ("1m 2s", 62)
    assert main.timeinput_to_timeobj("30")[1] == "30"
    assert main.timeinput_to_timeobj("-0") == ("0", 0)
    assert main.timeinput_to_timeobj("2:01") is ValueError
    assert main.timeinput_to_timeobj("invalid") is None


@pytest.mark.parametrize(
    ("text", "threshold", "end", "as_tuple", "expected"),
    [
        ("short", 100, 8, False, "short"),
        ("abcdefghijklmnopqrstuvwxyz", 20, 4, False, "abcdefghijklm...wxyz"),
        ("abcdefghijklmnopqrstuvwxyz", 20, 4, True, ("abcdefghijklm", "wxyz")),
        ("text", 13, 4, False, None),
    ],
)
def test_text_overflow_prettify(text, threshold, end, as_tuple, expected):
    assert main.text_overflow_prettify(text, threshold, end, as_tuple) == expected


def test_recents_queue_enforces_capacity_and_encodes_media(monkeypatch):
    monkeypatch.setattr(main, "RECENTS_QUEUE", [[None, -1, "old"]])
    monkeypatch.setattr(main, "MAX_RECENTS_SIZE", 1)
    monkeypatch.setattr(main, "current_media_type", 0)
    monkeypatch.setattr(main, "YOUTUBE_PLAY_TYPE", 1)
    main.recents_queue_save(("Title", "URL"))
    assert main.RECENTS_QUEUE == [[1, 0, ("Title", "URL")]]

    monkeypatch.setattr(main, "MAX_RECENTS_SIZE", 2)
    monkeypatch.setattr(main, "current_media_type", None)
    main.recents_queue_save((1, "track.mp3"))
    assert main.RECENTS_QUEUE[-1] == [None, -1, (1, "track.mp3")]


def test_prettified_recents_support_every_media_type(monkeypatch):
    monkeypatch.setattr(
        main,
        "RECENTS_QUEUE",
        [
            [None, -1, (1, "C:/music/local.mp3")],
            [0, 0, ("Video", "https://youtube")],
            [None, 1, "https://media"],
            [None, 2, "coffee"],
            [None, 3, ("Session", "https://reddit")],
        ],
    )
    results = main.get_prettified_recents(range(5))
    joined = "\n".join(results)
    assert "Session" in joined
    assert "@webradio" in joined
    assert "@media-link" in joined
    assert "Video" in joined
    assert "local" in joined


def test_enqueue_skips_invalid_and_deduplicates(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "_sound_files", ["one.mp3", "two.mp3"])
    monkeypatch.setattr(main, "IPrint", lambda *_a, **_k: None)
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda paths, _songindex, is_queue: captured.update(paths=paths, queue=is_queue),
    )
    main.enqueue(["2", "3", "2"])
    assert captured == {"paths": ["two.mp3"], "queue": True}


def test_local_play_commands_support_index_queue_and_path(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_sound_files", ["one.mp3", "two.mp3"])
    monkeypatch.setattr(main, "purge_old_lyrics_if_exist", lambda: None)
    monkeypatch.setattr(main, "play_local_default_player", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(main, "enqueue", lambda values: calls.append({"queue": values}))

    main.local_play_commands(["play", "2"])
    main.local_play_commands(["play", "1", "2", "bad"])
    main.local_play_commands([], _command=".C:/music/song.mp3")

    assert calls[0]["songpath"] == "two.mp3"
    assert calls[1] == {"queue": ["1", "2"]}
    assert calls[2]["songpath"] == "C:/music/song.mp3"


def test_choose_media_url_handles_single_multiple_skip_and_invalid(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "play_vas_media", lambda **kwargs: calls.append(kwargs))
    main.choose_media_url([("Title", "url")])
    assert calls[-1]["single_video"] is True

    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")
    main.choose_media_url([(1, "One", "u1"), (2, "Two", "u2")])
    assert calls[-1]["media_url"] == "u2"

    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    main.choose_media_url([(1, "One", "u1"), (2, "Two", "u2")])
    count = len(calls)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "invalid")
    main.choose_media_url([(1, "One", "u1"), (2, "Two", "u2")])
    assert len(calls) == count


def test_display_and_choose_podcast_plays_selected_url(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "IPrint", lambda *_a, **_k: None)
    monkeypatch.setattr(main, "play_vas_media", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    episodes = [{"title": "Episode", "caption": "Caption", "pub_date": "Today", "is_explicit": False, "url": "stream"}]
    main.display_and_choose_podbean(episodes, ["pods"], 1)
    assert calls[0]["media_url"] == "stream"


def test_safe_command_families_dispatch(monkeypatch):
    printed = []
    stopped = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(value))
    monkeypatch.setattr(main, "_sound_files_names_only", ["Blue Moon", "Red Sky"])
    monkeypatch.setattr(main, "_sound_files_names_enumerated", [(1, "Blue Moon"), (2, "Red Sky")])
    monkeypatch.setattr(main, "_sound_files", ["blue.mp3", "red.mp3"])
    monkeypatch.setattr(main, "stopsong", lambda: stopped.append(True))
    monkeypatch.setattr(main, "rand_song_index_generate", lambda: 0)

    main.process("count")
    main.process("find blue")
    main.process("/rs")
    main.process("stop")
    main.process("rand")

    rendered = "\n".join(map(str, printed))
    assert "2" in rendered
    assert "Blue Moon" in rendered
    assert "retired" in rendered.lower()
    assert stopped == [True]


def test_volume_and_pause_command_dispatch(monkeypatch):
    player = SimpleNamespace(audio_set_volume=lambda value: setattr(player, "volume", value))
    monkeypatch.setattr(main.vas, "player", player)
    toggles = []
    monkeypatch.setattr(main, "playpausetoggle", lambda **kwargs: toggles.append(kwargs))
    monkeypatch.setattr(main, "cached_volume", 0.5)
    main.process("volume 25")
    main.process("p")
    main.process("ph")
    assert player.volume == 25
    assert main.cached_volume == 0.25
    assert toggles == [{}, {"softtoggle": False}]


class PlaybackPlayer:
    def __init__(self, length=60_000):
        self.length = length
        self.volume = None
        self.time = None

    def audio_set_volume(self, value):
        self.volume = value

    def get_length(self):
        return self.length

    def get_time(self):
        return 5_000

    def set_time(self, value):
        self.time = value


def playback_user_data():
    return {
        "default_user_data": {
            "stats": {
                "play_count": {
                    "local": 0,
                    "radio": 0,
                    "general": 0,
                    "youtube": 0,
                    "redditsession": 0,
                    "total": 0,
                },
                "times_spent": [],
                "log_ins": 0,
            }
        }
    }


@pytest.mark.parametrize(
    ("media_type", "media_url", "media_name", "expected_type", "counter", "expected_length"),
    [
        ("video", "youtube", "Video", 0, "youtube", 60),
        ("general", "stream", None, 1, "general", 60),
        ("radio", None, "coffee", 2, "radio", -1),
        ("redditsession", "reddit", "Session", 3, "redditsession", 60),
    ],
)
def test_play_vas_media_state_machine(
    monkeypatch, media_type, media_url, media_name, expected_type, counter, expected_length
):
    player = PlaybackPlayer()
    set_calls = []
    play_calls = []
    recents = []
    monkeypatch.setattr(main, "stopsong", lambda: None)
    monkeypatch.setattr(main.vas, "set_media", lambda **kwargs: set_calls.append(kwargs) or "direct-audio")
    monkeypatch.setattr(main.vas, "media_player", lambda **kwargs: play_calls.append(kwargs))
    monkeypatch.setattr(main.vas, "player", player)
    monkeypatch.setattr(main.vas, "wait_until_playing", lambda _timeout: True)
    monkeypatch.setattr(main, "recents_queue_save", lambda value: recents.append(value))
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
    monkeypatch.setattr(main, "IPrint", lambda *_a, **_k: None)
    monkeypatch.setattr(main, "USER_DATA", playback_user_data())

    main.play_vas_media(media_url, media_name=media_name, media_type=media_type)

    assert main.current_media_type == expected_type
    assert main.USER_DATA["default_user_data"]["stats"]["play_count"][counter] == 1
    assert play_calls == [{"action": "play"}]
    assert player.volume == int(main.cached_volume * 100)
    assert main.currentsong_length == expected_length
    assert recents
    assert set_calls


def test_play_vas_media_handles_unresolved_title_and_invalid_type(monkeypatch):
    player = PlaybackPlayer()
    logs = []
    monkeypatch.setattr(main, "stopsong", lambda: None)
    monkeypatch.setattr(main.vas, "set_media", lambda **_kwargs: "direct")
    monkeypatch.setattr(main.vas, "media_player", lambda **_kwargs: None)
    monkeypatch.setattr(main.vas, "player", player)
    monkeypatch.setattr(main.vas, "wait_until_playing", lambda _timeout: True)
    monkeypatch.setattr(main.YT_query, "vid_info", lambda _url: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(main, "recents_queue_save", lambda _value: None)
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "SAY", lambda **kwargs: logs.append(kwargs))
    monkeypatch.setattr(main, "IPrint", lambda *_a, **_k: None)
    monkeypatch.setattr(main, "USER_DATA", playback_user_data())

    main.play_vas_media("youtube", media_type="video")
    assert main.currentsong[0] == "[VIDEO NAME COULD NOT BE RESOLVED]"
    assert "youtube" in logs[0]["log_message"]

    before = playback_user_data()
    monkeypatch.setattr(main, "USER_DATA", before)
    assert main.play_vas_media("url", media_type="unsupported") is False
    assert before["default_user_data"]["stats"]["play_count"]["total"] == 0


def test_progress_length_seek_and_volume_transition(monkeypatch):
    player = PlaybackPlayer(length=90_000)
    volumes = []
    player.audio_set_volume = lambda value: volumes.append(value)
    monkeypatch.setattr(main.vas, "player", player)
    monkeypatch.setattr(main, "currentsong", "track.mp3")
    monkeypatch.setattr(main, "currentsong_length", None)
    assert main.get_currentsong_length() == 90
    assert main.get_current_progress() == 5
    assert main.song_seek(12) is True
    assert player.time == 12_000

    monkeypatch.setattr(main, "ismuted", False)
    monkeypatch.setattr(main.time, "sleep", lambda _seconds: None)
    main.voltransition(initial=0, final=1, transition_time=0)
    assert volumes[0] == 0
    assert volumes[-1] == 100


def test_volume_transition_helper_does_not_spawn_a_frozen_app(monkeypatch):
    captured = []
    monkeypatch.setattr(main, "cached_volume", 0.75)
    monkeypatch.setattr(main, "voltransition", lambda **kwargs: captured.append(kwargs))
    main.vol_trans_process_spawn()
    assert captured == [{"initial": 0.75, "final": 0, "disablecaching": True}]


def test_play_pause_stop_and_fade_transitions(monkeypatch):
    actions = []
    transitions = []
    player = PlaybackPlayer()
    monkeypatch.setattr(main.vas, "media_player", lambda **kwargs: actions.append(kwargs["action"]))
    monkeypatch.setattr(main.vas, "player", player)
    monkeypatch.setattr(main, "voltransition", lambda **kwargs: transitions.append(kwargs))
    monkeypatch.setattr(main, "purge_old_lyrics_if_exist", lambda: actions.append("purge"))
    monkeypatch.setattr(main, "IPrint", lambda *_a, **_k: None)
    monkeypatch.setattr(main, "currentsong", "track.mp3")
    monkeypatch.setattr(main, "isplaying", True)
    monkeypatch.setattr(main, "ismuted", False)

    main.playpausetoggle(transition_time=0)
    assert main.isplaying is False
    main.playpausetoggle(transition_time=0)
    assert main.isplaying is True
    main.fade_in_out(finalvol=0, fade_duration=0)
    assert main.isplaying is False
    main.stopsong()
    assert main.currentsong is None
    assert actions[-2:] == ["stop", "purge"]
    assert transitions


def test_random_commands_handle_first_item(monkeypatch):
    printed = []
    played = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(value))
    monkeypatch.setattr(main, "rand_song_index_generate", lambda: 0)
    monkeypatch.setattr(main, "_sound_files_names_only", ["First"])
    monkeypatch.setattr(main, "_sound_files", ["first.mp3"])
    monkeypatch.setattr(main, "local_play_commands", lambda commandslist: played.append(commandslist))

    for command in ("rand", "rand*", "=rand", "/rand", ".rand"):
        main.process(command)

    assert "First" in printed
    assert "first.mp3" in printed
    assert 1 in printed
    assert "1: First" in printed
    assert played == [[None, "1"]]


def test_online_command_families_dispatch_without_network(monkeypatch):
    chosen = []
    played = []
    messages = []
    monkeypatch.setattr(main, "url_is_valid", lambda _url, **_kwargs: True)
    monkeypatch.setattr(
        main.YT_query,
        "search_youtube",
        lambda search, rescount=1: ("One", "u1") if rescount == 1 else [(1, "One", "u1"), (2, "Two", "u2")],
    )
    monkeypatch.setattr(main, "choose_media_url", lambda media_url_choices: chosen.append(media_url_choices))
    monkeypatch.setattr(main, "play_vas_media", lambda **kwargs: played.append(kwargs))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    monkeypatch.setattr(main, "IPrint", lambda *_a, **_k: None)

    main.process('/ys "query" 2')
    main.process("/yl https://youtu.be/abc12345678")
    main.process("/ml https://example.test/audio")
    main.process("/wra 2")
    main.process("/wra missing")

    assert len(chosen[0]) == 2
    assert played[0]["single_video"] is True
    assert played[1]["media_type"] == "general"
    assert played[2] == {"media_url": None, "media_type": "radio", "media_name": "chillout"}
    assert any("Unknown webradio" in item["log_message"] for item in messages)


def test_custom_media_failure_is_reported_without_escaping_or_leaking_url(monkeypatch):
    messages = []
    stopped = []
    monkeypatch.setattr(main, "url_is_valid", lambda _url, **_kwargs: True)
    monkeypatch.setattr(
        main,
        "play_vas_media",
        lambda **_kwargs: (_ for _ in ()).throw(
            MediaFailure(
                FailureCode.UNAVAILABLE,
                MediaSource.URL,
                "The media page could not be resolved to a playable audio stream",
            )
        ),
    )
    monkeypatch.setattr(main, "stopsong", lambda: stopped.append(True))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))

    main.process("/ml https://soundcloud.com/artist/private?token=secret")

    assert stopped == [True]
    assert messages[-1]["display_message"] == "The media page could not be resolved to a playable audio stream"
    assert "soundcloud.com" not in messages[-1]["log_message"]
    assert "secret" not in messages[-1]["log_message"]


def test_seek_progress_and_status_command_families(monkeypatch):
    printed = []
    seeks = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(value))
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
    monkeypatch.setattr(main, "currentsong", "track.mp3")
    monkeypatch.setattr(main, "currentsong_length", 100)
    monkeypatch.setattr(main, "isplaying", True)
    monkeypatch.setattr(main, "ismuted", False)
    monkeypatch.setattr(main, "get_current_progress", lambda: 20)
    monkeypatch.setattr(main, "song_seek", lambda timeval=None, **_kwargs: seeks.append(timeval) or True)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING),
    )

    main.process("seek +10")
    main.process("progress*")
    main.process("ism?")
    main.process("isplaying?")

    assert seeks == ["30"]
    rendered = "\n".join(map(str, printed))
    assert "Seeking to" in rendered
    assert "progress" in rendered


def test_create_files_save_user_data_and_run_lifecycle(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    main.create_required_files_if_not_exist("nested/one.txt")
    assert (tmp_path / "nested" / "one.txt").is_file()

    user = playback_user_data()
    user["default_user_data"]["stats"]["play_count"].update(local=2, radio=1, general=3, youtube=4, redditsession=5)
    monkeypatch.setattr(main, "USER_DATA", user)
    (tmp_path / "user").mkdir()
    main.save_user_data()
    assert user["default_user_data"]["stats"]["play_count"]["total"] == 15

    events = []
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(main, "visible", False)
    monkeypatch.setattr(main, "initialize_audio_output", lambda: events.append("audio"))
    monkeypatch.setattr(main, "save_user_data", lambda: events.append("save"))
    monkeypatch.setattr(main, "mainprompt", lambda: events.append("prompt"))
    monkeypatch.setattr(
        main,
        "DESKTOP_CONTROL",
        SimpleNamespace(
            start_playback_monitor=lambda _callback: None,
            start_safety_monitor=lambda _callback: None,
            emit=lambda *_args: None,
        ),
    )
    monkeypatch.setattr(main, "LIBRARY_SERVICE", SimpleNamespace(start=lambda **_kwargs: None))
    main.run()
    assert events == ["audio", "save", "prompt"]
    assert user["default_user_data"]["stats"]["log_ins"] == 1


def test_clear_terminal_erases_screen_scrollback_and_homes_cursor(monkeypatch, capsys):
    main.clear_terminal()
    assert capsys.readouterr().out == "\033[2J\033[3J\033[H"

    calls = []
    monkeypatch.setattr(main, "clear_terminal", lambda: calls.append("clear"))
    monkeypatch.setattr(main, "showbanner", lambda: calls.append("banner"))
    monkeypatch.setattr(main, "visible", True)
    main.process("cls")
    assert calls == ["clear", "banner"]


def test_startup_enforces_platform_and_fatal_state(monkeypatch):
    monkeypatch.setattr(main, "first_startup_greet", lambda _first: None)
    monkeypatch.setattr(main, "ensure_managed_tool_migration", lambda: None)
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(main, "_sound_files", [])
    monkeypatch.setattr(main, "SOFT_FATAL_ERROR_INFO", None)
    monkeypatch.setattr(main, "enforce_os_requirement", True)
    monkeypatch.setattr(main.sys, "platform", "plan9")
    with pytest.raises(SystemExit, match="does not support plan9"):
        main.startup()

    monkeypatch.setattr(main, "enforce_os_requirement", False)
    monkeypatch.setattr(main, "FATAL_ERROR_INFO", "broken")
    monkeypatch.setattr(main, "IPrint", lambda *_a, **_k: None)
    with pytest.raises(SystemExit) as error:
        main.startup()
    assert error.value.code == 1


def test_reload_sounds_uses_index_cache_and_full_scan(monkeypatch, tmp_path):
    cache = tmp_path / "data" / "snd_files.json"
    cache.parent.mkdir()
    library_file = tmp_path / "lib.lib"
    library_file.write_text(str(tmp_path), encoding="utf-8")
    indexed = [str(tmp_path / "indexed.mp3")]
    catalog = SimpleNamespace(
        paths=lambda: indexed,
        scan=lambda mode: setattr(catalog, "scan_mode", mode),
        roots=lambda: [{"path": str(tmp_path), "available": True}],
        media_refs=lambda: [main.MediaRef(main.MediaSource.LOCAL, path) for path in indexed],
    )
    synced = []
    monkeypatch.setattr(main, "LIBRARY", catalog)
    monkeypatch.setattr(main, "SOUND_CACHE_PATH", cache)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(library_file=library_file))
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(
        main.QUEUE,
        "sync_library_defaults",
        lambda items: synced.append([item.original_uri for item in items]),
    )
    main.reload_sounds()
    assert main._sound_files == indexed
    assert main._sound_files_names_only == ["indexed"]
    assert synced[-1] == indexed

    indexed[:] = [str(tmp_path / "rescanned.mp3")]
    main.reload_sounds(quick_load=False, full=True)
    assert catalog.scan_mode == "full"
    assert json.loads(cache.read_text(encoding="utf-8")) == indexed


def test_reload_sounds_cache_fallback_and_missing_library(monkeypatch, tmp_path):
    cache = tmp_path / "snd_files.json"
    cache.write_text(json.dumps([str(tmp_path / "cached.mp3")]), encoding="utf-8")
    missing_library = tmp_path / "missing.lib"
    messages = []
    catalog = SimpleNamespace(
        paths=list,
        scan=lambda _mode: None,
        roots=list,
        media_refs=lambda: [
            main.MediaRef(main.MediaSource.LOCAL, str(tmp_path / "cached.mp3"))
        ],
    )
    monkeypatch.setattr(main, "LIBRARY", catalog)
    monkeypatch.setattr(main, "SOUND_CACHE_PATH", cache)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(library_file=missing_library))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(main.QUEUE, "sync_library_defaults", lambda _items: None)
    main.reload_sounds()
    assert main._sound_files_names_only == ["cached"]
    cache.unlink()
    main.reload_sounds()
    assert any("vanished" in message["display_message"] for message in messages)


def test_mainprompt_clears_busy_state_after_interrupt_and_exit(monkeypatch):
    entered = iter([KeyboardInterrupt(), "quit"])
    printed = []

    def prompt(_value):
        value = next(entered)
        if isinstance(value, BaseException):
            raise value
        return value

    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main, "process", lambda command: False if command == "quit" else None)
    monkeypatch.setattr(main, "exitplayer", lambda: printed.append("exit"))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(value))
    main.mainprompt()
    assert printed == ["\n", "exit"]
    assert not main.COMMAND_BUSY.is_set()


def test_banner_version_and_audio_initialization(monkeypatch, tmp_path, capsys):
    def query_devices_with_outputs(max_output_channels):
        device = {
            "name": "Test speakers",
            "max_output_channels": max_output_channels,
            "hostapi": 0,
        }

        def query_devices(_device=None, kind=None):
            return device if kind == "output" else [device]

        return query_devices

    monkeypatch.setattr(output_devices, "_windows_default_endpoint", lambda: None)
    banner = tmp_path / "banner.banner"
    banner.write_text("one\nlonger", encoding="utf-8")
    rendered = []
    showversion = main.showversion
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(resource=lambda *_parts: banner))
    monkeypatch.setattr(main, "blue_gradient_print", lambda line, colors: rendered.append((line, colors)))
    monkeypatch.setattr(main, "showversion", lambda: rendered.append(("version", None)))
    monkeypatch.setattr(main, "visible", True)
    main.showbanner()
    assert len(rendered) == 3
    assert len(rendered[0][0]) == 10

    monkeypatch.setattr(main.sounddevice, "query_devices", query_devices_with_outputs(2))
    main.initialize_audio_output()
    monkeypatch.setenv("MARIANA_E2E", "1")
    monkeypatch.setattr(
        main.sounddevice,
        "query_devices",
        lambda: pytest.fail("headless E2E must not query physical audio devices"),
    )
    main.initialize_audio_output()
    monkeypatch.delenv("MARIANA_E2E")
    monkeypatch.setattr(main.sounddevice, "query_devices", query_devices_with_outputs(0))
    with pytest.raises(RuntimeError, match="audio output device"):
        main.initialize_audio_output()

    monkeypatch.setattr(main, "showversion", showversion)
    monkeypatch.setattr(main, "SYSTEM_SETTINGS", {"about": {}})
    main.showversion()
    assert capsys.readouterr().out


def test_run_reports_every_update_safety_reason_and_first_boot(monkeypatch, tmp_path):
    safety = {}
    events = []
    startup_sound = tmp_path / "startup.mp3"
    startup_sound.write_bytes(b"audio")
    desktop = SimpleNamespace(
        start_playback_monitor=lambda callback: events.append(("playback-monitor", callback)),
        start_safety_monitor=lambda callback: safety.update(callback=callback),
        emit=lambda *args: events.append(args),
    )
    monkeypatch.setattr(main, "DESKTOP_CONTROL", desktop)
    monkeypatch.setattr(main, "initialize_audio_output", lambda: events.append("audio"))
    monkeypatch.setattr(main, "LIBRARY_SERVICE", SimpleNamespace(
        start=lambda **kwargs: events.append(("library", kwargs)),
        status=lambda: {"jobs": [{"status": "leased"}]},
    ))
    monkeypatch.setattr(main, "SLEEP_TIMER", SimpleNamespace(status=lambda: SimpleNamespace(active=True)))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING),
    )
    monkeypatch.setattr(
        main,
        "BROADCASTER",
        SimpleNamespace(snapshot=lambda: SimpleNamespace(state=main.BroadcastState.LIVE)),
    )
    monkeypatch.setattr(main.vas, "set_media", lambda **kwargs: events.append(("set-media", kwargs)))
    monkeypatch.setattr(main.vas, "media_player", lambda **kwargs: events.append(("play", kwargs)))
    monkeypatch.setattr(main, "notify", lambda **kwargs: events.append(("notify", kwargs)))
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(resource=lambda *_parts: startup_sound))
    monkeypatch.setattr(main, "save_user_data", lambda: events.append("save"))
    monkeypatch.setattr(main, "showbanner", lambda: events.append("banner"))
    monkeypatch.setattr(main, "mainprompt", lambda: events.append("prompt"))
    monkeypatch.setattr(main, "FIRST_BOOT", True)
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main, "USER_DATA", playback_user_data())
    main.COMMAND_BUSY.set()
    try:
        main.run()
        safe, reasons = safety["callback"]()
    finally:
        main.COMMAND_BUSY.clear()
    assert safe is False
    assert reasons == [
        "command-active",
        "sleep-timer",
        "playback-active",
        "broadcast-active",
        "profiler-transaction",
    ]
    assert any(event[0] == "set-media" for event in events if isinstance(event, tuple))
    assert "banner" in events and "prompt" in events


def test_startup_skips_run_for_soft_failure_and_runs_when_healthy(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "first_startup_greet", lambda _first: calls.append("greet"))
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(main, "enforce_os_requirement", False)
    monkeypatch.setattr(main, "FATAL_ERROR_INFO", None)
    monkeypatch.setattr(main, "run", lambda: calls.append("run"))
    monkeypatch.setattr(main, "ensure_managed_tool_migration", lambda: calls.append("tools"))
    monkeypatch.setattr(main, "SOFT_FATAL_ERROR_INFO", "cancelled")
    main.startup()
    assert calls == ["greet"]
    monkeypatch.setattr(main, "SOFT_FATAL_ERROR_INFO", None)
    main.startup()
    assert calls == ["greet", "greet", "tools", "run"]


def test_compact_help_autoplay_and_theme_commands_persist(monkeypatch):
    printed = []
    saved = []
    emitted = []
    settings = {"playback": {"autoplay": True}, "appearance": {"terminal theme": "aurora"}}
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "save_user_settings", lambda value, path: saved.append((value, path)))
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=Path("settings.yml")))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=lambda *args: emitted.append(args)))

    assert main.process("help") is None
    cleared = []
    monkeypatch.setattr(main.vas.controller, "clear_prefetch", lambda: cleared.append(True))
    assert main.process("autonext off") is None
    assert settings["playback"]["autoplay"] is False
    assert cleared == [True]
    assert main.process("theme gruvbox") is None
    assert settings["appearance"]["terminal theme"] == "gruvbox"
    assert emitted == [("theme", {"name": "gruvbox"})]
    assert len(saved) == 2
    assert any("Playback" in value for value in printed)


def test_station_command_parses_options_prints_upcoming_and_controls(monkeypatch):
    seed = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=seed",
        title="Seed",
        artist="Artist",
        resolver_data={"is_music": True},
    )
    recommended = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/next", title="Next", artist="Other")
    session = StationSession(
        "session",
        seed,
        scope="online",
        limit=None,
        state=StationState.READY,
        generated_count=11,
        ready_ahead=10,
    )
    calls = []

    class Station:
        def start(self, media, **options):
            calls.append(("start", media, options))
            return session

        def session(self):
            return session

        def wait_initial(self, _timeout):
            return session

        def items(self, count):
            return [{"media": recommended, "reasons": ["similar artist"]}][:count]

        def more(self, count):
            calls.append(("more", count))

        def pause(self):
            calls.append(("pause",))

        def resume(self):
            calls.append(("resume",))

        def cancel_generation(self):
            calls.append(("cancel",))

        def stop(self):
            calls.append(("stop",))

    monkeypatch.setattr(main, "STATION", Station())
    monkeypatch.setattr(main, "visible", False)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: calls.append(("print", str(value))))
    monkeypatch.setattr(main, "_station_seed", lambda _value: seed)
    monkeypatch.setattr(main, "_play_queue_item", lambda item: calls.append(("play", item)))
    monkeypatch.setattr(main.QUEUE, "current", lambda: SimpleNamespace(media=seed))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE))

    assert main.station_command(["start", "current", "--scope", "online", "--unlimited"]) is session
    assert calls[0] == ("start", seed, {"scope": "online", "limit": None})
    assert any("Next" in call[1] for call in calls if call[0] == "print")
    assert main.station_command(["status"]) is session
    assert main.station_command(["list", "1"])
    assert main.station_command(["more", "2"]) is session
    main.station_command(["pause"])
    main.station_command(["resume"])
    main.station_command(["stop"])
    assert {call[0] for call in calls} >= {"more", "pause", "resume", "stop"}
    assert len([call for call in calls if call[0] == "play"]) == 2
    with pytest.raises(main.StationError, match="Unknown station option"):
        main.station_command(["start", "--bad"])


def test_station_command_ctrl_c_restores_start_and_retains_refill(monkeypatch):
    session = StationSession(
        "session",
        MediaRef(
            MediaSource.YOUTUBE,
            "https://www.youtube.com/watch?v=seed",
            title="Seed",
            artist="Artist",
            resolver_data={"is_music": True},
        ),
        state=StationState.LOADING,
    )
    calls = []

    class Station:
        def start(self, *_args, **_kwargs):
            calls.append("start")
            return session

        def stop(self):
            calls.append("stop")

        def more(self, _count):
            calls.append("more")

        def cancel_generation(self):
            calls.append("cancel")

        def session(self):
            return session

    monkeypatch.setattr(main, "STATION", Station())
    monkeypatch.setattr(main, "visible", False)
    monkeypatch.setattr(main, "_station_seed", lambda _value: session.seed)
    monkeypatch.setattr(main.QUEUE, "current", lambda: SimpleNamespace(media=session.seed))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=session.seed))
    monkeypatch.setattr(main, "_wait_for_station_initial", lambda: (_ for _ in ()).throw(KeyboardInterrupt))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)

    assert main.station_command(["start", "current"]) is None
    assert calls == ["start", "stop"]
    calls.clear()
    assert main.station_command(["more", "3"]) is session
    assert calls == ["more", "cancel"]


def test_autonext_requires_the_completed_item_to_belong_to_the_active_queue(monkeypatch, tmp_path):
    first = str(tmp_path / "first.mp3")
    second = str(tmp_path / "second.mp3")
    played = []
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    monkeypatch.setattr(main, "_sound_files", [first, second])
    monkeypatch.setattr(main.QUEUE, "current", lambda: None)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda path, _songindex: played.append((path, _songindex)),
    )
    main._on_queue_item_complete(main.MediaRef(main.MediaSource.LOCAL, first))
    assert played == []
    main._on_queue_item_complete(main.MediaRef(main.MediaSource.URL, "https://example.test/live"))
    assert played == []


def test_disabled_autonext_neither_prefetches_nor_advances_queue(monkeypatch):
    media = main.MediaRef(main.MediaSource.LOCAL, "C:/music/track.mp3")
    item = SimpleNamespace(media=media, queue_id=1)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", False)
    monkeypatch.setattr(main.QUEUE, "items", lambda: [item])
    monkeypatch.setattr(main.QUEUE, "current", lambda: item)
    monkeypatch.setattr(
        main.QUEUE,
        "next",
        lambda: (_ for _ in ()).throw(AssertionError("auto-next must be disabled")),
    )
    monkeypatch.setattr(
        main.vas.controller,
        "prefetch",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not prefetch")),
    )
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    retrained = []
    monkeypatch.setattr(main.RECOMMENDER, "retrain_if_due", lambda: retrained.append(True))

    main._prefetch_after(item)
    main._on_queue_item_complete(media)

    assert retrained == [True]


def test_autonext_queue_cursor_drives_navigation_when_legacy_index_is_stale(monkeypatch, tmp_path):
    paths = [str(tmp_path / name) for name in ("Alpha.mp3", "Leadley.mp3", "Actual Next.mp3")]
    media = [
        main.MediaRef(main.MediaSource.LOCAL, path, stable_id=f"track-{index}", title=Path(path).stem)
        for index, path in enumerate(paths)
    ]
    items = [SimpleNamespace(queue_id=index + 1, media=value) for index, value in enumerate(media)]
    printed = []
    played = []
    jumps = []

    monkeypatch.setattr(main, "_sound_files", paths)
    monkeypatch.setattr(main, "_sound_files_names_only", [Path(path).stem for path in paths])
    monkeypatch.setattr(main, "songindex", 1)  # Reproduces the stale pre-auto-next index.
    monkeypatch.setattr(main, "current_media_type", None)
    monkeypatch.setattr(main, "isplaying", True)
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main.QUEUE, "items", lambda: items)
    monkeypatch.setattr(main.QUEUE, "current", lambda: items[1])
    monkeypatch.setattr(main.QUEUE, "state", lambda: {"repeat_mode": "off"})
    monkeypatch.setattr(main.QUEUE, "jump", lambda position: jumps.append(position) or items[position])
    monkeypatch.setattr(main, "_play_queue_item", lambda item: played.append(item))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media[1]),
    )

    main.process("+")
    assert any("Actual Next" in line and "3" in line for line in printed)
    assert not any("Leadley" in line for line in printed)

    main.process(".+")
    assert jumps == [2]
    assert played == [items[2]]


def test_rich_prompt_reports_media_progress(monkeypatch):
    media = main.MediaRef(main.MediaSource.LOCAL, "C:/music/track.mp3", title="Track")
    monkeypatch.setattr(main, "songindex", 3)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=media,
            position=30,
            duration=120,
            current_chapter=MediaChapter("A very long 章 chapter title that must be trimmed safely", 20, 40),
        ),
    )
    prompt = main.prompt_text()
    assert "┏━" in prompt and "┗━" in prompt
    assert "[3] Track" in prompt
    assert "00:30" in prompt and "02:00" in prompt and "25%" in prompt
    assert "A very long 章 chapter title" in prompt and "…" in prompt


def test_exit_closes_independent_services_without_serial_waits(monkeypatch):
    closed = []
    messages = []
    empty = PlaybackSnapshot(PlaybackState.IDLE)
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main, "APP_BOOT_END_TIME", main.time.time())
    monkeypatch.setattr(main, "USER_DATA", playback_user_data())
    monkeypatch.setattr(main, "save_user_data", lambda: closed.append("save"))
    monkeypatch.setattr(main, "purge_old_lyrics_if_exist", lambda: closed.append("lyrics"))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: messages.append(str(value)))
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: empty)
    monkeypatch.setattr(main.vas.supervisor, "close", lambda: closed.append("playback"))
    monkeypatch.setattr(main, "SLEEP_TIMER", SimpleNamespace(close=lambda: closed.append("sleep")))
    monkeypatch.setattr(main, "STATION", SimpleNamespace(close=lambda: closed.append("station")))
    monkeypatch.setattr(main, "BROADCASTER", SimpleNamespace(close=lambda: closed.append("broadcast")))
    monkeypatch.setattr(
        main,
        "DESKTOP_CONTROL",
        SimpleNamespace(emit=lambda *_args: closed.append("ack"), close=lambda: closed.append("desktop")),
    )
    monkeypatch.setattr(main, "LIBRARY_SERVICE", SimpleNamespace(close=lambda: closed.append("library")))

    main.exitplayer()
    assert {"sleep", "station", "broadcast", "desktop", "playback", "library", "save", "lyrics"} <= set(closed)
    assert "ack" in closed
    assert any("Exiting" in value for value in messages)


def test_help_autoplay_and_theme_validation_and_rollback(monkeypatch):
    printed = []
    settings = {"playback": {"autoplay": True}, "appearance": {"terminal theme": "aurora"}}
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=Path("settings.yml")))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=lambda *_args: None))

    assert main.help_command(["play"])[0][0] == "Playback"
    assert main.autoplay_command([]) is True
    assert main.theme_command(["list"]) == "aurora"
    assert main.theme_command(["status"]) == "aurora"
    with pytest.raises(ValueError, match="Unknown help topic"):
        main.help_command(["missing"])
    with pytest.raises(ValueError, match="Usage: autoplay"):
        main.autoplay_command(["maybe"])
    with pytest.raises(ValueError, match="Usage: theme"):
        main.theme_command(["missing"])

    monkeypatch.setattr(
        main,
        "save_user_settings",
        lambda *_args: (_ for _ in ()).throw(OSError("read-only")),
    )
    with pytest.raises(OSError, match="read-only"):
        main.autoplay_command(["off"])
    assert main.AUTOPLAY_ENABLED is True and settings["playback"]["autoplay"] is True
    with pytest.raises(OSError, match="read-only"):
        main.theme_command(["gruvbox"])
    assert settings["appearance"]["terminal theme"] == "aurora"


def test_media_commands_cover_saved_and_live_identity_paths(monkeypatch, tmp_path):
    source = tmp_path / "Artist - Track.mp3"
    source.write_bytes(b"audio")
    info = {
        "library_id": "a" * 32,
        "canonical_path": str(source),
        "state": "available",
        "metadata": {"title": "Track", "artist": "Artist", "duration": 120},
        "fingerprint_duration": 119.0,
        "fingerprint": "chromaprint-value",
    }
    printed = []
    identified = SimpleNamespace(
        status=main.IdentityStatus.IDENTIFIED,
        to_dict=lambda: {"status": "identified", "title": "Track", "artist": "Artist"},
    )
    ambiguous = SimpleNamespace(
        status=main.IdentityStatus.AMBIGUOUS,
        to_dict=lambda: {"status": "ambiguous", "title": None},
    )
    identity_calls = []
    controller = SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING),
        fingerprint_pcm=lambda: b"pcm",
    )
    monkeypatch.setattr(main.vas, "controller", controller)
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(info=lambda target: info if target == "1" else None))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(
        main,
        "IDENTITY",
        SimpleNamespace(
            identify_fingerprint=lambda *args: identity_calls.append(("saved", args)) or identified,
            identify=lambda *args, **kwargs: identity_calls.append(("pcm", args, kwargs)) or ambiguous,
        ),
    )

    assert main.media_command(["info", "1"]) is info
    assert "chromaprint-value" not in printed[-1]
    assert main.media_command(["fingerprint", "1"]) == "chromaprint-value"
    assert "17 characters" in printed[-1]
    assert main.media_command(["fingerprint", "1", "--full"]) == "chromaprint-value"
    assert "chromaprint-value" in printed[-1]
    assert main.media_command(["identify", "1"]) is identified
    assert identity_calls[-1][0] == "saved"

    info["fingerprint"] = None
    assert main.media_command(["fingerprint", "1"]) is None
    assert "No saved Chromaprint" in printed[-1]
    assert main.media_command(["identify", "1"]) is ambiguous
    assert identity_calls[-1][0] == "pcm"
    assert "No confident identity" in printed[-1]
    with pytest.raises(ValueError, match="Usage: media"):
        main.media_command(["unknown", "1"])
    with pytest.raises(ValueError, match="was not found"):
        main.media_command(["info", "missing"])
    with pytest.raises(ValueError, match="No media"):
        main.media_command(["info"])


def test_short_rename_preview_cancel_and_apply(monkeypatch, tmp_path):
    source = tmp_path / "old.mp3"
    source.write_bytes(b"audio")
    media = main.MediaRef(main.MediaSource.LOCAL, str(source), stable_id="stable")
    info = {
        "library_id": "stable",
        "canonical_path": str(source),
        "state": "available",
        "metadata": {"artist": "Artist", "title": "Track", "date": "2025"},
    }
    renamed = source.with_name("Artist - Track 2025.mp3")
    printed = []
    events = []
    monkeypatch.setattr(main, "_media_info", lambda _args: (media, info))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(rename=lambda *_args: renamed))
    monkeypatch.setattr(main, "reload_sounds", lambda **kwargs: events.append(("reload", kwargs)))
    monkeypatch.setattr(main, "stopsong", lambda: events.append("stop"))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    )
    monkeypatch.setattr(main, "currentsong", str(source))

    assert main.rename_command(["short", "--dry-run"]) == renamed
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert main.rename_command(["short"]) is None
    assert "Rename cancelled" in printed[-1]
    assert main.rename_command(["short", "--yes"]) == renamed
    assert "stop" in events and main.currentsong == str(renamed)
    assert any(isinstance(event, tuple) and event[0] == "reload" for event in events)
    with pytest.raises(ValueError, match="Usage: rename"):
        main.rename_command([])
    info["state"] = "missing"
    with pytest.raises(ValueError, match="available"):
        main.rename_command(["short", "--yes"])


def test_managed_tool_migration_handles_complete_declined_success_and_failure(monkeypatch):
    states = {}
    status = SimpleNamespace(complete=True)
    messages = []
    database = SimpleNamespace(
        get_state=lambda key: states.get(key),
        set_state=lambda key, value: states.__setitem__(key, value),
    )
    monkeypatch.setattr(main, "DATABASE", database)
    monkeypatch.setattr(main, "discover_media_tools", lambda _settings: status)
    monkeypatch.setattr(main, "find_javascript_runtime", lambda *_args: "deno")
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: messages.append(str(value)))
    assert main.ensure_managed_tool_migration() is status
    assert states["managed_tool_prompt_version"] == "official-tools-2026.07.1"

    status.complete = False
    states.clear()
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    assert main.ensure_managed_tool_migration() is status
    assert "Skipped" in messages[-1]

    states.clear()
    installed = []
    incomplete = SimpleNamespace(complete=False)
    complete = SimpleNamespace(complete=True)
    statuses = iter([incomplete, complete])
    monkeypatch.setattr(main, "discover_media_tools", lambda _settings: next(statuses))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    monkeypatch.setattr(
        main,
        "TOOLCHAIN",
        SimpleNamespace(install_recommended=lambda **_kwargs: installed.append("install")),
    )
    monkeypatch.setattr(main, "persist_media_tools", lambda *_args, **_kwargs: installed.append("persist"))
    monkeypatch.setattr(main, "refresh_runtime_configuration", lambda **_kwargs: installed.append("refresh"))
    assert main.ensure_managed_tool_migration() is complete
    assert installed == ["install", "persist", "refresh"]

    states.clear()
    monkeypatch.setattr(main, "discover_media_tools", lambda _settings: incomplete)
    monkeypatch.setattr(
        main,
        "TOOLCHAIN",
        SimpleNamespace(
            install_recommended=lambda **_kwargs: (_ for _ in ()).throw(main.ToolchainError("offline"))
        ),
    )
    assert main.ensure_managed_tool_migration() is incomplete
    assert "failed" in messages[-1].casefold()
    assert "managed_tool_prompt_version" not in states
