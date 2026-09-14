import copy
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mariana import session_recipes as recipes
from mariana.models import MediaRef, MediaSource, PlaybackState
from mariana.session_service import SessionRecipeService


def reference():
    return {"source": "local", "stable_id": "a" * 24, "fingerprint": "b" * 64,
            "duration_ms": 60_000, "live": False, "provider_id": None}


def playable_recipe():
    recipe = recipes.new_recipe(session_id="boundary-session", media={"track": reference()})
    recipe["initial_state"].update(media="track", playing=True)
    recipe["events"] = [{"seq": 0, "at_ms": 1000, "session_id": recipe["session_id"],
                         "kind": "pause", "reason": "manual", "data": {"position_ms": 1000}}]
    recipe["duration_ms"] = 2000
    return recipe


def header():
    value = recipes.new_recipe(session_id="journal-session")
    value.update(complete=False, incomplete_reason="unsealed")
    return {"type": "header", "value": value}


def seal():
    return {"type": "seal", "value": {"duration_ms": 0, "complete": True,
                                      "incomplete_reason": None, "event_count": 0}}


def write_records(path: Path, records: list) -> bytes:
    payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records).encode("utf-8") + b"\n"
    path.write_bytes(payload)
    return payload


def replay_host():
    host = Mock(spec=recipes.RecipeReplayHost)
    host.capabilities = frozenset({"playback", "queue", "queue_settings", "gain_settings", "crossfade_settings"})
    host.resolve.side_effect = lambda ref: recipes.ResolvedRecipeMedia("resolved-track", ref)
    host.is_buffering.return_value = False
    return host


@pytest.mark.parametrize("field,value", [
    ("version", True), ("version", "2"), ("version", 0), ("version", 3),
    ("format", "terminal-recording"), ("clock", "unix-ms"), ("clock", "relative-seconds"),
    ("complete", True), ("incomplete_reason", "private diagnostic"),
])
def test_import_rejects_incompatible_or_inconsistent_envelopes_before_authority(tmp_path, field, value):
    recipe = playable_recipe()
    if field == "complete":
        recipe["incomplete_reason"] = "overflow"
    recipe[field] = value
    path = tmp_path / "untrusted.json"
    payload = json.dumps(recipe).encode()
    path.write_bytes(payload)
    host = replay_host()
    with pytest.raises(recipes.RecipeError):
        recipes.RecipeReplayEngine(recipes.load_recipe(path), host)
    assert host.mock_calls == []
    assert path.read_bytes() == payload


@pytest.mark.parametrize("payload", [b"\xff\xfe{}", b'{"format":"\xc3"}', b"[" * 2000 + b"]" * 2000,
                                    b'{"type":"header","value":NaN}', b'{"type":"header","value":Infinity}'])
def test_invalid_utf8_nonfinite_or_excessive_json_nesting_is_safe_validation_error(tmp_path, payload):
    path = tmp_path / "invalid.jsonl"
    path.write_bytes(payload)
    with pytest.raises(recipes.RecipeError):
        recipes.load_recipe(path)
    assert path.read_bytes() == payload


@pytest.mark.parametrize("change,match", [
    (lambda rows: rows.append(seal()), "follow journal seal"),
    (lambda rows: rows.append({"type": "media", "value": {"key": "new", "reference": reference()}}),
     "follow journal seal"),
    (lambda rows: rows[-1]["value"].update(event_count=True), "event count"),
    (lambda rows: rows[-1]["value"].update(event_count=1), "event count"),
    (lambda rows: rows[0]["value"].update(complete=True, incomplete_reason=None), "Invalid journal header"),
    (lambda rows: rows[0]["value"].update(duration_ms=1), "Invalid journal header"),
    (lambda rows: rows.insert(1, {"type": "header", "value": header()["value"]}), "Unknown journal record"),
])
def test_journal_seal_and_header_contract_cannot_be_bypassed(tmp_path, change, match):
    rows = [header(), seal()]
    change(rows)
    path = tmp_path / "journal.jsonl"
    payload = write_records(path, rows)
    with pytest.raises(recipes.RecipeError, match=match):
        recipes.load_recipe(path)
    assert path.read_bytes() == payload


def test_journal_cannot_replace_registered_identity_or_add_oversized_records(tmp_path):
    registration = {"type": "media", "value": {"key": "track", "reference": reference()}}
    changed = copy.deepcopy(registration)
    changed["value"]["reference"]["fingerprint"] = "c" * 64
    path = tmp_path / "replaced.jsonl"
    write_records(path, [header(), registration, changed, seal()])
    with pytest.raises(recipes.RecipeError, match="cannot be replaced"):
        recipes.load_recipe(path)
    write_records(path, [header(), {"type": "event", "value": "x" * recipes.MAX_RECORD_BYTES}])
    with pytest.raises(recipes.RecipeError, match="record exceeds its byte limit"):
        recipes.load_recipe(path)


