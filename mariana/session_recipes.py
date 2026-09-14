"""Bounded local listening recipes, independent of command text and decoders.

Hosts must submit *committed* events and explicitly implement replay authority.
This module never resolves a URL, executes a command, or creates an audio player.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import queue
import re
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit

from .recipe_errors import RecipeError
from .recipe_queue import MAX_GROUP_IDENTITIES, MAX_INTEGER, MIN_INTEGER, flat_tree, validate_tree

FORMAT = "mariana-session-recipe"
VERSION = 2
FROZEN_GAIN_VERSION = 3
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_EVENTS = 20_000
MAX_MEDIA = 512
MAX_QUEUE = 2048
MAX_CHECKPOINTS = 512
MAX_DURATION_MS = 7 * 24 * 60 * 60 * 1000
MAX_POSITION_MS = 31 * 24 * 60 * 60 * 1000
KINDS = frozenset({
    "media_start", "pause", "resume", "seek", "stop", "queue_set", "shuffle",
    "queue_settings", "gain_settings", "crossfade_settings", "transition",
})
REASONS = frozenset({"manual", "automatic", "recovery"})
INCOMPLETE_REASONS = frozenset({
    "overflow", "persistence_failed", "shutdown_timeout", "unsealed", "invalid_event", "limit", "unsupported_operation",
})
_OPAQUE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_IDENTITY = re.compile(r"(?:[a-f0-9]{24}|[a-f0-9]{64})\Z")
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_YOUTUBE = re.compile(r"[A-Za-z0-9_-]{11}\Z")


class ReplayBlocked(RecipeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code.replace("_", " "))


def _object(value: Any, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise RecipeError(f"Invalid {label} fields")
    return value


def _integer(value: Any, maximum: int, label: str, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise RecipeError(f"Invalid {label}")
    return value


def _number(value: Any, minimum: float, maximum: float, label: str) -> float:
    if type(value) not in {int, float} or not minimum <= value <= maximum or not math.isfinite(value):
        raise RecipeError(f"Invalid {label}")
    return float(value)


def _boolean(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise RecipeError(f"Invalid {label}")
    return value


def _key(value: Any, label: str = "identity") -> str:
    if not isinstance(value, str) or not _OPAQUE.fullmatch(value):
        raise RecipeError(f"Invalid {label}")
    return value


def _choice(value: Any, choices: set[str] | frozenset[str], label: str) -> str:
    if not isinstance(value, str) or value not in choices:
        raise RecipeError(f"Invalid {label}")
    return value


def validate_media_reference(value: Any) -> dict:
    ref = _object(value, {"source", "stable_id", "fingerprint", "duration_ms", "live", "provider_id"}, "media")
    _choice(ref["source"], {"local", "youtube", "url", "podcast", "radio"}, "media source")
    if not isinstance(ref["stable_id"], str) or not _IDENTITY.fullmatch(ref["stable_id"]):
        raise RecipeError("Invalid catalog identity")
    if ref["fingerprint"] is not None and (
        not isinstance(ref["fingerprint"], str) or not _SHA256.fullmatch(ref["fingerprint"])
    ):
        raise RecipeError("Invalid content fingerprint")
    if ref["duration_ms"] is not None:
        _integer(ref["duration_ms"], MAX_POSITION_MS, "media duration")
    _boolean(ref["live"], "live flag")
    if ref["source"] == "youtube":
        if not isinstance(ref["provider_id"], str) or not _YOUTUBE.fullmatch(ref["provider_id"]):
            raise RecipeError("Invalid public provider identity")
    elif ref["provider_id"] is not None:
        raise RecipeError("Only a supported public provider identity is allowed")
    return copy.deepcopy(ref)


def canonical_media_reference(media: Any, *, fingerprint: str | None = None) -> dict:
    """Project a MediaRef without paths, signed URLs, titles, or resolver data.

    Content hashing is deliberately separate from the real-time commit hook.
    Non-YouTube online sources are catalog-only and require the original host.
    """
    source = str(media.source)
    provider_id = None
    if source == "youtube":
        parsed = urlsplit(media.original_uri)
        if parsed.username or parsed.password or parsed.port:
            raise RecipeError("Invalid public provider identity")
        if parsed.hostname in {"youtu.be", "www.youtu.be"}:
            provider_id = parsed.path.strip("/")
        elif parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            provider_id = parse_qs(parsed.query).get("v", [None])[0]
            if provider_id is None and parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
                provider_id = parsed.path.split("/")[2]
    duration = None if media.duration is None else round(_number(media.duration, 0, MAX_POSITION_MS / 1000, "duration") * 1000)
    return validate_media_reference({
        "source": source, "stable_id": media.stable_id, "fingerprint": fingerprint,
        "duration_ms": duration, "live": bool(media.capabilities.live), "provider_id": provider_id,
    })


def fingerprint_file(path: str | Path, *, cancelled: Callable[[], bool] | None = None,
                     deadline: float | None = None) -> str:
    """Explicit local preflight helper; never call on a PCM/control callback."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        before = os.fstat(source.fileno())
        while True:
            if (cancelled is not None and cancelled()) or (deadline is not None and time.monotonic() >= deadline):
                raise RecipeError("Source fingerprint cancelled or timed out")
            block = source.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(source.fileno())
        current = Path(path).stat()
    def signature(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    if signature(before) != signature(after) or signature(after) != signature(current):
        raise RecipeError("Source changed while its fingerprint was being read")
    return digest.hexdigest()


def default_settings() -> dict:
    return {
        "repeat": "off", "consume": False, "autofill": False, "crossfade_ms": 0,
        "replaygain": {"enabled": False, "mode": "track", "preamp_db": 0.0, "prevent_clipping": True},
    }


def _gain_settings(value: Any) -> None:
    value = _object(value, {"enabled", "mode", "preamp_db", "prevent_clipping"}, "gain settings")
    _boolean(value["enabled"], "gain enabled")
    _boolean(value["prevent_clipping"], "clipping prevention")
    _choice(value["mode"], {"off", "track", "album", "auto"}, "gain mode")
    _number(value["preamp_db"], -15, 15, "gain preamp")


def _queue_settings(value: Any) -> None:
    value = _object(value, {"repeat", "consume", "autofill"}, "queue settings")
    _choice(value["repeat"], {"off", "one", "all"}, "repeat mode")
    _boolean(value["consume"], "consume")
    _boolean(value["autofill"], "autofill")


def _settings(value: Any) -> None:
    value = _object(value, set(default_settings()), "settings")
    _queue_settings({key: value[key] for key in ("repeat", "consume", "autofill")})
    _gain_settings(value["replaygain"])
    _integer(value["crossfade_ms"], 30_000, "crossfade duration")


def initial_state(settings: dict | None = None, *, version: int = VERSION) -> dict:
    result = {
        "at_ms": 0, "media": None, "position_ms": 0, "playing": False, "overlap": None,
        "queue": [], "current_index": None, "shuffle_seed": None,
        "settings": copy.deepcopy(settings if settings is not None else default_settings()),
    }
    if version >= VERSION:
        result["queue_tree"] = flat_tree([])
    if version >= FROZEN_GAIN_VERSION:
        result["program_gain_db"] = None
    _settings(result["settings"])
    return result


def _media_key(value: Any, media: Mapping) -> str:
    key = _key(value, "media key")
    if key not in media:
        raise RecipeError("Unknown media reference")
    return key


def _queue_data(data: dict, media: Mapping, *, version: int = VERSION) -> None:
    items = data["queue"]
    if not isinstance(items, list) or len(items) > MAX_QUEUE:
        raise RecipeError("Queue exceeds its limit")
    for item in items:
        _media_key(item, media)
    if data["current_index"] is not None:
        _integer(data["current_index"], len(items) - 1, "queue current index")
    if version >= VERSION:
        validate_tree(data["queue_tree"], items)


def _validate_state(value: Any, media: Mapping, *, version: int = VERSION) -> None:
    state = _object(value, set(initial_state(version=version)), "state")
    _integer(state["at_ms"], MAX_DURATION_MS, "state time")
    _integer(state["position_ms"], MAX_POSITION_MS, "position")
    _boolean(state["playing"], "playing")
    if state["media"] is not None:
        _media_key(state["media"], media)
    elif state["playing"] or state["position_ms"] or state["overlap"]:
        raise RecipeError("Empty playback state is inconsistent")
    if version >= FROZEN_GAIN_VERSION:
        if state["media"] is None:
            if state["program_gain_db"] is not None:
                raise RecipeError("Empty playback cannot retain a source gain")
        else:
            _number(state["program_gain_db"], -120, 60, "active program gain")
    _queue_data(state, media, version=version)
    if state["shuffle_seed"] is not None:
        _integer(state["shuffle_seed"], MAX_INTEGER if version >= VERSION else 2**31 - 1, "shuffle seed",
                 MIN_INTEGER if version >= VERSION else 0)
    _settings(state["settings"])
    if state["overlap"] is not None:
        overlap = _object(state["overlap"], {
            "incoming", "incoming_position_ms", "duration_ms", "progress_ms", "outgoing_gain_db", "incoming_gain_db",
        }, "overlap")
        _overlap_data(overlap, media)
        if version >= FROZEN_GAIN_VERSION and overlap["outgoing_gain_db"] != state["program_gain_db"]:
            raise RecipeError("Overlap outgoing gain does not match its active source")


def _overlap_data(data: dict, media: Mapping) -> None:
    _media_key(data["incoming"], media)
    _integer(data["incoming_position_ms"], MAX_POSITION_MS, "incoming offset")
    duration = _integer(data["duration_ms"], 30_000, "overlap duration", 1)
    _integer(data["progress_ms"], duration - 1, "overlap progress")
    _number(data["outgoing_gain_db"], -120, 60, "outgoing gain")
    _number(data["incoming_gain_db"], -120, 60, "incoming gain")


def validate_event(event: Any, *, media: Mapping, session_id: str, sequence: int, previous_ms: int,
                   version: int = VERSION) -> dict:
    event = _object(event, {"seq", "at_ms", "session_id", "kind", "reason", "data"}, "event")
    if type(event["seq"]) is not int or event["seq"] != sequence:
        raise RecipeError("Event sequence is not contiguous")
    _integer(event["at_ms"], MAX_DURATION_MS, "event time", previous_ms)
    if event["session_id"] != session_id:
        raise RecipeError("Event session does not match")
    kind = _choice(event["kind"], KINDS, "event kind")
    _choice(event["reason"], REASONS, "event reason")
    fields = {
        "media_start": {"media", "position_ms"}, "pause": {"position_ms"}, "resume": {"position_ms"},
        "seek": {"position_ms"}, "stop": set(), "queue_set": {"queue", "current_index"},
        "shuffle": {"queue", "current_index", "seed"}, "queue_settings": {"repeat", "consume", "autofill"},
        "gain_settings": {"enabled", "mode", "preamp_db", "prevent_clipping"},
        "crossfade_settings": {"crossfade_ms"},
        "transition": {"incoming", "incoming_position_ms", "duration_ms", "progress_ms", "outgoing_gain_db", "incoming_gain_db"},
    }
    if version >= VERSION:
        fields["queue_set"] = fields["shuffle"] = {"queue", "current_index", "seed", "queue_tree"}
    if version >= FROZEN_GAIN_VERSION:
        fields["media_start"] |= {"program_gain_db"}
        fields["gain_settings"] |= {"program_gain_db"}
        for action in ('pause', 'resume', 'seek'):
            fields[action] |= {'media', 'overlap'}
        fields['transition'] |= {'media', 'position_ms'}
    data = _object(event["data"], fields[kind], "event payload")
    if "position_ms" in data:
        _integer(data["position_ms"], MAX_POSITION_MS, "event position")
    if version >= FROZEN_GAIN_VERSION and 'media' in data:
        _media_key(data['media'], media)
    if version >= FROZEN_GAIN_VERSION and kind in {'pause', 'resume', 'seek'} and data['overlap'] is not None:
        expected_fields = {'incoming', 'incoming_position_ms', 'duration_ms', 'progress_ms',
                           'outgoing_gain_db', 'incoming_gain_db'}
        _overlap_data(_object(data['overlap'], expected_fields, 'captured overlap'), media)
    if kind == "media_start":
        _media_key(data["media"], media)
        if version >= FROZEN_GAIN_VERSION:
            _number(data["program_gain_db"], -120, 60, "active program gain")
    elif kind in {"queue_set", "shuffle"}:
        _queue_data(data, media, version=version)
        if kind == "shuffle" or (version >= VERSION and data["seed"] is not None):
            _integer(data["seed"], MAX_INTEGER if version >= VERSION else 2**31 - 1, "shuffle seed",
                     MIN_INTEGER if version >= VERSION else 0)
    elif kind == "queue_settings":
        _queue_settings(data)
    elif kind == "gain_settings":
        _gain_settings({key: value for key, value in data.items() if key != "program_gain_db"})
        if version >= FROZEN_GAIN_VERSION and data["program_gain_db"] is not None:
            _number(data["program_gain_db"], -120, 60, "active program gain")
    elif kind == "crossfade_settings":
        _integer(data["crossfade_ms"], 30_000, "crossfade duration")
    elif kind == "transition":
        _overlap_data(data, media)
    return copy.deepcopy(event)


def _advance(state: dict, at_ms: int) -> dict:
    result = copy.deepcopy(state)
    delta = at_ms - result["at_ms"]
    if delta < 0:
        raise RecipeError("State time cannot move backwards")
    if result["playing"] and result["media"] is not None:
        result["position_ms"] += delta
        if result["overlap"] is not None:
            overlap = result["overlap"]
            overlap["incoming_position_ms"] += delta
            overlap["progress_ms"] += delta
            if overlap["progress_ms"] >= overlap["duration_ms"]:
                result["media"] = overlap["incoming"]
                result["position_ms"] = overlap["incoming_position_ms"]
                if "program_gain_db" in result:
                    result["program_gain_db"] = overlap["incoming_gain_db"]
                result["overlap"] = None
    result["at_ms"] = at_ms
    return result


def _apply(state: dict, event: dict) -> dict:
    state = _advance(state, event["at_ms"])
    data, kind = event["data"], event["kind"]
    if kind == "media_start":
        state.update(media=data["media"], position_ms=data["position_ms"], playing=True, overlap=None)
        if "program_gain_db" in state:
            state["program_gain_db"] = data["program_gain_db"]
    elif kind in {"pause", "resume", "seek"}:
        if state["media"] is None:
            raise RecipeError("Playback event requires current media")
        if kind == "pause" and not state["playing"]:
            raise RecipeError("Pause requires playing media")
        if kind == "resume" and state["playing"]:
            raise RecipeError("Resume requires paused media")
        if state["overlap"] is not None and kind == "seek":
            raise RecipeError("Seek during overlap needs an explicit new media state")
        if 'program_gain_db' in state:
            if data['media'] != state['media']:
                raise RecipeError('Playback event does not match the effective source')
            captured = data['overlap']
            if (captured is None) != (state['overlap'] is None):
                raise RecipeError('Playback event lost its effective overlap')
            if captured is not None:
                effective_overlap = state['overlap']
                assert effective_overlap is not None
                if any(captured[key] != effective_overlap[key] for key in (
                    'incoming', 'duration_ms', 'outgoing_gain_db', 'incoming_gain_db',
                )):
                    raise RecipeError('Playback event changed its overlap identity or gains')
                state['overlap'] = copy.deepcopy(captured)
        state["position_ms"] = data["position_ms"]
        if kind != "seek":
            state["playing"] = kind == "resume"
    elif kind == "stop":
        state.update(media=None, position_ms=0, playing=False, overlap=None)
        if "program_gain_db" in state:
            state["program_gain_db"] = None
    elif kind in {"queue_set", "shuffle"}:
        if kind == "shuffle":
            if Counter(data["queue"]) != Counter(state["queue"]):
                raise RecipeError("Shuffle must preserve queued occurrences")
            state["shuffle_seed"] = data["seed"]
        else:
            state["shuffle_seed"] = data.get("seed")
        state["queue"] = list(data["queue"])
        state["current_index"] = data["current_index"]
        if "queue_tree" in state:
            state["queue_tree"] = copy.deepcopy(data["queue_tree"])
    elif kind == "queue_settings":
        state["settings"].update(data)
    elif kind == "gain_settings":
        if state["overlap"] is not None:
            raise RecipeError("Gain changes during overlap require new effective source gains")
        state["settings"]["replaygain"] = {key: value for key, value in data.items() if key != "program_gain_db"}
        if "program_gain_db" in state:
            state["program_gain_db"] = data["program_gain_db"]
    elif kind == "crossfade_settings":
        state["settings"]["crossfade_ms"] = data["crossfade_ms"]
    elif kind == "transition":
        if state["media"] is None or not state["playing"] or state["overlap"] is not None:
            raise RecipeError("Transition requires one playing source")
        if 'program_gain_db' in state:
            if data['media'] != state['media']:
                raise RecipeError('Transition does not match its outgoing source')
            state['position_ms'] = data['position_ms']
        state["overlap"] = {key: value for key, value in data.items() if key not in {'media', 'position_ms'}}
    return state


def new_recipe(*, session_id: str | None = None, media: dict | None = None, settings: dict | None = None,
               version: int = VERSION) -> dict:
    settings = copy.deepcopy(settings if settings is not None else default_settings())
    return {
        "format": FORMAT, "version": version, "clock": "relative-ms", "session_id": session_id or uuid.uuid4().hex,
        "media": copy.deepcopy(media or {}), "settings": settings, "initial_state": initial_state(settings, version=version),
        "events": [], "checkpoints": [], "duration_ms": 0, "complete": True, "incomplete_reason": None,
    }


def validate_recipe(value: Any, *, _upgrade: bool = True) -> dict:
    recipe = _object(value, set(new_recipe()), "recipe")
    if (recipe["format"] != FORMAT or type(recipe["version"]) is not int
            or recipe["version"] not in {1, VERSION, FROZEN_GAIN_VERSION}):
        raise RecipeError("Unsupported recipe format or version")
    version = recipe["version"]
    if recipe["clock"] != "relative-ms":
        raise RecipeError("Unsupported recipe clock")
    _key(recipe["session_id"], "session identity")
    media = recipe["media"]
    if not isinstance(media, dict) or len(media) > MAX_MEDIA:
        raise RecipeError("Media manifest exceeds its limit")
    for key, ref in media.items():
        _key(key, "media key")
        validate_media_reference(ref)
    _settings(recipe["settings"])
    _validate_state(recipe["initial_state"], media, version=version)
    group_identities: set[str] = set()

    def count_group_identities(state: dict) -> None:
        if version >= VERSION:
            group_identities.update(group["id"] for group in state["queue_tree"]["groups"])
            if len(group_identities) > MAX_GROUP_IDENTITIES:
                raise RecipeError("Recipe group identity budget exhausted")

    count_group_identities(recipe["initial_state"])
    if recipe["initial_state"]["at_ms"] != 0 or recipe["initial_state"]["settings"] != recipe["settings"]:
        raise RecipeError("Initial state must match initial settings at zero")
    events = recipe["events"]
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise RecipeError("Event count exceeds its limit")
    checkpoints = recipe["checkpoints"]
    if not isinstance(checkpoints, list) or len(checkpoints) > MAX_CHECKPOINTS:
        raise RecipeError("Checkpoint count exceeds its limit")
    checkpoint_by_index: dict[int, list[dict]] = {}
    previous_checkpoint = (-1, -1)
    for checkpoint in checkpoints:
        cp = _object(checkpoint, {"at_ms", "event_index", "state"}, "checkpoint")
        _integer(cp["event_index"], len(events), "checkpoint index")
        _integer(cp["at_ms"], MAX_DURATION_MS, "checkpoint time")
        if (cp["at_ms"], cp["event_index"]) <= previous_checkpoint:
            raise RecipeError("Checkpoints must be ordered and distinct")
        previous_checkpoint = (cp["at_ms"], cp["event_index"])
        _validate_state(cp["state"], media, version=version)
        count_group_identities(cp["state"])
        checkpoint_by_index.setdefault(cp["event_index"], []).append(cp)
    state = copy.deepcopy(recipe["initial_state"])
    for event in events:
        _object(event, {"seq", "at_ms", "session_id", "kind", "reason", "data"}, "event")
        _integer(event["at_ms"], MAX_DURATION_MS, "event time")
    for index in range(len(events) + 1):
        for cp in checkpoint_by_index.get(index, []):
            if index < len(events) and cp["at_ms"] > events[index].get("at_ms", -1):
                raise RecipeError("Checkpoint skips committed events")
            if _advance(state, cp["at_ms"]) != cp["state"]:
                raise RecipeError("Checkpoint does not match effective state")
        if index < len(events):
            event = validate_event(events[index], media=media, session_id=recipe["session_id"], sequence=index,
                                   previous_ms=state["at_ms"], version=version)
            if event["kind"] in {"queue_set", "shuffle"}:
                count_group_identities(event["data"])
            state = _apply(state, event)
            _validate_state(state, media, version=version)
    minimum_duration = max(state["at_ms"], previous_checkpoint[0], 0)
    _integer(recipe["duration_ms"], MAX_DURATION_MS, "recipe duration", minimum_duration)
    _boolean(recipe["complete"], "complete flag")
    if recipe["complete"]:
        if recipe["incomplete_reason"] is not None:
            raise RecipeError("Complete recipe has an incomplete reason")
    else:
        _choice(recipe["incomplete_reason"], INCOMPLETE_REASONS, "incomplete reason")
    try:
        encoded = json.dumps(recipe, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as error:
        raise RecipeError("Recipe is not bounded JSON") from error
    if len(encoded) > MAX_BYTES:
        raise RecipeError("Recipe exceeds its byte limit")
    result = copy.deepcopy(recipe)
    if version == 1 and _upgrade:
        result["version"] = VERSION
        for state in [result["initial_state"], *[cp["state"] for cp in result["checkpoints"]]]:
            state["queue_tree"] = flat_tree(state["queue"])
        for event in result["events"]:
            if event["kind"] in {"queue_set", "shuffle"}:
                event["data"]["queue_tree"] = flat_tree(event["data"]["queue"])
                event["data"].setdefault("seed", None)
        return validate_recipe(result)
    return result


def _effective_state(recipe: dict, at_ms: int) -> dict:
    _integer(at_ms, recipe["duration_ms"], "replay position")
    index, state = 0, copy.deepcopy(recipe["initial_state"])
    for checkpoint in recipe["checkpoints"]:
        if checkpoint["at_ms"] > at_ms:
            break
        index, state = checkpoint["event_index"], copy.deepcopy(checkpoint["state"])
    for event in recipe["events"][index:]:
        if event["at_ms"] > at_ms:
            break
        state = _apply(state, event)
    return _advance(state, at_ms)


def effective_state(recipe: dict, at_ms: int) -> dict:
    """Fold skipped history without issuing any backend operations."""
    return _effective_state(validate_recipe(recipe), at_ms)


def _json_loads(text: str) -> Any:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise RecipeError("Duplicate JSON field")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=unique_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(RecipeError("Non-finite JSON number")))
    except (ValueError, RecursionError) as error:
        raise RecipeError("Invalid recipe JSON") from error


def load_recipe(path: str | Path) -> dict:
    """Load a bounded export or recorder journal; unsealed journals are incomplete."""
    with Path(path).open("rb") as source:
        payload = source.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise RecipeError("Recipe exceeds its byte limit")
    try:
        text = payload.decode("utf-8")
    except UnicodeError as error:
        raise RecipeError("Recipe must be UTF-8 JSON") from error
    # A regular export is a complete JSON document, including pretty-printed exports.
    try:
        whole = _json_loads(text)
    except RecipeError:
        whole = None
    if isinstance(whole, dict) and "format" in whole:
        return validate_recipe(whole)
    lines = text.splitlines()
    if not lines or len(lines) > MAX_EVENTS + MAX_MEDIA + MAX_CHECKPOINTS + 2:
        raise RecipeError("Invalid journal length")
    recipe = None
    sealed = False
    for index, line in enumerate(lines):
        if len(line.encode("utf-8")) > MAX_RECORD_BYTES:
            raise RecipeError("Journal record exceeds its byte limit")
        record = _object(_json_loads(line), {"type", "value"}, "journal record")
        if sealed:
            raise RecipeError("Records follow journal seal")
        kind, value = record["type"], record["value"]
        if index == 0:
            if kind != "header":
                raise RecipeError("Journal header is missing")
            # Keep the original format while parsing its exact-schema records.
            # Upgrade only after the complete legacy journal has been validated.
            recipe = validate_recipe(value, _upgrade=False)
            if recipe["events"] or recipe["checkpoints"] or recipe["duration_ms"] or recipe["complete"]:
                raise RecipeError("Invalid journal header")
            continue
        assert recipe is not None
        if kind == "media":
            value = _object(value, {"key", "reference"}, "media registration")
            key = _key(value["key"], "media key")
            if key in recipe["media"]:
                raise RecipeError("Media identity cannot be replaced")
            recipe["media"][key] = validate_media_reference(value["reference"])
        elif kind == "event":
            recipe["events"].append(validate_event(
                value, media=recipe["media"], session_id=recipe["session_id"], sequence=len(recipe["events"]),
                previous_ms=recipe["events"][-1]["at_ms"] if recipe["events"] else 0,
                version=recipe["version"],
            ))
        elif kind == "checkpoint":
            _object(value, {"at_ms", "event_index", "state"}, "checkpoint")
            _integer(value["at_ms"], MAX_DURATION_MS, "checkpoint time")
            recipe["checkpoints"].append(value)
        elif kind == "seal":
            value = _object(value, {"duration_ms", "complete", "incomplete_reason", "event_count"}, "journal seal")
            if type(value["event_count"]) is not int or value["event_count"] != len(recipe["events"]):
                raise RecipeError("Journal event count does not match")
            recipe.update({key: value[key] for key in ("duration_ms", "complete", "incomplete_reason")})
            sealed = True
        else:
            raise RecipeError("Unknown journal record")
    assert recipe is not None
    if not sealed:
        recipe["complete"] = False
        recipe["incomplete_reason"] = "unsealed"
        recipe["duration_ms"] = max(
            [0, *[event.get("at_ms", 0) for event in recipe["events"]],
             *[checkpoint.get("at_ms", 0) for checkpoint in recipe["checkpoints"]]],
        )
    return validate_recipe(recipe)


def inspect_recipe(recipe: dict) -> dict:
    """Read-only privacy/portability inspection; no network, source lookup, or playback."""
    recipe = validate_recipe(recipe)
    return {
        "session_id": recipe["session_id"], "version": recipe["version"], "complete": recipe["complete"],
        "incomplete_reason": recipe["incomplete_reason"], "duration_ms": recipe["duration_ms"],
        "event_count": len(recipe["events"]), "checkpoint_count": len(recipe["checkpoints"]),
        "event_kinds": dict(sorted(Counter(event["kind"] for event in recipe["events"]).items())),
        "media_count": len(recipe["media"]), "required_capabilities": sorted(required_capabilities(recipe)),
        "live_sources": sorted(key for key, ref in recipe["media"].items() if ref["live"]),
        "unverified_local_sources": sorted(key for key, ref in recipe["media"].items()
                                           if ref["source"] == "local" and ref["fingerprint"] is None),
        "catalog_only_sources": sorted(key for key, ref in recipe["media"].items()
                                       if ref["source"] not in {"local", "youtube"}),
        "privacy": "No paths, URLs, command text, output-device settings, or credentials are permitted.",
        "availability_checked": False,
    }


def required_capabilities(recipe: dict) -> frozenset[str]:
    required = {"playback", "queue", "queue_settings", "gain_settings", "crossfade_settings"}
    states = [recipe["initial_state"], *[cp["state"] for cp in recipe["checkpoints"]]]
    queue_states = [*states, *[event["data"] for event in recipe["events"] if event["kind"] in {"queue_set", "shuffle"}]]
    if any("queue_tree" in state and state["queue_tree"] != flat_tree(state["queue"]) for state in queue_states):
        required.add("queue_tree")
    if any(state["overlap"] or state["settings"]["crossfade_ms"] > 0 for state in states) or any(
        event["kind"] == "transition" or (event["kind"] == "crossfade_settings" and event["data"]["crossfade_ms"] > 0)
        for event in recipe["events"]
    ):
        required.add("overlap")
    if recipe["version"] >= FROZEN_GAIN_VERSION:
        required.add("program_gain")
    return frozenset(required)


class SessionRecipeRecorder:
    """An explicit opt-in recorder with nonblocking commits and one bounded writer.

    A full queue rejects the event and permanently marks the recipe incomplete.
    No terminal/history parsing or implicit subscription to analytics is used.
    """

    def __init__(self, path: str | Path, *, media: dict | None = None, settings: dict | None = None,
                 initial_state: dict | None = None, session_id: str | None = None, capacity: int = 256,
                 clock: Callable[[], float] = time.monotonic, version: int = VERSION) -> None:
        self.path = Path(path)
        self._clock = clock
        self._origin = clock()
        self._buffering_at: float | None = None
        self._buffered_seconds = 0.0
        self._recipe = new_recipe(session_id=session_id, media=media, settings=settings, version=version)
        if initial_state is not None:
            self._recipe["initial_state"] = copy.deepcopy(initial_state)
        self._recipe["complete"] = False
        self._recipe["incomplete_reason"] = "unsealed"
        self._recipe = validate_recipe(self._recipe)
        self._state = copy.deepcopy(self._recipe["initial_state"])
        self._events = 0
        self._checkpoints = 0
        self._last_checkpoint = (-1, -1)
        self._bytes = 0
        self._reason: str | None = None
        self._dropped = 0
        self._lock = threading.Lock()
        self._pending: queue.Queue[str] = queue.Queue(maxsize=_integer(capacity, 4096, "recorder capacity", 1))
        self._closing = threading.Event()
        self._ready = threading.Event()
        self._closed_at_ms: int | None = None
        self._worker = threading.Thread(target=self._run, name="mariana-session-recipes", daemon=True)
        self._worker.start()
        if not self._ready.wait(1.0):
            self.close(0)
            raise RecipeError("Recipe writer did not become ready")
        if self._reason:
            raise RecipeError("Recipe file could not be created")

    @property
    def session_id(self) -> str:
        return self._recipe["session_id"]

    def _time_ms(self) -> int:
        now = self._buffering_at if self._buffering_at is not None else self._clock()
        return max(0, round((now - self._origin - self._buffered_seconds) * 1000))

    def set_buffering(self, buffering: bool) -> None:
        """Host hook: exclude actual buffering, not user-paused listening time."""
        _boolean(buffering, "buffering")
        with self._lock:
            now = self._clock()
            if buffering and self._buffering_at is None:
                self._buffering_at = now
            elif not buffering and self._buffering_at is not None:
                self._buffered_seconds += max(0, now - self._buffering_at)
                self._buffering_at = None

    @staticmethod
    def _encode(kind: str, value: Any) -> str:
        result = json.dumps({"type": kind, "value": value}, allow_nan=False, separators=(",", ":")) + "\n"
        if len(result.encode("utf-8")) > MAX_RECORD_BYTES:
            raise RecipeError("Journal record exceeds its byte limit")
        return result

    def _enqueue(self, kind: str, value: Any) -> bool:
        if self._closing.is_set() or self._reason is not None:
            return False
        encoded = self._encode(kind, value)
        size = len(encoded.encode("utf-8"))
        # Reserve enough bytes for a seal even when the event budget is exhausted.
        if self._bytes + size > MAX_BYTES - 1024:
            self._reason = "limit"
            self._dropped += 1
            return False
        try:
            self._pending.put_nowait(encoded)
        except queue.Full:
            self._reason = "overflow"
            self._dropped += 1
            return False
        self._bytes += size
        return True

    def register_media(self, key: str, reference: dict) -> bool:
        key, reference = _key(key, "media key"), validate_media_reference(reference)
        with self._lock:
            existing = self._recipe["media"].get(key)
            if existing is not None:
                if existing != reference:
                    raise RecipeError("Media identity cannot be replaced")
                return self._reason is None and not self._closing.is_set()
            if len(self._recipe["media"]) >= MAX_MEDIA:
                self._reason = "limit"
                return False
            if not self._enqueue("media", {"key": key, "reference": reference}):
                return False
            self._recipe["media"][key] = reference
            return True

    def commit(self, kind: str, data: dict, *, at_ms: int | None = None, reason: str = "manual") -> bool:
        """Called after an authoritative operation succeeds; never before it."""
        with self._lock:
            if self._reason is not None or self._closing.is_set():
                return False
            if self._events >= MAX_EVENTS:
                self._reason = "limit"
                self._dropped += 1
                return False
            event = {"seq": self._events, "at_ms": self._time_ms() if at_ms is None else at_ms,
                     "session_id": self.session_id, "kind": kind, "reason": reason, "data": data}
            try:
                event = validate_event(event, media=self._recipe["media"], session_id=self.session_id,
                                       sequence=self._events, previous_ms=self._state["at_ms"],
                                       version=self._recipe["version"])
                state = _apply(self._state, event)
                _validate_state(state, self._recipe["media"], version=self._recipe["version"])
                accepted = self._enqueue("event", event)
            except (RecipeError, TypeError, ValueError, RecursionError):
                self._reason = "invalid_event"
                self._dropped += 1
                return False
            if accepted:
                self._state = state
                self._events += 1
            return accepted

    def checkpoint(self, *, at_ms: int | None = None) -> bool:
        """Persist folded effective state; host transition hooks must already be committed."""
        with self._lock:
            if self._checkpoints >= MAX_CHECKPOINTS:
                self._reason = "limit"
                return False
            at_ms = self._time_ms() if at_ms is None else at_ms
            _integer(at_ms, MAX_DURATION_MS, "checkpoint time", self._state["at_ms"])
            if (at_ms, self._events) <= self._last_checkpoint:
                return False
            state = _advance(self._state, at_ms)
            _validate_state(state, self._recipe["media"], version=self._recipe["version"])
            if not self._enqueue("checkpoint", {"at_ms": at_ms, "event_index": self._events, "state": state}):
                return False
            self._last_checkpoint = (at_ms, self._events)
            self._state = state
            self._checkpoints += 1
            return True

    def status(self) -> dict:
        with self._lock:
            return {"session_id": self.session_id, "event_count": self._events, "checkpoint_count": self._checkpoints,
                    "pending": self._pending.qsize(), "capacity": self._pending.maxsize, "dropped": self._dropped,
                    "incomplete_reason": self._reason, "recording": not self._closing.is_set(),
                    "writer_alive": self._worker.is_alive()}

    def mark_incomplete(self, reason: str = "unsupported_operation") -> None:
        """Host reports an action whose committed semantics cannot be represented."""
        _choice(reason, INCOMPLETE_REASONS - {"unsealed"}, "incomplete reason")
        with self._lock:
            self._reason = self._reason or reason

    def _run(self) -> None:
        try:
            # Exclusive create: a user-selected existing recipe is never clobbered.
            with self.path.open("x", encoding="utf-8", newline="\n") as output:
                header = self._encode("header", self._recipe)
                output.write(header)
                output.flush()
                with self._lock:
                    self._bytes = len(header.encode("utf-8"))
                self._ready.set()
                while not self._closing.is_set() or not self._pending.empty():
                    try:
                        line = self._pending.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    output.write(line)
                    output.flush()
                with self._lock:
                    seal = {"duration_ms": self._closed_at_ms or 0, "complete": self._reason is None,
                            "incomplete_reason": self._reason, "event_count": self._events}
                output.write(self._encode("seal", seal))
                output.flush()
        except Exception:
            with self._lock:
                self._reason = "persistence_failed"
        finally:
            self._ready.set()

    def close(self, timeout: float = 2.0) -> bool:
        timeout = _number(timeout, 0, 30, "shutdown timeout")
        with self._lock:
            if self._closed_at_ms is None:
                self._closed_at_ms = min(MAX_DURATION_MS, max(self._time_ms(), self._state["at_ms"]))
            self._closing.set()
        self._worker.join(timeout)
        with self._lock:
            if self._worker.is_alive():
                self._reason = self._reason or "shutdown_timeout"
            return not self._worker.is_alive() and self._reason is None


@dataclass(frozen=True, slots=True)
class ResolvedRecipeMedia:
    media: object
    reference: dict


class RecipeReplayHost(Protocol):
    """The sole backend authority, supplied by the application composition root.

    Resolve must verify current content; restore/apply must use existing typed
    backend APIs, enforce source policy, and suppress independent queue advance.
    """

    capabilities: frozenset[str]

    def resolve(self, reference: dict) -> ResolvedRecipeMedia: ...
    def restore(self, state: dict, resolved: dict[str, object]) -> None: ...
    def apply(self, event: dict, state: dict, resolved: dict[str, object]) -> None: ...
    def halt(self) -> None: ...
    def is_buffering(self) -> bool: ...


def _matching_reference(expected: dict, actual: dict) -> None:
    actual = validate_media_reference(actual)
    if expected["live"] or actual["live"]:
        raise ReplayBlocked("live_source_requires_archive")
    if expected["source"] == "local" and expected["fingerprint"] is None:
        raise ReplayBlocked("unverified_local_source")
    for key in ("source", "stable_id", "provider_id"):
        if expected[key] != actual[key]:
            raise ReplayBlocked("changed_source")
    if expected["fingerprint"] is not None and expected["fingerprint"] != actual["fingerprint"]:
        raise ReplayBlocked("changed_source")
    duration, actual_duration = expected["duration_ms"], actual["duration_ms"]
    if duration is not None and (actual_duration is None or abs(duration - actual_duration) > min(2000, max(1000, duration * .01))):
        raise ReplayBlocked("changed_source")


class RecipeReplayEngine:
    """Deterministic host-ticked replay, with no scheduler thread or second player.

    Host calls can block on their existing resolver; callers should dispatch
    start/seek/tick on their normal serial worker, never on a PCM callback.
    """

    def __init__(self, recipe: dict, host: RecipeReplayHost, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.recipe = validate_recipe(recipe)
        self.host = host
        self._clock = clock
        self.status = "idle"
        self.error_code: str | None = None
        self.position_ms = 0
        self._anchor = clock()
        self._base_ms = 0
        self._index = 0
        self._state = copy.deepcopy(self.recipe["initial_state"])
        self._buffering = False

    def _block(self, code: str) -> None:
        self.status, self.error_code = "paused", code
        with suppress(Exception):
            self.host.halt()
        raise ReplayBlocked(code)

    def _preflight(self) -> None:
        if not self.recipe["complete"]:
            self._block("incomplete_recipe")
        missing = required_capabilities(self.recipe) - self.host.capabilities
        if missing:
            self._block("unsupported_overlap" if "overlap" in missing else "unsupported_host_capability")

    def _resolve_state(self, state: dict, *, keys: set[str] | None = None) -> dict[str, object]:
        if keys is None:
            keys = set(state["queue"])
            if state["media"] is not None:
                keys.add(state["media"])
            if state["overlap"] is not None:
                keys.add(state["overlap"]["incoming"])
        resolved = {}
        for key in sorted(keys):
            expected = self.recipe["media"][key]
            if expected["live"]:
                self._block("live_source_requires_archive")
            if expected["source"] == "local" and expected["fingerprint"] is None:
                self._block("unverified_local_source")
            try:
                result = self.host.resolve(copy.deepcopy(expected))
                if not isinstance(result, ResolvedRecipeMedia):
                    raise ReplayBlocked("missing_source")
                _matching_reference(expected, result.reference)
            except ReplayBlocked as error:
                self._block(error.code)
            except Exception:
                self._block("missing_source")
            resolved[key] = result.media
        return resolved

    def _resolve_event(self, event: dict, state: dict) -> dict[str, object]:
        kind = event["kind"]
        if kind in {"media_start", "seek"}:
            # A media seek creates a replacement decoder too; reverify only its
            # source, never repeatedly hash an unrelated entire queue.
            keys = {state["media"]}
        elif kind in {"queue_set", "shuffle"}:
            keys = set(state["queue"])
        elif kind == "transition":
            keys = {state["media"], state["overlap"]["incoming"]}
        else:
            return {}
        return self._resolve_state(state, keys=keys)

    def start(self, at_ms: int = 0) -> None:
        self.seek(at_ms)

    def seek(self, at_ms: int) -> None:
        """Restore one effective checkpoint state, never execute skipped commands."""
        _integer(at_ms, self.recipe["duration_ms"], "replay position")
        self._preflight()
        state = _effective_state(self.recipe, at_ms)
        self.position_ms = at_ms
        resolved = self._resolve_state(state)
        try:
            self.host.restore(copy.deepcopy(state), resolved)
        except ReplayBlocked as error:
            self._block(error.code)
        except Exception:
            self._block("backend_error")
        self._state = state
        self._index = sum(event["at_ms"] <= at_ms for event in self.recipe["events"])
        self._base_ms, self._anchor = at_ms, self._clock()
        self._buffering = False
        self.status, self.error_code = "running", None

    def _position(self) -> int:
        if self.status != "running" or self._buffering:
            return self.position_ms
        return min(self.recipe["duration_ms"], self._base_ms + max(0, round((self._clock() - self._anchor) * 1000)))

    def set_buffering(self, buffering: bool) -> None:
        _boolean(buffering, "buffering")
        if buffering == self._buffering:
            return
        if buffering:
            self.position_ms = self._position()
        else:
            self._base_ms, self._anchor = self.position_ms, self._clock()
        self._buffering = buffering

    def tick(self, *, max_events: int = 128) -> int:
        _integer(max_events, 1024, "tick event budget", 1)
        if self.status != "running":
            return 0
        try:
            self.set_buffering(bool(self.host.is_buffering()))
        except ReplayBlocked as error:
            self._block(error.code)
        except Exception:
            self._block("backend_error")
        if self._buffering:
            return 0
        self.position_ms = self._position()
        count = 0
        while self._index < len(self.recipe["events"]) and count < max_events:
            event = self.recipe["events"][self._index]
            if event["at_ms"] > self.position_ms:
                break
            state = _apply(self._state, event)
            before = self._clock()
            target_ms = self.position_ms
            # If this event blocks, an explicit retry must return to its boundary,
            # not silently skip it by restoring the later polling timestamp.
            self.position_ms = event["at_ms"]
            resolved = self._resolve_event(event, state)
            try:
                self.host.apply(copy.deepcopy(event), copy.deepcopy(state), resolved)
            except ReplayBlocked as error:
                self._block(error.code)
            except Exception:
                self._block("backend_error")
            # Resolver/decoder preparation time does not advance the recipe clock.
            self._anchor += max(0.0, self._clock() - before)
            self._state = state
            self._index += 1
            count += 1
            self.position_ms = target_ms
        if self._index == len(self.recipe["events"]) and self.position_ms == self.recipe["duration_ms"]:
            try:
                self.host.halt()
            except Exception:
                self._block("backend_error")
            self.status = "completed"
        return count

    def stop(self) -> None:
        self.position_ms = self._position()
        try:
            self.host.halt()
        finally:
            self.status = "stopped"


# Short name for composition roots which already qualify the module namespace.
ReplayEngine = RecipeReplayEngine
