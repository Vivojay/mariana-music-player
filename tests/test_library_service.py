import threading
import time

from mariana.library_service import LibraryProfilerService
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