@pytest.mark.parametrize("case", ["skips-event", "backwards", "duplicate", "missing-media", "wrong-index"])
def test_checkpoint_must_represent_available_history_and_media(case):
    recipe = playable_recipe()
    checkpoint = {"at_ms": 500, "event_index": 0, "state": recipes.effective_state(recipe, 500)}
    recipe["checkpoints"] = [checkpoint]
    if case == "skips-event":
        checkpoint["at_ms"] = 1500
    elif case == "backwards":
        recipe["checkpoints"].append({**copy.deepcopy(checkpoint), "at_ms": 400})
    elif case == "duplicate":
        recipe["checkpoints"].append(copy.deepcopy(checkpoint))
    elif case == "missing-media":
        checkpoint["state"]["media"] = "not-in-manifest"
    else:
        checkpoint["event_index"] = 2
    host = replay_host()
    with pytest.raises(recipes.RecipeError):
        recipes.RecipeReplayEngine(recipe, host)
    assert not host.mock_calls


@pytest.mark.parametrize("field,limit", [("events", recipes.MAX_EVENTS), ("checkpoints", recipes.MAX_CHECKPOINTS)])
def test_import_collection_limits_are_checked_before_member_parsing(field, limit):
    recipe = recipes.new_recipe()
    recipe[field] = [None] * (limit + 1)
    with pytest.raises(recipes.RecipeError, match="count exceeds its limit"):
        recipes.validate_recipe(recipe)


@pytest.mark.parametrize("budget", ["event", "checkpoint", "media", "bytes"])
def test_recorder_exhausted_budget_is_sealed_incomplete_without_accepting_late_events(tmp_path, monkeypatch, budget):
    recorder = recipes.SessionRecipeRecorder(tmp_path / "limit.jsonl")
    try:
        if budget == "event":
            monkeypatch.setattr(recipes, "MAX_EVENTS", 1)
            assert recorder.commit("stop", {}, at_ms=0)
            accepted = recorder.commit("stop", {}, at_ms=1)
        elif budget == "checkpoint":
            monkeypatch.setattr(recipes, "MAX_CHECKPOINTS", 1)
            assert recorder.checkpoint(at_ms=0)
            accepted = recorder.checkpoint(at_ms=1)
        elif budget == "media":
            monkeypatch.setattr(recipes, "MAX_MEDIA", 1)
            assert recorder.register_media("first", reference())
            accepted = recorder.register_media("second", reference())
        else:
            monkeypatch.setattr(recipes, "MAX_BYTES", recorder._bytes + 1024)
            accepted = recorder.commit("stop", {}, at_ms=0)
        assert not accepted
        assert recorder.status()["incomplete_reason"] == "limit"
        assert not recorder.commit("stop", {}, at_ms=2)
        assert not recorder.close()
        loaded = recipes.load_recipe(recorder.path)
        assert not loaded["complete"] and loaded["incomplete_reason"] == "limit"
        host = replay_host()
        with pytest.raises(recipes.ReplayBlocked, match="incomplete recipe"):
            recipes.RecipeReplayEngine(loaded, host).start()
        host.resolve.assert_not_called()
        host.restore.assert_not_called()
    finally:
        recorder.close()


@pytest.mark.parametrize("failure", ["restore", "apply", "buffering"])
def test_backend_failure_suspends_replay_with_safe_error_and_no_later_actions(failure):
    host = replay_host()
    clock = [0.0]
    replay = recipes.RecipeReplayEngine(playable_recipe(), host, clock=lambda: clock[0])
    if failure == "restore":
        host.restore.side_effect = OSError("private path or token")
        operation = replay.start
    else:
        replay.start()
        clock[0] = 1.5
        if failure == "apply":
            host.apply.side_effect = RuntimeError("private path or token")
        else:
            host.is_buffering.side_effect = RuntimeError("private path or token")
        operation = replay.tick
    with pytest.raises(recipes.ReplayBlocked, match="backend error") as caught:
        operation()
    assert "private" not in str(caught.value)
    assert replay.status == "paused" and replay.error_code == "backend_error"
    host.halt.assert_called_once()
    calls = list(host.mock_calls)
    clock[0] = 60
    assert replay.tick() == 0 and host.mock_calls == calls


def test_explicit_stop_during_buffering_freezes_position_and_prevents_delayed_replay_actions():
    host = replay_host()
    clock = [0.0]
    replay = recipes.RecipeReplayEngine(playable_recipe(), host, clock=lambda: clock[0])
    replay.start()
    clock[0] = .4
    host.is_buffering.return_value = True
    assert replay.tick() == 0
    clock[0] = 100
    replay.stop()
    assert replay.position_ms == 400 and replay.status == "stopped"
    host.is_buffering.return_value = False
    assert replay.tick() == 0
    host.apply.assert_not_called()
    host.halt.assert_called_once()


