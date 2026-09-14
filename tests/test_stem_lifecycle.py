import threading
import time
from concurrent.futures import Future

import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.stems import StemError, StemInput, StemManifest, StemService


def write_stems(output, expected):
    output.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name in expected:
        paths[name] = output / f"{name}.wav"
        paths[name].write_bytes((name * 8).encode())
    return paths


@pytest.fixture
def scene(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source recording")
    media = MediaRef(
        MediaSource.LOCAL, str(source), title="Original title", duration=10,
        capabilities=MediaCapabilities(finite=True, fingerprintable=True),
    )
    entered, release, callback_done = threading.Event(), threading.Event(), threading.Event()

    def runner(_source, output, _model, expected, _cancel):
        entered.set()
        assert release.wait(3), "Test runner was not released"
        # Deliberately ignores cancellation to reproduce a late provider return.
        return write_stems(output, expected)

    service = StemService(tmp_path / "cache", runner=runner)
    monkeypatch.setattr(service, "_check_storage", lambda *_args: None)
    complete = service._complete

    def finished(future, job):
        try:
            complete(future, job)
        finally:
            callback_done.set()

    monkeypatch.setattr(service, "_complete", finished)
    yield service, media, StemInput(str(source), {}), entered, release, callback_done
    release.set()
    service.shutdown(timeout=1)


def test_cancelled_runner_cannot_write_manifest_prune_or_publish_ready(scene, monkeypatch):
    service, media, source, entered, release, done = scene
    monkeypatch.setattr(service, "_write_manifest", lambda *_args: pytest.fail("Cancelled manifest write"))
    monkeypatch.setattr(service, "_prune", lambda **_kwargs: pytest.fail("Cancelled prune"))
    service.prepare(media, source)
    assert entered.wait(2)
    assert service.cancel()
    assert service.status().state == "cancelling"
    with pytest.raises(StemError, match="already running"):
        service.prepare(media, source)
    release.set()
    with pytest.raises(StemError, match="cancelled"):
        service.wait(2)
    assert done.wait(2)
    assert service.status().state == "cancelled"
    assert service.manifest() is None
    assert not list(service.results.iterdir())


def test_cancel_then_restart_uses_new_job_and_rejects_old_progress_and_completion(scene):
    service, media, source, entered, release, done = scene
    service.prepare(media, source)
    old_job, old_future = service._job, service._future
    assert old_job is not None and old_future is not None
    assert entered.wait(2)
    service.cancel()
    release.set()
    with pytest.raises(StemError, match="cancelled"):
        service.wait(2)
    assert done.wait(2)
    done.clear()
    service.prepare(media, source)
    current = service.wait(2)
    assert done.wait(2)
    assert service.status().state == "ready"
    assert service.manifest() == current
    status = service.status()
    with pytest.raises(StemError, match="cancelled"):
        service._set_progress(old_job, 0.01, "obsolete")
    service._complete(old_future, old_job)
    assert service.status() == status
    assert service.manifest() == current


def test_shutdown_is_bounded_and_late_runner_cannot_publish(scene, monkeypatch):
    service, media, source, entered, release, done = scene
    monkeypatch.setattr(service, "_write_manifest", lambda *_args: pytest.fail("Closed manifest write"))
    service.prepare(media, source)
    assert entered.wait(2)
    started = time.monotonic()
    service.shutdown(timeout=0.02)
    assert time.monotonic() - started < 0.5
    assert service.status().state == "cancelled"
    with pytest.raises(StemError, match="closed"):
        service.prepare(media, source)
    release.set()
    with pytest.raises(StemError, match="cancelled"):
        service.wait(2)
    assert done.wait(2)
    assert service.status().state == "cancelled"
    assert "shutdown" in (service.status().error or "")
    assert service.manifest() is None


def test_shutdown_during_manifest_write_preserves_finished_cache_without_success(scene, monkeypatch):
    service, media, source, _entered, release, done = scene
    writing, finish_write = threading.Event(), threading.Event()
    write = service._write_manifest
    prune_calls = []

    def delayed_write(path, manifest, parent):
        write(path, manifest, parent)
        writing.set()
        assert finish_write.wait(3)

    monkeypatch.setattr(service, "_write_manifest", delayed_write)
    monkeypatch.setattr(service, "_prune", lambda **_kwargs: prune_calls.append(True))
    release.set()
    try:
        service.prepare(media, source)
        assert writing.wait(2)
        service.shutdown(timeout=0)
        finish_write.set()
        with pytest.raises(StemError, match="cancelled"):
            service.wait(2)
        assert done.wait(2)
        assert service.manifest() is None
        assert service.status().state == "cancelled"
        assert len(list(service.results.glob("*/manifest.json"))) == 1
        assert len(list(service.results.rglob("*.wav"))) == 4
        assert prune_calls == []
    finally:
        finish_write.set()


def test_cancel_can_invalidate_completed_future_before_callback_publication(scene, monkeypatch):
    service, media, source, _entered, release, _done = scene
    callback_entered, release_callback, complete_done = threading.Event(), threading.Event(), threading.Event()
    complete = service._complete
    worker_thread: list[threading.Thread | None] = [None]

    def blocked_completion(future, job):
        # Only block the worker callback, not cancel's same-thread reconciliation.
        if threading.current_thread() is worker_thread[0]:
            callback_entered.set()
            assert release_callback.wait(3)
        try:
            complete(future, job)
        finally:
            if threading.current_thread() is worker_thread[0]:
                complete_done.set()

    def runner(_source, output, _model, expected, _cancel):
        worker_thread[0] = threading.current_thread()
        assert release.wait(3)
        return write_stems(output, expected)

    monkeypatch.setattr(service, "_runner", runner)
    monkeypatch.setattr(service, "_complete", blocked_completion)
    try:
        service.prepare(media, source)
        release.set()
        assert callback_entered.wait(2)
        assert service._future is not None and service._future.done()
        assert service.cancel()
        with pytest.raises(StemError, match="cancelled"):
            service.wait(2)
        assert service.status().state == "cancelled"
        release_callback.set()
        assert complete_done.wait(2)
        assert service.manifest() is None
        assert len(list(service.results.glob("*/manifest.json"))) == 1
    finally:
        release_callback.set()


def test_stale_failure_callback_cannot_replace_new_success(scene):
    service, media, source, _entered, release, done = scene
    release.set()
    service.prepare(media, source)
    old_job = service._job
    assert old_job is not None
    service.wait(2)
    assert done.wait(2)
    done.clear()
    service.prepare(media, source)
    current = service.wait(2)
    assert done.wait(2)
    failed = Future()
    failed.set_exception(StemError("Obsolete worker failed"))
    service._complete(failed, old_job)
    assert service.status().state == "ready"
    assert service.manifest() == current
    assert service.status().error is None


def test_submission_failure_is_recoverable_and_preserves_previous_manifest(scene, monkeypatch):
    service, media, source, _entered, release, done = scene
    release.set()
    service.prepare(media, source)
    previous = service.wait(2)
    assert done.wait(2)
    submit = service._executor.submit

    def cannot_start(*_args):
        raise RuntimeError("Worker thread unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(service._executor, "submit", cannot_start)
        with pytest.raises(StemError, match="could not start"):
            service.prepare(media, source)
        assert service.status().state == "failed"
        assert service.manifest() == previous
        assert service._future is None
    assert service._executor.submit == submit
    service.prepare(media, source)
    assert service.wait(2) == previous


def test_job_captures_input_metadata_before_caller_mutation(scene):
    service, media, source, entered, release, done = scene
    service.prepare(media, source)
    assert entered.wait(2)
    media.title = "Later edited title"
    media.stable_id = "changed-identity"
    release.set()
    manifest = service.wait(2)
    assert done.wait(2)
    assert manifest.title == "Original title"
    assert manifest.media_id != media.stable_id


def test_closed_or_cancelled_job_does_not_start_a_process(monkeypatch):
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr("mariana.stems.subprocess.Popen", lambda *_args, **_kwargs: pytest.fail("Unexpected process"))
    with pytest.raises(StemError, match="cancelled"):
        StemService._run_process(["separator"], cancel, environment=None)


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -1, "invalid"])
def test_shutdown_rejects_nonfinite_or_invalid_wait_budgets_without_hanging(scene, timeout):
    service, media, source, entered, release, done = scene
    service.prepare(media, source)
    assert entered.wait(2)
    started = time.monotonic()
    service.shutdown(timeout=timeout)
    assert time.monotonic() - started < 0.5
    release.set()
    assert done.wait(2)
    assert service.status().state == "cancelled"


