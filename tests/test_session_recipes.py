import copy
import json
import queue
import threading
import time
from collections.abc import Callable

import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.recipe_playback import ExistingPlaybackRecipeHost
from mariana.recipe_queue import flat_tree
from mariana.session_recipes import (
    MAX_BYTES,
    RecipeError,
    RecipeReplayEngine,
    ReplayBlocked,
    ResolvedRecipeMedia,
    SessionRecipeRecorder,
    canonical_media_reference,
    effective_state,
    fingerprint_file,
    inspect_recipe,
    load_recipe,
    new_recipe,
    validate_media_reference,
    validate_recipe,
)


def reference(identity="a", *, fingerprint="b", live=False, duration_ms=60_000):
    return {"source": "local", "stable_id": identity * 24,
            "fingerprint": fingerprint * 64 if fingerprint else None,
            "duration_ms": duration_ms, "live": live, "provider_id": None}


def recipe_with_events(*events):
    recipe = new_recipe(session_id="test-session", media={"a": reference(), "b": reference("c")})
    recipe["events"] = [
        {"seq": index, "at_ms": at_ms, "session_id": "test-session", "kind": kind, "reason": "manual",
         "data": ({"seed": None, **data, "queue_tree": flat_tree(data["queue"])}
                  if kind in {"queue_set", "shuffle"} else data)}
        for index, (at_ms, kind, data) in enumerate(events)
    ]
    recipe["duration_ms"] = max([0, *[event[0] for event in events]]) + 1000
    return recipe


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Host:
    capabilities = frozenset({"playback", "queue", "queue_settings", "gain_settings", "crossfade_settings", "overlap"})

    def __init__(self):
        self.calls = []
        self.buffering = False
        self.changed = False
        self.missing = False
        self.resolve_hook: Callable[[], None] | None = None

    def resolve(self, reference):
        self.calls.append(("resolve", copy.deepcopy(reference)))
        if self.resolve_hook:
            self.resolve_hook()
        if self.missing:
            raise OSError("private source path must never reach error projection")
        if self.changed:
            reference["fingerprint"] = "f" * 64
        return ResolvedRecipeMedia(reference["stable_id"], reference)

    def restore(self, state, resolved):
        self.calls.append(("restore", copy.deepcopy(state), resolved))

    def apply(self, event, state, resolved):
        self.calls.append(("apply", event, state, resolved))

    def halt(self):
        self.calls.append(("halt",))

    def is_buffering(self):
        return self.buffering


def test_reference_projection_never_exports_paths_or_resolver_secrets(tmp_path):
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "Private-name.mp3"),
                     title="Sensitive title", resolver_data={"Authorization": "Bearer SECRET"}, duration=12.25)
    result = canonical_media_reference(media, fingerprint="d" * 64)
    serialized = json.dumps(result)
    assert result["duration_ms"] == 12_250
    assert not any(secret in serialized for secret in ("Private-name", "SECRET", "Authorization", "Sensitive"))
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk&token=SECRET")
    result = canonical_media_reference(media)
    assert result["provider_id"] == "abcdefghijk"
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("extra", ["path", "url", "headers", "token", "cookie", "command", "download", "delete", "publish"])
def test_reference_and_envelope_reject_extra_authority(extra):
    ref = reference()
    ref[extra] = "private"
    with pytest.raises(RecipeError):
        validate_media_reference(ref)
    recipe = new_recipe()
    recipe[extra] = "private"
    with pytest.raises(RecipeError):
        validate_recipe(recipe)


@pytest.mark.parametrize("identity", ["C:\\private\\song.mp3", "/home/private", "https://host/?token=secret", "a\n", "token:value"])
def test_references_reject_noncanonical_identities(identity):
    ref = reference()
    ref["stable_id"] = identity
    with pytest.raises(RecipeError):
        validate_media_reference(ref)


