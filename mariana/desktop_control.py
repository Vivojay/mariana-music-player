"""Best-effort authenticated event stream from the CLI to the Electron host."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any, BinaryIO

from .playback_status import PlaybackStatusProjection

ControlHandler = Callable[[str, dict[str, Any]], dict[str, Any]]


class DesktopControl:
    def __init__(self, endpoint: str | None = None, token: str | None = None) -> None:
        self.endpoint = endpoint or os.environ.get("MARIANA_CONTROL_ENDPOINT")
        self.token = token or os.environ.get("MARIANA_CONTROL_TOKEN")
        self._lock = threading.RLock()
        self._stream: BinaryIO | socket.socket | None = None
        self._monitor_stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._safety_monitor: threading.Thread | None = None
        self._request_monitor: threading.Thread | None = None
        self._request_buffer = b""

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.token)

    def _connect(self) -> BinaryIO | socket.socket | None:
        if not self.enabled:
            return None
        assert self.endpoint is not None
        if os.name == "nt":
            return open(self.endpoint, "r+b", buffering=0)
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.connect(self.endpoint)
        connection.settimeout(0.2)
        return connection

    def _connected_stream(self) -> BinaryIO | socket.socket | None:
        with self._lock:
            self._stream = self._stream or self._connect()
            return self._stream

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

    def start_playback_monitor(
        self,
        status: Callable[[], PlaybackStatusProjection],
        interval: float = 1.0,
    ) -> None:
        if not self.enabled or (self._monitor and self._monitor.is_alive()):
            return
        self._monitor_stop.clear()

        def monitor() -> None:
            previous: dict[str, Any] | None = None
            while not self._monitor_stop.wait(interval):
                try:
                    current = status()
                    payload = current.to_dict()
                    if payload != previous:
                        self.emit("playback", payload)
                        self.emit("loudness", {
                            "replaygain_db": current.replaygain_db,
                            "live_leveling": current.live_leveling,
                            "stream_title": current.title if current.live else None,
                        })
                        previous = payload
                except Exception as error:
                    self.emit("fatal-error", {"message": f"Playback monitor failed: {error}"})
                    return

        self._monitor = threading.Thread(target=monitor, name="mariana-desktop-events", daemon=True)
        self._monitor.start()

    def start_safety_monitor(self, checker: Callable[[], tuple[bool, list[str]]], interval: float = 1.0) -> None:
        if not self.enabled or (self._safety_monitor and self._safety_monitor.is_alive()):
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

    def _read_request_line(self, stream: BinaryIO | socket.socket) -> bytes | None:
        if not isinstance(stream, socket.socket):
            return stream.readline()
        while b"\n" not in self._request_buffer:
            try:
                chunk = stream.recv(4096)
            except TimeoutError:
                return None
            if not chunk:
                return b""
            self._request_buffer += chunk
            if len(self._request_buffer) > 64_000:
                self._request_buffer = b""
                return None
        line, self._request_buffer = self._request_buffer.split(b"\n", 1)
        return line

    def start_request_listener(self, handler: ControlHandler) -> None:
        """Receive narrow authenticated desktop intents over the event stream."""
        if not self.enabled or (self._request_monitor and self._request_monitor.is_alive()):
            return
        self._monitor_stop.clear()

        def monitor() -> None:
            while not self._monitor_stop.is_set():
                try:
                    stream = self._connected_stream()
                    if stream is None:
                        return
                    line = self._read_request_line(stream)
                    if line is None:
                        continue
                    if not line:
                        with self._lock:
                            self._close_stream()
                        self._monitor_stop.wait(0.1)
                        continue
                    message = json.loads(line.decode("utf-8"))
                    if not isinstance(message, dict) or message.get("token") != self.token:
                        continue
                    request_id = message.get("request_id")
                    action = message.get("action")
                    payload = message.get("payload", {})
                    if (
                        not isinstance(request_id, str)
                        or not request_id
                        or len(request_id) > 128
                        or not isinstance(action, str)
                        or not isinstance(payload, dict)
                    ):
                        continue
                    try:
                        result = handler(action, payload)
                    except Exception:
                        result = {"ok": False, "error": "Backend control request failed"}
                    safe_result = result if isinstance(result, dict) else {
                        "ok": False,
                        "error": "Backend control request failed",
                    }
                    self.emit("control-result", {"request_id": request_id, **safe_result})
                except (OSError, UnicodeError, json.JSONDecodeError):
                    with self._lock:
                        self._close_stream()
                    self._monitor_stop.wait(0.1)

        self._request_monitor = threading.Thread(
            target=monitor,
            name="mariana-desktop-control",
            daemon=True,
        )
        self._request_monitor.start()

    def close(self) -> None:
        self._monitor_stop.set()
        with self._lock:
            self._close_stream()
        if self._monitor and self._monitor is not threading.current_thread():
            self._monitor.join(timeout=1)
        self._monitor = None
        if self._safety_monitor and self._safety_monitor is not threading.current_thread():
            self._safety_monitor.join(timeout=1)
        self._safety_monitor = None
        if self._request_monitor and self._request_monitor is not threading.current_thread():
            self._request_monitor.join(timeout=1)
        self._request_monitor = None

    def _close_stream(self) -> None:
        if self._stream is not None:
            with suppress(OSError):
                self._stream.close()
            self._stream = None
        self._request_buffer = b""