def test_normal_completion_and_shutdown_keep_prepared_outputs_available(scene):
    service, media, source, _entered, release, done = scene
    release.set()
    service.prepare(media, source)
    result = service.wait(2)
    assert done.wait(2)
    assert isinstance(result, StemManifest)
    assert not service.cancel()
    service.shutdown()
    assert service.status().state == "ready"
    assert service.manifest() == result


def test_clear_cannot_hide_or_delete_active_preparation(scene):
    service, media, source, entered, release, done = scene
    service.prepare(media, source)
    assert entered.wait(2)
    with pytest.raises(StemError, match="preparation finishes"):
        service.clear(media.stable_id)
    assert service.status().state == "preparing"
    assert service.cancel()
    with pytest.raises(StemError, match="preparation finishes"):
        service.clear(media.stable_id)
    release.set()
    assert done.wait(2)
    assert service.status().state == "cancelled"


def test_preparation_cannot_start_during_clear_and_state_lock_stays_available(scene, monkeypatch):
    service, media, source, _entered, release, done = scene
    release.set()
    service.prepare(media, source)
    service.wait(2)
    assert done.wait(2)
    import shutil

    remove = shutil.rmtree
    deleting, finish_delete = threading.Event(), threading.Event()
    result = []

    def slow_remove(path):
        deleting.set()
        assert finish_delete.wait(3)
        remove(path)

    monkeypatch.setattr("mariana.stems.shutil.rmtree", slow_remove)
    worker = threading.Thread(target=lambda: result.append(service.clear(media.stable_id)))
    worker.start()
    try:
        assert deleting.wait(2)
        # These calls must not wait for filesystem cleanup to release a lock.
        assert service.status().state == "ready"
        with pytest.raises(StemError, match="cleanup is already running"):
            service.prepare(media, source)
        with pytest.raises(StemError, match="cleanup is already running"):
            service.clear(media.stable_id)
        finish_delete.set()
        worker.join(2)
        assert not worker.is_alive()
        assert result == [True]
        assert service.manifest() is None
        with pytest.raises(StemError, match="No stem preparation"):
            service.wait()
    finally:
        finish_delete.set()
        worker.join(2)