@pytest.mark.parametrize("kind", ["delete", "download", "publish", "exec", "volume", "output_device", "unknown"])
def test_unknown_or_nonrecipe_operations_are_rejected(kind):
    with pytest.raises(RecipeError):
        validate_recipe(recipe_with_events((0, kind, {})))


@pytest.mark.parametrize("value", [True, -1, float("nan"), float("inf"), "1000", 2**64])
def test_times_are_strict_finite_bounded_integers(value):
    recipe = recipe_with_events((0, "media_start", {"media": "a", "position_ms": value}))
    with pytest.raises(RecipeError):
        validate_recipe(recipe)


def test_events_require_contiguous_sequence_same_session_and_monotonic_time():
    valid = recipe_with_events((100, "media_start", {"media": "a", "position_ms": 0}),
                               (200, "pause", {"position_ms": 100}))
    for field, value in [("seq", 5), ("session_id", "foreign-session"), ("at_ms", 99)]:
        recipe = copy.deepcopy(valid)
        recipe["events"][1][field] = value
        with pytest.raises(RecipeError):
            validate_recipe(recipe)


def test_state_fold_preserves_pauses_seek_and_full_settings():
    recipe = recipe_with_events(
        (0, "media_start", {"media": "a", "position_ms": 5000}),
        (1000, "queue_set", {"queue": ["a", "b", "a"], "current_index": 0}),
        (2000, "pause", {"position_ms": 7000}),
        (3000, "queue_settings", {"repeat": "all", "consume": True, "autofill": False}),
        (4000, "seek", {"position_ms": 20_000}),
        (5000, "resume", {"position_ms": 20_000}),
        (5500, "gain_settings", {"enabled": True, "mode": "album", "preamp_db": -4, "prevent_clipping": False}),
        (6000, "shuffle", {"queue": ["a", "a", "b"], "current_index": 0, "seed": 42}),
    )
    state = effective_state(recipe, 4500)
    assert not state["playing"] and state["position_ms"] == 20_000
    state = effective_state(recipe, 6500)
    assert state["position_ms"] == 21_500
    assert state["queue"] == ["a", "a", "b"] and state["shuffle_seed"] == 42
    assert state["settings"]["repeat"] == "all"
    assert state["settings"]["replaygain"]["preamp_db"] == -4


def test_shuffle_records_realized_order_and_seed_not_python_random_implementation():
    recipe = recipe_with_events(
        (0, "queue_set", {"queue": ["a", "b", "a"], "current_index": 0}),
        (100, "shuffle", {"queue": ["a", "a", "b"], "current_index": 0, "seed": 123}),
    )
    assert effective_state(recipe, 500)["queue"] == ["a", "a", "b"]
    recipe["events"][1]["data"]["queue"] = ["a", "b"]
    recipe["events"][1]["data"]["queue_tree"] = flat_tree(["a", "b"])
    with pytest.raises(RecipeError, match="occurrences"):
        validate_recipe(recipe)


def test_checkpoints_are_verified_against_history_and_seek_folds_only_state():
    recipe = recipe_with_events((0, "media_start", {"media": "a", "position_ms": 0}),
                               (1000, "pause", {"position_ms": 1000}),
                               (3000, "resume", {"position_ms": 1000}))
    checkpoint_state = effective_state(recipe, 2000)
    recipe["checkpoints"] = [{"at_ms": 2000, "event_index": 2, "state": checkpoint_state}]
    assert effective_state(recipe, 3500)["position_ms"] == 1500
    host = Host()
    replay = RecipeReplayEngine(recipe, host)
    replay.seek(3500)
    assert [call[0] for call in host.calls] == ["resolve", "restore"]
    assert host.calls[-1][1]["position_ms"] == 1500
    recipe["checkpoints"][0]["state"]["position_ms"] = 9999
    with pytest.raises(RecipeError, match="effective state"):
        validate_recipe(recipe)


