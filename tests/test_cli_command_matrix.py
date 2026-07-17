"""Broad behavior-level coverage for the preserved interactive command surface."""

import threading
from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaChapter, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
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
    monkeypatch.setattr(main, "station_command", lambda args: actions.append(("station", args)))
    monkeypatch.setattr(main, "replaygain_command", lambda args: actions.append(("replaygain", args)))
    monkeypatch.setattr(main, "broadcast_command", lambda args: actions.append(("broadcast", args)))
    monkeypatch.setattr(main.vas, "set_youtube_browser_profile", lambda value: actions.append(("youtube-profile", value)))
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *args, **kwargs: actions.append(("event", args, kwargs)))
    monkeypatch.setattr(main.PREFERENCES, "set", lambda *args, **kwargs: True)
    monkeypatch.setattr(main.PREFERENCES, "get", lambda *_args: PreferenceState.NEUTRAL)
    monkeypatch.setattr(main.PREFERENCES, "toggle", lambda _media, state: state)
    monkeypatch.setattr(main.PREFERENCES, "list", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main, "set_download_library_inclusion", lambda enabled: actions.append(("downloads-root", enabled)))
    monkeypatch.setattr(main, "edit_current_lyrics", lambda **_kwargs: actions.append(("lyrics-edit",)))
    monkeypatch.setattr(main, "recycle_library_media", lambda args: actions.append(("recycle", args)))
    monkeypatch.setattr(main, "open_path", lambda path: actions.append(("open-path", path)))
    monkeypatch.setattr(main, "reveal_path", lambda path: actions.append(("reveal", path)))
    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: ("Video", "https://youtube.test/watch?v=1"))
    monkeypatch.setattr(main, "play_vas_media", lambda *args, **kwargs: actions.append(("play-vas", args, kwargs)))
    monkeypatch.setattr(
        main,
        "url_is_valid",
        lambda value=None, url=None, **_kwargs: (value or url or "").startswith("https://"),
    )
    monkeypatch.setattr(main, "download_media", lambda *args, **kwargs: actions.append(("download-media", args, kwargs)) or tmp_path / "media.mp3")
    monkeypatch.setattr(main, "start_youtube_download", lambda parameters: actions.append(("download-job", parameters)))
    monkeypatch.setattr(
        main,
        "DOWNLOADS",
        SimpleNamespace(
            create=lambda *args, **kwargs: (
                actions.append(("persistent-download", args, kwargs))
                or SimpleNamespace(job_id="download-job", state=SimpleNamespace(value="queued"))
            ),
            status=lambda *_args: [],
            pause=lambda job_id: SimpleNamespace(job_id=job_id, state=SimpleNamespace(value="paused")),
            resume=lambda job_id: SimpleNamespace(job_id=job_id, state=SimpleNamespace(value="queued")),
            cancel=lambda job_id: SimpleNamespace(job_id=job_id, state=SimpleNamespace(value="cancelled")),
        ),
    )
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
        "autonext status",
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
        "youtube auth status",
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
    source = {
        None: MediaSource.LOCAL,
        0: MediaSource.YOUTUBE,
        1: MediaSource.URL,
        2: MediaSource.RADIO,
        3: MediaSource.URL,
    }[media_type]
    title = song if isinstance(song, str) and not song.startswith("https://") else "Safe title"
    if isinstance(song, tuple):
        title = song[0]
    chapter = MediaChapter("Complete chapter title", 60, 120)
    media = MediaRef(source, str(song), title=title, chapters=[chapter])
    monkeypatch.setattr(main.QUEUE, "playback_position", lambda _stable_id: (None, 0))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=media,
            position=75,
            duration=180,
            current_chapter=chapter,
        ),
    )
    main.process("now")
    assert any("Ch 1/1 · Complete chapter title (01:00-02:00)" in value for value in cli.printed)
    main.process("now*")
    main.process("open")


def test_exit_confirmation_paths(cli, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_args: "y")
    assert main.process("exit") is False
    for command in ("quit y", "exit yes", "quit --yes"):
        monkeypatch.setattr(
            "builtins.input",
            lambda *_args: pytest.fail("confirmation bypass prompted"),
        )
        assert main.process(command) is False

    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    assert main.process("exit") is None
    main.process("exit --yes yes")
    assert any("only one confirmation" in message.get("display_message", "") for message in cli.messages)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("fade to 35", (0.7, 0.35, 5.0)),
        ("fade to 35 in 3", (0.7, 0.35, 3.0)),
        ("fade to 30 in 3", (0.7, 0.3, 3.0)),
        ("fade from 20 in 2", (0.2, 0.7, 2.0)),
        ("fade from 20 to 80", (0.2, 0.8, 5.0)),
        ("fade from 20 to 80 in 6", (0.2, 0.8, 6.0)),
        ("fade from 20 to 80 in 0", (0.2, 0.8, 0.0)),
        ("fade 10 20 1", (0.1, 0.2, 1.0)),
        ("fade 10 20 0", (0.1, 0.2, 0.0)),
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
        "fade to 50 in nan",
        "fade to 50 in inf",
        "fade from nan to 50",
        "other to 50",
    ],
)
def test_fade_parser_rejects_partial_or_unsafe_values(command):
    with pytest.raises(ValueError):
        main.parse_fade_arguments(command.split(), 0.5)


