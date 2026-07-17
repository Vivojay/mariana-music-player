import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from mariana.albums import AlbumError
from mariana.database import MarianaDatabase
from mariana.download_jobs import DownloadJobError
from mariana.models import (
    AlbumRef,
    AlbumTrack,
    MediaCapabilities,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
)
from mariana.output_devices import OutputDeviceError
from mariana.queueing import PersistentQueue, QueueError
from mariana.station import StationError
from tests import test_cli_command_matrix


def local_media(path: str = "C:/music/song.mp3") -> MediaRef:
    return MediaRef(MediaSource.LOCAL, path, title="Song", artist="Artist")


@pytest.fixture
def cli_fixture(monkeypatch, tmp_path: Path):
    return test_cli_command_matrix.cli.__wrapped__(monkeypatch, tmp_path)


def test_lyrics_dispatch_covers_every_media_shape(monkeypatch, tmp_path: Path):
    calls = []
    output = []
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")
    monkeypatch.setattr(main.get_lyrics, "show_window", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "SETTINGS", {"get related songs": True})
    monkeypatch.setattr(main, "lyrics_saved_for_song", None)

    for media_type, current in (
        (0, ("Video", "https://youtube.test/watch?v=one")),
        (1, "https://example.test/audio"),
        (2, "radio"),
        (3, ("retired", "https://example.test/retired")),
    ):
        monkeypatch.setattr(main, "current_media_type", media_type)
        monkeypatch.setattr(main, "currentsong", current)
        main.lyrics_ops(show_window=True)

    monkeypatch.setattr(main, "current_media_type", None)
    monkeypatch.setattr(main, "currentsong", str(song))
    monkeypatch.setattr(main, "lyrics_saved_for_song", None)
    main.lyrics_ops(show_window=True)
    main.lyrics_ops(show_window=False)
    monkeypatch.setattr(main, "currentsong", str(tmp_path / "missing.mp3"))
    main.lyrics_ops(show_window=True)
    monkeypatch.setattr(main, "currentsong", None)
    main.lyrics_ops(show_window=True)

    assert {call.get("isYT", 0) for call in calls} == {0, 1}
    assert any("not supported" in value for value in output)


def test_recommendation_commands_cover_list_related_autofill_and_train(monkeypatch):
    seed = local_media()
    candidates = [
        SimpleNamespace(media=local_media("C:/music/one.mp3"), reasons=("taste",)),
        SimpleNamespace(media=local_media("C:/music/two.mp3"), reasons=("novelty",)),
    ]
    added = []
    output = []
    recommender = SimpleNamespace(
        recommend=lambda **_kwargs: candidates,
        retrain_if_due=lambda **_kwargs: "model-v2",
    )
    queue = SimpleNamespace(items=list, add=added.append)
    monkeypatch.setattr(main, "RECOMMENDER", recommender)
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=seed),
    )

    main.recommendation_command([])
    main.recommendation_command(["show", "2"])
    main.recommendation_command(["related", "1"])
    main.recommendation_command(["autofill", "2"])
    main.recommendation_command(["train"])
    assert len(added) == 2 and any("model-v2" in value for value in output)
    with pytest.raises(QueueError, match="Unknown"):
        main.recommendation_command(["invalid"])

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    with pytest.raises(QueueError, match="No active"):
        main.recommendation_command(["related"])


def test_station_seed_current_local_and_youtube_enrichment(monkeypatch):
    current = local_media()
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=current),
    )
    assert main._station_seed(None) == current
    assert main._station_seed("current") == current
    monkeypatch.setattr(main, "_media_from_argument", lambda _value: local_media("C:/music/other.mp3"))
    assert main._station_seed("other").source == MediaSource.LOCAL

    youtube = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch?v=one")
    monkeypatch.setattr(main, "_media_from_argument", lambda _value: youtube)
    monkeypatch.setattr(
        main,
        "media_info",
        lambda *_args, **_kwargs: {
            "title": "Video",
            "artist": "Artist",
            "album": "Album",
            "duration": 180,
            "categories": ["Music"],
            "track": None,
            "is_live": False,
        },
    )
    assert main._station_seed("youtube").resolver_data["is_music"] is True

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    with pytest.raises(StationError, match="No current"):
        main._station_seed("")


@pytest.mark.parametrize(
    ("muted", "playing", "final", "fade_type", "expected"),
    [
        (True, True, 0.5, 0, "transition"),
        (False, False, 0.5, 0, "transition"),
        (False, True, 0.0, 1, "transition"),
        (False, False, 0.0, 1, "transition"),
        (False, True, None, 0, "message"),
        (False, False, None, 0, "toggle"),
        (False, True, None, 1, "toggle"),
        (False, False, None, 1, "message"),
    ],
)
def test_fade_dispatch_branches(monkeypatch, muted, playing, final, fade_type, expected):
    actions = []
    monkeypatch.setattr(main, "ismuted", muted)
    monkeypatch.setattr(main, "isplaying", playing)
    monkeypatch.setattr(main, "visible", False)
    monkeypatch.setattr(main, "cached_volume", 0.6)
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: actions.append("message"))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: actions.append("print"))
    monkeypatch.setattr(main, "voltransition", lambda **_kwargs: actions.append("transition"))
    monkeypatch.setattr(main, "playpausetoggle", lambda **_kwargs: actions.append("toggle"))
    monkeypatch.setattr(main.vas, "media_player", lambda **_kwargs: actions.append("resume"))
    main.fade_in_out(finalvol=final, fade_type=fade_type, fade_duration=0)
    assert expected in actions


