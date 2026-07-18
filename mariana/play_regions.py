"""Persistent, non-destructive preferred playback regions."""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from itertools import pairwise

from .database import MarianaDatabase
from .models import MediaRef, PlayRegion

_BARE_SECONDS = re.compile(r"^\d+(?:\.\d+)?s?$", re.IGNORECASE)
_CLOCK_FIELD = re.compile(r"^\d+$")
_CLOCK_SECONDS = re.compile(r"^\d+(?:\.\d+)?$")
_LABELED_PART = re.compile(r"(\d+(?:\.\d+)?)(ms|d|h|m|s)", re.IGNORECASE)
_UNIT_SECONDS = {"d": 86400.0, "h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}
_UNIT_ORDER = {unit: index for index, unit in enumerate(("d", "h", "m", "s", "ms"))}


class PlayRegionError(ValueError):
    """Raised when preferred playback bounds cannot be stored or applied."""


@dataclass(frozen=True, slots=True)
class PlayRegionEntry:
    stable_id: str
    start_seconds: float | None
    end_seconds: float | None
    updated_at: float

    @property
    def active(self) -> bool:
        return self.start_seconds is not None or self.end_seconds is not None


def parse_region_time(value: str) -> float:
    """Parse a finite non-negative timestamp with millisecond precision."""
    text = str(value).strip().casefold()
    if not text:
        raise PlayRegionError("Playback bound is empty")
    if text.startswith(("+", "-")):
        raise PlayRegionError("Playback bounds must be non-negative absolute times")

    if _BARE_SECONDS.fullmatch(text):
        seconds = float(text.removesuffix("s"))
    elif ":" in text:
        fields = text.split(":")
        if len(fields) not in {2, 3, 4}:
            raise PlayRegionError("Use MM:SS, HH:MM:SS, or DD:HH:MM:SS")
        if any(not _CLOCK_FIELD.fullmatch(field) for field in fields[:-1]) or not _CLOCK_SECONDS.fullmatch(
            fields[-1]
        ):
            raise PlayRegionError("Clock fields must be numeric")
        multipliers = {
            2: (60.0, 1.0),
            3: (3600.0, 60.0, 1.0),
            4: (86400.0, 3600.0, 60.0, 1.0),
        }[len(fields)]
        seconds = sum(float(field) * multiplier for field, multiplier in zip(fields, multipliers, strict=True))
    else:
        compact = re.sub(r"\s+", "", text)
        matches = list(_LABELED_PART.finditer(compact))
        if not matches or "".join(match.group(0) for match in matches) != compact:
            raise PlayRegionError("Use seconds, clock notation, or labeled d/h/m/s/ms values")
        units = [match.group(2).casefold() for match in matches]
        if len(set(units)) != len(units) or any(
            _UNIT_ORDER[current] >= _UNIT_ORDER[following]
            for current, following in pairwise(units)
        ):
            raise PlayRegionError("Playback-bound units must be unique and ordered d, h, m, s, ms")
        seconds = sum(float(match.group(1)) * _UNIT_SECONDS[match.group(2).casefold()] for match in matches)

    if not math.isfinite(seconds) or seconds < 0:
        raise PlayRegionError("Playback bound must be a finite non-negative time")
    return round(seconds, 3)


def format_region_time(seconds: float | None) -> str:
    if seconds is None:
        return "natural"
    milliseconds = max(0, round(float(seconds) * 1000))
    whole, fraction = divmod(milliseconds, 1000)
    hours, remainder = divmod(whole, 3600)
    minutes, value = divmod(remainder, 60)
    suffix = f".{fraction:03d}" if fraction else ""
    return f"{hours}:{minutes:02d}:{value:02d}{suffix}" if hours else f"{minutes}:{value:02d}{suffix}"


def validate_region(
    stable_id: str,
    *,
    start_seconds: float | None,
    end_seconds: float | None,
    duration: float | None,
) -> PlayRegion:
    start = None if start_seconds is None else round(float(start_seconds), 3)
    end = None if end_seconds is None else round(float(end_seconds), 3)
    if start is not None and (not math.isfinite(start) or start < 0):
        raise PlayRegionError("Start bound must be a finite non-negative time")
    if end is not None and (not math.isfinite(end) or end <= 0):
        raise PlayRegionError("End bound must be a finite positive time")
    if start is not None and end is not None and end <= start:
        raise PlayRegionError("End bound must be after the start bound")
    try:
        known_duration = float(duration) if duration is not None else None
    except (TypeError, ValueError, OverflowError):
        known_duration = None
    if known_duration is None or not math.isfinite(known_duration) or known_duration <= 0:
        raise PlayRegionError("A finite known media duration is required for playback bounds")
    if start is not None and start >= known_duration:
        raise PlayRegionError("Start bound must be before the media duration")
    if end is not None and end > known_duration:
        raise PlayRegionError("End bound exceeds the media duration")
    return PlayRegion(stable_id=stable_id, start_seconds=start, end_seconds=end)


class PlayRegionStore:
    def __init__(self, database: MarianaDatabase):
        self.database = database

    def get(self, media_or_id: MediaRef | str) -> PlayRegion | None:
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
        row = self.database.fetchone(
            "SELECT start_ms,end_ms FROM media_play_regions WHERE stable_id=?", (stable_id,)
        )
        if row is None:
            return None
        return PlayRegion(
            stable_id,
            None if row["start_ms"] is None else row["start_ms"] / 1000.0,
            None if row["end_ms"] is None else row["end_ms"] / 1000.0,
        )

    def set(
        self,
        media_or_id: MediaRef | str,
        *,
        start_seconds: float | None,
        end_seconds: float | None,
        duration: float | None,
    ) -> PlayRegion:
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
        region = validate_region(
            stable_id,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            duration=duration,
        )
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO media_play_regions(stable_id,start_ms,end_ms,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(stable_id) DO UPDATE SET start_ms=excluded.start_ms, "
                "end_ms=excluded.end_ms, updated_at=excluded.updated_at",
                (
                    stable_id,
                    None if region.start_seconds is None else round(region.start_seconds * 1000),
                    None if region.end_seconds is None else round(region.end_seconds * 1000),
                    time.time(),
                ),
            )
        return region

    def clear(self, media_or_id: MediaRef | str) -> bool:
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM media_play_regions WHERE stable_id=?", (stable_id,))
        return bool(cursor.rowcount)

    def clear_bound(self, media_or_id: MediaRef | str, bound: str) -> PlayRegion | None:
        current = self.get(media_or_id)
        if current is None:
            return None
        start = None if bound == "start" else current.start_seconds
        end = None if bound == "end" else current.end_seconds
        if start is None and end is None:
            self.clear(media_or_id)
            return None
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE media_play_regions SET start_ms=?,end_ms=?,updated_at=? WHERE stable_id=?",
                (
                    None if start is None else round(start * 1000),
                    None if end is None else round(end * 1000),
                    time.time(),
                    stable_id,
                ),
            )
        return self.get(stable_id)

    def list(self) -> list[PlayRegionEntry]:
        return [
            PlayRegionEntry(
                stable_id=row["stable_id"],
                start_seconds=None if row["start_ms"] is None else row["start_ms"] / 1000.0,
                end_seconds=None if row["end_ms"] is None else row["end_ms"] / 1000.0,
                updated_at=float(row["updated_at"]),
            )
            for row in self.database.fetchall(
                "SELECT stable_id,start_ms,end_ms,updated_at FROM media_play_regions "
                "ORDER BY updated_at DESC,stable_id ASC"
            )
        ]
