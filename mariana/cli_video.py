"""Own the muted picture window for a terminal session. Audio owns the clock."""
from __future__ import annotations

import contextlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

_HANDLE = re.compile(r"[0-9a-f]{32}")
_PROXY = re.compile(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})/[A-Za-z0-9_-]{32}/media")
_CHILD_ERRORS = {
    "display": "Could not open a graphical display for the video window.",
    "dependency": "The video window requires Python Tk and Pillow.",
    "decoder": "FFmpeg could not decode this picture.",
    "decode": "FFmpeg could not decode this picture.",
}
_UNAVAILABLE = "Video is unavailable for the current recording."


class CliVideoError(RuntimeError):
    pass


def _picture_sample(status, cache, sampled_at):
    """Map one generation-checked LocalVideo host envelope to decoder time."""
    revision = status.get("revision")
    media_id = status.get("media_id")
    kind = status.get("state")
    sample = {"source": None, "media_id": media_id, "revision": revision, "state": "idle", "rate": status.get("playback_rate", 1.0),
                  "position": 0.0, "sampled_at": sampled_at, "caption": "", "message": "", "filter": status.get("filter")}
    if kind != "ready" or not media_id:
        sample["message"] = {"error": _UNAVAILABLE + " Run video status for details.",
                             "preparing": "Preparing video…"}.get(kind, "Waiting for video…")
        if kind == "error" and isinstance(status.get("error"), str):
            sample["message"] = status["error"][:250]
        stage = status.get("stage")
        if kind == "preparing" and stage in {"Resolving the video format", "Checking provider byte ranges",
                                              "Reading the video index", "Preparing the first picture",
                                              "Preparing a picture at the current position",
                                              "Preparing a lighter picture preview"}:
            elapsed = status.get("elapsed_seconds")
            sample["message"] = f"{stage}… {elapsed}s" if isinstance(elapsed, int) else f"{stage}…"
        return sample

    absolute = status.get("position_seconds")
    if not isinstance(absolute, (float, int)) or not math.isfinite(absolute):
        return sample
    absolute = max(0.0, absolute)
    source = status.get("resource")
    relative = absolute
    if status.get("transport") == "source":
        # Only the existing localhost capability may leave the service. Signed
        # extractor URLs, HTTP headers and original media URIs stay in the host.
        match = _PROXY.fullmatch(source) if isinstance(source, str) else None
        if not match or int(match.group(1)) > 65535:
            sample["message"] = _UNAVAILABLE
            return sample
    else:
        handle = status.get("handle")
        start, end = status.get("window_start_seconds"), status.get("window_end_seconds")
        if (not isinstance(handle, str) or not _HANDLE.fullmatch(handle)
                or not isinstance(start, (float, int)) or not isinstance(end, (float, int))
                or not 0 <= start <= absolute <= end):
            sample["message"] = "Preparing video…"
            return sample
        path = cache / (handle + ".mp4")
        if path.is_symlink() or not path.is_file():
            sample["message"] = "Preparing video…"
            return sample
        source, relative = str(path), absolute - start

    captions = status.get("captions")
    if isinstance(captions, dict) and captions.get("enabled") and isinstance(captions.get("text"), str):
        sample["caption"] = captions["text"][:2000]
    sample.update(source=source, position=relative, state="playing" if status.get("playing") else "paused")
    return sample


@dataclass(eq=False)
class _Window:
    process: subprocess.Popen
    ready: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    finished: threading.Event = field(default_factory=threading.Event)
    started: bool = False
    error: str | None = None
    manual: bool = False