def test_refresh_runtime_configuration_updates_all_live_services(monkeypatch):
    configured = []
    settings = {
        "visible": False,
        "loglevel": 1,
        "editor path": "editor",
        "playback": {"autoplay": False, "crossfade seconds": 2},
        "media tools": {"ffmpeg bin": "ffmpeg", "fpcalc bin": "fpcalc", "rsgain bin": "rsgain"},
        "sources": {"youtube": {"browser profile": "firefox:default"}},
    }
    report = SimpleNamespace(errors=["broken"])
    monkeypatch.setattr(main, "SETTINGS", {})
    monkeypatch.setattr(main, "MEDIA_TOOLS", {})
    monkeypatch.setattr(main, "RUNTIME_REPORT", None)
    monkeypatch.setattr(main, "FATAL_ERROR_INFO", None)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main, "loglevel", 3)
    monkeypatch.setattr(main, "DEFAULT_EDITOR", None)
    monkeypatch.setattr(main.IDENTITY, "fpcalc_bin", main.IDENTITY.fpcalc_bin)
    monkeypatch.setattr(main.LIBRARY, "ffmpeg_bin", main.LIBRARY.ffmpeg_bin)
    monkeypatch.setattr(main.LIBRARY, "fpcalc_bin", main.LIBRARY.fpcalc_bin)
    monkeypatch.setattr(main.LIBRARY, "rsgain", main.LIBRARY.rsgain)
    monkeypatch.setattr(main, "load_user_settings", lambda: settings)
    monkeypatch.setattr(main.YT_query, "configure", lambda **kwargs: configured.append(("youtube", kwargs)))
    monkeypatch.setattr(main.vas, "configure", lambda **kwargs: configured.append(("playback", kwargs)))
    monkeypatch.setattr(main, "check_runtime", lambda *_args: report)
    monkeypatch.setattr(main, "format_runtime_report", lambda _report: ["runtime report"])
    monkeypatch.setattr(main, "RSGainAnalyzer", lambda value: ("rsgain", value))
    result = main.refresh_runtime_configuration(show_report=True)
    assert result is report and main.FATAL_ERROR_INFO == "broken"
    assert main.IDENTITY.fpcalc_bin == "fpcalc"
    assert main.LIBRARY.rsgain == ("rsgain", "rsgain")
    assert len(configured) == 2

    settings["media tools"].pop("javascript bin", None)
    report.errors = []
    main.refresh_runtime_configuration(show_report=False)
    assert main.FATAL_ERROR_INFO is None


def test_local_player_success_queue_timeout_and_failure_paths(monkeypatch, tmp_path: Path):
    song = tmp_path / "Song.mp3"
    song.write_bytes(b"audio")
    actions = []
    queue_media = local_media(str(song))
    queue_item = SimpleNamespace(media=queue_media)
    lengths = iter([0, 1_000])
    player = SimpleNamespace(
        audio_set_volume=lambda value: actions.append(("volume", value)),
        get_length=lambda: next(lengths, 1_000),
    )
    monkeypatch.setattr(main, "_sound_files", [str(song)])
    monkeypatch.setattr(main, "_sound_files_names_only", ["Song"])
    monkeypatch.setattr(main, "_queued_local_item", lambda _path: (0, queue_item))
    monkeypatch.setattr(main.QUEUE, "jump", lambda value: actions.append(("jump", value)))
    monkeypatch.setattr(main, "recents_queue_save", lambda value: actions.append(("recent", value)))
    monkeypatch.setattr(main, "save_user_data", lambda: actions.append(("save",)))
    monkeypatch.setattr(main, "get_currentsong_length", lambda: actions.append(("length",)))
    monkeypatch.setattr(main, "_prefetch_after", lambda item: actions.append(("prefetch", item)))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "SAY", lambda **kwargs: actions.append(("say", kwargs)))
    monkeypatch.setattr(main.vas, "set_media", lambda **kwargs: actions.append(("set", kwargs)))
    monkeypatch.setattr(main.vas, "media_player", lambda **kwargs: actions.append(("play", kwargs)))
    monkeypatch.setattr(main.vas, "wait_until_playing", lambda *_args: None)
    monkeypatch.setattr(main.vas, "player", player)
    monkeypatch.setattr(main, "USER_DATA", {"default_user_data": {"stats": {"play_count": {"local": 0}}}})
    monkeypatch.setattr(main, "cached_volume", 0.5)

    main.play_local_default_player(str(song), 1)
    assert ("jump", 0) in actions and any(item[0] == "prefetch" for item in actions)
    assert main.currentsong_length == 1

    monkeypatch.setattr(main, "_queued_local_item", lambda _path: (None, None))
    main.play_local_default_player(str(song), None, is_queue=True, media=queue_media)
    assert main.songindex == 1
    main.play_local_default_player(str(tmp_path / "outside.mp3"), 1)

    monkeypatch.setattr(main.vas, "set_media", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("decoder")))
    main.play_local_default_player(str(song), None)
    assert any("Failed to play" in item[1].get("display_message", "") for item in actions if item[0] == "say")


def test_process_syntax_idle_routing_and_empty_library_branches(cli_fixture, monkeypatch):
    cli = cli_fixture
    main.process('playlist create "unterminated')
    assert cli.messages

    monkeypatch.setattr(main, "isplaying", True)
    monkeypatch.setattr(main, "currentsong", cli.songs[0])
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    main.process("")
    assert main.currentsong is None and not main.isplaying

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: (_ for _ in ()).throw(RuntimeError("snapshot")),
    )
    main.process("list")
    monkeypatch.setattr(main, "help_command", lambda _args: (_ for _ in ()).throw(ValueError("bad help")))
    main.process("help")
    assert any("bad help" in message.get("display_message", "") for message in cli.messages)

    monkeypatch.setattr(main, "_sound_files", [])
    monkeypatch.setattr(main, "_sound_files_names_only", [])
    main.process("list")
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    assert main.process("exit") is None