@pytest.mark.parametrize(
    ("command", "fade_type", "duration"),
    [
        ("fade in", 0, None),
        ("fade in 5", 0, 5.0),
        ("fade out", 1, None),
        ("fade out 10", 1, 10.0),
        ("fade out 0", 1, 0.0),
    ],
)
def test_simple_fade_forms_preserve_defaults_and_accept_finite_durations(cli, command, fade_type, duration):
    main.process(command)
    expected = {"fade_type": fade_type}
    if duration is not None:
        expected["fade_duration"] = duration
    assert cli.actions[-1] == ("fade", expected)


@pytest.mark.parametrize("command", ["fade in -1", "fade out nan", "fade in inf"])
def test_simple_fade_forms_reject_unsafe_durations(cli, command):
    before = list(cli.actions)
    main.process(command)
    assert cli.actions == before
    assert "finite non-negative" in cli.messages[-1]["display_message"]


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
    monkeypatch.setattr(main, "_sound_files", [first.media.original_uri, second.media.original_uri])
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
    assert main.songindex == 2


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

    for token in ("y", "yes", "--yes"):
        monkeypatch.setattr(
            "builtins.input",
            lambda *_args: pytest.fail("refresh confirmation bypass prompted"),
        )
        main.process(f"refresh all {token}")
    assert cli.actions.count(("refresh-settings",)) == 4


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
    media = MediaRef(MediaSource.URL, "https://example.test/stream", title="Stream")
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=12, duration=None),
    )
    monkeypatch.setattr(main.QUEUE, "playback_position", lambda _stable_id: (None, 0))
    main.process("progress")
    assert any("duration unknown" in line for line in cli.printed)
    assert any("No audio to seek" in message.get("display_message", "") for message in cli.messages)


def test_download_confirmation_and_rejection_paths(cli, monkeypatch):
    monkeypatch.setattr(main, "current_media_type", 0)
    monkeypatch.setattr(main, "currentsong", ("Video", "https://youtube.test/watch?v=1"))
    answers = iter(["invalid", "yes", "y"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))
    main.process("download-yv")
    main.process("download-ya")
    jobs = [action for action in cli.actions if action[0] == "download-job"]
    assert [job[1]["typ"] for job in jobs] == [1]
    assert len([action for action in cli.actions if action[0] == "persistent-download"]) == 1
    assert not [action for action in cli.actions if action[0] == "spawn"]

    monkeypatch.setattr(main, "current_media_type", None)
    main.process("download-yv")
    main.process("download-ya")
    assert any("stored locally" in message.get("display_message", "") for message in cli.messages)


@pytest.mark.parametrize("token", ["y", "yes", "--yes"])
def test_video_download_confirmation_bypass_tokens(cli, monkeypatch, token):
    monkeypatch.setattr(main, "current_media_type", 0)
    monkeypatch.setattr(main, "currentsong", ("Video", "https://youtube.test/watch?v=1"))
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args: pytest.fail("video download confirmation bypass prompted"),
    )

    main.process(f"download-yv {token}")

    assert any(action[0] == "download-job" and action[1]["typ"] == 1 for action in cli.actions)


def test_youtube_download_worker_never_spawns_another_mariana(monkeypatch):
    completed = threading.Event()
    messages = []
    monkeypatch.setattr(main, "media_DL", lambda **_kwargs: completed.set() or 4)
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    monkeypatch.setattr(main.sp, "Popen", lambda *_args, **_kwargs: pytest.fail("download spawned a process"))
    thread = main.start_youtube_download({"typ": 0})
    thread.join(timeout=2)

    assert completed.is_set()
    assert not thread.is_alive()
    assert any("download completed" in message["display_message"] for message in messages)


def test_explicit_youtube_download_validates_syntax_without_network(cli, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_args: "y")
    monkeypatch.setattr(main, "url_is_valid", lambda *_args, **_kwargs: pytest.fail("network validation ran"))

    main.process("download-ya https://www.youtube.com/watch?v=abc12345678")
    main.process("download-yv https://example.test/watch?v=abc12345678")

    jobs = [action for action in cli.actions if action[0] == "download-job"]
    assert jobs == []
    assert len([action for action in cli.actions if action[0] == "persistent-download"]) == 1
    assert any("Invalid YouTube URL for video download" in message["display_message"] for message in cli.messages)


def test_youtube_link_validates_syntax_then_defers_network_resolution(cli, monkeypatch):
    monkeypatch.setattr(
        main,
        "url_is_valid",
        lambda *_args, **_kwargs: pytest.fail("YouTube link command performed duplicate network validation"),
    )

    main.process("/yl https://www.youtube.com/watch?v=abc12345678")

    actions = [action for action in cli.actions if action[0] == "play-vas"]
    assert actions[-1][2] == {
        "media_url": "https://www.youtube.com/watch?v=abc12345678",
        "single_video": True,
    }


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
        "station_command",
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
        "station status",
    ):
        main.process(command)
    assert sum("invalid request" in message.get("display_message", "") for message in cli.messages) == 9