def test_overlap_offsets_envelope_progress_and_pause_are_preserved():
    recipe = recipe_with_events(
        (0, "media_start", {"media": "a", "position_ms": 10_000}),
        (1000, "transition", {"incoming": "b", "incoming_position_ms": 500, "duration_ms": 4000,
                              "progress_ms": 0, "outgoing_gain_db": -3, "incoming_gain_db": -6}),
        (2000, "pause", {"position_ms": 12_000}),
        (4000, "resume", {"position_ms": 12_000}),
    )
    recipe["duration_ms"] = 8000
    frozen = effective_state(recipe, 3500)
    assert frozen["position_ms"] == 12_000
    assert frozen["overlap"]["progress_ms"] == 1000
    assert frozen["overlap"]["incoming_position_ms"] == 1500
    recipe["checkpoints"] = [{"at_ms": 3500, "event_index": 3, "state": frozen}]
    state = effective_state(recipe, 4500)
    assert state["overlap"]["progress_ms"] == 1500
    assert state["overlap"]["incoming_position_ms"] == 2000
    state = effective_state(recipe, 7500)
    assert state["media"] == "b" and state["overlap"] is None
    assert state["position_ms"] == 5000


def test_unsupported_overlap_fails_before_backend_restore():
    recipe = recipe_with_events((0, "crossfade_settings", {"crossfade_ms": 2000}))
    host = Host()
    host.capabilities -= {"overlap"}
    with pytest.raises(ReplayBlocked, match="unsupported overlap"):
        RecipeReplayEngine(recipe, host).start()
    assert host.calls == [("halt",)]


@pytest.mark.parametrize("failure,code", [("missing", "missing_source"), ("changed", "changed_source")])
def test_missing_or_changed_sources_pause_without_substitution(failure, code):
    host = Host()
    setattr(host, failure, True)
    replay = RecipeReplayEngine(recipe_with_events((0, "media_start", {"media": "a", "position_ms": 0})), host)
    with pytest.raises(ReplayBlocked) as error:
        replay.start()
    assert error.value.code == code
    assert replay.status == "paused" and replay.error_code == code
    assert not any(call[0] == "restore" for call in host.calls)
    assert "private" not in str(error.value)


def test_source_duration_changes_and_absent_fingerprint_are_not_silent():
    recipe = recipe_with_events((0, "media_start", {"media": "a", "position_ms": 0}))
    recipe["media"]["a"]["fingerprint"] = None
    host = Host()
    with pytest.raises(ReplayBlocked, match="unverified local source"):
        RecipeReplayEngine(recipe, host).start()
    assert host.calls == [("halt",)]
    recipe["media"]["a"]["live"] = True
    with pytest.raises(ReplayBlocked, match="live source requires archive"):
        RecipeReplayEngine(recipe, host).start()


def test_scheduler_order_buffers_and_rebases_synchronous_preparation_time():
    clock, host = Clock(), Host()
    recipe = recipe_with_events((0, "media_start", {"media": "a", "position_ms": 0}),
                               (1000, "pause", {"position_ms": 1000}),
                               (2000, "resume", {"position_ms": 1000}),
                               (3000, "seek", {"position_ms": 15_000}))
    replay = RecipeReplayEngine(recipe, host, clock=clock)
    replay.start()
    clock.advance(.5)
    replay.set_buffering(True)
    host.buffering = True
    clock.advance(20)
    assert replay.tick() == 0 and replay.position_ms == 500
    host.buffering = False
    replay.set_buffering(False)
    clock.advance(.5)
    host.resolve_hook = lambda: clock.advance(4)
    assert replay.tick() == 1
    assert replay.position_ms == 1000
    assert replay.tick() == 0
    clock.advance(1)
    assert replay.tick() == 1
    assert [call[1]["kind"] for call in host.calls if call[0] == "apply"] == ["pause", "resume"]
    clock.advance(2)
    assert replay.tick() == 1
    assert replay.status == "completed" and host.calls[-1] == ("halt",)


