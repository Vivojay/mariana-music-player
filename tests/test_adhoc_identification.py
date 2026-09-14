import queue
import threading
import time

import numpy as np
import pytest

from mariana.adhoc_identification import (
    SAMPLE_RATE,
    AdHocIdentificationError,
    AdHocIdentificationService,
    CapturePhase,
)
from mariana.identity import IdentificationService
from mariana.models import IdentityStatus, MediaRef, MediaSource, TrackIdentity


def media(name: str = "Long mix") -> MediaRef:
    return MediaRef(MediaSource.LOCAL, f"C:/{name}.flac", title=name, duration=3600)


def wait_for(service: AdHocIdentificationService, phase: CapturePhase) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if service.status().phase == phase:
            return
        time.sleep(0.01)
    assert service.status().phase == phase


def test_capture_starts_at_invocation_and_identifies_only_new_pcm():
    received = []
    updates = []
    service = AdHocIdentificationService(
        lambda selected, pcm: received.append((selected, pcm)) or {"title": "Detected"},
        on_update=updates.append,
    )
    selected = media()
    try:
        status = service.start(selected, "session-1", "decoder-1", 125.0, 8)
        block = np.full((SAMPLE_RATE, 2), 0.25, dtype=np.float32)
        for second in range(8):
            service.offer(
                block,
                SAMPLE_RATE,
                media_id=selected.stable_id,
                playback_session_id="session-1",
                decoder_token="decoder-1",
                start_position_seconds=125.0 + second,
            )
        wait_for(service, CapturePhase.COMPLETE)
        status = service.status()
        assert status.capture_id
        assert status.requested_start_seconds == 125.0
        assert status.captured_start_seconds == 125.0
        assert status.captured_end_seconds == 133.0
        assert len(received) == 1
        assert len(received[0][1]) == 8 * SAMPLE_RATE * 2 * 4
        assert status.result == {"title": "Detected"}
        assert updates[0].phase == CapturePhase.CAPTURING
    finally:
        service.close()


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"media_id": "different"}, "Playback changed"),
        ({"playback_session_id": "different"}, "Playback changed"),
        ({"decoder_token": "different"}, "seeked or restarted"),
        ({"mixed": True}, "mixed transition"),
        ({"start_position_seconds": 12.0}, "position changed"),
    ],
)
def test_capture_rejects_identity_discontinuity_and_crossfade(override, reason):
    service = AdHocIdentificationService(lambda *_args: None)
    selected = media()
    try:
        service.start(selected, "session", "decoder", 10.0, 8)
        values = {
            "media_id": selected.stable_id,
            "playback_session_id": "session",
            "decoder_token": "decoder",
            "start_position_seconds": 10.0,
            "mixed": False,
        }
        values.update(override)
        service.offer(np.zeros((32, 2), dtype=np.float32), 32, **values)
        assert service.status().phase == CapturePhase.FAILED
        assert reason in service.status().reason
    finally:
        service.close()


def test_manual_stop_requires_minimum_and_cancel_discards_capture():
    service = AdHocIdentificationService(lambda *_args: None)
    selected = media()
    try:
        service.start(selected, "session", "decoder", 1.0, 20)
        with pytest.raises(AdHocIdentificationError, match="at least 8 seconds"):
            service.stop()
        status = service.cancel()
        assert status.phase == CapturePhase.CANCELLED
        assert status.result is None
    finally:
        service.close()


def test_capture_queue_overflow_fails_without_blocking_playback_callback():
    service = AdHocIdentificationService(lambda *_args: None)
    selected = media()
    original_queue = service._queue

    class FullQueue:
        @staticmethod
        def put_nowait(_packet):
            raise queue.Full

    try:
        service.start(selected, "session", "decoder", 0, 8)
        service._queue = FullQueue()
        started = time.monotonic()
        service.offer(
            np.zeros((32, 2), dtype=np.float32),
            32,
            media_id=selected.stable_id,
            playback_session_id="session",
            decoder_token="decoder",
            start_position_seconds=0,
        )
        assert time.monotonic() - started < 0.1
        assert service.status().phase == CapturePhase.FAILED
        assert "keep up" in service.status().reason
    finally:
        service._queue = original_queue
        service.close()


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), 7.9, 120.1, None, 10**400])
def test_capture_duration_is_finite_and_bounded(duration):
    service = AdHocIdentificationService(lambda *_args: None)
    try:
        with pytest.raises(AdHocIdentificationError, match="between 8 and 120"):
            service.start(media(), "session", "decoder", 0, duration)
    finally:
        service.close()


def test_invocation_window_identity_is_not_saved_as_whole_media_identity(monkeypatch):
    class Database:
        def transaction(self):
            raise AssertionError("ad-hoc segment identity must not be persisted for the container")

    class AcoustID:
        def identify(self, duration, fingerprint, expected_duration):
            assert (duration, fingerprint, expected_duration) == (8.0, "fresh", None)
            return TrackIdentity(IdentityStatus.IDENTIFIED, title="Song inside mix")

    class MusicBrainz:
        def enrich(self, identity):
            return identity

    monkeypatch.setattr("mariana.identity.fingerprint_pcm", lambda _pcm, _bin=None: (8.0, "fresh"))
    service = IdentificationService(Database(), acoustid=AcoustID(), musicbrainz=MusicBrainz())

    identity = service.identify_pcm_window(media(), b"new audio only")

    assert identity.title == "Song inside mix"