def test_online_resolution_failures_do_not_escape_process(cli, monkeypatch):
    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(main, "play_vas_media", lambda **_kwargs: (_ for _ in ()).throw(OSError("offline")))
    monkeypatch.setattr(main, "url_is_valid", lambda value=None, url=None, **_kwargs: bool(value or url))
    main.process('/ys "query"')
    main.process('/ys "query" 1')
    main.process("/yl https://www.youtube.com/watch?v=abc12345678")
    main.process("vivojay fav")
    assert sum("YouTube" in message.get("display_message", "") for message in cli.messages) == 3


def test_youtube_auth_commands_persist_and_apply_profile_atomically(cli, monkeypatch):
    settings = {"sources": {"youtube": {"browser profile": None}}}
    saves = []
    configured = []
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "save_user_settings", lambda value, path: saves.append((value.copy(), path)))
    monkeypatch.setattr(main.YT_query, "configure", lambda **kwargs: configured.append(kwargs["browser_profile"]))

    assert main.youtube_auth_command(["set", "firefox:default-release"]) == "firefox:default-release"
    assert main.youtube_auth_command(["status"]) == "firefox:default-release"
    assert main.youtube_auth_command(["clear"]) is None

    assert len(saves) == 2
    assert configured == ["firefox:default-release", None]
    assert ("youtube-profile", "firefox:default-release") in cli.actions
    assert ("youtube-profile", None) in cli.actions
    assert settings["sources"]["youtube"]["browser profile"] is None


def test_youtube_auth_test_resolves_without_exposing_stream_url(cli, monkeypatch):
    monkeypatch.setattr(main, "SETTINGS", {"sources": {"youtube": {"browser profile": "firefox"}}})
    monkeypatch.setattr(
        main,
        "resolve_stream",
        lambda url, **kwargs: {
            "url": "https://signed.example.test/secret",
            "title": "Resolved title",
            "input": (url, kwargs),
        },
    )

    result = main.youtube_auth_command(["test", "https://youtu.be/abc12345678"])
    assert result["input"][1] == {"browser_profile": "firefox"}
    assert any("Resolved title" in line for line in cli.printed)
    assert not any("signed.example.test" in line for line in cli.printed)


def test_youtube_auth_save_failure_restores_previous_profile(cli, monkeypatch):
    settings = {"sources": {"youtube": {"browser profile": "edge:Default"}}}
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(
        main,
        "save_user_settings",
        lambda *_args: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        main.youtube_auth_command(["set", "firefox"])
    assert settings["sources"]["youtube"]["browser profile"] == "edge:Default"


def test_like_without_active_media_and_update_failure_are_reported(cli, monkeypatch):
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE))
    main.process("like")
    assert "No active media" in cli.printed
    monkeypatch.setattr(main, "prepare_update", lambda: (_ for _ in ()).throw(OSError("disk full")))
    main.process("update prepare")
    assert any("disk full" in message.get("display_message", "") for message in cli.messages)


def test_legacy_aliases_route_to_modern_handlers(cli):
    main.process("mute")
    main.process("dl-ml https://example.test/audio mp3")
    main.process("include downloads")
    main.process("exclude downloads")
    main.process("lyrics edit")
    main.process("/rpan")
    assert any(action[0] == "mute" for action in cli.actions)
    assert any(action[0] == "download-media" for action in cli.actions)
    assert ("downloads-root", True) in cli.actions
    assert ("downloads-root", False) in cli.actions
    assert ("lyrics-edit",) in cli.actions
    assert main.REDDIT_RETIRED_MESSAGE in cli.printed


@pytest.mark.parametrize("token", ["y", "yes", "--yes"])
def test_lyrics_edit_confirmation_bypass_tokens(cli, token):
    main.process(f"lyrics edit {token}")
    assert ("lyrics-edit",) in cli.actions


def test_stale_snapshot_shortcuts_are_explicitly_retired(cli):
    main.process("weblinks")
    main.process("vivojay fav")
    assert any("weblinks collection is retired" in line for line in cli.printed)
    assert any("hard-coded favorite shortcut is retired" in line for line in cli.printed)


def test_durable_lyrics_edit_creates_sidecar_only_after_confirmation(cli, monkeypatch):
    song = cli.tmp_path / "editable.mp3"
    song.write_bytes(b"audio")
    media = MediaRef(MediaSource.LOCAL, str(song))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media))
    monkeypatch.setattr(main.vas.controller, "fingerprint_pcm", lambda: b"pcm")
    monkeypatch.setattr(main, "_preference_media", lambda value: value)
    monkeypatch.setattr(main, "open_path", lambda _path: None)
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

    bypassed = cli.tmp_path / "bypassed.mp3"
    bypassed.write_bytes(b"audio")
    bypassed_media = MediaRef(MediaSource.LOCAL, str(bypassed))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=bypassed_media),
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args: pytest.fail("lyrics-sidecar confirmation bypass prompted"),
    )
    assert REAL_EDIT_CURRENT_LYRICS(assume_yes=True) == bypassed.with_suffix(".lrc")
