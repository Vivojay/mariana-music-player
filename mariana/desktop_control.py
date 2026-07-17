"""Best-effort authenticated event and request channels for the Electron host."""

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
        self._event_lock = threading.RLock()
        self._request_lock = threading.RLock()
        self._event_stream: BinaryIO | socket.socket | None = None
        self._request_stream: BinaryIO | socket.socket | None = None
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

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> bool:
        if not self.enabled:
            return False
        message = json.dumps(
            {"token": self.token, "event": event, "payload": payload or {}, "timestamp": time.time()},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        with self._event_lock:
            for _ in range(2):
                try:
                    self._event_stream = self._event_stream or self._connect()
                    if self._event_stream is None:
                        return False
                    if isinstance(self._event_stream, socket.socket):
                        self._event_stream.sendall(message)
                    else:
                        self._event_stream.write(message)
                    return True
                except OSError:
                    self._close_event_stream()
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
        """Receive narrow authenticated desktop intents over a dedicated channel."""
        if not self.enabled or (self._request_monitor and self._request_monitor.is_alive()):
            return
        self._monitor_stop.clear()

        def monitor() -> None:
            while not self._monitor_stop.is_set():
                try:
                    # A synchronous Windows named-pipe read can stall writes on the same
                    # FileIO handle, so typed requests use a dedicated connection.
                    with self._request_lock:
                        stream = self._request_stream or self._connect()
                        if stream is not None and self._request_stream is None:
                            self._request_stream = stream
                            handshake = json.dumps(
                                {"token": self.token, "channel": "requests"},
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ).encode("utf-8") + b"\n"
                            if isinstance(stream, socket.socket):
                                stream.sendall(handshake)
                            else:
                                stream.write(handshake)
                    if stream is None:
                        return
                    line = self._read_request_line(stream)
                    if line is None:
                        continue
                    if not line:
                        with self._request_lock:
                            self._close_request_stream()
                        self._monitor_stop.wait(0.1)
                        continue
                    try:
                        message = json.loads(line.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError):
                        continue
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
                except OSError:
                    with self._request_lock:
                        self._close_request_stream()
                    self._monitor_stop.wait(0.1)

        self._request_monitor = threading.Thread(
            target=monitor,
            name="mariana-desktop-control",
            daemon=True,
        )
        self._request_monitor.start()

    def close(self) -> None:
        self._monitor_stop.set()
        with self._event_lock:
            self._close_event_stream()
        with self._request_lock:
            self._close_request_stream()
        if self._monitor and self._monitor is not threading.current_thread():
            self._monitor.join(timeout=1)
        self._monitor = None
        if self._safety_monitor and self._safety_monitor is not threading.current_thread():
            self._safety_monitor.join(timeout=1)
        self._safety_monitor = None
        if self._request_monitor and self._request_monitor is not threading.current_thread():
            self._request_monitor.join(timeout=1)
        self._request_monitor = None

    def _close_event_stream(self) -> None:
        if self._event_stream is not None:
            with suppress(OSError):
                self._event_stream.close()
            self._event_stream = None

    def _close_request_stream(self) -> None:
        if self._request_stream is not None:
            with suppress(OSError):
                self._request_stream.close()
            self._request_stream = None
        self._request_buffer = b""