def offer_seconds(service, selected, seconds, *, start=0):
    service.offer(
        np.full((SAMPLE_RATE * seconds, 2), 0.25, dtype=np.float32), SAMPLE_RATE * seconds,
        media_id=selected.stable_id, playback_session_id="session", decoder_token="decoder",
        start_position_seconds=start,
    )


def test_paused_capture_expires_on_wall_clock_and_worker_publishes_failure_once():
    clock = [0.0]
    updates = []
    failed = threading.Event()
    callback_threads = []

    def update(status):
        updates.append(status)
        callback_threads.append(threading.current_thread())
        if status.phase == CapturePhase.FAILED:
            failed.set()

    service = AdHocIdentificationService(lambda *_: pytest.fail("no PCM to identify"),
                                         clock=lambda: clock[0], on_update=update)
    try:
        service.start(media(), "session", "decoder", 80, 20)
        clock[0] = 60.0
        assert failed.wait(2)
        assert service.status().captured_seconds == 0
        assert "paused or buffering" in service.status().reason
        assert callback_threads[-1] is service._worker
        assert len([item for item in updates if item.phase == CapturePhase.FAILED]) == 1
    finally:
        service.close()


def test_capture_failure_does_not_call_output_from_audio_thread():
    failure_thread = []
    published = threading.Event()

    def update(status):
        if status.phase == CapturePhase.FAILED:
            failure_thread.append(threading.current_thread())
            published.set()

    service = AdHocIdentificationService(lambda *_: None, on_update=update)
    try:
        service.start(media(), "session", "decoder", 0, 8)
        service.offer(b"", 1, media_id="new", playback_session_id="session", decoder_token="decoder",
                      start_position_seconds=0)
        assert published.wait(2)
        assert failure_thread == [service._worker]
    finally:
        service.close()


def test_manual_stop_identifies_exact_captured_window():
    received = []
    selected = media()
    service = AdHocIdentificationService(lambda _, pcm: received.append(pcm) or "match")
    try:
        service.start(selected, "session", "decoder", 90, 20)
        offer_seconds(service, selected, 8, start=90)
        service.stop()
        wait_for(service, CapturePhase.COMPLETE)
        assert len(received) == 1
        assert len(received[0]) == 8 * SAMPLE_RATE * 8
        assert service.status().captured_end_seconds == 98
    finally:
        service.close()


@pytest.mark.parametrize("action", ["cancel", "close"])
def test_inflight_provider_result_cannot_publish_after_cancel_or_shutdown(action):
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    updates = []

    def identify(*_):
        entered.set()
        assert release.wait(2)
        returned.set()
        return "stale match"

    service = AdHocIdentificationService(identify, on_update=updates.append)
    selected = media()
    try:
        service.start(selected, "session", "decoder", 0, 8)
        offer_seconds(service, selected, 8)
        assert entered.wait(2)
        if action == "cancel":
            service.cancel()
            # The next invocation must not inherit the old provider's result.
            service.start(selected, "session", "decoder", 20, 8)
        else:
            service.close(timeout=0.01)
            assert service.status().phase == CapturePhase.CANCELLED
            with pytest.raises(AdHocIdentificationError, match="closed"):
                service.start(selected, "session", "decoder", 0, 8)
        release.set()
        assert returned.wait(2)
    finally:
        release.set()
        service.close(timeout=2)
    assert not service._worker.is_alive()
    assert service.status().result is None
    assert not any(item.phase == CapturePhase.COMPLETE for item in updates)

@pytest.mark.parametrize("next_block", [False, True])
def test_capture_never_waits_for_control_lock_or_identifies_a_gapped_window(next_block):
    identified = []
    service = AdHocIdentificationService(lambda *_: identified.append(True))
    selected = media()
    finished = threading.Event()

    def callback():
        service.offer(
            b"\0" * 256, 32, media_id=selected.stable_id, playback_session_id="session",
            decoder_token="decoder", start_position_seconds=0,
        )
        finished.set()

    worker = threading.Thread(target=callback)
    try:
        service.start(selected, "session", "decoder", 0, 8)
        with service._lock:
            worker.start()
            assert finished.wait(1), "The playback callback waited for the control lock"
            if next_block:
                offer_seconds(service, selected, 8)
        wait_for(service, CapturePhase.FAILED)
        assert "keep up" in service.status().reason
        assert identified == []
    finally:
        worker.join(2)
        service.close()


@pytest.mark.parametrize("timeout", [float("inf"), "invalid", 10**400])
def test_shutdown_rejects_unbounded_waits_without_leaking_worker(timeout):
    service = AdHocIdentificationService(lambda *_: None)
    try:
        service.close(timeout=timeout)
        assert service._closed.is_set()
    finally:
        service.close(timeout=2)
    assert not service._worker.is_alive()


def test_provider_error_does_not_publish_private_reference_or_credentials():
    def unavailable(*_):
        raise RuntimeError("https://private.example/media?signature=secret Authorization: bearer-token")

    service = AdHocIdentificationService(unavailable)
    selected = media()
    try:
        service.start(selected, "session", "decoder", 0, 8)
        offer_seconds(service, selected, 8)
        wait_for(service, CapturePhase.FAILED)
        assert service.status().reason == "Identification failed; check the identification service and try again"
        assert service.status().result is None
    finally:
        service.close()