def test_failed_clear_releases_reservation_and_preserves_manifest(scene, monkeypatch):
    service, media, source, _entered, release, done = scene
    release.set()
    service.prepare(media, source)
    original = service.wait(2)
    assert done.wait(2)

    def cannot_remove(_path):
        raise OSError("Cleanup refused")

    with monkeypatch.context() as patch:
        patch.setattr("mariana.stems.shutil.rmtree", cannot_remove)
        with pytest.raises(OSError, match="Cleanup refused"):
            service.clear(media.stable_id)
    assert service.manifest() == original
    assert not service._clearing
    assert service.clear(media.stable_id)


def test_missing_clear_target_does_not_leave_cleanup_reserved(scene):
    service, media, source, _entered, release, _done = scene
    assert not service.clear("missing")
    assert not service._clearing
    release.set()
    service.prepare(media, source)
    assert service.wait(2).media_id == media.stable_id


def test_wait_translates_executor_cancellation_to_service_error(scene):
    service, media, source, entered, release, done = scene
    service.prepare(media, source)
    assert entered.wait(2)
    service.cancel()
    release.set()
    assert done.wait(2)
    cancelled = Future()
    cancelled.cancel()
    service._future = cancelled
    with pytest.raises(StemError, match="cancelled"):
        service.wait(0)
