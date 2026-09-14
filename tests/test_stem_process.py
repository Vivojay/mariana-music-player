"""Managed separator process lifetime and bounded output discovery contracts."""

import os
import subprocess
import sys
import threading
from types import SimpleNamespace
from typing import cast

import pytest

import mariana.stems as stems
from mariana.stems import FOUR_STEMS, StemError, StemService


@pytest.mark.parametrize("exit_code", [0, 7])
def test_managed_process_reports_real_exit_status_and_closes_job(monkeypatch, exit_code):
    actual_job = stems.WindowsJob
    jobs = []

    class TrackedJob:
        def __init__(self, process):
            self.wrapped = actual_job(process)
            self.handle = self.wrapped.handle
            self.closed = False
            jobs.append(self)

        def close(self):
            self.wrapped.close()
            self.closed = True

    monkeypatch.setattr(stems, "WindowsJob", TrackedJob)
    command = [sys.executable, "-c", f"raise SystemExit({exit_code})"]
    if exit_code:
        with pytest.raises(StemError, match="processing failed"):
            StemService._run_process(command, threading.Event(), environment=None)
    else:
        StemService._run_process(command, threading.Event(), environment=None)
    assert len(jobs) == 1 and jobs[0].closed


def test_cancellation_terminates_only_the_owned_real_child(monkeypatch):
    launch = subprocess.Popen
    entered = threading.Event()
    cancel = threading.Event()
    children = []
    errors = []

    def start(*args, **kwargs):
        child = launch(*args, **kwargs)
        children.append(child)
        entered.set()
        return child

    def run():
        try:
            # A blocked worker is deliberate; only the parent's cancellation can finish the test.
            StemService._run_process(
                [sys.executable, "-c", "import threading; threading.Event().wait(30)"],
                cancel, environment=None,
            )
        except StemError as error:
            errors.append(str(error))

    monkeypatch.setattr(stems.subprocess, "Popen", start)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(5)
        cancel.set()
        worker.join(timeout=10)
        assert not worker.is_alive()
        assert errors == ["Stem preparation cancelled"]
        assert len(children) == 1 and children[0].poll() is not None
    finally:
        cancel.set()
        for child in children:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        worker.join(timeout=5)


def test_process_launch_error_has_safe_context_without_private_command(monkeypatch):
    def denied(*_args, **_kwargs):
        raise PermissionError("secret local path and bearer token")

    monkeypatch.setattr(stems.subprocess, "Popen", denied)
    with pytest.raises(StemError, match="could not start") as caught:
        StemService._run_process(["private input"], threading.Event(), environment=None)
    assert "secret" not in str(caught.value) and "private" not in str(caught.value)


