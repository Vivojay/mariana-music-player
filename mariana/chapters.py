"""Normalization shared by online metadata, downloads, and local probing."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any, cast

_WHITESPACE = re.compile(r"\s+")


def _chapter_title(item: Mapping[str, Any]) -> str:
    value = item.get("title")
    if value is None and isinstance(item.get("tags"), Mapping):
        tags = cast(Mapping[str, Any], item["tags"])
        value = next((candidate for key, candidate in tags.items() if str(key).casefold() == "title"), None)
    return _WHITESPACE.sub(" ", str(value or "")).strip()


def normalize_chapters(value: Any, duration: Any = None) -> list[dict[str, Any]]:
    """Return sorted, finite, non-overlapping chapter dictionaries."""
    if not isinstance(value, list):
        return []
    parsed: list[tuple[str, float, float | None]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        title = _chapter_title(item)
        try:
            start = float(cast(Any, item.get("start_time")))
            end = float(cast(Any, item["end_time"])) if item.get("end_time") is not None else None
        except (TypeError, ValueError):
            continue
        if not title or not math.isfinite(start) or start < 0 or (end is not None and not math.isfinite(end)):
            continue
        parsed.append((title, start, end))
    parsed.sort(key=lambda item: item[1])
    try:
        media_end = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        media_end = None
    if media_end is not None and (not math.isfinite(media_end) or media_end <= 0):
        media_end = None
    normalized = []
    for index, (title, start, end) in enumerate(parsed):
        next_start = parsed[index + 1][1] if index + 1 < len(parsed) else media_end
        if end is None or (next_start is not None and end > next_start):
            end = next_start
        if end is None or end <= start:
            continue
        normalized.append({"title": title, "start_time": start, "end_time": end})
    return normalized
