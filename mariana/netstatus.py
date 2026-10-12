"""Continuous connectivity monitor + offline guards.

Local-first: a lightweight linear pinger that debounces flaps and emits
typed transitions. No discovery, download, or playback is started by the
monitor itself.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NetStatus:
    online: bool
    degraded: bool
    latency_ms: float | None
    last_change: float
    consecutive_failures: int
    checks: int


class NetMonitor:
    """Linear pinger with debounce.

    - interval_seconds: delay between probes (default 5s)
    - timeout_seconds: per-probe timeout (default 3s)
    - flip_threshold: consecutive identical results before flipping state
    """

    PROBE_HOSTS = (("1.1.1.1", 443), ("8.8.8.8", 53))
    PROBE_URL = "https://www.gstatic.com/generate_204"

    def __init__(
        self,
        *,
        interval_seconds: float = 5.0,
        timeout_seconds: float = 3.0,
        flip_threshold: int = 2,
        now=time.time,
    ) -> None:
        self.interval = max(1.0, float(interval_seconds))
        self.timeout = max(0.5, float(timeout_seconds))
        self.flip_threshold = max(1, int(flip_threshold))
        self._now = now
        self._lock = threading.RLock()
        self._online = True
        self._degraded = False
        self._latency_ms: float | None = None
        self._last_change = self._now()
        self._failures = 0
        self._successes = 0
        self._checks = 0
        self._watching = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._listeners: list = []

    # -- probing ---------------------------------------------------------
    def probe_once(self) -> tuple[bool, float | None]:
        start = time.monotonic()
        # Fast path: TCP connect to well-known anycast endpoints.
        for host, port in self.PROBE_HOSTS:
            try:
                socket.create_connection((host, port), timeout=self.timeout).close()
                latency = (time.monotonic() - start) * 1000.0
                return True, round(latency, 1)
            except OSError:
                continue
        # Fallback: tiny HTTPS 204 probe (no body read beyond headers).
        try:
            request = urllib.request.Request(self.PROBE_URL, method="GET")
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                ok = response.status in (200, 204)
            latency = (time.monotonic() - start) * 1000.0
            return ok, round(latency, 1) if ok else None
        except Exception:
            return False, None

    def _apply_result(self, ok: bool, latency: float | None) -> NetStatus | None:
        """Fold one probe result; return new status if a flip occurred."""
        with self._lock:
            self._checks += 1
            if ok:
                self._successes += 1
                self._failures = 0
                self._latency_ms = latency
                self._degraded = latency is not None and latency > 1500.0
                if not self._online and self._successes >= self.flip_threshold:
                    self._online = True
                    self._last_change = self._now()
                    self._successes = 0
                    return self.snapshot()
                if self._online:
                    self._successes = 0
                return None
            self._failures += 1
            self._successes = 0
            if self._online and self._failures >= self.flip_threshold:
                self._online = False
                self._degraded = False
                self._latency_ms = None
                self._last_change = self._now()
                return self.snapshot()
            return None

    def check(self) -> tuple[bool, NetStatus | None]:
        ok, latency = self.probe_once()
        flipped = self._apply_result(ok, latency)
        if flipped is not None:
            self._notify(flipped)
        return ok, flipped

    # -- public state ----------------------------------------------------
    def snapshot(self) -> NetStatus:
        with self._lock:
            return NetStatus(
                online=self._online,
                degraded=self._degraded,
                latency_ms=self._latency_ms,
                last_change=self._last_change,
                consecutive_failures=self._failures,
                checks=self._checks,
            )

    @property
    def online(self) -> bool:
        with self._lock:
            return self._online

    def mark_offline(self, *, reason: str = "") -> NetStatus | None:
        """Allow a typed failure (e.g. requests failure) to vote offline."""
        del reason
        with self._lock:
            self._failures += 1
            self._successes = 0
            self._checks += 1
            if self._online and self._failures >= self.flip_threshold:
                self._online = False
                self._last_change = self._now()
                status = self.snapshot()
            else:
                return None
        self._notify(status)
        return status

    def mark_online(self) -> NetStatus | None:
        with self._lock:
            self._successes += 1
            self._failures = 0
            self._checks += 1
            if not self._online and self._successes >= self.flip_threshold:
                self._online = True
                self._last_change = self._now()
                status = self.snapshot()
            else:
                return None
        self._notify(status)
        return status

    # -- watch loop ------------------------------------------------------
    def on_transition(self, listener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def _notify(self, status: NetStatus) -> None:
        for listener in list(self._listeners):
            try:
                listener(status)
            except Exception:
                continue

    def start(self) -> None:
        with self._lock:
            if self._watching:
                return
            self._watching = True
            self._stop.clear()
            thread = threading.Thread(target=self._loop, name="mariana-net-monitor", daemon=True)
            self._thread = thread
        thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception:
                continue

    def stop(self) -> None:
        self._stop.set()
        thread = None
        with self._lock:
            self._watching = False
            thread = self._thread
            self._thread = None
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1)


def offline_message(action: str, *, status: NetStatus | None = None) -> str:
    detail = ""
    if status is not None and not status.online:
        ago = max(0.0, time.time() - status.last_change)
        detail = f" (offline for {ago:.0f}s; local and cached media still play)"
    return f"Offline — cannot {action} right now{detail}. Try library, queue, or downloads instead."


def requires_network(source: str) -> bool:
    return str(source).casefold() in {"youtube", "url", "podcast", "radio", "recommendation"}
