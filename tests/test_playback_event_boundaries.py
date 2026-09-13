"""Event capture consent, persistence acknowledgement, and shutdown boundaries."""

import threading
from dataclasses import replace

import pytest

from mariana.database import MarianaDatabase
from mariana.playback_events import LocalPlaybackEvents
from tests.test_playback_events import event


def test_disabled_capture_rejects_direct_submissions_and_retains_existing_history(tmp_path):
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database)
        try:
            assert not capture.submit(event("disabled"))
            capture.configure(enabled=True)
            assert capture.submit(event("enabled"))
            assert capture.flush()
            capture.configure(enabled=False)
            assert not capture.submit(event("disabled-again"))
            assert capture.flush()
            assert capture.status()["stored"] == 1
        finally:
            assert capture.close()


@pytest.mark.parametrize("changes", [
    {"position_seconds": None},
    {"position_seconds": True},
    {"occurred_at": True},
    {"occurred_at": 10 ** 1000},
    {"action": []},
    {"origin": []},
    {"play_kind": []},
])
def test_invalid_structured_events_are_refused_without_throwing(tmp_path, changes):
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database, enabled=True)
        try:
            assert not capture.submit(replace(event("invalid"), **changes))
            assert capture.flush()
            assert capture.status()["stored"] == 0
        finally:
            assert capture.close()


def test_failed_clear_reports_failure_and_preserves_retryable_history(tmp_path, monkeypatch):
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database, enabled=True)
        try:
            assert capture.submit(event("retained"))
            assert capture.flush()
            transaction = database.transaction

            def unavailable():
                raise OSError("storage unavailable")

            monkeypatch.setattr(database, "transaction", unavailable)
            assert not capture.clear()
            monkeypatch.setattr(database, "transaction", transaction)
            assert capture.status()["stored"] == 1
            assert capture.status()["persistence_failures"] >= 1
            assert capture.clear()
            assert capture.status()["stored"] == 0
        finally:
            assert capture.close()


def test_shutdown_is_bounded_when_storage_is_busy_and_flushes_after_release(tmp_path):
    with MarianaDatabase(tmp_path / "events.db") as database:
        capture = LocalPlaybackEvents(database, enabled=True, batch_size=1)
        started, release = threading.Event(), threading.Event()
        persist = capture._persist

        def busy(events):
            if events:
                started.set()
                assert release.wait(3)
            return persist(events)

        capture._persist = busy
        try:
            assert capture.submit(event("pending"))
            assert started.wait(1)
            assert not capture.close(timeout=0)
            assert not capture.submit(event("after-close"))
        finally:
            release.set()
            assert capture.close()
        assert capture.status()["stored"] == 1


def test_personal_hotspots_accumulate_across_database_restarts(tmp_path):
    path = tmp_path / "events.db"
    for occurrence in range(2):
        with MarianaDatabase(path) as database:
            capture = LocalPlaybackEvents(database, enabled=True)
            try:
                assert capture.submit(event(f"seek-{occurrence}", action="seek", position=25, play_kind=None))
                assert capture.submit(event(f"recovery-{occurrence}", origin="recovery", position=25))
                bins = capture.aggregate("media-1")
                assert len(bins) == 1
                assert bins[0]["seek_destinations"] == occurrence + 1
                assert bins[0]["play_starts"] == 0
                assert bins[0]["total"] == occurrence + 1
            finally:
                assert capture.close()