def test_process_open_podcast_recent_history_and_reload_branches(cli_fixture, monkeypatch):
    cli = cli_fixture
    monkeypatch.setattr(main, "currentsong", None)
    main.process("/open")
    monkeypatch.setattr(main, "currentsong", cli.songs[0])
    monkeypatch.setattr(main, "open_in_youtube", lambda _value: (_ for _ in ()).throw(OSError("browser")))
    main.process("/open")
    monkeypatch.setattr(main, "open_in_youtube", lambda value: cli.actions.append(("youtube", value)))
    main.process(f'/open "{cli.songs[1]}"')
    monkeypatch.setattr(main, "current_media_type", 1)
    main.process("/open")

    monkeypatch.setattr(main, "current_media_type", None)
    monkeypatch.setattr(main, "get_latest_podbean_data", lambda **_kwargs: None)
    main.process("pods vendor")
    main.process("pods vendors")
    main.process("pod vendors all")
    main.process("pod vendors 1")
    main.process("pods 1 2")
    monkeypatch.setattr(main, "get_latest_podbean_data", lambda **_kwargs: [{"title": "Episode"}])
    main.process("pods custom")

    monkeypatch.setattr(main, "RECENTS_QUEUE", [])
    main.process("last played")
    monkeypatch.setattr(main, "RECENTS_QUEUE", [(None, None, (1, cli.songs[0]))])
    monkeypatch.setattr(main, "currentsong", None)
    main.process("last played")
    main.process("recent 1 1")
    main.process("recent 1 o desc")

    monkeypatch.setattr(main, "reveal_path", lambda _path: (_ for _ in ()).throw(OSError("history")))
    main.process("history count")
    main.process("history invalid")
    main.process("include invalid")
    main.process("reload invalid")


def test_process_refresh_skip_now_device_and_seek_state_branches(cli_fixture, monkeypatch):
    cli = cli_fixture
    answers = iter(["invalid", "n", "yes"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))
    main.process("refresh all")
    main.process("refresh all")

    monkeypatch.setattr(main, "songindex", -1)
    main.process("next")
    monkeypatch.setattr(main, "songindex", "N/A")
    main.process("prev")
    monkeypatch.setattr(main, "songindex", 1)
    main.process("prev 2")
    monkeypatch.setattr(main, "songindex", len(cli.songs))
    main.process("next 2")
    monkeypatch.setattr(main, "songindex", 2)
    main.process(".prev")

    selected = SimpleNamespace(key="new", name="JBL", route="default")
    active = SimpleNamespace(key="old", name="Headphones")
    monkeypatch.setattr(main.vas.controller, "default_output_device", lambda: selected)
    monkeypatch.setattr(main.vas.controller, "_output_device", active)
    main.process("out device")
    monkeypatch.setattr(
        main.vas.controller,
        "default_output_device",
        lambda: (_ for _ in ()).throw(OutputDeviceError("missing")),
    )
    main.process("output device")
    monkeypatch.setattr(main.sounddevice, "query_devices", lambda **_kwargs: {})
    main.process("in device")

    monkeypatch.setattr(main, "currentsong_length", -1)
    main.process("seek 1")
    monkeypatch.setattr(main, "currentsong_length", None)
    main.process("seek 1")
    monkeypatch.setattr(main, "currentsong_length", 120)
    monkeypatch.setattr(main, "validate_time", lambda _raw: 3)
    main.process("seek 1")


def test_process_progress_download_and_online_state_branches(cli_fixture, monkeypatch):
    cli = cli_fixture
    monkeypatch.setattr(main, "currentsong", None)
    main.process("progress")
    monkeypatch.setattr(main, "currentsong", cli.songs[0])
    monkeypatch.setattr(main, "currentsong_length", -1)
    main.process("progress")
    monkeypatch.setattr(main, "currentsong_length", None)
    monkeypatch.setattr(main, "get_currentsong_length", lambda: 120)
    main.process("progress*")

    monkeypatch.setattr(main, "current_media_type", None)
    main.process("download-yv")
    monkeypatch.setattr(main, "current_media_type", 0)
    monkeypatch.setattr(main, "currentsong", None)
    main.process("download-yv")
    monkeypatch.setattr(main, "currentsong", ("Video", "https://youtube.test/watch?v=abcdefghijk"))
    answers = iter(["invalid", "yes"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))
    main.process("download-yv")
    assert any(action[0] == "download-job" for action in cli.actions)

    for media_type, current in (
        (0, ("Video", "https://youtube.test/watch?v=abcdefghijk")),
        (1, "https://example.test/audio"),
        (2, "station"),
        (3, ("retired", "https://example.test/retired")),
    ):
        monkeypatch.setattr(main, "current_media_type", media_type)
        monkeypatch.setattr(main, "currentsong", current)
        monkeypatch.setattr(main, "YOUTUBE_PLAY_TYPE", 1)
        main.process("now")
        main.process("now*")