def service_fixture(tmp_path, lookup, *, capacity=128):
    playback = Mock()
    playback.snapshot.return_value = SimpleNamespace(state=PlaybackState.IDLE)
    guarded, queue_restores, queue_settings = Mock(), Mock(), Mock()
    service = SessionRecipeService(tmp_path / "recipes", playback=lambda: playback, lookup_media=lookup,
                                   restore_queue=queue_restores, configure_queue=queue_settings,
                                   set_replay_active=guarded, capacity=capacity)
    return service, playback, guarded, queue_restores, queue_settings


def test_closed_lazy_service_rejects_new_work_without_creating_storage_or_worker(tmp_path):
    lookup = Mock()
    service, playback, guarded, queues, settings = service_fixture(tmp_path, lookup)
    assert service.close() and service.close()
    with pytest.raises(recipes.RecipeError, match="closed"):
        service.start("later")
    with pytest.raises(recipes.RecipeError, match="closed"):
        service.replay("later")
    assert not service.capture_stop()
    assert service.stop_replay()
    assert service._worker is None and not service.directory.exists()
    assert not any(mock.mock_calls for mock in [lookup, playback, guarded, queues, settings])


@pytest.mark.parametrize("saturate", [False, True])
def test_shutdown_during_recording_preparation_is_bounded_and_rejects_late_capture(tmp_path, saturate):
    entered, release = threading.Event(), threading.Event()
    source = tmp_path / "local.wav"
    source.write_bytes(b"deterministic local bytes")
    media = MediaRef(MediaSource.LOCAL, str(source), duration=60)

    def lookup(_key):
        entered.set()
        assert release.wait(3)
        return media

    service, playback, guarded, queues, settings = service_fixture(tmp_path, lookup, capacity=1)
    try:
        service.start("interrupted", queue_ids=[media.stable_id])
        assert entered.wait(1)
        if saturate:
            assert service.capture_stop()
        before = time.monotonic()
        assert not service.close(.02)
        assert time.monotonic() - before < .5
        assert not service.capture_stop()
        assert not service.capture_playback_event(stable_id=media.stable_id, session_id="late", action="play",
                                                  play_kind="start", position_seconds=0, origin="cli")
    finally:
        release.set()
        assert service.close(2)
    assert service._worker is not None and not service._worker.is_alive()
    assert not list(service.directory.glob("*.jsonl"))
    assert service.status()["state"] == "failed"
    assert service.status()["error_code"] == "session_operation_failed"
    assert not any(mock.mock_calls for mock in [guarded, queues, settings])
    assert all(call[0] == "snapshot" for call in playback.mock_calls)
    assert source.read_bytes() == b"deterministic local bytes"


@pytest.mark.parametrize("operation", ["record", "replay"])
def test_service_worker_start_refusal_preserves_saved_recipe_and_allows_explicit_retry(tmp_path, monkeypatch, operation):
    service, playback, guarded, queues, settings = service_fixture(tmp_path, Mock())
    service.directory.mkdir()
    saved = service.directory / "saved.jsonl"
    payload = json.dumps(recipes.new_recipe()).encode()
    saved.write_bytes(payload)
    attempts = []
    original_start = threading.Thread.start

    def refuse(worker):
        if worker.name == "mariana-session-service":
            attempts.append(worker)
            raise RuntimeError("private operating-system diagnostic")
        return original_start(worker)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(threading.Thread, "start", refuse)
            with pytest.raises(recipes.RecipeError, match="worker could not start") as caught:
                if operation == "record":
                    service.start("new")
                else:
                    service.replay("saved")
            assert "private" not in str(caught.value)
            assert len(attempts) == 1 and not attempts[0].is_alive()
            assert service._worker is None and service.status()["pending"] == 0
            assert not service.status()["replay_active"]
            assert saved.read_bytes() == payload
            assert not (service.directory / "new.jsonl").exists()
            assert not any(mock.mock_calls for mock in [playback, guarded, queues, settings])
            service.status()
            assert len(attempts) == 1
        if operation == "record":
            service.start("new")
            assert service.stop()
            assert recipes.load_recipe(service.directory / "new.jsonl")["complete"]
        else:
            service.replay("saved")
            deadline = time.monotonic() + 2
            while service.status()["state"] not in {"completed", "failed"}:
                assert time.monotonic() < deadline
                time.sleep(.005)
            assert service.status()["state"] == "completed"
        assert saved.read_bytes() == payload
    finally:
        assert service.close()


def test_close_after_worker_start_refusal_does_not_join_an_unstarted_worker(tmp_path, monkeypatch):
    service, playback, _guarded, _queues, _settings = service_fixture(tmp_path, Mock())
    with monkeypatch.context() as patch:
        patch.setattr(threading.Thread, "start", Mock(side_effect=RuntimeError("thread unavailable")))
        with pytest.raises(recipes.RecipeError, match="worker could not start"):
            service.start("new")
    assert service.close() and service.close()
    assert service._worker is None and not service.directory.exists()
    assert not playback.mock_calls
