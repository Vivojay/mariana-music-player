import threading
import time
from types import SimpleNamespace

import pytest

from mariana.library_service import LibraryProfilerService, _EventHandler
from mariana.models import PlaybackState


class Catalog:
    online_enrichment = False
    identity_service = None

    def __init__(self):
        self.scans = []
        self.jobs = []
        self.lock = threading.Lock()

    def sync_roots(self):
        return []

    def scan(self, mode):
        with self.lock:
            self.scans.append(mode)

    def process_jobs(self, stage, **_kwargs):
        with self.lock:
            self.jobs.append(stage)
        return 0

    def status(self):
        return {"files": {"available": 0, "missing": 0}, "jobs": [], "scan": None}


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not reached")


def test_service_debounces_scans_and_prioritizes_playback():
    catalog = Catalog()
    state = {"value": PlaybackState.PLAYING}
    service = LibraryProfilerService(
        catalog,
        playback_state=lambda: state["value"],
        watch=False,
        debounce_seconds=0.1,
        probe_workers=2,
        deep_workers=1,
    )
    service.start(initial_scan=False)
    try:
        wait_until(lambda: "probe" in catalog.jobs)
        assert "fingerprint" not in catalog.jobs
        service.mark_dirty()
        service.mark_dirty()
        wait_until(lambda: catalog.scans == ["changed"])
        state["value"] = PlaybackState.IDLE
        wait_until(lambda: "fingerprint" in catalog.jobs)
        service.pause()
        before = len(catalog.jobs)
        time.sleep(0.35)
        assert len(catalog.jobs) == before
        service.resume()
        service.request_scan("full")
        wait_until(lambda: catalog.scans[-1] == "full")
        status = service.status()["service"]
        assert status["running"] and not status["paused"]
    finally:
        service.close()
    assert not service.status()["service"]["running"]


def test_service_start_and_close_are_idempotent():
    service = LibraryProfilerService(Catalog(), watch=False, probe_workers=1, deep_workers=1)
    service.start(initial_scan=False)
    threads = list(service._threads)
    service.start(initial_scan=False)
    assert service._threads == threads
    service.close()
    service.close()
    assert all(not thread.is_alive() for thread in threads)


def test_event_filter_invalid_request_and_full_request_precedence():
    changes = []
    handler = _EventHandler(lambda: changes.append(True))
    handler.on_any_event(SimpleNamespace(is_directory=True, event_type="opened"))
    assert changes == []
    handler.on_any_event(SimpleNamespace(is_directory=True, event_type="modified"))
    handler.on_any_event(SimpleNamespace(is_directory=False, event_type="opened"))
    assert len(changes) == 2
    service = LibraryProfilerService(Catalog(), watch=False)
    with pytest.raises(ValueError):
        service.request_scan("invalid")
    service.request_scan("changed")
    service.request_scan("full")
    service.request_scan("changed")
    assert service._scan_request == "full"


def test_observer_schedules_only_healthy_local_roots_and_closes(monkeypatch):
    class Roots(Catalog):
        def sync_roots(self):
            return [
                {"kind": "local", "available": 1, "path": "good"},
                {"kind": "local", "available": 1, "path": "bad"},
                {"kind": "network", "available": 1, "path": "network"},
                {"kind": "local", "available": 0, "path": "offline"},
            ]

    class FakeObserver:
        def __init__(self, **_kwargs):
            self.scheduled = []
            self.started = self.stopped = self.joined = False

        def schedule(self, _handler, path, **_kwargs):
            if path == "bad":
                raise OSError("denied")
            self.scheduled.append(path)

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def join(self, **_kwargs):
            self.joined = True

    observer = FakeObserver()
    monkeypatch.setattr("mariana.library_service.Observer", lambda **_kwargs: observer)
    service = LibraryProfilerService(Roots(), watch=True, probe_workers=1, deep_workers=1)
    service.start(initial_scan=True)
    service.close()
    assert observer.scheduled == ["good"]
    assert observer.started and observer.stopped and observer.joined


def test_coordinator_and_worker_record_errors_and_timer_scan():
    class Broken(Catalog):
        online_enrichment = True
        identity_service = object()

        def scan(self, mode):
            self.scans.append(mode)
            raise RuntimeError("scan failed")

        def process_jobs(self, stage, **_kwargs):
            if stage == "probe":
                raise RuntimeError("job failed")
            self.jobs.append(stage)
            return 1

    catalog = Broken()
    service = LibraryProfilerService(catalog, watch=False, probe_workers=1, deep_workers=1)
    service.reconcile_seconds = -1
    service.network_poll_seconds = -1
    service.start(initial_scan=False)
    try:
        wait_until(lambda: catalog.scans)
        wait_until(lambda: service._last_error is not None)
        assert any(thread.name == "mariana-library-enrich" for thread in service._threads)
    finally:
        service.close()
    assert "failed" in (service._last_error or "")


def test_paused_service_defers_requested_scan_until_resume():
    catalog = Catalog()
    service = LibraryProfilerService(catalog, watch=False, probe_workers=1, deep_workers=1)
    service.pause()
    service.start(initial_scan=False)
    try:
        service.request_scan("full")
        time.sleep(0.35)
        assert catalog.scans == []
        service.resume()
        wait_until(lambda: catalog.scans == ["full"])
    finally:
        service.close()


def test_loudness_worker_enablement_is_idempotent(monkeypatch):
    catalog = Catalog()
    catalog.analyze_loudness = False
    service = LibraryProfilerService(catalog, watch=False)
    service.enable_loudness()
    assert catalog.analyze_loudness and service._threads == []

    started = []

    class Thread:
        def __init__(self, *, target, args, name, **_kwargs):
            self.target, self.args, self.name = target, args, name
            self.alive = False

        def start(self):
            self.alive = True
            started.append(self.name)

        def is_alive(self):
            return self.alive

    monkeypatch.setattr("mariana.library_service.threading.Thread", Thread)
    service._running = True
    service.enable_loudness()
    service.enable_loudness()
    assert started == ["mariana-library-loudness"]
