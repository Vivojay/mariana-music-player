"""Privacy-safe control diagnostics, separate from the listening history.

Call only from control/worker threads, never from the PCM callback. Diagnostics
are best-effort and must not change a playback operation's result.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def _disabled() -> int:
    return 0


_level: Callable[[], int] = _disabled
_sink: Callable[[int, str], None] | None = None


def configure(level: Callable[[], int], sink: Callable[[int, str], None]) -> None:
    global _level, _sink
    _level, _sink = level, sink


def record(priority: int, event: str, **measurements: float) -> None:
    """Write static event names and finite numeric details, never media references."""
    try:
        if _sink is None or not 0 < priority <= _level():
            return
        details = " ".join(
            f"{key}={value:g}" for key, value in measurements.items()
            if math.isfinite(value)
        )
        _sink(priority, f"playback {event}" + (f" {details}" if details else ""))
    except Exception:
        # A full disk or broken logging destination must not interrupt playback.
        return


def operation(name: str, *, priority: int = 3) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Record requests at debug, failures at warning, and successful controls at info."""
    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            record(4, f"{name}.requested")
            try:
                result = function(*args, **kwargs)
            except Exception:
                record(2, f"{name}.failed")
                raise
            record(priority, f"{name}.completed")
            return result
        return wrapped
    return decorate
