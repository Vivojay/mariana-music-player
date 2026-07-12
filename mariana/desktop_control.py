"""Best-effort authenticated event stream from the CLI to the Electron host."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from typing import Any, BinaryIO, Callable


class DesktopControl:
    def __init__(self, endpoint: str | None = None, token: str | None = None) -> None:
        self.endpoint = endpoint or os.environ.get("MARIANA_CONTROL_ENDPOINT")
        self.token = token or os.environ.get("MARIANA_CONTROL_TOKEN")
        self._lock = threading.RLock()
        self._stream: BinaryIO | socket.socket | None = None
        self._monitor_stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._safety_monitor: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.token)

    def _connect(self) -> BinaryIO | socket.socket | None:
        if not self.enabled:
            return None
        if os.name == "nt":
            return open(self.endpoint, "r+b", buffering=0)  # noqa: SIM115 - retained for connection lifetime
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.connect(self.endpoint)
        return connection

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> bool:
        if not self.enabled:
            return False
        message = json.dumps(
            {"token": self.token, "event": event, "payload": payload or {}, "timestamp": time.time()},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        with self._lock:
            for _ in range(2):
                try:
                    self._stream = self._stream or self._connect()
                    if self._stream is None:
                        return False
                    if isinstance(self._stream, socket.socket):
                        self._stream.sendall(message)
                    else:
                        self._stream.write(message)
                    return True
                except OSError:
                    self._close_stream()
        return False

    def start_playback_monitor(self, snapshot: Callable[[], Any], interval: float = 1.0) -> None:
        if not self.enabled or self._monitor and self._monitor.is_alive():
            return
        self._monitor_stop.clear()

        def monitor() -> None:
            previous: dict[str, Any] | None = None
            while not self._monitor_stop.wait(interval):
                try:
                    current = snapshot()
                    media = current.media
                    payload = {
                        "state": current.state.value,
                        "position": current.position,
                        "duration": current.duration,
                        "volume": current.volume,
                        "muted": current.muted,
                        "error": current.error,
                        "replaygain_db": getattr(current, "replaygain_db", 0.0),
                        "live_leveling": getattr(current, "live_leveling", False),
                        "stream_title": getattr(current, "stream_title", None),
                        "media": {
                            "id": media.stable_id,
                            "source": media.source.value,
                            "title": media.title,
                            "artist": media.artist,
                        } if media else None,
                    }
                    if payload != previous:
                        self.emit("playback", payload)
                        self.emit("loudness", {
                            "replaygain_db": getattr(current, "replaygain_db", 0.0),
                            "live_leveling": getattr(current, "live_leveling", False),
                            "stream_title": getattr(current, "stream_title", None),
                        })
                        previous = payload
                except Exception as error:
                    self.emit("fatal-error", {"message": f"Playback monitor failed: {error}"})
                    return

        self._monitor = threading.Thread(target=monitor, name="mariana-desktop-events", daemon=True)
        self._monitor.start()

    def start_safety_monitor(self, checker: Callable[[], tuple[bool, list[str]]], interval: float = 1.0) -> None:
        if not self.enabled or self._safety_monitor and self._safety_monitor.is_alive():
            return
        self._monitor_stop.clear()

        def monitor() -> None:
            previous: tuple[bool, tuple[str, ...]] | None = None
            while not self._monitor_stop.wait(interval):
                try:
                    safe, reasons = checker()
                    current = safe, tuple(reasons)
                    if current != previous:
                        self.emit("update-safe", {"safe": safe, "reasons": reasons})
                        previous = current
                except Exception as error:
                    self.emit("fatal-error", {"message": f"Update-safety monitor failed: {error}"})
                    return

        self._safety_monitor = threading.Thread(target=monitor, name="mariana-update-safety", daemon=True)
        self._safety_monitor.start()

    def close(self) -> None:
        self._monitor_stop.set()
        if self._monitor and self._monitor is not threading.current_thread():
            self._monitor.join(timeout=1)
        self._monitor = None
        if self._safety_monitor and self._safety_monitor is not threading.current_thread():
            self._safety_monitor.join(timeout=1)
        self._safety_monitor = None
        with self._lock:
            self._close_stream()

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError:
                pass
            self._stream = None
