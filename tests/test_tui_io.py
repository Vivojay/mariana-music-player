"""Native command workers own foreground input and share one synchronized transcript."""
import builtins
import getpass
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mariana.terminal_io import TerminalIO, current_session, secret_input
from mariana.terminal_player import _Transcript


def test_foreground_line_reads_masked_facade_and_background_input_isolation():
    changed = threading.Event()
    log = _Transcript()
    session = TerminalIO(changed.set, log.write, log.clear)
    original = (builtins.input, getpass.getpass, sys.stdin, sys.stdout, sys.stderr)

    def foreground():
        with session.worker():
            assert current_session() is session
            return sys.stdin.readline(3), sys.stdin.readline(), secret_input("Password?")

    def wait_dialog():
        for _ in range(20):
            changed.wait(.1)
            changed.clear()
            if session.dialog is not None:
                return session.dialog
        raise AssertionError("Missing native dialog")

    with session.capture(), ThreadPoolExecutor(max_workers=1) as pool:
        print("Before")
        print("After", file=sys.stderr)
        task = pool.submit(foreground)
        first = wait_dialog()
        assert first.kind == "prompt" and not first.secret
        for read in (builtins.input, getpass.getpass, sys.stdin.readline):
            with pytest.raises(EOFError, match="foreground"):
                read()
        session.answer(first, "abcdef")
        protected = wait_dialog()
        assert protected.secret and protected.title == "Password?"
        session.answer(protected, "voiceless")
        assert task.result(timeout=1) == ("abc", "def\n", "voiceless")
        assert current_session() is None
    assert original == (builtins.input, getpass.getpass, sys.stdin, sys.stdout, sys.stderr)
    assert log.snapshot(-1)[1].text == "Before\nAfter"


def test_output_from_multiple_threads_is_retained_and_clear_drops_history():
    log = _Transcript()
    log.begin("help")
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda i: log.write(f"line-{i:03}\n"), range(100)))
    doc = log.snapshot(-1)[1]
    assert set(doc.text.splitlines()[1:]) == {f"line-{i:03}" for i in range(100)}
    log.begin("clear")
    log.clear()
    assert log.snapshot(-1)[1].text == ""
    log.begin("next")
    assert log.snapshot(-1)[1].text == "› next"


def test_ctrl_c_cancels_running_command_and_discards_queued_work():
    from types import SimpleNamespace

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from mariana.terminal_player import run_player

    started, stopped = threading.Event(), threading.Event()
    seen = []
    def dispatch(command):
        seen.append(command)
        if command == "web session":
            owner = current_session()
            started.set()
            assert owner.cancelled.wait(4)
            stopped.set()
        elif command == "quit":
            return False

    def project():
        return SimpleNamespace(artist="", title="Fixture", display_state="Paused", live=False,
                               duration_seconds=10, position_seconds=1, queue_count=0, queue_position=None)

    with create_pipe_input() as source:
        def drive():
            source.send_text(":web session\r")
            if started.wait(4):
                source.send_text(":help\r\x03")
            if stopped.wait(4):
                source.send_text(":quit\r")
        thread = threading.Thread(target=drive)
        thread.start()
        expiry = threading.Timer(8, source.close)
        expiry.start()
        try:
            assert run_player(project, dict, dispatch, input=source, output=DummyOutput()) is False
        finally:
            expiry.cancel()
            thread.join(1)
    assert seen == ["web session", "quit"]
