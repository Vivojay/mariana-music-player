"""A command keeps its TUI owner across worker dispatch and event-loop key handlers."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mariana.karaoke_stage import sing
from mariana.speech_capture import show_live
from mariana.terminal_io import TerminalIO
from mariana.web_session import review_at_terminal


@pytest.fixture
def views(monkeypatch):
    monkeypatch.setattr("mariana.terminal_view.Application", lambda **kw: pytest.fail("nested terminal application"))

    @contextmanager
    def start(function, *args):
        changed = threading.Event()
        host = TerminalIO(changed.set, lambda text: None)

        def invoke():
            with host.worker():
                return function(*args)

        def wait_view(previous=None):
            stop = time.monotonic() + 2
            while time.monotonic() < stop:
                dialog = host.dialog
                if dialog and dialog is not previous:
                    return dialog
                changed.wait(.02)
                changed.clear()
            pytest.fail("command did not mount its view")

        with ThreadPoolExecutor(max_workers=1) as pool:
            job = pool.submit(invoke)
            try:
                yield job, host, wait_view
            finally:
                host.cancel()
    return start


def key(dialog, text):
    binding = next(b for b in dialog.bindings.bindings if b.keys == (text,))
    binding.handler(SimpleNamespace())


def test_live_captions_render_and_stop_without_blocking_the_parent_event_loop(views):
    stop_threads = []
    take = SimpleNamespace(engine=object(), lock=threading.RLock(), cues=[(0, 1, "Jay", "Verse one")],
                           partial="Chorus", status=lambda: "Mic on", stop=lambda: stop_threads.append(threading.get_ident()))
    with views(show_live, take, {}) as (job, _, wait):
        dialog = wait()
        assert "Jay: Verse one" in dialog.focus.content.text()
        assert "Chorus" in dialog.focus.content.text()
        key(dialog, "s")
        job.result(2)
    assert stop_threads and stop_threads[0] != threading.get_ident()
    with views(show_live, take, {}) as (job, _, wait):
        key(wait(), "q")
        job.result(2)
    assert len(stop_threads) == 1


def test_karaoke_transport_returns_to_the_same_workspace_and_preserves_keys(views):
    media = SimpleNamespace(media=SimpleNamespace(stable_id="demo"), state="playing")
    score = SimpleNamespace(singers=["Alto", "Tenor"], score=1, duration=6000, sung_starts=[], segment=lambda _: None)
    session = SimpleNamespace(part=None, stage=lambda _: {"available":True, "media_id":"demo"},
                              active=lambda _: (score, 1800), select=Mock())
    transport = Mock()
    with views(sing, session, lambda: media, transport, {}, lambda: True) as (job, _, wait):
        first = wait()
        assert first.interval == .08
        assert "Instrumental" in "".join(text for _, text in first.focus.content.text())
        key(first, " ")
        second = wait(first)
        transport.assert_called_once_with("p")
        key(second, "q")
        job.result(2)


def test_browser_review_closes_on_expiry_and_drops_approval(views):
    valid = threading.Event()
    valid.set()
    with views(review_at_terminal, "Review room request", valid.is_set) as (job, _, wait):
        review = wait()
        review.focus.buffer.text = "s"
        valid.clear()
        review.focus.buffer.accept_handler(review.focus.buffer)
        assert job.result(2) == ""
    valid.set()
    with views(review_at_terminal, "Review room request", valid.is_set) as (job, _, wait):
        review = wait()
        review.focus.buffer.text = "r"
        review.focus.buffer.accept_handler(review.focus.buffer)
        assert job.result(2) == "r"


def test_file_manager_launched_from_the_workspace_cannot_read_or_write_its_terminal(monkeypatch, tmp_path):
    import subprocess

    from mariana import platform

    file = tmp_path / "Evening Mix.wav"
    file.touch()
    launch = Mock()
    monkeypatch.setattr(platform.sys, "platform", "linux")
    monkeypatch.setattr(platform.shutil, "which", lambda _: "/usr/bin/xdg-open")
    monkeypatch.setattr(platform.subprocess, "Popen", launch)
    with TerminalIO(lambda: None, lambda text: None).worker():
        platform.reveal_path(file)
    launch.assert_called_once_with(["/usr/bin/xdg-open", str(tmp_path)], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
