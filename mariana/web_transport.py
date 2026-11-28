"""Typed, media-bound controls for a paired Mariana browser."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BrowserControl:
    action: str
    label: str
    occurrence: str | None = None
    value: str | int | float | None = None
    direct: bool = False


def playback_fields(projection, snapshot, queue_state):
    payload = projection.to_dict()
    payload.update(
        occurrence=snapshot.session_id or None,
        playback_rate=snapshot.playback_rate,
        volume=round(snapshot.volume * 100),
        muted=snapshot.muted,
        queue_order=queue_state.get("root_strategy") or "sequential",
        queue_repeat=queue_state.get("repeat_mode") or "off",
    )
    return payload


def prepare(data, playback):
    action, value = data.get("action"), data.get("value")
    target = data.get("occurrence")
    if not isinstance(action, str) or set(data) - {"action", "value", "occurrence"}:
        raise ValueError("Invalid playback control.")
    if action == "shuffle":
        if target is not None or type(value) is not bool:
            raise ValueError("Choose a shuffle state.")
        order = "shuffle" if value else "sequential"
        return BrowserControl(action, f"queue order {order}", value=order)
    if action == "repeat":
        if target is not None or value not in ("off", "one", "all"):
            raise ValueError("Choose a repeat mode.")
        return BrowserControl(action, f"queue repeat {value}", value=value)
    if action == "volume" and target is None and type(value) is int and 0 <= value <= 100:
        return BrowserControl(action, f"volume {value}", value=value, direct=True)
    if action == "mute" and target is None and type(value) is bool:
        return BrowserControl(action, "m", value=value, direct=True)
    if not isinstance(target, str) or target != playback.get("occurrence") or not playback.get("media_id"):
        raise ValueError("Current recording changed. Try again on the current item.")
    if action == "seek":
        duration = playback.get("duration_seconds")
        if (not playback.get("seekable") or playback.get("live") or not duration
                or not (type(value) is int or type(value) is float) or not 0 <= value <= duration
                or playback.get("state") not in {"paused", "playing"}):
            raise ValueError("Choose a valid seek position on the current recording.")
        if not math.isfinite(value):
            raise ValueError("Choose a finite seek position.")
        return BrowserControl(action, f"seek {value:.3f}s", target, value, True)
    if action == "speed":
        if type(value) not in (int, float) or not 0.5 <= value <= 2 or playback.get("live") or not playback.get("seekable"):
            raise ValueError("Playback speed requires a finite seekable recording and a rate from 0.5 to 2.")
        return BrowserControl(action, f"speed {value:g}", target, value, True)
    if action == "favorite" and value is None:
        return BrowserControl(action, "fav !", target)
    if action == "rating" and type(value) is int and 0 <= value <= 5:
        return BrowserControl(action, f"rating {value or 'clear'}", target, value)
    if action in {"play", "pause", "previous", "next"} and value is None:
        return BrowserControl(action, action, target, direct=True)
    raise ValueError("Invalid playback control.")


def apply(intent, *, snap, dispatch, control):
    action = intent.action
    if action in {"shuffle", "repeat", "volume"}:
        dispatch(intent.label)
        return {"ok": True}
    snapshot = snap()
    if action == "mute":
        if snapshot.muted != intent.value:
            dispatch(intent.label)
        return {"ok": True}
    if snapshot.media is None or snapshot.session_id != intent.occurrence:
        return {"ok": False, "error": "Current recording changed. Try again on the current item."}
    target = {"media_id": snapshot.media.stable_id}
    if action == "speed":
        dispatch(intent.label)
        return {"ok": True}
    if action == "favorite":
        return control("favorite.toggle", target)
    if action == "rating":
        return control("rating.set", {**target, "rating": intent.value})
    if action == "seek":
        target["target_seconds"] = intent.value
    return control(f"playback.{action}", {**target, "origin": "web"})
