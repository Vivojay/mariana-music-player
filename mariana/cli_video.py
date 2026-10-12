"""Standalone-CLI video window: a spawned ffplay picture linked to the session.

Desktop builds keep using the in-app video window. When no desktop host is
present, `video open` spawns an OS-level ffplay window (video only, `-an`,
so CLI audio never doubles) and a monitor thread keeps it linked to the
triggering session: track changes reopen it, pause hides it, resume/seek
reopen at the live position, stop closes it. A video clock tracks the
picture independently of the audio clock; drift beyond tolerance re-anchors
the window, so holding/dragging the window (which stalls ffplay's own
render loop) self-heals on release instead of staying behind.
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass

from mariana.video_view import MAX_ZOOM, MIN_ZOOM, ViewTransform, clamp_pan, crop_filter, zoom_step


@dataclass(slots=True)
class CliVideoStatus:
    open: bool
    follow: bool
    media_id: str | None = None
    title: str | None = None
    backend: str = "ffplay"
    zoom: float = MIN_ZOOM
    fullscreen: bool = False
    subtitles: str | None = None


class CliVideoWindow:
    POLL_SECONDS = 1.0
    SEEK_TOLERANCE = 4.0
    REOPEN_COOLDOWN = 2.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._stderr_lines: deque[str] = deque(maxlen=30)
        self._stderr_head: list[str] = []
        self._media_id: str | None = None
        self._title: str | None = None
        self._follow = False
        self._paused_hidden = False
        self._last_change = 0.0
        self._last_error: str | None = None
        self._last_pos: float | None = None
        self._last_tick = 0.0
        self._view = ViewTransform()
        self._fullscreen = False
        self._size: tuple[int | None, int | None] | None = None
        self._subtitle_path: str | None = None
        self._video_clock = 0.0
        self._video_clock_at = 0.0
        self._monitor: threading.Thread | None = None
        self._snapshot_fn = None
        self._resolve_fn = None
        self._ffplay_fn = None
        self._announce_fn = None

    # -- wiring ----------------------------------------------------------
    def configure(self, *, snapshot_fn, resolve_fn, ffplay_fn, announce_fn) -> None:
        with self._lock:
            self._snapshot_fn = snapshot_fn
            self._resolve_fn = resolve_fn
            self._ffplay_fn = ffplay_fn
            self._announce_fn = announce_fn

    # -- public control --------------------------------------------------
    def open(self, *, follow: bool = True) -> CliVideoStatus:
        snapshot = self._snapshot()
        media = getattr(snapshot, "media", None) if snapshot else None
        if media is None:
            raise ValueError("No current media for video")
        self._open_for(media, getattr(snapshot, "position", 0.0) or 0.0, follow=follow)
        return self.status()

    def close(self) -> CliVideoStatus:
        with self._lock:
            self._follow = False
            self._paused_hidden = False
        self._terminate()
        return self.status()

    def follow(self, media) -> None:
        """Called on every playback commit; reopens when following."""
        with self._lock:
            if not self._follow or media is None:
                return
            if self._media_id == getattr(media, "stable_id", None) and self._running_locked():
                return
        worker = threading.Thread(
            target=self._safe_reopen,
            args=(media,),
            name="mariana-cli-video-follow",
            daemon=True,
        )
        worker.start()

    def status(self) -> CliVideoStatus:
        with self._lock:
            return CliVideoStatus(
                open=self._running_locked(),
                follow=self._follow,
                media_id=self._media_id,
                title=self._title,
                zoom=self._view.zoom,
                fullscreen=self._fullscreen,
                subtitles=self._subtitle_path,
            )

    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def sync_status(self) -> dict[str, float | None]:
        """Audio clock vs. picture clock snapshot for drift inspection."""
        snapshot = self._snapshot()
        try:
            audio = float(getattr(snapshot, "position", 0.0) or 0.0)
        except (TypeError, ValueError):
            audio = 0.0
        with self._lock:
            video = self._video_clock
        return {"audio_seconds": audio, "video_seconds": video, "drift_seconds": audio - video}

    # -- canonical view (mirrors MiniPlayerVideo semantics) --------------
    def set_zoom(self, value: float | str) -> CliVideoStatus:
        """Set 1-4, or in/out/reset; reopens anchored when the window runs."""
        with self._lock:
            current = self._view.zoom
        if isinstance(value, str):
            lowered = value.casefold()
            if lowered == "reset":
                target = MIN_ZOOM
            elif lowered in {"in", "+"}:
                target = zoom_step(current, 1)
            elif lowered in {"out", "-"}:
                target = zoom_step(current, -1)
            else:
                try:
                    target = min(MAX_ZOOM, max(MIN_ZOOM, float(value)))
                except (TypeError, ValueError):
                    raise ValueError("Usage: video zoom <1-4|in|out|reset>") from None
        else:
            try:
                target = min(MAX_ZOOM, max(MIN_ZOOM, float(value)))
            except (TypeError, ValueError):
                raise ValueError("Usage: video zoom <1-4|in|out|reset>") from None
        return self._apply_view(zoom=target)

    def set_pan(self, dx: float, dy: float) -> CliVideoStatus:
        """Pan in normalized units; clamped exactly like the app surface."""
        with self._lock:
            zoom = self._view.zoom
            x = clamp_pan(self._view.x + float(dx), 1.0, zoom)
            y = clamp_pan(self._view.y + float(dy), 1.0, zoom)
        return self._apply_view(x=x, y=y)

    def reset_view(self) -> CliVideoStatus:
        return self._apply_view(zoom=MIN_ZOOM, x=0.0, y=0.0)

    def set_fullscreen(self, mode: bool | str = True) -> CliVideoStatus:
        if isinstance(mode, str):
            lowered = mode.casefold()
            if lowered in {"on", "yes", "true", "1"}:
                mode = True
            elif lowered in {"off", "no", "false", "0"}:
                mode = False
            elif lowered == "toggle":
                with self._lock:
                    mode = not self._fullscreen
            else:
                raise ValueError("Usage: video fullscreen [on|off|toggle]")
        with self._lock:
            if bool(mode) == self._fullscreen:
                return self.status()
            self._fullscreen = bool(mode)
        return self._reopen_anchored("fullscreen")

    def set_size(self, width: int | None, height: int | None) -> CliVideoStatus:
        if width is None and height is None:
            with self._lock:
                self._size = None
            return self._reopen_anchored("size reset")
        try:
            size = (
                max(160, min(7680, int(width))) if width is not None else None,
                max(90, min(4320, int(height))) if height is not None else None,
            )
        except (TypeError, ValueError):
            raise ValueError("Usage: video resize <width>x<height>|reset>") from None
        with self._lock:
            self._size = size
        return self._reopen_anchored("size")

    def set_subtitles(self, path: str | None) -> CliVideoStatus:
        with self._lock:
            self._subtitle_path = path
        return self._reopen_anchored("subtitles")

    def _apply_view(
        self, *, zoom: float | None = None, x: float | None = None, y: float | None = None
    ) -> CliVideoStatus:
        with self._lock:
            if zoom is not None:
                self._view.zoom = zoom
            if x is not None:
                self._view.x = x
            if y is not None:
                self._view.y = y
            running = self._running_locked()
        if not running:
            return self.status()
        return self._reopen_anchored("view")

    def _reopen_anchored(self, _reason: str) -> CliVideoStatus:
        snapshot = self._snapshot()
        media = getattr(snapshot, "media", None) if snapshot else None
        if media is None:
            return self.status()
        try:
            position = float(getattr(snapshot, "position", 0.0) or 0.0)
        except (TypeError, ValueError):
            position = 0.0
        with self._lock:
            follow = self._follow
        try:
            self._open_for(media, position, follow=follow)
        except (ValueError, RuntimeError, OSError) as error:
            with self._lock:
                self._last_error = str(error)[:300]
            raise
        return self.status()

    # -- internals -------------------------------------------------------
    def _snapshot(self):
        try:
            return self._snapshot_fn() if self._snapshot_fn else None
        except (AttributeError, RuntimeError, ValueError, OSError):
            return None

    def _running_locked(self) -> bool:
        process = self._process
        if process is None:
            return False
        try:
            return process.poll() is None
        except (OSError, ValueError):
            return False

    def _terminate(self) -> None:
        with self._lock:
            process, self._process = self._process, None
        if process is None:
            return
        with suppress(OSError, RuntimeError, ValueError):
            process.terminate()
        try:
            process.wait(timeout=3)
        except (OSError, RuntimeError, ValueError):
            with suppress(OSError, RuntimeError, ValueError):
                process.kill()

    def _ffplay_bin(self) -> str:
        hint = None
        fn = self._ffplay_fn
        if callable(fn):
            try:
                hint = fn()  # type: ignore[operator]
            except (AttributeError, RuntimeError, ValueError, OSError, TypeError):
                hint = None
        if hint:
            return str(hint)
        found = shutil.which("ffplay") or shutil.which("ffplay.exe")
        if not found:
            raise ValueError("ffplay is unavailable (install FFmpeg incl. ffplay or configure the toolchain)")
        return found

    def _open_for(self, media, position: float, *, follow: bool) -> None:
        try:
            uri, headers = self._resolve_fn(media)
        except (AttributeError, RuntimeError, ValueError, OSError, TypeError) as error:
            raise ValueError(f"Video unavailable for this media: {error}") from error
        if not uri:
            raise ValueError("Audio-only media has no video picture")
        command = [
            self._ffplay_bin(),
            "-hide_banner",
            "-an",
            "-reconnect",
            "1",
            "-reconnect_streamed",
            "1",
            "-reconnect_delay_max",
            "5",
            "-window_title",
            f"Mariana - {getattr(media, 'title', None) or 'video'}",
        ]
        with self._lock:
            if getattr(media, "stable_id", None) != self._media_id:
                self._view.reset(getattr(media, "stable_id", None))
                self._subtitle_path = None
            view_filter = crop_filter(self._view.zoom, self._view.x, self._view.y)
            filters: list[str] = []
            if view_filter:
                filters.append(view_filter)
            subtitle = self._subtitle_path
            if subtitle:
                filters.append(f"subtitles={_escape_subtitle_filter(subtitle)}")
            size = self._size
            fullscreen = self._fullscreen
        if filters:
            command += ["-vf", ",".join(filters)]
        if size is not None and (size[0] is not None or size[1] is not None):
            command += ["-x", str(size[0] or -1), "-y", str(size[1] or -1)]
        if fullscreen:
            command.append("-fs")
        try:
            at = max(0.0, float(position or 0.0))
        except (TypeError, ValueError):
            at = 0.0
        if at > 1.0:
            command += ["-ss", f"{at:.3f}"]
        header_lines = "".join(
            f"{key}: {value}\r\n"
            for key, value in (headers or {}).items()
            if str(key).casefold() not in {"authorization", "cookie", "cookie2"}
        )
        if header_lines:
            command += ["-headers", header_lines]
        command.append(uri)
        self._terminate()
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise ValueError(f"Video window could not start: {error}") from error
        with self._lock:
            self._stderr_lines.clear()
            self._stderr_head = []
            self._last_error = None
        drain = threading.Thread(target=self._drain_stderr, args=(process,), name="mariana-cli-video-log", daemon=True)
        drain.start()
        # Honest startup: ffplay exits fast on bad URLs/headers/codecs. Never
        # claim success while the window is already gone. Report the head of
        # the log (the actual error) plus the tail, not just the tail.
        time.sleep(1.5)
        if process.poll() is not None:
            with suppress(OSError, ValueError):
                process.wait(timeout=2)
            with self._lock:
                head = " ".join(self._stderr_head)[:1500]
                tail = " ".join(self._stderr_lines)[-400:]
            detail = head
            if tail and tail not in detail:
                detail = f"{detail} ... {tail}" if detail else tail
            self._terminate()
            with self._lock:
                self._last_error = detail or "ffplay exited immediately"
            raise ValueError(f"Video window exited immediately: {detail or 'no ffplay output'}")
        with self._lock:
            self._process = process
            self._media_id = getattr(media, "stable_id", None)
            self._title = getattr(media, "title", None)
            self._follow = follow
            self._paused_hidden = False
            self._last_change = time.time()
            self._last_pos = at
            self._last_tick = time.time()
            self._video_clock = at
            self._video_clock_at = time.time()
        self._ensure_monitor()

    def _drain_stderr(self, process: subprocess.Popen) -> None:
        try:
            stream = getattr(process, "stderr", None)
            if stream is None:
                return
            for line in iter(stream.readline, b""):
                try:
                    text = line.decode("utf-8", errors="replace").strip()
                except (AttributeError, ValueError):
                    continue
                if text:
                    with self._lock:
                        if len(self._stderr_head) < 8:
                            self._stderr_head.append(text)
                        self._stderr_lines.append(text)
        except (OSError, ValueError):
            return

    def _safe_reopen(self, media) -> None:
        try:
            snapshot = self._snapshot()
            position = getattr(snapshot, "position", 0.0) or 0.0
            with self._lock:
                follow = self._follow
            self._open_for(media, position, follow=follow)
            self._announce(f"Video window follows: {getattr(media, 'title', None) or 'media'}.")
        except (ValueError, RuntimeError, OSError) as error:
            with self._lock:
                self._last_error = str(error)[:300]
            self._announce(f"Video window could not follow: {error}")

    def _announce(self, message: str) -> None:
        try:
            if self._announce_fn:
                self._announce_fn(message)
        except (AttributeError, RuntimeError, ValueError, OSError, TypeError):
            pass

    def _ensure_monitor(self) -> None:
        with self._lock:
            if self._monitor is not None and self._monitor.is_alive():
                return
            self._monitor = threading.Thread(target=self._monitor_loop, name="mariana-cli-video-monitor", daemon=True)
        self._monitor.start()

    def _monitor_loop(self) -> None:
        while True:
            time.sleep(self.POLL_SECONDS)
            try:
                self._tick()
            except (AttributeError, RuntimeError, ValueError, OSError, TypeError):
                continue

    def _tick(self) -> None:
        with self._lock:
            if not self._follow and not self._running_locked():
                return
            follow = self._follow
        snapshot = self._snapshot()
        media = getattr(snapshot, "media", None) if snapshot else None
        state = str(getattr(snapshot, "state", "") or "").upper()
        now = time.time()
        with self._lock:
            running = self._running_locked()
            current_id = self._media_id
        if not follow:
            return
        if media is None or "STOP" in state or "FAIL" in state:
            if running:
                self._terminate()
                with self._lock:
                    self._media_id = None
                    self._title = None
                    self._paused_hidden = False
            return
        if not running:
            # User closed the window by hand: stop following quietly.
            if current_id is not None and now - self._last_change > self.REOPEN_COOLDOWN:
                with self._lock:
                    self._follow = False
                    self._media_id = None
                    self._paused_hidden = False
            return
        if getattr(media, "stable_id", None) != current_id:
            self._safe_reopen(media)
            return
        if "PAUS" in state:
            with self._lock:
                self._paused_hidden = True
            self._terminate()
            return
        with self._lock:
            paused_hidden = self._paused_hidden
        try:
            position = float(getattr(snapshot, "position", 0.0) or 0.0)
        except (TypeError, ValueError):
            return
        if paused_hidden and "PLAY" in state:
            self._safe_reopen(media)
            return
        with self._lock:
            last_pos = self._last_pos
            last_tick = self._last_tick
            self._last_pos = position
            self._last_tick = now
            cooled = now - self._last_change > self.REOPEN_COOLDOWN
            # Advance the independent picture clock while it renders; freeze
            # it while paused/hidden so drag stalls show up as drift.
            if self._running_locked() and "PLAY" in state and not paused_hidden:
                elapsed = max(0.0, now - self._video_clock_at) if self._video_clock_at else 0.0
                self._video_clock += min(elapsed, 2 * self.POLL_SECONDS)
            self._video_clock_at = now
            video_clock = self._video_clock
        if last_pos is None or last_tick <= 0 or not cooled:
            return
        expected = last_pos + max(0.0, now - last_tick)
        if abs(position - expected) > self.SEEK_TOLERANCE:
            self._safe_reopen(media)
            return
        if abs(position - video_clock) > self.SEEK_TOLERANCE:
            # Picture lags/leads the audio clock (e.g. after the window was
            # dragged, which stalls ffplay's render loop): re-anchor it.
            self._safe_reopen(media)


def _escape_subtitle_filter(path: str) -> str:
    """Escape a file path for ffplay's subtitles filter on any platform."""
    text = str(path).replace("\\", "/").replace("'", r"\'").replace(":", r"\:")
    return f"'{text}'"