def test_queue_command_and_group_dispatch_cover_every_operation(monkeypatch, tmp_path: Path):
    output = []
    played = []
    events = []
    with MarianaDatabase(tmp_path / "queue-command.db") as database:
        queue = PersistentQueue(database)
        recommender = SimpleNamespace(
            record_event=lambda *args, **kwargs: events.append((args, kwargs)),
            recommend=lambda *_args, **_kwargs: [],
        )
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "RECOMMENDER", recommender)
        monkeypatch.setattr(main, "STATION", SimpleNamespace(mark_played=lambda media: events.append(media)))
        monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(media_refs=lambda: [local_media()]))
        monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
        monkeypatch.setattr(main, "_play_queue_item", played.append)
        monkeypatch.setattr(main, "_media_from_argument", lambda value: local_media(f"C:/music/{value}.mp3"))
        monkeypatch.setattr(
            main.vas.controller,
            "snapshot",
            lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=local_media()),
        )

        main.queue_command([])
        with pytest.raises(QueueError, match="Usage"):
            main._queue_group_command([])
        with pytest.raises(QueueError, match="Usage"):
            main._queue_group_command(["create"])
        main.queue_command(["group", "create", "Set"])
        main.queue_command(["group", "create", "Nested", "--parent", "1", "--at", "1"])
        main.queue_command(["group", "rename", "1.1", "Inside"])
        main.queue_command(["group", "atomic", "1", "off"])
        main.queue_command(["group", "move", "1.1", "--parent", "root", "--at", "1"])
        with pytest.raises(QueueError, match="Usage"):
            main._queue_group_command(["move", "1", "extra", "--parent", "root"])
        main.queue_command(["tree"])
        with pytest.raises(QueueError, match="Usage"):
            main.queue_command(["group", "remove", "1"])
        main.queue_command(["group", "remove", "1", "--flatten"])
        main.queue_command(["group", "remove", "1", "--recursive"])
        with pytest.raises(QueueError, match="Invalid queue group"):
            main.queue_command(["group", "invalid"])

        main.queue_command(["reset"])
        main.queue_command(["add", "two"])
        with pytest.raises(QueueError, match="Usage"):
            main.queue_command(["add"])
        with pytest.raises(QueueError, match="Usage"):
            main.queue_command(["insert", "bad", "three"])
        main.queue_command(["insert", "2", "three"])
        main.queue_command(["list"])
        main.queue_command(["priority", "1", "7"])
        with pytest.raises(QueueError, match="Usage"):
            main.queue_command(["priority", "1"])
        main.queue_command(["move", "1", "2"])
        main.queue_command(["swap", "1", "2"])
        main.queue_command(["jump", "1"])
        main.queue_command(["next"])
        main.queue_command(["previous"])
        main.queue_command(["shuffle"])
        main.queue_command(["shuffle", "42"])
        main.queue_command(["order", "shuffle", "--seed", "7"])
        with pytest.raises(QueueError, match="Usage"):
            main.queue_command(["order"])
        main.queue_command(["dedupe", "identity"])
        with pytest.raises(QueueError, match="Usage"):
            main.queue_command(["dedupe"])
        main.queue_command(["repeat", "all"])
        main.queue_command(["consume", "on"])
        main.queue_command(["autofill", "off"])
        main.queue_command(["save", "Saved"])
        main.queue_command(["clear", "--yes"])
        main.queue_command(["load", "Saved"])
        main.queue_command(["undo"])
        main.queue_command(["redo"])
        main.queue_command(["remove", "1"])
        queue.clear()
        main.queue_command(["next"])
        with pytest.raises(QueueError, match="Unknown queue operation"):
            main.queue_command(["invalid"])
        assert output and played and events


def test_album_command_empty_fetch_validation_and_empty_play_branches(monkeypatch, tmp_path: Path):
    output = []
    empty = AlbumRef("empty", "Empty Album", album_artist="Artist")
    catalog = SimpleNamespace(
        search=lambda *_args, **_kwargs: [],
        resolve_reference=lambda _value: empty,
        fetch=lambda *_args, **_kwargs: empty,
        select_tracks=lambda album, _selector: album.tracks,
        order_tracks=lambda tracks, _order, **_kwargs: (tracks, None),
    )
    with MarianaDatabase(tmp_path / "album-command.db") as database:
        queue = PersistentQueue(database)
        monkeypatch.setattr(main, "ALBUMS", catalog)
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
        monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
        monkeypatch.setattr(main.DESKTOP_CONTROL, "emit", lambda *_args, **_kwargs: None)
        main.album_command(["search", "missing"])
        main.album_command(["fetch", "empty", "--refresh"])
        main.album_command(["play", "empty"])
        assert queue.items() == [] and any("no albums" in value for value in output)
        with pytest.raises(AlbumError, match="Usage"):
            main.album_command(["fetch"])
        with pytest.raises(AlbumError, match="does not accept"):
            main.album_command(["play", "empty", "--flatten"])
        with pytest.raises(AlbumError, match="Usage"):
            main.album_command(["queue"])
        with pytest.raises(AlbumError, match="Invalid album command"):
            main.album_command(["invalid"])


