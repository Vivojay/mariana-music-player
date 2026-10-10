from types import SimpleNamespace

import pytest

import main
from mariana import playback_diagnostics as diagnostics
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback import PlaybackController, PlaybackError, UnsupportedAction
from mariana.sources import FailureCode, MediaFailure
from mariana.supervisor import PlaybackSupervisor


@pytest.fixture
def journal(monkeypatch):
    entries = []
    monkeypatch.setattr(diagnostics, "_level", lambda: 4)
    monkeypatch.setattr(diagnostics, "_sink", lambda priority, message: entries.append((priority, message)))
    return entries


def test_diagnostic_levels_and_nonfatal_writer(monkeypatch, journal):
    for level in range(5):
        journal.clear()
        monkeypatch.setattr(diagnostics, "_level", lambda level=level: level)
        for priority in (2, 3, 4):
            diagnostics.record(priority, "test")
        assert [priority for priority, _ in journal] == [p for p in (2, 3, 4) if p <= level]

    def unavailable(*_args):
        raise OSError("private path")

    diagnostics.configure(lambda: 4, unavailable)

    @diagnostics.operation("control")
    def control():
        return 42

    assert control() == 42


def test_pause_resume_seek_reset_stop_and_rejection_are_diagnostic_only(monkeypatch, journal):
    controller = PlaybackController()
    media = MediaRef(MediaSource.LOCAL, "C:/private/audio.mp3", duration=60)
    controller._active = SimpleNamespace(media=media, position=0.0, stop=lambda: None)
    controller._state = PlaybackState.PLAYING
    targets = []

    def session(_media, *, start_at):
        targets.append(start_at)
        return SimpleNamespace(
            media=media, position=float(start_at), start=lambda: None, stop=lambda: None,
            wait_for_buffer=lambda: True,
        )

    monkeypatch.setattr(controller, "_new_session", session)
    controller.pause()
    controller.seek(12)
    assert controller._state == PlaybackState.PAUSED
    controller.resume()
    controller.seek(0)  # The established finite-media reset operation.
    controller.set_volume(0.5)
    controller.set_muted(True)
    controller.stop()
    with pytest.raises(UnsupportedAction):
        controller.pause()
    with pytest.raises(PlaybackError):
        PlaybackController().play()
    controller.close()

    assert targets == [12, 0]
    messages = [message for _, message in journal]
    for action in ("pause", "resume", "seek", "volume", "mute", "stop", "close"):
        assert f"playback {action}.requested" in messages
        assert f"playback {action}.completed" in messages
    assert (2, "playback pause.failed") in journal
    assert (2, "playback play.failed") in journal
    assert "playback seek.target seconds=0" in messages
    assert "private" not in str(journal)


def test_retry_failure_codes_are_logged_without_exception_or_media_secrets(journal):
    media = MediaRef(MediaSource.URL, "https://private.test/audio?token=secret")
    outcomes = iter([PlaybackError(media.original_uri), media])

    def play(*_args, **_kwargs):
        result = next(outcomes)
        if isinstance(result, Exception):
            raise result
        return result

    controller = SimpleNamespace(play=play, resolvers=None, on_failure=None)
    supervisor = PlaybackSupervisor(controller, wait=lambda _delay: False)
    assert supervisor.play(media) is media
    assert (2, "playback attempt.failed.decode attempt=1") in journal
    assert (2, "playback retry.scheduled attempt=2 delay_seconds=1") in journal
    assert (3, "playback supervised_play.completed") in journal
    assert "private" not in str(journal) and "secret" not in str(journal)

    supervisor._wait = lambda _delay: True
    outcomes = iter([PlaybackError("secret")])
    with pytest.raises(MediaFailure) as error:
        supervisor.play(media)
    assert error.value.code == FailureCode.CANCELLED
    assert (3, "playback retry.cancelled") in journal
    assert (2, "playback supervised_play.failed") in journal


@pytest.fixture
def queue_history(monkeypatch, journal):
    history = []
    monkeypatch.setattr(main, "SAY", lambda **kwargs: history.append(kwargs))
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    monkeypatch.setattr(main.QUEUE, "items", list)
    monkeypatch.setattr(main.LIBRARY.loudness, "get", lambda _identity: None)
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args: None)
    monkeypatch.setattr(main.STATION, "mark_played", lambda _media: None)
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda _media: None)
    monkeypatch.setattr(main, "_set_current_media_state", lambda _media: None)
    monkeypatch.setattr(main, "_prefetch_after", lambda _item: None)
    return history


def test_online_queue_history_records_success_only_and_keeps_repeated_listens(monkeypatch, queue_history):
    media = MediaRef(MediaSource.URL, "https://private.test/audio?token=secret", title="A song")
    item = SimpleNamespace(media=media, queue_id=1)
    attempts = iter([False, True, True])
    origins = []

    def play(_media, *, origin):
        origins.append(origin)
        if not next(attempts):
            raise PlaybackError("temporary")

    monkeypatch.setattr(main.vas.supervisor, "play", play)
    monkeypatch.setattr(main.QUEUE, "mark_failure", lambda _id: "retry")
    main._play_queue_item(item)
    assert len(queue_history) == 1
    main._play_queue_item(item)
    assert [row["log_message"] for row in queue_history] == ["A song", "A song"]
    assert all(row["out_file"].name == "history.log" for row in queue_history)
    assert origins == ["automatic", "automatic", "automatic"]
    assert "secret" not in str(queue_history)


@pytest.mark.parametrize("source", [MediaSource.LOCAL, MediaSource.PODCAST])
def test_prefetched_autoplay_records_the_new_song_not_the_completed_song(monkeypatch, queue_history, source):
    old = MediaRef(source, "old", title="Previous")
    new = MediaRef(source, "new", title="Automatically played")
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    monkeypatch.setattr(main.QUEUE, "current", lambda: SimpleNamespace(media=old))
    monkeypatch.setattr(main, "_advance_queue_to_playable", lambda: SimpleNamespace(media=new))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=new))
    main._on_queue_item_complete(old)
    assert [row["log_message"] for row in queue_history] == ["Automatically played"]


def test_history_privacy_and_write_failure_do_not_change_playback(monkeypatch, queue_history, journal):
    media = MediaRef(MediaSource.URL, "https://private.test/audio?token=secret")
    main._record_queue_history(media)
    assert queue_history[0]["log_message"] == "Online media"

    def unavailable(**_kwargs):
        raise OSError("private path")

    monkeypatch.setattr(main, "SAY", unavailable)
    main._record_queue_history(media)
    assert (2, "playback history.write_failed") in journal


def test_automatic_history_is_persisted_even_when_diagnostics_are_off(monkeypatch, tmp_path, journal):
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(logs=tmp_path))
    monkeypatch.setattr(diagnostics, "_level", lambda: 0)
    media = MediaRef(MediaSource.PODCAST, "https://private.test/file?token=secret", title="Episode")
    main._record_queue_history(media)
    main._record_queue_history(media)
    entries = (tmp_path / "history.log").read_text(encoding="utf-8").splitlines()
    assert len(entries) == 2
    assert all(entry.endswith("=> Episode") for entry in entries)
    assert "secret" not in str(entries)
    assert journal == []
