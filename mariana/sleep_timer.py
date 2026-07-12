"""Session-scoped, monotonic playback sleep timer."""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from .models import PlaybackSnapshot, PlaybackState


class SleepAction(StrEnum):
    PAUSE = "pause"
    STOP = "stop"


class SleepController(Protocol):
    def snapshot(self) -> PlaybackSnapshot: ...
    def pause(self) -> None: ...
    def stop(self) -> None: ...
    def set_automation_gain(self, value: float) -> None: ...


@dataclass(frozen=True, slots=True)
class SleepStatus:
    active: bool
    remaining_seconds: float = 0.0
    duration_seconds: float = 0.0
    fade_seconds: float = 0.0
    action: SleepAction = SleepAction.PAUSE
    gain: float = 1.0

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["action"] = self.action.value
        return value


_COMPACT_DURATION = re.compile(r"(?i)(\d+(?:\.\d+)?)([hms])")


def parse_duration(value: str) -> float:
    text = value.strip()
    if not text:
        raise ValueError("A duration is required")
    if ":" in text:
        parts = text.split(":")
        if len(parts) not in {2, 3} or any(not part.isdigit() for part in parts):
            raise ValueError(f"Invalid clock duration: {value}")
        numbers = [int(part) for part in parts]
        if len(numbers) == 2:
            hours, minutes, seconds = 0, *numbers
        else:
            hours, minutes, seconds = numbers
        if minutes >= 60 or seconds >= 60:
            raise ValueError("Clock minutes and seconds must be below 60")
        total = hours * 3600 + minutes * 60 + seconds
    else:
        matches = list(_COMPACT_DURATION.finditer(text))
        if not matches or "".join(match.group(0) for match in matches).casefold() != text.casefold():
            raise ValueError(f"Invalid duration: {value}")
        units: set[str] = set()
        total = 0.0
        for match in matches:
            amount, unit = float(match.group(1)), match.group(2).casefold()
            if unit in units:
                raise ValueError(f"Duration unit repeated: {unit}")
            units.add(unit)
            total += amount * {"h": 3600, "m": 60, "s": 1}[unit]
    if total <= 0:
        raise ValueError("Duration must be greater than zero")
    return float(total)


class SleepTimer:
    DEFAULT_FADE_SECONDS = 10 * 60
    MIN_DB = -60.0

    def __init__(
        self,
        controller: SleepController,
        *,
        clock: Callable[[], float] = time.monotonic,
        on_update: Callable[[SleepStatus], None] | None = None,
    ) -> None:
        self.controller = controller
        self._clock = clock
        self._on_update = on_update
        self._lock = threading.RLock()
        self._generation = 0
        self._cancel: threading.Event | None = None
        self._thread: threading.Thread | None = None
        self._status = SleepStatus(False)

    def status(self) -> SleepStatus:
        with self._lock:
            status = self._status
            if not status.active:
                return status
            remaining = max(0.0, self._deadline - self._clock())
            return SleepStatus(True, remaining, status.duration_seconds, status.fade_seconds, status.action, status.gain)

    def start(
        self,
        duration_seconds: float,
        *,
        action: SleepAction | str = SleepAction.PAUSE,
        fade_seconds: float | None = None,
    ) -> SleepStatus:
        duration = float(duration_seconds)
        if duration <= 0:
            raise ValueError("Sleep duration must be greater than zero")
        action = SleepAction(action)
        fade = min(duration, self.DEFAULT_FADE_SECONDS if fade_seconds is None else float(fade_seconds))
        if fade < 0:
            raise ValueError("Fade duration cannot be negative")
        with self._lock:
            if self._cancel:
                self._cancel.set()
            self._generation += 1
            generation = self._generation
            cancel = threading.Event()
            self._cancel = cancel
            self._deadline = self._clock() + duration
            self._status = SleepStatus(True, duration, duration, fade, action, 1.0)
            self.controller.set_automation_gain(1.0)
            self._thread = threading.Thread(
                target=self._run,
                args=(generation, cancel, self._deadline, duration, fade, action),
                name="mariana-sleep-timer",
                daemon=True,
            )
            self._thread.start()
            status = self._status
        self._notify(status)
        return status

    def _run(
        self,
        generation: int,
        cancel: threading.Event,
        deadline: float,
        duration: float,
        fade: float,
        action: SleepAction,
    ) -> None:
        while not cancel.is_set():
            remaining = max(0.0, deadline - self._clock())
            if remaining <= 0:
                self._expire(generation, action)
                return
            gain = self._gain(remaining, fade)
            with self._lock:
                if generation != self._generation:
                    return
                self.controller.set_automation_gain(gain)
                self._status = SleepStatus(True, remaining, duration, fade, action, gain)
                status = self._status
            self._notify(status)
            cancel.wait(min(1.0, remaining))

    @classmethod
    def _gain(cls, remaining: float, fade: float) -> float:
        if fade <= 0 or remaining >= fade:
            return 1.0
        progress = 1.0 - remaining / fade
        return math.pow(10.0, (cls.MIN_DB * progress) / 20.0)

    def _expire(self, generation: int, action: SleepAction) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self.controller.set_automation_gain(0.0)
        snapshot = self.controller.snapshot()
        if action == SleepAction.STOP:
            if snapshot.state != PlaybackState.IDLE:
                self.controller.stop()
        elif snapshot.state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}:
            self.controller.pause()
        with self._lock:
            if generation != self._generation:
                return
            self.controller.set_automation_gain(1.0)
            self._cancel = None
            self._thread = None
            self._status = SleepStatus(False, action=action)
            status = self._status
        self._notify(status)

    def cancel(self) -> bool:
        with self._lock:
            was_active = self._status.active
            self._generation += 1
            if self._cancel:
                self._cancel.set()
            self._cancel = None
            self._thread = None
            self.controller.set_automation_gain(1.0)
            self._status = SleepStatus(False, action=self._status.action)
            status = self._status
        self._notify(status)
        return was_active

    def close(self) -> None:
        self.cancel()

    def _notify(self, status: SleepStatus) -> None:
        if self._on_update:
            self._on_update(status)