class CliVideoWindow:
    def __init__(self, *, video_status, cache, ffmpeg, allowed=lambda: True, on_close=lambda: None):
        self.video_status = video_status
        self.cache = Path(cache).resolve()
        self.ffmpeg = ffmpeg
        self.allowed = allowed
        self.on_close = on_close
        self._lock = threading.Lock()
        self._window = None
        self._last_error = None
        self._detector = (0, None)
        self._detector_state = "off"

    def configure_detector(self, path):
        with self._lock:
            self._detector = (self._detector[0] + 1, os.fspath(path) if path else None)
            self._detector_state = "loading" if path and self._window else "waiting" if path else "off"

    def detector_status(self):
        with self._lock:
            return self._detector_state

    @property
    def is_open(self):
        with self._lock:
            return self._window is not None and not self._window.stop.is_set()

    def status(self):
        with self._lock:
            window = self._window
            if window is not None and not window.stop.is_set():
                return {"state": "open" if window.started else "starting", "error": window.error}
            return {"state": "error" if self._last_error else "closed", "error": self._last_error}

    def open(self):
        if not self.allowed():
            raise CliVideoError("The current playback policy does not allow a video window.")
        with self._lock:
            window = self._window
            if window is None or window.stop.is_set():
                executable = self.ffmpeg()
                if not executable:
                    raise CliVideoError("FFmpeg is unavailable. Run tools setup to configure video playback.")
                args = ([sys.executable, "--mariana-video-window"] if getattr(sys, "frozen", False)
                        else [sys.executable, "-m", "mariana.video_window"])
                try:
                    process = subprocess.Popen(
                        [*args, "--ffmpeg", os.fspath(executable)], cwd=Path(__file__).resolve().parents[1],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                except OSError:
                    raise CliVideoError("Could not start the separate video window.") from None
                window = self._window = _Window(process)
                self._last_error = None
                if self._detector[1]:
                    self._detector_state = "loading"
                threading.Thread(target=self._events, args=(window,), name="mariana-picture-events", daemon=True).start()
                threading.Thread(target=self._stream, args=(window,), name="mariana-picture-clock", daemon=True).start()

        if not window.ready.wait(8):
            self._fail(window, "The video window did not become ready in time.")
        if not window.started or window.stop.is_set():
            raise CliVideoError(window.error or "The video window closed before it became ready.")

    def _fail(self, window, message):
        with self._lock:
            if not window.stop.is_set():
                window.error = message
                if self._window is window:
                    self._last_error = message
                window.stop.set()
            window.ready.set()

    def _events(self, window):
        # The child reports fixed error classes. Never copy child stderr, paths
        # or playback URLs into the CLI transcript.
        try:
            with window.process.stdout as stream:
                while raw := stream.readline(2049):
                    if len(raw) > 2048:
                        break
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        break
                    kind = event.get("event")
                    if kind == "ready":
                        with self._lock:
                            if not window.stop.is_set():
                                window.started = True
                            window.ready.set()
                    elif kind == "error":
                        code = event.get("code")
                        fallback = "The separate video window encountered an error."
                        message = _CHILD_ERRORS.get(code, fallback) if isinstance(code, str) else fallback
                        if event.get("fatal", True):
                            self._fail(window, message)
                            return
                        with self._lock:
                            window.error = message
                    elif kind == "closed":
                        window.manual = True
                        break
                    elif kind == "showing":
                        with self._lock:
                            window.error = None
                    elif kind == "detector":
                        state = event.get("state")
                        with self._lock:
                            if (self._window is window and event.get("version") == self._detector[0]
                                    and state in {"off", "loading", "ready", "error"}):
                                self._detector_state = state
        except (ValueError, OSError, TypeError):
            pass
        if not window.manual and not window.stop.is_set():
            self._fail(window, "Video window stopped unexpectedly. Check Tk and Pillow and try video open again.")
        window.stop.set()
        window.ready.set()

    def _stream(self, window):
        process = window.process
        try:
            while not window.stop.is_set():
                if not self.allowed():
                    self._fail(window, "Video window closed by playback policy.")
                    break
                if window.started:
                    stamp = time.monotonic()
                    sample = _picture_sample(self.video_status(), self.cache, stamp)
                    with self._lock:
                        version, model = self._detector
                    sample["detector"] = {"version": version, "path": model}
                    if window.stop.is_set() or not self.allowed():
                        break
                    process.stdin.write(json.dumps(sample, ensure_ascii=True).encode("ascii") + b"\n")
                    process.stdin.flush()
                window.stop.wait(0.1)
        except (BrokenPipeError, OSError, ValueError, RuntimeError):
            if not window.stop.is_set() and process.poll() is None:
                self._fail(window, "Lost the video window connection.")
        finally:
            window.stop.set()
            window.ready.set()
            with contextlib.suppress(OSError):
                process.stdin.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
            with self._lock:
                notify = self._window is window
                if notify:
                    self._window = None
                    self._last_error = window.error if not window.manual else None
                    self._detector_state = "waiting" if self._detector[1] else "off"
            window.finished.set()
            if notify:
                self.on_close()

    def close(self):
        with self._lock:
            window, self._window = self._window, None
            self._last_error = None
            self._detector_state = "waiting" if self._detector[1] else "off"
            if window is None:
                return
            window.stop.set()
            window.ready.set()
        # EOF gives the GUI time to release its decoder and file handles.
        # Killing the child also unblocks a writer if the GUI stopped reading.
        if not window.finished.wait(3):
            with contextlib.suppress(OSError):
                window.process.kill()
            window.finished.wait(1)
