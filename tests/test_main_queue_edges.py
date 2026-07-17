from types import SimpleNamespace

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback_status import project_playback_status
from mariana.queueing import PersistentQueue, QueueError


def test_media_argument_and_open_in_youtube_edges(monkeypatch, tmp_path):
    song = tmp_path / "song.mp3"
    song.touch()
    monkeypatch.setattr(main, "_sound_files", [str(song)])
    assert main._media_from_argument("1").source == MediaSource.LOCAL
    assert main._media_from_argument(str(song)).source == MediaSource.LOCAL
    assert main._media_from_argument("https://youtube.com/watch?v=x").source == MediaSource.YOUTUBE
    assert main._media_from_argument("https://example.test/audio").source == MediaSource.URL
    with pytest.raises(QueueError):
        main._media_from_argument("missing")
    opened = []
    monkeypatch.setattr(main, "get_song_info", lambda *_args, **_kwargs: "Artist Title")
    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: ("Title", "https://youtube.test"))
    monkeypatch.setattr(main.webbrowser, "open", opened.append)
    assert main.open_in_youtube(song) == 0 and opened
    monkeypatch.setattr(main, "get_song_info", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
    assert main.open_in_youtube(song) == 1


def test_indexed_local_playback_media_uses_catalog_metadata_and_safe_display_label(monkeypatch, tmp_path):
    song = tmp_path / "maybe you miss me [932698612].mp3"
    song.touch()
    indexed = {
        "library_id": "library-id",
        "canonical_path": str(song),
        "state": "available",
        "metadata": {"artist": "Artist", "duration": 120},
    }
    monkeypatch.setattr(main.LIBRARY, "info", lambda value: indexed if value == str(song) else None)

    enriched = main._indexed_local_playback_media(MediaRef(MediaSource.LOCAL, str(song)))

    assert enriched is not None
    assert enriched.stable_id == "library-id"
    assert enriched.artist == "Artist" and enriched.duration == 120
    assert enriched.title is None
    assert enriched.resolver_data["library_display_title"] == "maybe you miss me [932698612]"
    assert str(song) not in str(enriched.resolver_data)
    assert project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=enriched)
    ).title == "maybe you miss me [932698612]"


def test_unindexed_local_playback_media_keeps_generic_fallback(monkeypatch, tmp_path):
    song = tmp_path / "outside.mp3"
    song.touch()
    monkeypatch.setattr(main.LIBRARY, "info", lambda _value: None)

    original = MediaRef(MediaSource.LOCAL, str(song))
    assert main._indexed_local_playback_media(original) is original


def test_online_queue_play_retries_then_records_start(monkeypatch):
    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    item = SimpleNamespace(media=media, queue_id=1)
    calls = []

    def play(_media):
        calls.append("play")
        if len(calls) == 1:
            raise RuntimeError("temporary")

    monkeypatch.setattr(main.vas.supervisor, "play", play)
    monkeypatch.setattr(main.QUEUE, "mark_failure", lambda _queue_id: "retry")
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: calls.append("event"))
    monkeypatch.setattr(main, "_prefetch_after", lambda _item: calls.append("prefetch"))
    main._play_queue_item(item)
    assert calls.count("play") == 2 and calls[-1] == "prefetch"
    assert main.currentsong == media.original_uri and main.current_media_type == 1


def test_queue_play_skip_and_prefetch_modes(monkeypatch):
    prefetch_after = main._prefetch_after
    first = SimpleNamespace(
        media=MediaRef(MediaSource.URL, "https://example.test/bad"),
        queue_id=1,
    )
    second = SimpleNamespace(
        media=MediaRef(MediaSource.URL, "https://example.test/next", capabilities=MediaCapabilities(finite=True)),
        queue_id=2,
    )
    calls = []
    attempts = iter([RuntimeError("bad"), None])

    def play(_media):
        outcome = next(attempts)
        if outcome:
            raise outcome

    monkeypatch.setattr(main.vas.supervisor, "play", play)
    monkeypatch.setattr(main.QUEUE, "mark_failure", lambda _queue_id: "skip")
    monkeypatch.setattr(main.QUEUE, "next", lambda: second)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_prefetch_after", lambda item: calls.append(item))
    main._play_queue_item(first)
    assert calls == [second]
    # Exercise prefetch selection independently; playback failures never leak from prefetch.
    monkeypatch.setattr(main, "_prefetch_after", prefetch_after)
    monkeypatch.setattr(main.QUEUE, "items", lambda: [first, second])
    monkeypatch.setattr(main.QUEUE, "state", lambda: {"repeat_mode": "off"})
    monkeypatch.setattr(main.vas.controller, "prefetch", lambda media: calls.append(media))
    main._prefetch_after(first)
    assert second.media in calls
    monkeypatch.setattr(main.QUEUE, "state", lambda: {"repeat_mode": "one"})
    main._prefetch_after(first)