def test_tick_budget_preserves_equal_timestamp_order_and_excludes_skipped_history():
    recipe = recipe_with_events((0, "media_start", {"media": "a", "position_ms": 0}),
                               (1000, "pause", {"position_ms": 1000}),
                               (1000, "seek", {"position_ms": 5000}),
                               (1000, "resume", {"position_ms": 5000}))
    clock, host = Clock(), Host()
    replay = RecipeReplayEngine(recipe, host, clock=clock)
    replay.start()
    clock.advance(1)
    assert replay.tick(max_events=1) == 1
    assert replay.tick(max_events=1) == 1
    assert replay.tick(max_events=1) == 1
    assert [call[1]["kind"] for call in host.calls if call[0] == "apply"] == ["pause", "seek", "resume"]


def test_async_recorder_roundtrip_buffers_and_checkpoint(tmp_path):
    clock = Clock()
    path = tmp_path / "session.jsonl"
    recorder = SessionRecipeRecorder(path, clock=clock)
    assert recorder.register_media("a", reference())
    assert recorder.commit("media_start", {"media": "a", "position_ms": 1000})
    clock.advance(1)
    recorder.set_buffering(True)
    clock.advance(30)
    recorder.set_buffering(False)
    assert recorder.checkpoint()
    clock.advance(1)
    assert recorder.commit("pause", {"position_ms": 3000})
    assert recorder.close()
    recipe = load_recipe(path)
    assert recipe["complete"] and recipe["duration_ms"] == 2000
    assert len(recipe["checkpoints"]) == 1
    assert effective_state(recipe, 2000)["position_ms"] == 3000
    assert not recorder.commit("stop", {})
    assert "unsealed" not in str(inspect_recipe(recipe))


def test_recorded_data_is_copied_and_media_identity_cannot_be_replaced(tmp_path):
    recorder = SessionRecipeRecorder(tmp_path / "session.jsonl", media={"a": reference()})
    data = {"media": "a", "position_ms": 0}
    assert recorder.commit("media_start", data, at_ms=0)
    data["position_ms"] = 9000
    with pytest.raises(RecipeError, match="replaced"):
        recorder.register_media("a", reference("c"))
    assert recorder.close()
    assert load_recipe(recorder.path)["events"][0]["data"]["position_ms"] == 0


def test_overflow_is_nonblocking_and_permanently_incomplete(tmp_path, monkeypatch):
    recorder = SessionRecipeRecorder(tmp_path / "overflow.jsonl", media={"a": reference()})

    def full(_value):
        raise queue.Full

    monkeypatch.setattr(recorder._pending, "put_nowait", full)
    before = time.monotonic()
    assert not recorder.commit("media_start", {"media": "a", "position_ms": 0})
    assert time.monotonic() - before < .2
    assert not recorder.close()
    recipe = load_recipe(recorder.path)
    assert not recipe["complete"] and recipe["incomplete_reason"] == "overflow"
    assert recipe["events"] == []
    with pytest.raises(ReplayBlocked, match="incomplete recipe"):
        RecipeReplayEngine(recipe, Host()).start()


def test_invalid_committed_event_marks_session_incomplete(tmp_path):
    recorder = SessionRecipeRecorder(tmp_path / "invalid.jsonl")
    assert not recorder.commit("delete", {"path": "private"})
    assert not recorder.close()
    assert load_recipe(recorder.path)["incomplete_reason"] == "invalid_event"
    assert "private" not in recorder.path.read_text()


def test_recorder_refuses_clobber_and_reports_persistence_failure(tmp_path, monkeypatch):
    path = tmp_path / "existing.jsonl"
    path.write_text("existing data")
    with pytest.raises(RecipeError, match="could not be created"):
        SessionRecipeRecorder(path)
    assert path.read_text() == "existing data"


