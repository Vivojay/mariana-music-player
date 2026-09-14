"""Application-facing local recipe service with explicit committed-event hooks.

Capture hooks enqueue compact identities only. Catalog lookup, local hashing,
file IO, and recipe replay run on one bounded serial service worker. The sole
audio authority remains the application's existing PlaybackController.
"""

from __future__ import annotations

import copy
import queue
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from .models import MediaSource
from .recipe_mix import CommittedOverlap, CommittedProgramEvent
from .recipe_playback import ExistingPlaybackRecipeHost
from .recipe_queue import MAX_INTEGER, MIN_INTEGER, GroupIdentityMap, flat_tree, validate_tree
from .recipe_sources import prepare_online_recipe_source
from .session_recipes import (
    FROZEN_GAIN_VERSION,
    MAX_QUEUE,
    RecipeError,
    RecipeReplayEngine,
    ReplayBlocked,
    ResolvedRecipeMedia,
    SessionRecipeRecorder,
    _integer,
    _key,
    _number,
    canonical_media_reference,
    default_settings,
    fingerprint_file,
    initial_state,
    inspect_recipe,
    load_recipe,
)


class SessionRecipeService:
    """Lazy local recorder and serialized replay; no polling-based event inference.

    The root must guard every competing playback/queue/program-setting mutation
    while replay_active is true. Stop/retry remain explicitly available.
    """

    def __init__(self, directory: str | Path, *, playback: Any, lookup_media: Callable[[str], Any],
                 restore_queue: Callable[[dict, dict[str, object]], None], configure_queue: Callable[[dict], None],
                 set_replay_active: Callable[[bool], None], clock: Callable[[], float] = time.monotonic,
                 capacity: int = 128) -> None:
        self.directory = Path(directory)
        self._playback = playback
        self._lookup_media = lookup_media
        self._set_replay_active_callback = set_replay_active
        self._clock = clock
        self._pending: queue.Queue[tuple[str, Any, int, threading.Event | None]] = queue.Queue(
            maxsize=_integer(capacity, 1024, "service capacity", 1),
        )
        self._lock = threading.Lock()
        self._closing = threading.Event()
        self._worker: threading.Thread | None = None
        self._recorder: SessionRecipeRecorder | None = None
        self._replay: RecipeReplayEngine | None = None
        self._state = "idle"
        self._error: str | None = None
        self._name: str | None = None
        self._origin = clock()
        self._buffering_at: float | None = None
        self._buffered_seconds = 0.0
        self._replay_active = False
        self._stop_recording_requested = False
        self._last_recording: dict | None = None
        self._last_at_ms = 0
        self._current_media_id: str | None = None
        self._playback_session_id: str | None = None
        self._last_queue: dict | None = None
        self._group_ids = GroupIdentityMap()
        self._cancel_replay = threading.Event()
        self._cancel_preparation = threading.Event()
        self._operation_deadline: float | None = None
        self._capture_version = 2
        self._capture_loss = False
        self._host = ExistingPlaybackRecipeHost(
            playback, resolve=self._resolve, restore_queue=restore_queue,
            configure_queue=configure_queue, set_replay_active=self._set_replay_active,
            cancelled=lambda: self._cancel_replay.is_set() or self._closing.is_set(),
        )

    def _path(self, name: str) -> Path:
        return self.directory / (_key(name, "recipe name") + ".jsonl")

    def _ensure_worker(self) -> None:
        if self._closing.is_set():
            raise RecipeError("Session service is closed")
        if self._worker is None:
            try:
                worker = threading.Thread(target=self._run, name="mariana-session-service", daemon=True)
                worker.start()
            except RuntimeError:
                raise RecipeError("Session worker could not start; retry the requested operation") from None
            # The caller holds the state lock and has not queued work or claimed
            # replay authority yet. Only a started worker is safe to retain/join.
            self._worker = worker

    def _time_ms(self) -> int:
        now = self._buffering_at if self._buffering_at is not None else self._clock()
        return max(0, round((now - self._origin - self._buffered_seconds) * 1000))

    def _queue(self, kind: str, payload: Any, *, completed: threading.Event | None = None) -> bool:
        with self._lock:
            return self._enqueue_locked(kind, payload, completed)

    def _enqueue_locked(self, kind: str, payload: Any, completed: threading.Event | None = None) -> bool:
        if self._closing.is_set():
            return False
        try:
            self._pending.put_nowait((kind, payload, self._time_ms(), completed))
            return True
        except queue.Full:
            self._error = "overflow"
            if self._recorder is not None:
                self._recorder.mark_incomplete("overflow")
            return False

    @staticmethod
    def _queue_ids(values: Iterable[str]) -> list[str]:
        result = []
        for value in values:
            if len(result) >= MAX_QUEUE:
                raise RecipeError("Queue exceeds its limit")
            result.append(_key(value, "catalog identity"))
        return result

    def start(self, name: str, *, initial_media_id: str | None = None, position_ms: int = 0, playing: bool = False,
              queue_ids: Iterable[str] = (), current_index: int | None = None, settings: dict | None = None,
              initial_playback_session_id: str | None = None, queue_snapshot: dict | None = None) -> dict:
        self._path(name)
        settings = copy.deepcopy(settings if settings is not None else default_settings())
        initial_state(settings)  # Validate settings before claiming recording intent.
        native_capture = callable(getattr(type(self._host.playback), 'begin_recipe_capture', None))
        if settings["crossfade_ms"] and not native_capture:
            raise RecipeError("Recording with overlap is not supported by this host")
        ids = self._queue_ids(queue_ids)
        group_ids = GroupIdentityMap()
        if queue_snapshot is not None:
            if ids or current_index is not None:
                raise RecipeError("Supply one committed queue snapshot, not conflicting flat queue arguments")
            queue_state = group_ids.project(queue_snapshot)
            ids, current_index = queue_state["queue"], queue_state["current_index"]
        else:
            queue_state = {"queue": ids, "current_index": current_index, "seed": None, "queue_tree": flat_tree(ids)}
        if initial_media_id is not None:
            _key(initial_media_id, "catalog identity")
        if initial_playback_session_id is not None:
            _key(initial_playback_session_id, "playback session")
        payload = {"name": name, "media": initial_media_id, "position_ms": position_ms, "playing": playing,
                   "queue": ids, "current_index": current_index, "settings": settings,
                   "playback_session_id": initial_playback_session_id, "queue_tree": queue_state["queue_tree"],
                   "shuffle_seed": queue_state["seed"]}
        with self._lock:
            if self._state in {"preparing", "recording", "stopping", "replay_preparing", "replaying"}:
                raise RecipeError("A session operation is already active")
            self._ensure_worker()
            self._state, self._error, self._name = "preparing", None, name
            self._origin, self._buffered_seconds, self._buffering_at = self._clock(), 0.0, None
            self._stop_recording_requested = False
            self._cancel_preparation.clear()
            self._last_queue = copy.deepcopy(queue_state)
            self._group_ids = group_ids
            self._capture_version = FROZEN_GAIN_VERSION if native_capture else 2
            self._capture_loss = False
            if not native_capture and not self._enqueue_locked("start", payload):
                self._state = "failed"
                raise RecipeError("Session service queue is full")
        if native_capture:
            try:
                def initialize(event: CommittedProgramEvent) -> None:
                    if event.stable_id != initial_media_id or event.session_id != initial_playback_session_id:
                        raise RecipeError('Current media changed before recording could start; retry')
                    payload.update(position_ms=round(event.position_seconds * 1000), playing=event.playing,
                                   program_gain_db=event.program_gain_db, overlap=self._overlap_payload(event.overlap))
                    if not self._queue('start', payload):
                        raise RecipeError('Session service queue is full')

                self._host.playback.begin_recipe_capture(self.capture_program_event, initialize)
            except Exception:
                with self._lock:
                    self._state = 'failed'
                raise
        return self.status()

    @staticmethod
    def _overlap_payload(overlap: CommittedOverlap | None) -> dict | None:
        if overlap is None:
            return None
        from .playback import SAMPLE_RATE

        duration = max(1, round(overlap.duration_frames * 1000 / SAMPLE_RATE))
        return {
            'incoming': overlap.incoming_id, 'incoming_position_ms': round(overlap.incoming_position_seconds * 1000),
            'duration_ms': duration, 'progress_ms': min(duration - 1, round(overlap.elapsed_frames * 1000 / SAMPLE_RATE)),
            'outgoing_gain_db': overlap.outgoing_gain_db, 'incoming_gain_db': overlap.incoming_gain_db,
        }

    def capture_program_event(self, event: CommittedProgramEvent) -> bool:
        """Typed committed state; no resolver, hashing, persistence, or log parsing."""
        if self._state not in {'preparing', 'recording'} or self._stop_recording_requested or self._closing.is_set():
            return False
        if not self._lock.acquire(blocking=False):
            self._capture_loss = True
            return False
        try:
            if self._state not in {'preparing', 'recording'} or self._stop_recording_requested:
                return False
            kind = 'program' if isinstance(event, CommittedProgramEvent) and event.action != 'unsupported' else 'unsupported'
            try:
                self._pending.put_nowait((kind, event if kind == 'program' else None, self._time_ms(), None))
                return True
            except queue.Full:
                # The callback must not acquire recorder/writer locks to report
                # loss. The worker and final seal consume this sticky flag.
                self._capture_loss = True
                return False
        finally:
            self._lock.release()

    def _capture(self, kind: str, payload: Any) -> bool:
        with self._lock:
            active = self._state in {"preparing", "recording"} and not self._stop_recording_requested
            return self._enqueue_locked(kind, payload) if active else False

    def capture_playback_event(self, **event: Any) -> bool:
        """Direct multicast target for the existing committed playback-event sink."""
        if self._capture_version >= FROZEN_GAIN_VERSION:
            return False  # The typed backend capture is authoritative; never duplicate analytics multicast.
        try:
            payload = {key: event.get(key) for key in (
                "stable_id", "session_id", "action", "origin", "position_seconds", "play_kind",
            )}
            _key(payload["stable_id"], "catalog identity")
            _key(payload["session_id"], "playback session")
            _number(payload["position_seconds"], 0, 31 * 86400, "event position")
            if payload["action"] not in {"play", "pause", "seek"}:
                return self.mark_unsupported()
            return self._capture("playback", payload)
        except (RecipeError, TypeError, ValueError):
            return self.mark_unsupported()

    def capture_stop(self, *, reason: str = "manual") -> bool:
        return self._capture("commit", ("stop", {}, reason))

    def capture_queue(self, queue_ids: Iterable[str], current_index: int | None, *, shuffle_seed: int | None = None) -> bool:
        ids = self._queue_ids(queue_ids)
        payload = {"queue": ids, "current_index": current_index, "seed": shuffle_seed, "queue_tree": flat_tree(ids)}
        with self._lock:
            return self._capture_queue_locked(payload)

    def capture_queue_snapshot(self, snapshot: dict) -> bool:
        """Project one committed transaction snapshot before asynchronous capture."""
        with self._lock:
            if self._state not in {"preparing", "recording"} or self._stop_recording_requested:
                return False
            return self._capture_queue_locked(self._group_ids.project(snapshot))

    def _capture_queue_locked(self, payload: dict) -> bool:
        if self._state not in {"preparing", "recording"} or self._stop_recording_requested:
            return False
        validate_tree(payload["queue_tree"], payload["queue"])
        if payload["current_index"] is not None:
            _integer(payload["current_index"], len(payload["queue"]) - 1, "queue current index")
        if payload["seed"] is not None:
            _integer(payload["seed"], MAX_INTEGER, "shuffle seed", MIN_INTEGER)
        if payload == self._last_queue:
            return True
        previous = self._last_queue
        event_kind = "shuffle" if previous is not None and payload["seed"] is not None \
            and Counter(payload["queue"]) == Counter(previous["queue"]) \
            and (payload["queue"] != previous["queue"] or payload["seed"] != previous["seed"]) else "queue_set"
        if not self._enqueue_locked("queue", {**copy.deepcopy(payload), "event_kind": event_kind}):
            return False
        self._last_queue = copy.deepcopy(payload)
        return True

    def capture_settings(self, kind: str, data: dict) -> bool:
        if kind not in {"queue_settings", "gain_settings", "crossfade_settings"}:
            return self.mark_unsupported()
        if kind == "crossfade_settings" and data.get("crossfade_ms") != 0 and self._capture_version < FROZEN_GAIN_VERSION:
            return self.mark_unsupported()
        if kind == 'gain_settings' and self._capture_version >= FROZEN_GAIN_VERSION:
            data = {**data, 'program_gain_db': self._host.playback.recipe_capture_snapshot().program_gain_db}
        return self._capture("commit", (kind, copy.deepcopy(data), "manual"))

    def mark_unsupported(self) -> bool:
        return self._capture("unsupported", None)

    def set_buffering(self, buffering: bool) -> None:
        if type(buffering) is not bool:
            raise RecipeError("Buffering must be true or false")
        with self._lock:
            now = self._clock()
            changed = False
            if buffering and self._buffering_at is None:
                self._buffering_at = now
                changed = True
            elif not buffering and self._buffering_at is not None:
                self._buffered_seconds += max(0, now - self._buffering_at)
                self._buffering_at = None
                changed = True
        # Replay-clock changes are also serialized with the existing backend.
        if self._replay_active and changed:
            self._queue("replay_buffering", buffering)

    def stop(self, timeout: float = 2.0) -> bool:
        timeout = _number(timeout, 0, 30, "stop timeout")
        with self._lock:
            if self._state not in {"preparing", "recording", "stopping"} and self._recorder is None:
                return self._last_recording is not None and self._last_recording.get("complete", False)
            self._stop_recording_requested = True
            self._state = "stopping"
        done = threading.Event()
        if not self._queue("stop_recording", None, completed=done) or not done.wait(timeout):
            self._cancel_preparation.set()
            with self._lock:
                self._error = self._error or "shutdown_timeout"
                if self._recorder is not None:
                    self._recorder.mark_incomplete("shutdown_timeout")
            return False
        with self._lock:
            return self._last_recording is not None and self._last_recording.get("complete", False)

    def inspect(self, name: str) -> dict:
        return inspect_recipe(load_recipe(self._path(name)))

    def replay(self, name: str, *, at_ms: int = 0) -> dict:
        self._path(name)
        with self._lock:
            if self._state in {"preparing", "recording", "stopping", "replay_preparing", "replaying"}:
                raise RecipeError("A session operation is already active")
            self._ensure_worker()
            self._state, self._error, self._name = "replay_preparing", None, name
            self._replay_active = True
            self._cancel_replay.clear()
            self._cancel_preparation.clear()
            self._replay = None
        # Guard immediately, including resolution time before the first restore.
        self._set_replay_active_callback(True)
        if not self._queue("replay", {"name": name, "at_ms": at_ms}):
            self._set_replay_active(False)
            raise RecipeError("Session service queue is full")
        return self.status()

    def seek_replay(self, at_ms: int, *, active_only: bool = False) -> dict:
        """Queue an effective-state restore on the same serial replay worker."""
        with self._lock:
            if active_only and not self._replay_active:
                raise RecipeError("Start session replay before seeking; use session play to confirm replacement")
            if self._replay is None or self._state in {"preparing", "recording", "stopping", "replay_preparing"}:
                raise RecipeError("No prepared recipe is available to seek")
            _integer(at_ms, self._replay.recipe["duration_ms"], "replay position")
            self._state, self._error = "replay_preparing", None
            self._replay_active = True
            self._cancel_replay.clear()
            self._cancel_preparation.clear()
        self._set_replay_active_callback(True)
        if not self._queue("seek_replay", at_ms):
            self._set_replay_active(False)
            raise RecipeError("Session service queue is full")
        return self.status()

    def stop_replay(self, timeout: float = 2.0) -> bool:
        timeout = _number(timeout, 0, 30, "stop timeout")
        done = threading.Event()
        if not self._replay_active:
            return True
        self._cancel_replay.set()
        return self._queue("stop_replay", None, completed=done) and done.wait(timeout)

    def status(self) -> dict:
        with self._lock:
            return {"state": self._state, "name": self._name, "error_code": self._error or ('overflow' if self._capture_loss else None),
                    "replay_active": self._replay_active, "pending": self._pending.qsize(),
                    "capacity": self._pending.maxsize,
                    "recording": self._recorder.status() if self._recorder is not None else None,
                    "last_recording": copy.deepcopy(self._last_recording),
                    "replay_position_ms": self._replay.position_ms if self._replay else None}

    def _set_replay_active(self, active: bool) -> None:
        if active and self._cancel_replay.is_set():
            raise ReplayBlocked("replay_cancelled")
        with self._lock:
            self._replay_active = active
        self._set_replay_active_callback(active)

    def _media(self, stable_id: str) -> tuple[Any, dict]:
        media = self._lookup_media(stable_id)
        if media is None or media.stable_id != stable_id:
            raise ReplayBlocked("missing_source")
        if media.capabilities.live or not media.capabilities.finite or not media.capabilities.seekable:
            raise ReplayBlocked("live_source_requires_archive")
        if media.resolver_data.get("play_region"):
            raise ReplayBlocked("unsupported_play_region")
        fingerprint = fingerprint_file(
            media.original_uri,
            cancelled=lambda: self._closing.is_set() or self._cancel_preparation.is_set()
            or (self._replay_active and self._cancel_replay.is_set()),
            deadline=self._operation_deadline,
        ) if media.source == MediaSource.LOCAL else None
        return media, canonical_media_reference(media, fingerprint=fingerprint)

    def _resolve(self, reference: dict) -> ResolvedRecipeMedia:
        if self._cancel_replay.is_set():
            raise ReplayBlocked("replay_cancelled")
        media, actual = self._media(reference["stable_id"])
        if media.source != MediaSource.LOCAL:
            prepared, actual = prepare_online_recipe_source(
                media, reference, self._host.playback.resolvers,
                cancelled=lambda: self._cancel_replay.is_set() or self._closing.is_set(),
                deadline=self._operation_deadline,
            )
            return ResolvedRecipeMedia(prepared, actual)
        if self._cancel_replay.is_set():
            raise ReplayBlocked("replay_cancelled")
        return ResolvedRecipeMedia(media, actual)

    def _register(self, stable_id: str) -> None:
        assert self._recorder is not None
        _, ref = self._media(stable_id)
        if not self._recorder.register_media(stable_id, ref):
            raise RecipeError("Media registration failed")

    def _start_recording(self, payload: dict) -> None:
        manifest = {}
        keys = set(payload["queue"])
        if payload["media"] is not None:
            keys.add(payload["media"])
        if payload.get('overlap') is not None:
            keys.add(payload['overlap']['incoming'])
        for key in keys:
            _, manifest[key] = self._media(key)
        state = initial_state(payload["settings"], version=self._capture_version)
        state.update({key: payload[key] for key in (
            "media", "position_ms", "playing", "queue", "current_index", "queue_tree", "shuffle_seed",
        )})
        if self._capture_version >= FROZEN_GAIN_VERSION:
            state.update(program_gain_db=payload['program_gain_db'], overlap=payload['overlap'])
        self.directory.mkdir(parents=True, exist_ok=True)
        recorder = SessionRecipeRecorder(self._path(payload["name"]), media=manifest, settings=payload["settings"],
                                        initial_state=state, clock=lambda: self._time_ms() / 1000,
                                        version=self._capture_version)
        with self._lock:
            self._recorder = recorder
            if self._error:
                recorder.mark_incomplete(self._error if self._error in {"overflow", "shutdown_timeout"} else "unsupported_operation")
            self._state = "stopping" if self._stop_recording_requested else "recording"
            self._last_at_ms = 0
            self._current_media_id = payload["media"]
            self._playback_session_id = payload["playback_session_id"]

    def _finish_recording(self, at_ms: int) -> None:
        recorder = self._recorder
        if recorder is None:
            return
        if self._capture_loss:
            recorder.mark_incomplete('overflow')
        # Use the service's captured stop boundary, not time spent hashing/draining.
        recorder.checkpoint(at_ms=max(at_ms, self._last_at_ms))
        complete = recorder.close(1)
        with self._lock:
            self._last_recording = {"complete": complete, **recorder.status()}
            self._recorder = None
            self._state = "idle" if complete else "incomplete"
            self._error = self._last_recording["incomplete_reason"]

    def _handle(self, kind: str, payload: Any, at_ms: int) -> None:
        if kind == "start":
            self._start_recording(payload)
        elif kind == "stop_recording":
            self._finish_recording(at_ms)
        elif kind == "replay":
            self._replay = RecipeReplayEngine(load_recipe(self._path(payload["name"])), self._host, clock=self._clock)
            self._replay.start(payload["at_ms"])
            self._state = "replaying"
        elif kind == "stop_replay":
            if self._replay:
                self._replay.stop()
            else:
                self._host.halt()
            self._state = "idle"
        elif kind == "seek_replay":
            if self._replay is None:
                raise RecipeError("No prepared recipe is available to seek")
            self._replay.seek(payload)
            self._state = "replaying"
        elif kind == "replay_buffering":
            if self._replay:
                self._replay.set_buffering(payload)
        elif self._recorder is not None:
            if self._recorder.status()["incomplete_reason"] is not None:
                return
            if kind == "unsupported":
                self._recorder.mark_incomplete()
                return
            if kind == 'program':
                captured: CommittedProgramEvent = payload
                if captured.action == 'transition':
                    overlap = self._overlap_payload(captured.overlap)
                    if (overlap is None or captured.stable_id != self._current_media_id
                            or captured.session_id != self._playback_session_id):
                        self._recorder.mark_incomplete('invalid_event')
                        return
                    self._register(overlap['incoming'])
                    self._commit_recorded('transition', {
                        **overlap, 'media': captured.stable_id,
                        'position_ms': round(captured.position_seconds * 1000),
                    }, 'automatic', at_ms)
                    return
                payload = {
                    'stable_id': captured.stable_id, 'session_id': captured.session_id,
                    'action': captured.action, 'origin': captured.origin,
                    'play_kind': captured.play_kind, 'position_seconds': captured.position_seconds,
                    'program_gain_db': captured.program_gain_db, 'overlap': self._overlap_payload(captured.overlap),
                }
                kind = 'playback'
            if kind == "playback":
                action = payload["action"]
                event_kind = "media_start" if action == "play" and payload["play_kind"] == "start" else (
                    "resume" if action == "play" else action
                )
                if event_kind == "media_start":
                    self._register(payload["stable_id"])
                    self._current_media_id = payload["stable_id"]
                    self._playback_session_id = payload["session_id"]
                elif payload["stable_id"] != self._current_media_id or (
                    self._playback_session_id is not None and payload["session_id"] != self._playback_session_id
                ):
                    self._recorder.mark_incomplete("invalid_event")
                    return
                data = {"position_ms": round(payload["position_seconds"] * 1000)}
                if event_kind == "media_start":
                    data["media"] = payload["stable_id"]
                    if self._capture_version >= FROZEN_GAIN_VERSION:
                        data['program_gain_db'] = payload['program_gain_db']
                elif self._capture_version >= FROZEN_GAIN_VERSION:
                    data.update(media=payload['stable_id'], overlap=payload['overlap'])
                reason = "automatic" if payload["origin"] in {"automatic", "system"} else (
                    "recovery" if payload["origin"] == "recovery" else "manual"
                )
            elif kind == "queue":
                for stable_id in set(payload["queue"]):
                    self._register(stable_id)
                event_kind = payload["event_kind"]
                data = {key: payload[key] for key in ("queue", "current_index", "seed", "queue_tree")}
                reason = "manual"
            elif kind == "commit":
                event_kind, data, reason = payload
                if event_kind == "stop":
                    self._current_media_id = None
                    self._playback_session_id = None
            else:
                return
            self._commit_recorded(event_kind, data, reason, at_ms)

    def _commit_recorded(self, kind: str, data: dict, reason: str, at_ms: int) -> None:
        assert self._recorder is not None
        if not self._recorder.commit(kind, data, at_ms=at_ms, reason=reason):
            self._error = self._recorder.status()['incomplete_reason'] or 'invalid_event'
        self._last_at_ms = at_ms
        event_count = self._recorder.status()['event_count']
        if event_count and event_count % 64 == 0:
            self._recorder.checkpoint(at_ms=at_ms)

    def _run(self) -> None:
        while not self._closing.is_set() or not self._pending.empty():
            done = None
            try:
                if self._capture_loss:
                    self._error = 'overflow'
                    if self._recorder is not None:
                        self._recorder.mark_incomplete('overflow')
                if self._state in {"preparing", "recording"}:
                    self.set_buffering(str(self._host.playback.snapshot().state) in {"resolving", "buffering", "seeking"})
                try:
                    kind, payload, at_ms, done = self._pending.get(timeout=.05)
                except queue.Empty:
                    kind = None
                if kind is not None:
                    self._operation_deadline = time.monotonic() + 10
                    self._handle(kind, payload, at_ms)
                if self._replay is not None and self._state == "replaying":
                    self._operation_deadline = time.monotonic() + 10
                    self._replay.tick()
                    if self._replay.status == "completed":
                        self._state = "completed"
            except Exception as error:
                code = error.code if isinstance(error, ReplayBlocked) else "session_operation_failed"
                with self._lock:
                    self._error = code
                    self._state = "failed"
                    recorder = self._recorder
                if recorder is not None:
                    recorder.mark_incomplete()
                if self._replay_active:
                    with suppress(Exception):
                        self._host.halt()
            finally:
                if done is not None:
                    done.set()
        if self._recorder is not None:
            self._recorder.mark_incomplete("shutdown_timeout")
            self._finish_recording(max(self._time_ms(), self._last_at_ms))
        if self._replay_active:
            with suppress(Exception):
                self._host.halt()

    def close(self, timeout: float = 2.0) -> bool:
        timeout = _number(timeout, 0, 30, "shutdown timeout")
        started = time.monotonic()
        self.stop(timeout=timeout / 2)
        self.stop_replay(timeout=timeout / 2)
        self._closing.set()
        if self._worker is not None:
            self._worker.join(max(0, timeout - (time.monotonic() - started)))
        return self._worker is None or not self._worker.is_alive()