def test_prefetch_attaches_fresh_indexed_identity_before_auto_advance(monkeypatch, tmp_path):
    first_path = tmp_path / "First.mp3"
    next_path = tmp_path / "Elina - Mirage (Official Video) [audio].mp3"
    first = SimpleNamespace(
        queue_id=1,
        media=MediaRef(
            MediaSource.LOCAL,
            str(first_path),
            stable_id="library-first",
            capabilities=MediaCapabilities(finite=True),
        ),
    )
    second = SimpleNamespace(
        queue_id=2,
        media=MediaRef(
            MediaSource.LOCAL,
            str(next_path),
            stable_id="library-second",
            capabilities=MediaCapabilities(finite=True),
        ),
    )
    info = {
        "library_id": "library-second",
        "canonical_path": str(next_path),
        "state": "available",
        "metadata": {},
    }
    prefetched = []
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    monkeypatch.setattr(main.QUEUE, "items", lambda: [first, second])
    monkeypatch.setattr(main.QUEUE, "state", lambda: {"repeat_mode": "off"})
    monkeypatch.setattr(main.LIBRARY, "info", lambda value: info if value == str(next_path) else None)
    monkeypatch.setattr(main.vas.controller, "prefetch", prefetched.append)

    main._prefetch_after(first)

    assert len(prefetched) == 1
    assert prefetched[0].stable_id == "library-second"
    assert prefetched[0].provenance == "library"
    assert prefetched[0].resolver_data["library_display_title"] == next_path.stem
    projected = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=prefetched[0]),
        library_index=2,
        queue_position=2,
        queue_count=2,
    )
    assert projected.title == next_path.stem
    assert projected.library_index == projected.queue_position == 2


@pytest.fixture
def queue_cli(monkeypatch, tmp_path):
    database = MarianaDatabase(tmp_path / "queue.db")
    queue = PersistentQueue(database)
    paths = []
    for name in ("one.mp3", "two.mp3", "three.mp3", "new.mp3"):
        path = tmp_path / name
        path.touch()
        paths.append(path)
    for path in paths[:3]:
        queue.add(MediaRef(MediaSource.LOCAL, str(path)))
    queue.save("saved")
    queue.jump(0)
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "_sound_files", [str(path) for path in paths])
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_play_queue_item", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    yield queue, paths
    database.close()


@pytest.mark.parametrize(
    "arguments",
    [
        ["list"],
        ["add", "4"],
        ["insert", "1", "4"],
        ["remove", "1"],
        ["move", "1", "2"],
        ["swap", "1", "2"],
        ["jump", "2"],
        ["next"],
        ["previous"],
        ["clear", "--yes"],
        ["shuffle", "42"],
        ["repeat", "all"],
        ["consume", "on"],
        ["autofill", "on"],
        ["save", "new queue"],
        ["load", "saved"],
        ["undo"],
    ],
)
def test_every_queue_command_mutation(queue_cli, arguments):
    main.queue_command(arguments)


def test_queue_redo_and_validation(queue_cli):
    queue, _paths = queue_cli
    queue.remove(0)
    assert queue.undo()
    main.queue_command(["redo"])
    with pytest.raises(QueueError):
        main.queue_command(["unknown"])


@pytest.mark.parametrize("token", ["y", "yes", "--yes"])
def test_queue_clear_confirmation_bypass_tokens(queue_cli, monkeypatch, token):
    queue, _paths = queue_cli
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args: pytest.fail("queue clear confirmation bypass prompted"),
    )
    main.queue_command(["clear", token])
    assert queue.items() == []


def test_queue_clear_prompt_rejection_preserves_items(queue_cli, monkeypatch):
    queue, _paths = queue_cli
    original = [item.queue_id for item in queue.items()]
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    main.queue_command(["clear"])
    assert [item.queue_id for item in queue.items()] == original
    with pytest.raises(QueueError, match="Usage"):
        main.queue_command(["clear", "unexpected"])


def test_queue_next_marks_the_station_item_played(queue_cli, monkeypatch):
    marked = []
    media = queue_cli[0].current().media
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=5, duration=30),
    )
    monkeypatch.setattr(main.STATION, "mark_played", marked.append)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: None)

    main.queue_command(["next"])

    assert marked == [media]


def test_queue_reset_restores_the_library_projection(queue_cli, monkeypatch):
    queue, paths = queue_cli
    library_media = [MediaRef(MediaSource.LOCAL, str(path), title=path.stem) for path in paths]
    monkeypatch.setattr(main.LIBRARY, "media_refs", lambda: library_media)
    queue.clear()

    main.queue_command(["reset"])

    assert queue.origin() == "default-library"
    assert [item.media.title for item in queue.items()] == [path.stem for path in paths]


