"""Adaptive background scheduling and native events for library profiling."""

from __future__ import annotations

import threading
import time
from typing import Callable
import uuid

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .library import LibraryCatalog
from .models import PlaybackState


BUSY_PLAYBACK_STATES = {
    PlaybackState.RESOLVING,
    PlaybackState.BUFFERING,
    PlaybackState.PLAYING,
    PlaybackState.PAUSED,
    PlaybackState.SEEKING,
    PlaybackState.CROSSFADING,
}


class _EventHandler(FileSystemEventHandler):
    def __init__(self, changed: Callable[[], None]) -> None:
        super().__init__()
        self.changed = changed

    def on_any_event(self, event: FileSystemEvent) -> None:
        if not event.is_directory or event.event_type in {"created", "deleted", "moved", "modified"}:
            self.changed()


class LibraryProfilerService:
    def __init__(
        self,
        catalog: LibraryCatalog,
        *,
        playback_state: Callable[[], PlaybackState] | None = None,
        watch: bool = True,
        debounce_seconds: float = 2,
        reconcile_seconds: float = 6 * 60 * 60,
        network_poll_seconds: float = 10 * 60,
        probe_workers: int = 2,
        deep_workers: int = 1,
    ) -> None:
        self.catalog = catalog
        self.playback_state = playback_state or (lambda: PlaybackState.IDLE)
        self.watch = watch
        self.debounce_seconds = max(0.1, debounce_seconds)
        self.reconcile_seconds = max(60, reconcile_seconds)
        self.network_poll_seconds = max(60, network_poll_seconds)
        self.probe_workers = max(1, probe_workers)
        self.deep_workers = max(1, deep_workers)
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._wake = threading.Event()
        self._dirty_at: float | None = None
        self._scan_request: str | None = None
        self._request_lock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._observer: Observer | None = None
        self._running = False
        self._last_error: str | None = None

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def mark_dirty(self) -> None:
        with self._request_lock:
            self._dirty_at = time.monotonic()
        self._wake.set()

    def request_scan(self, mode: str = "changed") -> None:
        if mode not in {"changed", "full"}:
            raise ValueError("scan mode must be changed or full")
        with self._request_lock:
            if mode == "full" or self._scan_request is None:
                self._scan_request = mode
        self._wake.set()

    def pause(self) -> None:
        self._paused.set()

    def resume(self) -> None:
        self._paused.clear()
        self._wake.set()

    def enable_loudness(self) -> None:
        self.catalog.analyze_loudness = True
        if not self._running:
            return
        if any(thread.is_alive() and thread.name == "mariana-library-loudness" for thread in self._threads):
            self._wake.set()
            return
        worker = threading.Thread(
            target=self._job_worker,
            args=("loudness", 0),
            name="mariana-library-loudness",
            daemon=True,
        )
        self._threads.append(worker)
        worker.start()
        self._wake.set()

    def _start_observer(self) -> None:
        if not self.watch:
            return
        observer = Observer(timeout=1)
        handler = _EventHandler(self.mark_dirty)
        scheduled = 0
        for root in self.catalog.sync_roots():
            if root["kind"] == "local" and root["available"]:
                try:
                    observer.schedule(handler, root["path"], recursive=True)
                    scheduled += 1
                except OSError:
                    continue
        if scheduled:
            observer.start()
            self._observer = observer

    def start(self, *, initial_scan: bool = True) -> None:
        if self._running:
            return
        self._running = True
        self._stop.clear()
        self._start_observer()
        if initial_scan:
            self.request_scan("changed")
        coordinator = threading.Thread(target=self._coordinate, name="mariana-library-coordinator", daemon=True)
        self._threads.append(coordinator)
        coordinator.start()
        for index in range(self.probe_workers):
            worker = threading.Thread(
                target=self._job_worker,
                args=("probe", index),
                name=f"mariana-library-probe-{index + 1}",
                daemon=True,
            )
            self._threads.append(worker)
            worker.start()
        for index in range(self.deep_workers):
            worker = threading.Thread(
                target=self._job_worker,
                args=("fingerprint", index),
                name=f"mariana-library-fingerprint-{index + 1}",
                daemon=True,
            )
            self._threads.append(worker)
            worker.start()
        if getattr(self.catalog, "analyze_loudness", False):
            worker = threading.Thread(
                target=self._job_worker,
                args=("loudness", 0),
                name="mariana-library-loudness",
                daemon=True,
            )
            self._threads.append(worker)
            worker.start()
        if self.catalog.online_enrichment and self.catalog.identity_service:
            worker = threading.Thread(
                target=self._job_worker,
                args=("enrich", 0),
                name="mariana-library-enrich",
                daemon=True,
            )
            self._threads.append(worker)
            worker.start()

    def _coordinate(self) -> None:
        next_local = time.monotonic() + self.reconcile_seconds
        next_network = time.monotonic() + self.network_poll_seconds
        while not self._stop.is_set():
            now = time.monotonic()
            mode = None
            with self._request_lock:
                if self._scan_request and not self._paused.is_set():
                    mode, self._scan_request = self._scan_request, None
                elif (
                    not self._paused.is_set()
                    and self._dirty_at is not None
                    and now - self._dirty_at >= self.debounce_seconds
                ):
                    mode, self._dirty_at = "changed", None
                elif not self._paused.is_set() and (now >= next_local or now >= next_network):
                    mode = "changed"
            if mode:
                try:
                    self.catalog.scan(mode)
                    self._last_error = None
                except Exception as error:
                    self._last_error = str(error)
                next_local = time.monotonic() + self.reconcile_seconds
                next_network = time.monotonic() + self.network_poll_seconds
            self._wake.wait(0.25)
            self._wake.clear()

    def _job_worker(self, stage: str, index: int) -> None:
        owner = f"service-{uuid.uuid4().hex}"
        while not self._stop.is_set():
            state = self.playback_state()
            busy = state in BUSY_PLAYBACK_STATES
            allowed = not self._paused.is_set()
            if stage in {"fingerprint", "loudness", "enrich"} and busy:
                allowed = False
            if stage == "probe" and busy and index > 0:
                allowed = False
            processed = 0
            if allowed:
                try:
                    processed = self.catalog.process_jobs(stage, limit=1, owner=owner)
                except Exception as error:
                    self._last_error = str(error)
            if not processed:
                self._stop.wait(0.25)

    def status(self) -> dict:
        result = self.catalog.status()
        result["service"] = {
            "running": self._running and not self._stop.is_set(),
            "paused": self.paused,
            "watching": self._observer is not None,
            "last_error": self._last_error,
            "workers": len(self._threads),
        }
        return result

    def close(self) -> None:
        if not self._running:
            return
        self._stop.set()
        self._wake.set()
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()
        self._running = False
