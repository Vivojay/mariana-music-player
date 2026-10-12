"""Shared helpers for the feature pack (net/query/cache/chapters/console-art).

Kept dependency-light so main.py can import without cycles. Functions take
explicit arguments; main.py wires authoritative singletons.
"""

from __future__ import annotations

import re


def parse_rate_filter(value: str) -> tuple[int, int] | None:
    """Parse `5` or `3-5` into an inclusive (low, high) star range."""
    text = (value or "").strip()
    if re.fullmatch(r"[0-5]", text):
        number = int(text)
        if number == 0:
            return None
        return (number, number)
    match = re.fullmatch(r"([0-5])\s*-\s*([0-5])", text)
    if not match:
        raise ValueError("Rate filter must be a star 1-5 or a range like 3-5")
    low, high = int(match.group(1)), int(match.group(2))
    if low == 0 or high == 0:
        raise ValueError("Rate range uses stars 1-5 (0 means unrated; use --unrated)")
    if low > high:
        low, high = high, low
    return (low, high)


def parse_tag_list(values: list[str]) -> list[str]:
    tags: list[str] = []
    for value in values:
        for chunk in value.split(","):
            name = chunk.strip()
            if name and name not in tags:
                tags.append(name)
    return tags[:20]


def ascii_art_placeholder(width: int = 48, height: int = 16) -> str:
    """Fallback console preview frame when no pixels are available."""
    width = max(16, min(120, width))
    height = max(4, min(40, height))
    shades = " .:-=+*#%@"
    lines: list[str] = []
    for row in range(height):
        line = "".join(shades[(row * 3 + col) % len(shades)] for col in range(0, width, 2))
        lines.append(line)
    border = "+" + "-" * (len(lines[0])) + "+"
    return "\n".join([border, *[f"|{line}|" for line in lines], border])


def describe_region_live_apply(label: str, start: float | None, end: float | None) -> str:
    from mariana.play_regions import format_region_time

    return (
        f"Preferred play region live-applied for {label}: "
        f"{format_region_time(start)} -> {format_region_time(end)}. "
        "Current playback re-clamped without restart."
    )
