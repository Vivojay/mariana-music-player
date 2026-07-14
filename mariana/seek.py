"""Pure parsing for Mariana's human-friendly seek targets."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

END_MARGIN_SECONDS = 0.25
_UNITS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0}
_UNIT_ORDER = {unit: index for index, unit in enumerate(("d", "h", "m", "s"))}
_RELATIVE = re.compile(r"^([+-])(\d+)([dhms]?)$", re.IGNORECASE)
_LABELED = re.compile(r"^(\d+)([dhms])$", re.IGNORECASE)
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")


class SeekSyntaxError(ValueError):
    """Raised when a seek target is ambiguous or cannot be applied safely."""


@dataclass(frozen=True, slots=True)
class SeekTarget:
    seconds: float
    display: str


def _known_duration(duration: float | None) -> float:
    if duration is None:
        raise SeekSyntaxError("This seek form requires a known media duration")
    value = float(duration)
    if not math.isfinite(value) or value <= 0:
        raise SeekSyntaxError("The current media duration is unavailable")
    return value


def _safe_end(duration: float) -> float:
    margin = min(END_MARGIN_SECONDS, duration / 2)
    return max(0.0, duration - margin)


def format_seek_position(seconds: float) -> str:
    total_milliseconds = max(0, round(float(seconds) * 1000))
    whole_seconds, milliseconds = divmod(total_milliseconds, 1000)
    days, remainder = divmod(whole_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, value = divmod(remainder, 60)
    second_text = f"{value:02d}" if not milliseconds else f"{value:02d}.{milliseconds:03d}".rstrip("0")
    if days:
        return f"{days}d {hours:02d}:{minutes:02d}:{second_text}"
    if hours:
        return f"{hours:02d}:{minutes:02d}:{second_text}"
    return f"{minutes:02d}:{second_text}"


def _absolute_target(value: float, duration: float | None) -> float:
    if value < 0:
        raise SeekSyntaxError("Seek target must not be negative")
    if duration is None:
        return value
    known = _known_duration(duration)
    if value > known:
        raise SeekSyntaxError("Seek target exceeds the current media duration")
    return _safe_end(known) if value == known else value


def _relative_target(delta: float, position: float, duration: float | None) -> float:
    current = float(position)
    if not math.isfinite(current):
        raise SeekSyntaxError("The current playback position is unavailable")
    target = max(0.0, current + delta)
    if duration is not None:
        target = min(target, _safe_end(_known_duration(duration)))
    return target


def _colon_seconds(value: str) -> float:
    fields = value.split(":")
    if len(fields) not in {2, 3, 4} or not any(fields):
        raise SeekSyntaxError("Use MM:SS, HH:MM:SS, or DD:HH:MM:SS")
    if any(field and not field.isdigit() for field in fields):
        raise SeekSyntaxError("Colon-separated seek fields must be whole numbers")
    numbers = [int(field or 0) for field in fields]
    multipliers = {
        2: (60, 1),
        3: (3600, 60, 1),
        4: (86400, 3600, 60, 1),
    }[len(numbers)]
    return float(sum(number * multiplier for number, multiplier in zip(numbers, multipliers, strict=True)))


def _labeled_seconds(arguments: Sequence[str]) -> float:
    total = 0.0
    previous_order = -1
    seen: set[str] = set()
    for argument in arguments:
        match = _LABELED.fullmatch(argument)
        if not match:
            raise SeekSyntaxError("Use labeled values such as 1d 2h 3m 4s")
        amount, unit = match.groups()
        unit = unit.casefold()
        order = _UNIT_ORDER[unit]
        if unit in seen or order <= previous_order:
            raise SeekSyntaxError("Seek units must be unique and ordered as d, h, m, s")
        seen.add(unit)
        previous_order = order
        total += int(amount) * _UNITS[unit]
    return total


def parse_seek_target(
    arguments: Sequence[str],
    *,
    position: float = 0.0,
    duration: float | None = None,
) -> SeekTarget:
    """Resolve CLI seek arguments into one safe absolute playback position."""
    values = [str(value).strip().casefold() for value in arguments]
    if not values or any(not value for value in values):
        raise SeekSyntaxError("Usage: seek <time|relative|percent|start|end>")

    if len(values) > 1:
        target = _absolute_target(_labeled_seconds(values), duration)
        return SeekTarget(target, format_seek_position(target))

    value = values[0]
    if value == "start":
        return SeekTarget(0.0, format_seek_position(0))
    if value == "end":
        target = _safe_end(_known_duration(duration))
        return SeekTarget(target, format_seek_position(target))

    if match := _PERCENT.fullmatch(value):
        percent = float(match.group(1))
        if not 0 <= percent <= 100:
            raise SeekSyntaxError("Seek percentage must be between 0 and 100")
        known = _known_duration(duration)
        target = known * percent / 100
        if percent == 100:
            target = _safe_end(known)
        return SeekTarget(target, format_seek_position(target))

    if match := _RELATIVE.fullmatch(value):
        sign, amount, unit = match.groups()
        delta = int(amount) * _UNITS.get(unit.casefold(), 1.0)
        if sign == "-":
            delta = -delta
        target = _relative_target(delta, position, duration)
        return SeekTarget(target, format_seek_position(target))

    if ":" in value:
        target = _absolute_target(_colon_seconds(value), duration)
        return SeekTarget(target, format_seek_position(target))

    if value.isdigit():
        target = _absolute_target(float(value), duration)
        return SeekTarget(target, format_seek_position(target))

    if _LABELED.fullmatch(value):
        target = _absolute_target(_labeled_seconds(values), duration)
        return SeekTarget(target, format_seek_position(target))

    raise SeekSyntaxError("Invalid seek target; use seconds, clock fields, units, percent, start, or end")
