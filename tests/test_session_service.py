import threading
import time
from types import SimpleNamespace

import pytest

from mariana.models import MediaRef, MediaSource, PlaybackState
from mariana.session_recipes import RecipeError, default_settings, load_recipe
from mariana.session_service import SessionRecipeService


def wait_for(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.005)
    assert predicate()


class Playback:
    def __init__(self):
        self.calls = []
        self.state = PlaybackState.IDLE

    def snapshot(self):
        return SimpleNamespace(state=self.state)

    def play(self, media, **kwargs):
        self.calls.append(("play", media, kwargs))
        self.state = PlaybackState.PAUSED if kwargs.get("start_paused") else PlaybackState.PLAYING

    def pause(self, **kwargs):
        self.state = PlaybackState.PAUSED
        self.calls.append(("pause",))

    def resume(self, **kwargs):
        self.state = PlaybackState.PLAYING
        self.calls.append(("resume",))

    def stop(self):
        self.state = PlaybackState.IDLE
        self.calls.append(("stop",))

    def clear_prefetch(self):
        self.calls.append(("clear_prefetch",))

    def configure_replaygain(self, **kwargs):
        self.calls.append(("gain", kwargs))

    def set_crossfade_seconds(self, value):
        self.calls.append(("crossfade", value))


@pytest.fixture
def environment(tmp_path):
    path = tmp_path / "private.wav"
    path.write_bytes(b"synthetic local media bytes")
    media = MediaRef(MediaSource.LOCAL, str(path), duration=60)
    playback = Playback()
    callbacks = []
    service = SessionRecipeService(
        tmp_path / "recipes", playback=lambda: playback,
        lookup_media=lambda stable_id: media if stable_id == media.stable_id else None,
        restore_queue=lambda state, resolved: callbacks.append(("queue", state["queue"])),
        configure_queue=lambda settings: callbacks.append(("queue_settings", settings)),
        set_replay_active=lambda active: callbacks.append(("guard", active)),
    )
    yield service, media, playback, callbacks
    service.close()


def capture(service, media, action="play", play_kind: str | None = "start", position: float = 0):
    return service.capture_playback_event(
        stable_id=media.stable_id, session_id="playback-session", action=action, play_kind=play_kind,
        position_seconds=position, origin="cli", seek_from_seconds=None, seek_to_seconds=None,
    )


def test_service_lazy_capture_stop_inspection_and_existing_authority_replay(environment):
    service, media, playback, callbacks = environment
    assert service._worker is None and not service.directory.exists()
    assert not capture(service, media)
    service.start("example", queue_ids=[media.stable_id], current_index=0)
    assert capture(service, media)
    assert service.capture_queue([media.stable_id], 0)
    assert service.capture_queue([media.stable_id], 0)  # read-only projection repeat must deduplicate
    assert capture(service, media, "pause", None, .5)
    assert service.stop()
    recipe = load_recipe(service.directory / "example.jsonl")
    assert recipe["complete"]
    kinds = [event["kind"] for event in recipe["events"]]
    assert kinds.count("media_start") == 1 and kinds.count("pause") == 1
    assert kinds.count("queue_set") <= 1
    assert service.inspect("example")["media_count"] == 1
    assert not playback.calls
    service.replay("example", at_ms=recipe["duration_ms"])
    wait_for(lambda: service.status()["state"] in {"completed", "failed"})
    assert service.status()["state"] == "completed"
    assert next(call for call in playback.calls if call[0] == "play")[2]["start_paused"]
    assert ("guard", True) in callbacks and callbacks[-1] == ("guard", False)


def test_committed_nested_queue_changes_preserve_seed_and_do_not_capture_raw_metadata(environment):
    service, media, playback, _callbacks = environment
    snapshot = {
        "groups": [{"group_id": "installation-private-group", "name": "Private album", "kind": "album",
                    "parent_id": None, "sibling_position": 0, "strategy": "shuffle", "shuffle_seed": 7,
                    "atomic": True, "source_ref": "https://private.invalid?token=SECRET"}],
        "items": [{"stable_id": media.stable_id, "group_id": "installation-private-group", "sibling_position": 0}],
        "state": {"current_position": 0, "shuffle_seed": 7, "root_strategy": "shuffle", "root_seed": 7},
    }
    service.start("nested", queue_snapshot=snapshot)
    snapshot["groups"][0]["atomic"] = False
    assert service.capture_queue_snapshot(snapshot)
    assert service.capture_queue_snapshot(snapshot)  # Unchanged notification is not another event.
    snapshot["items"].append({"stable_id": media.stable_id, "group_id": None, "sibling_position": 1})
    assert service.capture_queue_snapshot(snapshot)  # Retained seed is not proof that this was a shuffle.
    assert service.stop()
    recipe = load_recipe(service.directory / "nested.jsonl")
    assert recipe["complete"] and recipe["version"] == 2
    events = recipe["events"]
    assert [event["kind"] for event in events] == ["queue_set", "queue_set"]
    assert events[-1]["data"]["seed"] == 7 and len(events[-1]["data"]["queue"]) == 2
    assert not events[0]["data"]["queue_tree"]["groups"][0]["atomic"]
    text = (service.directory / "nested.jsonl").read_text()
    assert "installation-private" not in text and "Private album" not in text and "SECRET" not in text
    assert not playback.calls