@pytest.mark.parametrize("violation", [None, "byte-limit", "free-space", "inspection-error"])
def test_storage_watchdog_stops_output_growth_and_always_closes_job(tmp_path, monkeypatch, violation):
    output = tmp_path / "owned-output"
    output.mkdir()
    (output / "vocals.wav").write_bytes(b"prepared audio")
    events = []
    states = iter([None, None, 0])
    process = SimpleNamespace(poll=lambda: next(states), returncode=0)
    job = SimpleNamespace(close=lambda: events.append("closed"))
    monkeypatch.setattr(stems.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(stems, "WindowsJob", lambda _process: job)
    monkeypatch.setattr(StemService, "_terminate_process", lambda selected, owned: events.append(
        "terminated" if selected is process and owned is job else "wrong child",
    ))
    monkeypatch.setattr(stems.shutil, "disk_usage", lambda _path: SimpleNamespace(
        free=0 if violation == "free-space" else stems.MIN_WORKING_BYTES * 2,
    ))
    if violation == "inspection-error":
        def cannot_inspect(_path):
            raise OSError("unavailable output directory")

        monkeypatch.setattr(StemService, "_tree", cannot_inspect)
    def run():
        StemService._run_process(
            ["separator"], threading.Event(), environment=None, output_directory=output,
            byte_limit=1 if violation == "byte-limit" else 4096,
        )

    if violation:
        with pytest.raises((StemError, OSError), match=r"storage safety|unavailable output"):
            run()
        assert events == ["terminated", "closed"]
    else:
        run()
        assert events == ["closed"]


@pytest.mark.parametrize("platform,job_handle", [("nt", object()), ("nt", None), ("posix", None)])
@pytest.mark.parametrize("needs_force", [False, True])
def test_process_termination_escalates_with_bounded_waits(monkeypatch, platform, job_handle, needs_force):
    events = []
    waits = 0

    def wait(*, timeout):
        nonlocal waits
        waits += 1
        events.append(("wait", timeout))
        if waits == 1 and needs_force:
            raise subprocess.TimeoutExpired("owned separator", timeout)
        return 0

    process = SimpleNamespace(
        pid=123,
        wait=wait,
        terminate=lambda: events.append("terminate"),
        kill=lambda: events.append("kill"),
    )
    job = SimpleNamespace(handle=job_handle, close=lambda: events.append("close-job"))
    # This tests the selected platform contract, never sends a signal to a real process ID.
    monkeypatch.setattr(stems, "os", SimpleNamespace(
        name=platform, killpg=lambda pid, signal: events.append(("group-signal", pid, signal)),
    ))
    monkeypatch.setattr(stems, "signal", SimpleNamespace(SIGTERM=15, SIGKILL=9))
    StemService._terminate_process(cast(subprocess.Popen, process), cast(stems.WindowsJob, job))
    initial = "close-job" if job_handle is not None else "terminate" if platform == "nt" else (
        "group-signal", 123, 15,
    )
    expected = [initial, ("wait", 2)]
    if needs_force:
        expected += ["kill" if platform == "nt" else ("group-signal", 123, 9), ("wait", 2)]
    assert events == expected


@pytest.mark.parametrize("availability", [False, "import-error", "invalid-module"])
def test_optional_separator_detection_never_imports_model_runtime(monkeypatch, availability):
    import importlib.util

    def lookup(name):
        assert name == "demucs"
        if availability == "import-error":
            raise ImportError("unavailable")
        if availability == "invalid-module":
            raise ValueError("module lacks a specification")
        return None

    monkeypatch.setattr(importlib.util, "find_spec", lookup)
    assert StemService.separator_available() is False


def test_missing_optional_separator_is_refused_before_creating_outputs(tmp_path, monkeypatch):
    service = StemService(tmp_path / "cache")
    monkeypatch.setattr(service, "separator_available", lambda: False)
    monkeypatch.setattr(service, "_run_process", lambda *_args, **_kwargs: pytest.fail("Unexpected process"))
    output = tmp_path / "output"
    try:
        with pytest.raises(StemError, match="not installed"):
            service._run_demucs(tmp_path / "input.wav", output, "htdemucs", FOUR_STEMS, threading.Event())
        assert not output.exists()
    finally:
        service.shutdown()


@pytest.mark.parametrize("result", ["complete", "missing", "duplicate"])
def test_separator_output_is_model_scoped_and_unambiguous(tmp_path, monkeypatch, result):
    service = StemService(tmp_path / "cache")
    monkeypatch.setattr(service, "separator_available", lambda: True)
    commands = []
    output = tmp_path / "output"

    def run(command, _cancel, **kwargs):
        commands.append((command, kwargs))
        folder = output / "htdemucs" / "source"
        folder.mkdir(parents=True)
        for name in FOUR_STEMS:
            if result == "missing" and name == "other":
                continue
            (folder / f"{name}.wav").write_bytes(b"prepared")
        if result == "duplicate":
            (output / "vocals.wav").write_bytes(b"ambiguous")

    monkeypatch.setattr(service, "_run_process", run)
    try:
        if result == "complete":
            selected = service._run_demucs(tmp_path / "input.wav", output, "htdemucs", FOUR_STEMS, threading.Event())
            assert tuple(selected) == FOUR_STEMS
            assert all(path.is_relative_to(output) for path in selected.values())
        else:
            with pytest.raises(StemError, match="ambiguous"):
                service._run_demucs(tmp_path / "input.wav", output, "htdemucs", FOUR_STEMS, threading.Event())
        command, options = commands[0]
        assert command[:4] == [sys.executable, "-m", "demucs", "--name"]
        assert options["environment"]["TORCH_HOME"] == str(service.model_cache)
        assert options["output_directory"] == output
        assert options["byte_limit"] == service.max_cache_bytes
    finally:
        service.shutdown()


@pytest.mark.parametrize("kind", ["deep-tree", "hardlink"])
def test_separator_output_discovery_rejects_unsafe_tree_even_with_all_stems(tmp_path, monkeypatch, kind):
    service = StemService(tmp_path / "cache")
    monkeypatch.setattr(service, "separator_available", lambda: True)
    output = tmp_path / "out"
    outside = tmp_path / "unrelated.txt"
    outside.write_bytes(b"must stay intact")

    def produce(_command, _cancel, **_kwargs):
        for name in FOUR_STEMS:
            (output / f"{name}.wav").write_bytes(b"prepared")
        if kind == "hardlink":
            os.link(outside, output / "unexpected.txt")
        else:
            output.joinpath(*(["part"] * 13)).mkdir(parents=True)

    monkeypatch.setattr(service, "_run_process", produce)
    try:
        with pytest.raises(StemError, match=r"nesting|unsupported file"):
            service._run_demucs(tmp_path / "input.wav", output, "htdemucs", FOUR_STEMS, threading.Event())
        assert outside.read_bytes() == b"must stay intact"
    finally:
        service.shutdown()
