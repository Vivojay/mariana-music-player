"""Bounded parsing and position selection for synchronized lyrics."""

from __future__ import annotations

import math
import re
from bisect import bisect_right
from dataclasses import dataclass, field

from .models import IdentityStatus, LyricsResult

MAX_SYNCED_LYRICS_CHARACTERS = 1_000_000
MAX_TIMED_LYRIC_LINES = 10_000
MAX_USER_OFFSET_MS = 60_000

_TIMESTAMP = re.compile(r"\[(?P<minutes>\d{1,4}):(?P<seconds>\d{1,2})(?:[.:](?P<fraction>\d{1,3}))?\]")
_OFFSET = re.compile(r"^\[offset\s*:\s*(?P<offset>[+-]?\d+)\]\s*$", re.IGNORECASE)


class LyricsTimelineError(ValueError):
    """Raised when synchronized lyrics cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class TimedLyricLine:
    """One lyric cue at its source timestamp, before display correction."""

    start_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class LyricsCursor:
    """The lyric cue selected for one authoritative playback position."""

    position_ms: int
    active_index: int | None
    active: TimedLyricLine | None
    previous: TimedLyricLine | None
    following: TimedLyricLine | None
    effective_start_ms: int | None
    effective_end_ms: int | None


@dataclass(frozen=True, slots=True)
class LyricsTimeline:
    """Immutable timed lyrics bound to one stable media identity."""

    stable_id: str
    lines: tuple[TimedLyricLine, ...]
    source_offset_ms: int = 0
    duration_ms: int | None = None
    provider: str | None = None
    attribution: str | None = None
    _timestamps: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_timestamps", tuple(line.start_ms for line in self.lines))

    def cursor(self, position_seconds: float, *, user_offset_ms: int = 0) -> LyricsCursor:
        position_ms = _position_ms(position_seconds)
        correction = self.source_offset_ms + validate_user_offset(user_offset_ms)
        index = bisect_right(self._timestamps, position_ms - correction) - 1
        if index < 0 or not self.lines:
            return LyricsCursor(
                position_ms,
                None,
                None,
                None,
                self.lines[0] if self.lines else None,
                None,
                _effective_time(self.lines[0].start_ms, correction) if self.lines else None,
            )

        if self.duration_ms is not None and position_ms > self.duration_ms:
            return LyricsCursor(position_ms, None, None, self.lines[-1], None, None, None)

        line = self.lines[index]
        following = self.lines[index + 1] if index + 1 < len(self.lines) else None
        effective_end = (
            _effective_time(following.start_ms, correction)
            if following is not None
            else self.duration_ms
        )
        return LyricsCursor(
            position_ms,
            index,
            line,
            self.lines[index - 1] if index else None,
            following,
            _effective_time(line.start_ms, correction),
            effective_end,
        )


def validate_user_offset(offset_ms: int) -> int:
    """Validate an explicit display correction without changing source timing."""

    if isinstance(offset_ms, bool) or not isinstance(offset_ms, int):
        raise LyricsTimelineError("Lyrics offset must be an integer number of milliseconds")
    if abs(offset_ms) > MAX_USER_OFFSET_MS:
        raise LyricsTimelineError(
            f"Lyrics offset must be between {-MAX_USER_OFFSET_MS} and {MAX_USER_OFFSET_MS} ms"
        )
    return offset_ms


def parse_lrc(
    value: str,
    *,
    stable_id: str,
    duration_seconds: float | None = None,
    provider: str | None = None,
    attribution: str | None = None,
) -> LyricsTimeline:
    """Parse line-synchronized LRC while retaining intentional blank cues."""

    if not isinstance(value, str):
        raise LyricsTimelineError("Synchronized lyrics must be text")
    if len(value) > MAX_SYNCED_LYRICS_CHARACTERS:
        raise LyricsTimelineError("Synchronized lyrics exceed the supported size")
    stable_id = stable_id.strip()
    if not stable_id:
        raise LyricsTimelineError("Synchronized lyrics require a stable media identity")

    source_offset_ms = 0
    cues: dict[int, list[str]] = {}
    cue_count = 0
    for raw_line in value.removeprefix("\ufeff").splitlines():
        offset_match = _OFFSET.fullmatch(raw_line.strip())
        if offset_match:
            try:
                offset = int(offset_match.group("offset"))
            except ValueError as error:
                raise LyricsTimelineError("Source lyrics offset exceeds the supported range") from error
            source_offset_ms = _bounded_source_offset(offset)
            continue

        matches = tuple(_TIMESTAMP.finditer(raw_line))
        if not matches:
            continue
        text = _TIMESTAMP.sub("", raw_line).strip()
        for match in matches:
            seconds = int(match.group("seconds"))
            if seconds >= 60:
                continue
            timestamp_ms = int(match.group("minutes")) * 60_000 + seconds * 1_000
            timestamp_ms += _fraction_ms(match.group("fraction"))
            bucket = cues.setdefault(timestamp_ms, [])
            if text not in bucket:
                bucket.append(text)
                cue_count += 1
                if cue_count > MAX_TIMED_LYRIC_LINES:
                    raise LyricsTimelineError("Synchronized lyrics contain too many cues")

    lines = tuple(
        TimedLyricLine(timestamp_ms, "\n".join(texts))
        for timestamp_ms, texts in sorted(cues.items())
    )
    if not lines:
        raise LyricsTimelineError("No valid synchronized lyric timestamps were found")
    return LyricsTimeline(
        stable_id=stable_id,
        lines=lines,
        source_offset_ms=source_offset_ms,
        duration_ms=_duration_ms(duration_seconds),
        provider=provider,
        attribution=attribution,
    )


def timeline_from_result(
    stable_id: str,
    result: LyricsResult,
    *,
    duration_seconds: float | None = None,
) -> LyricsTimeline | None:
    """Build a timeline from a provider result; malformed sync data stays nonfatal."""

    if result.status != IdentityStatus.IDENTIFIED or not result.synced:
        return None
    try:
        return parse_lrc(
            result.synced,
            stable_id=stable_id,
            duration_seconds=duration_seconds,
            provider=result.provider,
            attribution=result.attribution,
        )
    except LyricsTimelineError:
        return None


def _position_ms(value: float) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LyricsTimelineError("Playback position must be finite")
    return max(0, round(float(value) * 1_000))


def _duration_ms(value: float | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise LyricsTimelineError("Media duration must be finite")
    if value < 0:
        raise LyricsTimelineError("Media duration cannot be negative")
    return round(float(value) * 1_000)


def _fraction_ms(value: str | None) -> int:
    if not value:
        return 0
    return int(value.ljust(3, "0"))


def _bounded_source_offset(value: int) -> int:
    if abs(value) > MAX_USER_OFFSET_MS:
        raise LyricsTimelineError("Source lyrics offset exceeds the supported range")
    return value


def _effective_time(timestamp_ms: int, correction_ms: int) -> int:
    return max(0, timestamp_ms + correction_ms)