def test_close_is_bounded_and_unsealed_journal_is_not_replayable(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    recorder = SessionRecipeRecorder(tmp_path / "bounded.jsonl", media={"a": reference()})
    original_get = recorder._pending.get

    def blocked_get(*args, **kwargs):
        item = original_get(*args, **kwargs)
        entered.set()
        release.wait(2)
        return item

    monkeypatch.setattr(recorder._pending, "get", blocked_get)
    assert recorder.commit("media_start", {"media": "a", "position_ms": 0})
    # A first get may already be waiting; a second event reliably reaches the hook.
    assert recorder.commit("pause", {"position_ms": 0})
    assert entered.wait(1)
    before = time.monotonic()
    assert not recorder.close(.01)
    assert time.monotonic() - before < .2
    release.set()
    recorder.close(1)
    assert load_recipe(recorder.path)["incomplete_reason"] == "shutdown_timeout"


def test_load_rejects_duplicate_json_fields_unknown_records_and_oversize(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text('{"format":"mariana-session-recipe","format":"evil"}')
    with pytest.raises(RecipeError):
        load_recipe(path)
    path.write_bytes(b" " * (MAX_BYTES + 1))
    with pytest.raises(RecipeError, match="byte limit"):
        load_recipe(path)
    path.write_text('{"type":"exec","value":{}}\n')
    with pytest.raises(RecipeError, match="header"):
        load_recipe(path)


def test_unsealed_journal_and_readonly_inspection(tmp_path):
    recipe = new_recipe()
    recipe.update(complete=False, incomplete_reason="unsealed")
    path = tmp_path / "unsealed.jsonl"
    path.write_text(json.dumps({"type": "header", "value": recipe}) + "\n")
    loaded = load_recipe(path)
    assert loaded["incomplete_reason"] == "unsealed"
    report = inspect_recipe(loaded)
    assert not report["availability_checked"]
    assert not report["complete"]
    assert path.read_text().count("\n") == 1


def test_fingerprint_changes_with_content_without_exporting_filename(tmp_path):
    path = tmp_path / "private.wav"
    path.write_bytes(b"first")
    original = fingerprint_file(path)
    path.write_bytes(b"other")
    assert len(original) == 64 and fingerprint_file(path) != original


def test_live_projection_retains_nonreplayable_status():
    media = MediaRef(MediaSource.RADIO, "https://radio.invalid/private?token=SECRET",
                     capabilities=MediaCapabilities(live=True, finite=False))
    ref = canonical_media_reference(media)
    assert ref["live"] and "SECRET" not in json.dumps(ref)


def test_host_reports_uncaptured_operation_as_incomplete(tmp_path):
    recorder = SessionRecipeRecorder(tmp_path / "unsupported.jsonl")
    recorder.mark_incomplete()
    assert not recorder.commit("stop", {})
    assert not recorder.close()
    assert load_recipe(recorder.path)["incomplete_reason"] == "unsupported_operation"


def test_malformed_unsealed_event_is_validation_error_not_attribute_error(tmp_path):
    header = new_recipe()
    header.update(complete=False, incomplete_reason="unsealed")
    path = tmp_path / "malformed.jsonl"
    path.write_text(json.dumps({"type": "header", "value": header}) + '\n{"type":"event","value":7}\n')
    with pytest.raises(RecipeError):
        load_recipe(path)


def test_retry_of_late_failed_event_returns_to_failure_boundary():
    recipe = recipe_with_events((0, "media_start", {"media": "a", "position_ms": 0}),
                               (1000, "media_start", {"media": "b", "position_ms": 0}))
    clock, host = Clock(), Host()
    replay = RecipeReplayEngine(recipe, host, clock=clock)
    replay.start()
    host.missing = True
    clock.advance(2)
    with pytest.raises(ReplayBlocked):
        replay.tick()
    assert replay.position_ms == 1000


def test_existing_backend_adapter_uses_public_authority_and_explicit_queue_hooks():
    class Playback:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            return lambda *args, **kwargs: self.calls.append((name, args, kwargs))

    playback = Playback()
    queue_calls, guard_calls = [], []
    host = ExistingPlaybackRecipeHost(
        playback, resolve=lambda ref: ResolvedRecipeMedia("resolved", ref),
        restore_queue=lambda state, resolved: queue_calls.append((state, resolved)),
        configure_queue=lambda settings: queue_calls.append(settings), set_replay_active=guard_calls.append,
    )
    recipe = recipe_with_events((0, "media_start", {"media": "a", "position_ms": 0}),
                               (1000, "pause", {"position_ms": 1000}))
    replay = RecipeReplayEngine(recipe, host)
    replay.seek(1500)
    names = [call[0] for call in playback.calls]
    assert names == ["clear_prefetch", "stop", "configure_replaygain", "set_crossfade_seconds", "play"]
    play = playback.calls[-1]
    assert play[1] == ("resolved",) and play[2]["start_at"] == 1
    assert play[2]["start_paused"] is True
    assert guard_calls == [True] and len(queue_calls) == 2
    host.halt()
    assert guard_calls == [True, False]
    assert playback.calls[-1][0] == "stop"


def test_adapter_restores_committed_shuffle_without_reexecuting_randomness():
    class Playback:
        def configure_replaygain(self, **kwargs):
            raise AssertionError("Shuffle must not change gain")

    queues = []
    host = ExistingPlaybackRecipeHost(
        Playback(), resolve=lambda ref: ResolvedRecipeMedia("resolved", ref),
        restore_queue=lambda state, resolved: queues.append(state["queue"]),
        configure_queue=lambda settings: None, set_replay_active=lambda active: None,
    )
    recipe = recipe_with_events((0, "queue_set", {"queue": ["a", "b", "a"], "current_index": 0}),
                               (1000, "shuffle", {"queue": ["a", "a", "b"], "current_index": 0, "seed": 7}))
    host.apply(recipe["events"][-1], effective_state(recipe, 1500), {})
    assert queues == [["a", "a", "b"]]


def test_fingerprint_can_be_cancelled_or_deadline_bounded(tmp_path):
    path = tmp_path / "bounded.wav"
    path.write_bytes(b"synthetic")
    with pytest.raises(RecipeError, match="cancelled or timed out"):
        fingerprint_file(path, cancelled=lambda: True)
    with pytest.raises(RecipeError, match="cancelled or timed out"):
        fingerprint_file(path, deadline=time.monotonic() - 1)


def test_adapter_resolves_current_controller_provider():
    first, second = object(), object()
    current = [first]
    host = ExistingPlaybackRecipeHost(
        lambda: current[0], resolve=lambda ref: ResolvedRecipeMedia(None, ref),
        restore_queue=lambda state, resolved: None, configure_queue=lambda settings: None,
        set_replay_active=lambda active: None,
    )
    assert host.playback is first
    current[0] = second
    assert host.playback is second


def test_replay_only_revalidates_sources_needed_by_each_committed_event():
    recipe = recipe_with_events(
        (0, "queue_set", {"queue": ["a", "b"], "current_index": 0}),
        (0, "media_start", {"media": "a", "position_ms": 0}),
        (1000, "pause", {"position_ms": 1000}),
        (2000, "resume", {"position_ms": 1000}),
        (3000, "media_start", {"media": "b", "position_ms": 0}),
        (4000, "seek", {"position_ms": 10_000}),
    )
    clock, host = Clock(), Host()
    replay = RecipeReplayEngine(recipe, host, clock=clock)
    replay.start()
    assert len([call for call in host.calls if call[0] == "resolve"]) == 2
    host.calls.clear()
    clock.advance(2)
    assert replay.tick() == 2
    assert not any(call[0] == "resolve" for call in host.calls)
    host.calls.clear()
    clock.advance(1)
    replay.tick()
    assert [call[1]["stable_id"] for call in host.calls if call[0] == "resolve"] == ["c" * 24]
    host.calls.clear()
    clock.advance(1)
    host.changed = True
    with pytest.raises(ReplayBlocked, match="changed source"):
        replay.tick()
    assert [call[1]["stable_id"] for call in host.calls if call[0] == "resolve"] == ["c" * 24]
    assert not any(call[0] == "apply" for call in host.calls)
