"""Canonical video view model shared by every Mariana video surface.

The Electron mini-player (`MiniPlayerVideo.tsx`) and the standalone CLI
window (`CliVideoWindow`) render through different runtimes (browser
`<video>` vs. an `ffplay` child process), so the renderers cannot be one
source file. This module is the canonical contract instead: identical
constants, identical clamping, identical reset semantics, with conformance
tests on both sides asserting the same numbers. Any view behavior change
starts here.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_ZOOM = 1.0
MAX_ZOOM = 4.0
ZOOM_STEP = 1.25


def clamp_pan(value: float, stage_size: float, zoom: float) -> float:
    """Clamp a pan offset so the zoomed picture always covers the stage."""
    try:
        numeric = float(value)
        size = max(0.0, float(stage_size))
        factor = max(MIN_ZOOM, float(zoom))
    except (TypeError, ValueError):
        return 0.0
    limit = max(0.0, (size * factor - size) / 2.0)
    return min(limit, max(-limit, numeric))


def zoom_step(current: float, direction: int) -> float:
    """Step the zoom in (+1) or out (-1), clamped to [MIN_ZOOM, MAX_ZOOM]."""
    try:
        factor = ZOOM_STEP if direction >= 0 else 1.0 / ZOOM_STEP
        return min(MAX_ZOOM, max(MIN_ZOOM, float(current) * factor))
    except (TypeError, ValueError):
        return MIN_ZOOM


@dataclass(slots=True)
class ViewTransform:
    """Zoom/pan state for one media item; resets when the media changes."""

    media_id: str | None = None
    x: float = 0.0
    y: float = 0.0
    zoom: float = MIN_ZOOM

    def reset(self, media_id: str | None) -> None:
        self.media_id = media_id
        self.x = 0.0
        self.y = 0.0
        self.zoom = MIN_ZOOM

    @property
    def is_default(self) -> bool:
        return self.zoom == MIN_ZOOM and self.x == 0.0 and self.y == 0.0


def crop_filter(zoom: float, x: float, y: float) -> str | None:
    """Translate a view into an ffplay `-vf` fragment, or None when default.

    Pan offsets are normalized to [-0.5, 0.5] of the zoomed overflow, matching
    clamp_pan semantics on a unit stage.
    """
    try:
        factor = min(MAX_ZOOM, max(MIN_ZOOM, float(zoom)))
    except (TypeError, ValueError):
        return None
    if factor == MIN_ZOOM:
        return None
    try:
        nx = min(0.5, max(-0.5, float(x)))
        ny = min(0.5, max(-0.5, float(y)))
    except (TypeError, ValueError):
        nx = ny = 0.0
    # Crop a 1/factor window out of the scaled picture; offsets move it.
    ox = f"(in_w-out_w)*({0.5 + nx:.4f})"
    oy = f"(in_h-out_h)*({0.5 + ny:.4f})"
    return f"scale=iw*{factor:.4f}:ih*{factor:.4f},crop=iw/{factor:.4f}:ih/{factor:.4f}:{ox}:{oy}"