def test_download_command_validation_cancellation_and_album_edges(monkeypatch, tmp_path: Path):
    output = []
    youtube = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch?v=abcdefghijk", title="Track")
    unresolved = AlbumTrack("Missing")
    local = AlbumTrack("Local", media=local_media())
    album = AlbumRef("album", "Album", album_artist="Artist", tracks=[unresolved, local])
    jobs = SimpleNamespace(
        status=lambda *_args: [],
        create=lambda *_args, **_kwargs: SimpleNamespace(job_id="job", state=SimpleNamespace(value="queued")),
        pause=lambda value: SimpleNamespace(job_id=value, state=SimpleNamespace(value="paused")),
        resume=lambda value: SimpleNamespace(job_id=value, state=SimpleNamespace(value="queued")),
        cancel=lambda value: SimpleNamespace(job_id=value, state=SimpleNamespace(value="cancelled")),
    )
    monkeypatch.setattr(main, "DOWNLOADS", jobs)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "ALBUMS", SimpleNamespace(fetch=lambda _value: album, select_tracks=lambda value, _selector: value.tracks))
    monkeypatch.setattr(main, "_current_youtube_media", lambda: youtube)
    monkeypatch.setattr("builtins.input", lambda *_args: "n")

    assert main.download_audio_command(["status"]) == []
    with pytest.raises(DownloadJobError, match="Usage"):
        main.download_audio_command(["status", "one", "two"])
    for action in ("pause", "resume", "cancel"):
        assert main.download_audio_command([action, "job"]).job_id == "job"
        with pytest.raises(DownloadJobError, match="Usage"):
            main.download_audio_command([action])
    with pytest.raises(DownloadJobError, match="quality"):
        main.download_audio_command(["--quality", "lossless"])
    file_destination = tmp_path / "file"
    file_destination.write_text("not a directory", encoding="utf-8")
    with pytest.raises(DownloadJobError, match="directory"):
        main.download_audio_command(["--to", str(file_destination)])
    with pytest.raises(DownloadJobError, match="either"):
        main.download_audio_command(["--album", "--track"])
    with pytest.raises(DownloadJobError, match="Unknown track"):
        main.download_audio_command(["current", "--missing-only"])
    with pytest.raises(DownloadJobError, match="Usage"):
        main.download_audio_command(["one", "two"])
    assert main.download_audio_command(["current"]) is None

    with pytest.raises(DownloadJobError, match="Unknown album"):
        main._download_album_job("album", ["--unknown"], quality="best", destination=tmp_path, yes=True)
    with pytest.raises(DownloadJobError, match="unresolved"):
        main._download_album_job("album", [], quality="best", destination=tmp_path, yes=True)
    with pytest.raises(DownloadJobError, match="No selected"):
        main._download_album_job(
            "album", ["--allow-partial"], quality="best", destination=tmp_path, yes=True
        )

    downloadable = AlbumRef("download", "Album", tracks=[AlbumTrack("Online", media=youtube)])
    monkeypatch.setattr(
        main,
        "ALBUMS",
        SimpleNamespace(fetch=lambda _value: downloadable, select_tracks=lambda value, _selector: value.tracks),
    )
    assert main._download_album_job("download", [], quality="best", destination=tmp_path, yes=False) is None
    assert any("cancelled" in value.lower() for value in output)


def test_managed_roots_prefetch_and_completion_policy_branches(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main, "SETTINGS", {"download": {"downloads folder": str(tmp_path)}})
    monkeypatch.setattr(main.DATABASE, "get_state", lambda *_args: False)
    assert main._managed_library_roots() == []
    monkeypatch.setattr(main.DATABASE, "get_state", lambda *_args: True)
    assert main._managed_library_roots() == [(tmp_path, "downloads")]
    main.SETTINGS["download"]['make a separate mariana folder within "downloads folder"'] = True
    assert main._managed_library_roots()[0][0].parent == tmp_path
    main.SETTINGS["download"].pop("downloads folder")
    assert main._managed_library_roots() == []

    finite = local_media()
    current = SimpleNamespace(queue_id=1, media=finite)
    following = SimpleNamespace(queue_id=2, media=local_media("C:/music/following.mp3"))
    prefetched = []
    queue = SimpleNamespace(items=lambda: [current, following], state=lambda: {"repeat_mode": "off"})
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", False)
    monkeypatch.setattr(main.vas.controller, "prefetch", prefetched.append)
    main._prefetch_after(current)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    main._prefetch_after(current)
    assert prefetched[-1] == following.media
    queue.state = lambda: {"repeat_mode": "one"}
    main._prefetch_after(current)
    queue.items = lambda: [current]
    queue.state = lambda: {"repeat_mode": "all"}
    main._prefetch_after(current)
    main._prefetch_after(SimpleNamespace(queue_id=99, media=finite))

    events = []
    recommender = SimpleNamespace(
        record_event=lambda *args, **_kwargs: events.append(args),
        retrain_if_due=lambda: events.append(("train",)),
        recommend=lambda **_kwargs: [],
    )
    station = SimpleNamespace(mark_played=lambda media: events.append(("station", media)))
    monkeypatch.setattr(main, "RECOMMENDER", recommender)
    monkeypatch.setattr(main, "STATION", station)
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(current=lambda: None))
    main._on_queue_item_complete(finite)

    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", False)
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(current=lambda: current))
    main._on_queue_item_complete(finite)

    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    empty_queue = SimpleNamespace(
        current=lambda: current,
        next=lambda: None,
        state=lambda: {"autofill": True},
        items=lambda: [current],
    )
    monkeypatch.setattr(main, "QUEUE", empty_queue)
    main._on_queue_item_complete(finite)

    recommendation = SimpleNamespace(media=following.media)
    empty_queue.recommend = None
    recommender.recommend = lambda **_kwargs: [recommendation]
    empty_queue.add = lambda media: following
    empty_queue.jump = lambda _position: following
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=following.media),
    )
    monkeypatch.setattr(main, "_prefetch_after", lambda item: events.append(("prefetch", item)))
    main._on_queue_item_complete(finite)
    assert any(event[0] == "prefetch" for event in events)


