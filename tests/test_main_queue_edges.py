from types import SimpleNamespace

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
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
        ["clear"],
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