def test_youtube_search_queues_durable_reference_without_interrupting_playback(queue_cli, monkeypatch):
    queue, _paths = queue_cli
    active = queue.current()
    played = []
    printed = []
    monkeypatch.setattr(
        main.YT_query,
        "search_youtube",
        lambda **_kwargs: (
            "Queued Track",
            "https://www.youtube.com/watch?v=abc12345678&utm_source=search&token=temporary",
        ),
    )
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main.vas.supervisor, "play", lambda media: played.append(media))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=active.media),
    )

    main.queue_command(["youtube", "Queued", "Track"])

    queued = queue.items()[-1].media
    assert queued.source == MediaSource.YOUTUBE
    assert queued.original_uri == "https://www.youtube.com/watch?v=abc12345678"
    assert queued.resolver_data == {"youtube": True}
    assert queued.provenance == "youtube-search"
    assert queue.current().queue_id == active.queue_id
    assert not played
    assert printed == ["Queued YouTube result: Queued Track"]


def test_youtube_queue_selector_alias_and_idle_guidance(queue_cli, monkeypatch):
    queue, _paths = queue_cli
    printed = []
    searches = []
    monkeypatch.setattr(
        main.YT_query,
        "search_youtube",
        lambda **kwargs: searches.append(kwargs) or [
            (1, "First", "https://www.youtube.com/watch?v=abc12345678"),
            (2, "Second", "https://www.youtube.com/watch?v=def12345678"),
        ],
    )
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "2")

    main.process('/ysq "artist title" 2')

    queued = queue.items()[-1]
    assert queued.media.title == "Second"
    assert searches == [{"search": "artist title", "rescount": 2}]
    assert printed[-2] == "Queued YouTube result: Second"
    assert printed[-1] == f"No media is playing; use 'queue jump {len(queue.items())}' to start this item."


def test_youtube_queue_search_rejects_empty_limits_and_no_results(queue_cli, monkeypatch):
    with pytest.raises(QueueError, match="Usage: queue ys"):
        main.queue_command(["ys"])
    with pytest.raises(QueueError, match="greater than zero"):
        main.queue_command(["ys", "query", "0"])
    with pytest.raises(QueueError, match="must not exceed"):
        main.queue_command(["ys", "query", str(main.max_yt_search_results_threshold + 1)])

    monkeypatch.setattr(
        main.YT_query,
        "search_youtube",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("No YouTube results found")),
    )
    with pytest.raises(QueueError, match="returned no results"):
        main.queue_command(["ys", "missing"])


def test_youtube_queue_search_handles_selection_and_provider_failures(queue_cli, monkeypatch):
    queue, _paths = queue_cli
    original_count = len(queue.items())
    choices = [
        (1, "First", "https://www.youtube.com/watch?v=abc12345678"),
        (2, "Second", "https://www.youtube.com/watch?v=def12345678"),
    ]
    printed = []
    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: choices)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    main.queue_command(["ys", "cancelled", "2"])

    assert len(queue.items()) == original_count
    assert printed == ["YouTube queue selection cancelled"]

    monkeypatch.setattr("builtins.input", lambda _prompt="": "third")
    with pytest.raises(QueueError, match="number between 1 and 2"):
        main.queue_command(["ys", "invalid", "2"])

    monkeypatch.setattr(main.YT_query, "search_youtube", lambda **_kwargs: [])
    with pytest.raises(QueueError, match="returned no results"):
        main.queue_command(["ys", "empty", "2"])

    monkeypatch.setattr(
        main.YT_query,
        "search_youtube",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("provider unavailable")),
    )
    monkeypatch.setattr(main, "youtube_error_message", lambda *_args: "YouTube provider is unavailable")
    with pytest.raises(QueueError, match="provider is unavailable"):
        main.queue_command(["ys", "provider"])

    monkeypatch.setattr(
        main.YT_query,
        "search_youtube",
        lambda **_kwargs: ("Invalid", "https://example.test/transient"),
    )
    with pytest.raises(QueueError, match="invalid canonical media reference"):
        main.queue_command(["ys", "invalid-result"])


def test_direct_local_media_aligns_with_its_queue_identity(monkeypatch, tmp_path):
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.touch()
    second.touch()
    with MarianaDatabase(tmp_path / "aligned.db") as database:
        queue = PersistentQueue(database)
        media = [
            MediaRef(MediaSource.LOCAL, str(first), stable_id="library-first"),
            MediaRef(MediaSource.LOCAL, str(second), stable_id="library-second"),
        ]
        queue.sync_library_defaults(media)
        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main.vas, "set_media", lambda **_kwargs: None)
        monkeypatch.setattr(main.vas, "current_media", None)
        monkeypatch.setattr(main.vas, "media_player", lambda **_kwargs: None)
        monkeypatch.setattr(main.vas.player, "audio_set_volume", lambda _value: None)
        monkeypatch.setattr(main.vas.player, "get_length", lambda: 1000)
        monkeypatch.setattr(main.vas, "wait_until_playing", lambda *_args: True)
        monkeypatch.setattr(main, "save_user_data", lambda: None)
        monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
        monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(main, "_prefetch_after", lambda _item: None)
        monkeypatch.setattr(main, "USER_DATA", {
            "default_user_data": {"stats": {"play_count": {"local": 0}}}
        })

        main.play_local_default_player(str(second), _songindex=2)

        assert queue.current().media.stable_id == "library-second"
        assert main.vas.current_media.stable_id == "library-second"