def test_queue_item_failure_retry_skip_and_online_play(monkeypatch):
    local = SimpleNamespace(queue_id=1, media=local_media())
    online_media = MediaRef(MediaSource.URL, "https://example.test/audio", title="Online")
    online = SimpleNamespace(queue_id=2, media=online_media)
    events = []
    monkeypatch.setattr(main.LIBRARY.loudness, "get", lambda _stable_id: None)
    monkeypatch.setattr(main, "_prefetch_after", lambda item: events.append(("prefetch", item)))
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *args, **_kwargs: events.append(args))
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(items=lambda: [online]))
    monkeypatch.setattr(main.vas.supervisor, "play", lambda media: events.append(("online", media)))
    main._play_queue_item(online)
    assert ("online", online_media) in events

    actions = iter(["retry", "skip", "stop"])
    queue = SimpleNamespace(
        items=lambda: [local, online],
        mark_failure=lambda _queue_id: next(actions),
        next=lambda: online,
    )
    monkeypatch.setattr(main, "QUEUE", queue)
    calls = {"count": 0}

    def fail_then_play(*_args, **_kwargs):
        calls["count"] += 1
        if calls["count"] < 2:
            raise RuntimeError("decoder")

    monkeypatch.setattr(main, "play_local_default_player", fail_then_play)
    main._play_queue_item(local)
    calls["count"] = 0
    main._play_queue_item(local)
    calls["count"] = 0
    with pytest.raises(RuntimeError, match="decoder"):
        main._play_queue_item(local)


def test_media_info_and_lyrics_edit_defensive_branches(monkeypatch, tmp_path: Path):
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")
    indexed = {
        "library_id": "library-id",
        "canonical_path": str(song),
        "state": "available",
        "metadata": {"title": "Song", "artist": "Artist", "album": "Album", "duration": 10},
    }
    monkeypatch.setattr(main.LIBRARY, "info", lambda value: indexed if value in {"1", str(song)} else None)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    with pytest.raises(ValueError, match="not found"):
        main._media_info(["missing"])
    media, info = main._media_info(["1"])
    assert media.source == MediaSource.LOCAL and info == indexed
    with pytest.raises(ValueError, match="No media"):
        main._media_info([])

    local = local_media(str(song))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=local),
    )
    assert main._media_info([])[1] == indexed
    remote = MediaRef(MediaSource.URL, "https://example.test/audio", title="Remote")
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=remote, duration=20),
    )
    assert main._media_info([])[1]["metadata"]["source"] == "url"
    with pytest.raises(ValueError, match="local file"):
        main.edit_current_lyrics()

    missing = local_media(str(tmp_path / "missing.mp3"))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=missing),
    )
    with pytest.raises(ValueError, match="unavailable"):
        main.edit_current_lyrics()

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=local),
    )
    identity = SimpleNamespace()
    monkeypatch.setattr(main.IDENTITY, "identify", lambda *_args, **_kwargs: identity)
    monkeypatch.setattr(main.IDENTITY, "lyrics", lambda *_args: SimpleNamespace(synced=None, plain=None))
    with pytest.raises(ValueError, match="No lyrics"):
        main.edit_current_lyrics()
    monkeypatch.setattr(main.IDENTITY, "lyrics", lambda *_args: SimpleNamespace(synced="[00:00]Line", plain=None))
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    assert main.edit_current_lyrics() is None
    monkeypatch.setattr("builtins.input", lambda *_args: "y")
    opened = []
    monkeypatch.setattr(main, "DEFAULT_EDITOR", None)
    monkeypatch.setattr(main, "open_path", opened.append)
    assert main.edit_current_lyrics() == song.with_suffix(".lrc")
    song.with_suffix(".lrc").unlink()
    monkeypatch.setattr(main, "DEFAULT_EDITOR", "editor")
    monkeypatch.setattr(main.sp, "Popen", lambda args, **_kwargs: opened.append(args))
    assert main.edit_current_lyrics() == song.with_suffix(".lrc")


def test_lyrics_purge_checks_missing_present_and_failure(monkeypatch, tmp_path: Path):
    first = tmp_path / "lyrics.txt"
    second = tmp_path / "lyrics.html"
    first.write_text("lyrics", encoding="utf-8")
    monkeypatch.setattr(main, "LYRICS_TEXT_PATH", first)
    monkeypatch.setattr(main, "LYRICS_HTML_PATH", second)
    main.purge_old_lyrics_if_exist()
    assert not first.exists()
    first.write_text("lyrics", encoding="utf-8")
    monkeypatch.setattr(main.os, "remove", lambda _path: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError, match="locked"):
        main.purge_old_lyrics_if_exist()