def test_capture_never_calls_catalog_or_hash_and_overflow_is_incomplete(tmp_path):
    entered, release = threading.Event(), threading.Event()
    media_path = tmp_path / "track.wav"
    media_path.write_bytes(b"test")
    media = MediaRef(MediaSource.LOCAL, str(media_path), duration=60)
    threads = []

    def lookup(_identity):
        threads.append(threading.current_thread().name)
        entered.set()
        release.wait(2)
        return media

    service = SessionRecipeService(
        tmp_path / "recipes", playback=Playback(), lookup_media=lookup,
        restore_queue=lambda state, resolved: None, configure_queue=lambda settings: None,
        set_replay_active=lambda active: None, capacity=1,
    )
    try:
        service.start("overflow", queue_ids=[media.stable_id])
        assert entered.wait(1)
        before = time.monotonic()
        assert capture(service, media)
        assert not capture(service, media, "pause", None)
        assert time.monotonic() - before < .2
        release.set()
        wait_for(lambda: service.status()["state"] == "recording")
        assert not service.stop()
        assert service.inspect("overflow")["incomplete_reason"] == "overflow"
        assert threads and set(threads) == {"mariana-session-service"}
    finally:
        release.set()
        service.close()


def test_unsupported_crossfade_is_not_silently_disabled(environment):
    service, media, playback, _callbacks = environment
    settings = default_settings()
    settings["crossfade_ms"] = 2000
    with pytest.raises(RecipeError, match="overlap"):
        service.start("unsupported", settings=settings)
    assert not service.directory.exists() and not playback.calls
    service.start("later")
    assert capture(service, media)
    assert service.capture_settings("crossfade_settings", {"crossfade_ms": 5000})
    assert not service.stop()
    assert service.inspect("later")["incomplete_reason"] == "unsupported_operation"


def test_changed_source_replay_fails_without_playing_substitute(environment):
    service, media, playback, callbacks = environment
    service.start("changed", initial_media_id=media.stable_id, playing=True)
    assert service.stop()
    from pathlib import Path

    Path(media.original_uri).write_bytes(b"changed source bytes")
    service.replay("changed")
    wait_for(lambda: service.status()["state"] == "failed")
    assert service.status()["error_code"] == "changed_source"
    assert not any(call[0] == "play" for call in playback.calls)
    assert callbacks[-1] == ("guard", False)


def test_stale_playback_session_marks_recipe_incomplete(environment):
    service, media, _playback, _callbacks = environment
    service.start("stale", initial_media_id=media.stable_id, playing=True,
                  initial_playback_session_id="current-session")
    assert capture(service, media, "pause", None)
    assert not service.stop()
    assert service.inspect("stale")["incomplete_reason"] == "invalid_event"


def test_explicit_stop_and_settings_hooks_are_committed(environment):
    service, media, _playback, _callbacks = environment
    service.start("hooks")
    assert capture(service, media)
    assert service.capture_settings("gain_settings", {"enabled": True, "mode": "track", "preamp_db": -4,
                                                       "prevent_clipping": True})
    assert service.capture_stop()
    assert service.stop()
    recipe = load_recipe(service.directory / "hooks.jsonl")
    assert [event["kind"] for event in recipe["events"]] == ["media_start", "gain_settings", "stop"]


def test_recipe_names_cannot_escape_storage(environment):
    service, _media, _playback, _callbacks = environment
    for name in ["../elsewhere", "C:\\elsewhere", "foo.json", "https://invalid", ""]:
        with pytest.raises(RecipeError):
            service.start(name)


def test_mutual_exclusion_is_immediate_during_preparation(environment):
    service, _media, _playback, _callbacks = environment
    service.start("active")
    with pytest.raises(RecipeError, match="already active"):
        service.replay("active")
    assert service.stop()


def test_service_seek_is_serialized_and_completion_releases_guard(environment):
    service, media, playback, callbacks = environment
    service.start("seekable", initial_media_id=media.stable_id, playing=False, position_ms=5000)
    assert service.stop()
    duration = service.inspect("seekable")["duration_ms"]
    service.replay("seekable", at_ms=duration)
    wait_for(lambda: service.status()["state"] == "completed")
    assert not service.status()["replay_active"] and callbacks[-1] == ("guard", False)
    before = len([call for call in playback.calls if call[0] == "play"])
    with pytest.raises(RecipeError, match="Start session replay"):
        service.seek_replay(duration, active_only=True)
    assert len([call for call in playback.calls if call[0] == "play"]) == before
    assert not service.status()["replay_active"]
    service.seek_replay(duration)
    wait_for(lambda: service.status()["state"] == "completed")
    assert len([call for call in playback.calls if call[0] == "play"]) == before + 1
    assert not service.status()["replay_active"]


def test_repeated_buffering_polls_do_not_enqueue_duplicate_transitions(environment, monkeypatch):
    service, _media, _playback, _callbacks = environment
    service._replay_active = True
    calls = []
    monkeypatch.setattr(service, "_queue", lambda kind, payload: calls.append((kind, payload)) or True)
    service.set_buffering(False)
    service.set_buffering(True)
    service.set_buffering(True)
    service.set_buffering(False)
    service.set_buffering(False)
    assert calls == [("replay_buffering", True), ("replay_buffering", False)]
    service._replay_active = False


def test_recording_polls_buffering_without_cli_or_desktop_status_calls(environment):
    service, _media, playback, _callbacks = environment
    service.start("buffering")
    wait_for(lambda: service.status()["state"] == "recording")
    playback.state = PlaybackState.BUFFERING
    wait_for(lambda: service._buffering_at is not None)
    frozen = service._time_ms()
    time.sleep(.06)
    assert service._time_ms() == frozen
    playback.state = PlaybackState.IDLE
    wait_for(lambda: service._buffering_at is None)
    assert service.stop()