def test_replaygain_broadcast_youtube_and_library_command_edges(monkeypatch):
    output = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    analyzer = SimpleNamespace(verify=lambda: (_ for _ in ()).throw(main.LoudnessError("missing")))
    library = SimpleNamespace(
        loudness=SimpleNamespace(get=lambda _value: None, delete=lambda _value: None),
        rsgain=analyzer,
        schedule_loudness=lambda *_args: 0,
        info=lambda _value: None,
    )
    monkeypatch.setattr(main, "LIBRARY", library)
    with pytest.raises(main.LoudnessError, match="unavailable"):
        main.replaygain_command(["verify"])
    with pytest.raises(main.LibraryError, match="Unknown"):
        main.replaygain_command(["rescan", "missing"])
    with pytest.raises(ValueError, match="Usage"):
        main.replaygain_command(["mode"])

    profile = SimpleNamespace(name="live", codec="opus", bitrate_kbps=128, station_name="Station", reference="ref")
    credentials = SimpleNamespace(
        set=lambda *_args: None,
        delete=lambda _value: False,
        status=lambda _value: {"available": False, "source": "none", "environment": False},
    )
    broadcaster = SimpleNamespace(
        profiles={},
        credentials=credentials,
        start=lambda _value: None,
        test=lambda _value: True,
        stop=lambda: None,
        metadata=lambda _value: None,
        snapshot=lambda: SimpleNamespace(
            state=main.BroadcastState.IDLE,
            profile=None,
            codec=None,
            reconnects=0,
            dropped_blocks=0,
            title=None,
            error=None,
        ),
    )
    monkeypatch.setattr(main, "BROADCASTER", broadcaster)
    main.broadcast_command(["profiles"])
    broadcaster.profiles = {"live": profile}
    main.broadcast_command(["profiles"])
    with pytest.raises(main.BroadcastError, match="Unknown"):
        main.broadcast_command(["credentials", "status", "missing"])
    main.broadcast_command(["credentials", "delete", "live", "--yes"])
    main.broadcast_command(["credentials", "status", "live"])
    with pytest.raises(main.BroadcastError, match="Usage"):
        main.broadcast_command(["credentials", "invalid", "live"])
    main.broadcast_command(["start", "live"])
    main.broadcast_command(["test", "live"])
    broadcaster.test = lambda _value: False
    main.broadcast_command(["test", "live"])
    main.broadcast_command(["stop"])
    main.broadcast_command(["status"])
    with pytest.raises(main.BroadcastError, match="Usage"):
        main.broadcast_command(["invalid"])

    settings = {"sources": {"youtube": {"browser profile": None}}}
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "save_user_settings", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.YT_query, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(main.vas, "set_youtube_browser_profile", lambda _value: None)
    monkeypatch.setattr(main, "parse_browser_profile", lambda value: value)
    monkeypatch.setattr(main, "resolve_stream", lambda *_args, **_kwargs: {"title": "Resolved"})
    with pytest.raises(ValueError, match="Usage"):
        main.youtube_auth_command(["set"])
    assert main.youtube_auth_command(["set", "firefox:default"]) == "firefox:default"
    with pytest.raises(ValueError, match="Usage"):
        main.youtube_auth_command(["clear", "extra"])
    assert main.youtube_auth_command(["clear"]) is None
    with pytest.raises(ValueError, match="Usage"):
        main.youtube_auth_command(["test"])
    assert main.youtube_auth_command(["test", "https://youtube.test/watch?v=one"])["title"] == "Resolved"
    with pytest.raises(ValueError, match="Usage"):
        main.youtube_auth_command(["invalid"])

    service = SimpleNamespace(
        status=lambda: {
            "files": {"available": 1, "missing": 0},
            "service": {"paused": False, "running": True},
            "jobs": [{"stage": "probe", "status": "queued", "count": 1}],
        },
        pause=lambda: None,
        resume=lambda: None,
    )
    library = SimpleNamespace(
        sync_roots=list,
        scan=lambda _mode: SimpleNamespace(discovered=0, changed=0, unavailable_roots=0, errors=0),
        errors=list,
        info=lambda _value: None,
        retry=lambda _target: 0,
        verify=lambda: {"database": "ok", "unavailable_paths": []},
        clean_missing=lambda: 0,
    )
    monkeypatch.setattr(main, "LIBRARY_SERVICE", service)
    monkeypatch.setattr(main, "LIBRARY", library)
    main.library_command(["roots"])
    main.library_command(["status"])
    main.library_command(["errors"])
    with pytest.raises(main.LibraryError, match="Unknown"):
        main.library_command(["retry", "missing"])
    with pytest.raises(main.LibraryError, match="Unknown"):
        main.library_command(["info", "missing"])


def test_podcast_choice_media_playback_and_url_choice_edges(monkeypatch):
    output = []
    played = []
    real_play_vas_media = main.play_vas_media
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: output.append(kwargs.get("display_message", "")))
    monkeypatch.setattr(main, "play_vas_media", lambda **kwargs: played.append(kwargs))
    entries = [
        {"title": "Episode", "caption": "Long caption", "pub_date": "today", "is_explicit": False, "url": "https://example.test/episode"},
        {"title": "No URL", "caption": None, "pub_date": None, "is_explicit": None},
    ]
    monkeypatch.setattr(main, "visible", True)
    main.display_and_choose_podbean(entries, [".pod"], 1)
    assert played
    answers = iter(["2", "", "invalid", "99"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))
    for _ in range(4):
        main.display_and_choose_podbean(entries, ["pods"], 2, is_rss=True)
    assert any("No rss" in value for value in output)

    actions = []
    monkeypatch.setattr(main, "play_vas_media", real_play_vas_media)
    monkeypatch.setattr(main, "stopsong", lambda: actions.append("stop"))
    monkeypatch.setattr(main, "recents_queue_save", lambda value: actions.append(value))
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "USER_DATA", {"default_user_data": {"stats": {"play_count": {"youtube": 0, "general": 0, "radio": 0, "redditsession": 0}}}})
    monkeypatch.setattr(main.vas, "set_media", lambda **kwargs: kwargs.get("vidurl", "stream"))
    monkeypatch.setattr(main.vas, "media_player", lambda **_kwargs: None)
    monkeypatch.setattr(main.vas, "wait_until_playing", lambda *_args: None)
    monkeypatch.setattr(main.vas, "player", SimpleNamespace(audio_set_volume=lambda _value: None, get_length=lambda: 1_000))
    monkeypatch.setattr(main.YT_query, "vid_info", lambda _url: {"title": "Video"})
    main.play_vas_media("https://youtube.test/watch?v=one", single_video=True)
    main.play_vas_media("https://youtube.test/watch?v=two", single_video=False, media_name="Named")
    monkeypatch.setattr(main.YT_query, "vid_info", lambda _url: (_ for _ in ()).throw(RuntimeError("metadata")))
    main.play_vas_media("https://youtube.test/watch?v=three")
    main.play_vas_media("https://example.test/audio", media_type="general", show_link_chosen_msg=True)
    main.play_vas_media("ignored", media_type="radio", media_name="station")
    main.play_vas_media("https://example.test/retired", media_type="redditsession", media_name="retired")
    assert main.play_vas_media("invalid", media_type="invalid") is False

    monkeypatch.setattr(main, "play_vas_media", lambda **kwargs: played.append(kwargs))
    main.choose_media_url([("One", "https://youtube.test/one")])
    answers = iter(["", "bad", "99", "1"])
    monkeypatch.setattr("builtins.input", lambda *_args: next(answers))
    choices = [(1, "One", "https://youtube.test/one"), (2, "Two", "https://youtube.test/two")]
    for _ in range(4):
        main.choose_media_url(choices)
    main.choose_media_url(choices, yt=False)


def test_run_safety_callback_reports_every_busy_reason(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "initialize_audio_output", lambda: None)
    monkeypatch.setattr(main.DESKTOP_CONTROL, "start_request_listener", lambda callback: captured.update(control=callback))
    monkeypatch.setattr(main.DESKTOP_CONTROL, "start_playback_monitor", lambda callback: captured.update(playback=callback))
    monkeypatch.setattr(main.DESKTOP_CONTROL, "start_safety_monitor", lambda callback: captured.update(safety=callback))
    monkeypatch.setattr(main.DESKTOP_CONTROL, "emit", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "mainprompt", lambda: None)
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(main, "visible", False)
    monkeypatch.setattr(main, "USER_DATA", {"default_user_data": {"stats": {"log_ins": 0}}})
    monkeypatch.setattr(main.LIBRARY_SERVICE, "start", lambda **_kwargs: None)
    monkeypatch.setattr(main.LIBRARY_SERVICE, "status", lambda: {"jobs": [{"status": "leased"}]})
    monkeypatch.setattr(main.DOWNLOADS, "status", lambda *_args: [{"state": "running"}])
    monkeypatch.setattr(main.SLEEP_TIMER, "status", lambda: SimpleNamespace(active=True))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=local_media()),
    )
    monkeypatch.setattr(
        main.BROADCASTER,
        "snapshot",
        lambda: SimpleNamespace(state=main.BroadcastState.LIVE),
    )
    main.COMMAND_BUSY.set()
    try:
        main.run()
        assert captured["control"] is main._desktop_control_request
        assert captured["playback"] is main._playback_status_projection
        safe, reasons = captured["safety"]()
        assert not safe
        assert set(reasons) == {
            "command-active",
            "sleep-timer",
            "playback-active",
            "broadcast-active",
            "profiler-transaction",
            "download-active",
        }
        main.COMMAND_BUSY.clear()
        monkeypatch.setattr(main.SLEEP_TIMER, "status", lambda: SimpleNamespace(active=False))
        monkeypatch.setattr(
            main.vas.controller,
            "snapshot",
            lambda: PlaybackSnapshot(PlaybackState.IDLE),
        )
        monkeypatch.setattr(main.BROADCASTER, "snapshot", lambda: SimpleNamespace(state=main.BroadcastState.IDLE))
        monkeypatch.setattr(main.LIBRARY_SERVICE, "status", lambda: {"jobs": []})
        monkeypatch.setattr(main.DOWNLOADS, "status", list)
        assert captured["safety"]() == (True, [])
    finally:
        main.COMMAND_BUSY.clear()


def test_last_repository_branch_boundaries(monkeypatch):
    with pytest.raises(ValueError, match="Missing required"):
        main._command_option([], "--parent", required=True)
    with pytest.raises(ValueError, match="requires a value"):
        main._command_option(["--parent", "--at"], "--parent")

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    with pytest.raises(AlbumError, match="No media"):
        main._album_reference("current")
    no_album = local_media()
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=no_album),
    )
    with pytest.raises(AlbumError, match="no established"):
        main._album_reference("current")

    unbounded = MediaRef(
        MediaSource.RADIO,
        "https://example.test/live",
        capabilities=MediaCapabilities(finite=False, live=True),
    )
    item = SimpleNamespace(queue_id=1, media=unbounded)
    prefetched = []
    queue = SimpleNamespace(items=lambda: [item], state=lambda: {"repeat_mode": "off"})
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    monkeypatch.setattr(main.vas.controller, "prefetch", prefetched.append)
    main._prefetch_after(item)
    queue.state = lambda: {"repeat_mode": "all"}
    main._prefetch_after(item)
    assert prefetched == []

    setup_calls = []
    fake_setup = SimpleNamespace(fbs=lambda **_kwargs: setup_calls.append("setup") or False)
    fake_store = SimpleNamespace(load=lambda: SimpleNamespace(status="complete"))
    monkeypatch.setattr(main, "SETUP_STORE", fake_store)
    monkeypatch.setattr(main, "refresh_runtime_configuration", lambda **_kwargs: setup_calls.append("refresh"))
    monkeypatch.setattr(main, "reload_sounds", lambda **_kwargs: setup_calls.append("reload"))
    monkeypatch.setitem(sys.modules, "first_boot_setup", fake_setup)
    main.first_startup_greet(False)
    main.first_startup_greet(True)
    assert setup_calls == ["setup", "refresh", "reload"]
    fake_setup.fbs = lambda **_kwargs: "skipped"
    main.first_startup_greet(True)
    assert main.SOFT_FATAL_ERROR_INFO == "User skipped startup"
