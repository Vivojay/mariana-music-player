"""Exercise the real full-screen command editor across complete terminal round trips."""
import asyncio
import sys
import threading
from types import SimpleNamespace

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mariana.terminal_player import run_player


def _state():
    return SimpleNamespace(artist="Artist", title="Recording", queue_position=None, queue_count=0,
                           live=False, display_state="Paused", position_seconds=9, duration_seconds=90)


def test_arbitrary_native_command_is_unmodified_and_dispatch_has_no_running_event_loop():
    command = r'playlist add "old drafts" "D:\Vivo Jay\Odd Artist - q[t].flac"'
    seen = []
    with create_pipe_input() as pipe:
        def dispatch(line):
            async def native_work():
                seen.append(line)

            # Some Mariana handlers synchronously own an event loop or prompt.
            asyncio.run(native_work())
            if len(seen) == 1:
                print("first output\nsecond output")
                print("third output", file=sys.stderr)
                # Output view → command editor → recall and resubmit → game keys work as text.
                pipe.send_text(":\x1b[A\r")
            else:
                return False
            return None

        pipe.send_text(":" + command + "\r")
        timer = threading.Timer(5, pipe.close)
        timer.start()
        try:
            assert run_player(_state, dict, dispatch, input=pipe, output=DummyOutput()) is False
        finally:
            timer.cancel()
    assert seen == [command, command]


def test_view_returns_to_cli_after_visibility_changes():
    visible = True
    with create_pipe_input() as pipe:
        def dispatch(command):
            nonlocal visible
            assert command == "vis"
            visible = False

        pipe.send_text(":vis\r")
        assert run_player(_state, dict, dispatch, is_visible=lambda: visible,
                          input=pipe, output=DummyOutput()) is None
        assert not visible


def test_hidden_idle_session_closes_without_another_keypress():
    hidden = threading.Event()
    with create_pipe_input() as pipe:
        flip = threading.Timer(0.2, hidden.set)
        timeout = threading.Timer(4, pipe.close)
        flip.start()
        timeout.start()
        try:
            assert run_player(_state, dict, lambda _command: None, is_visible=lambda: not hidden.is_set(),
                              input=pipe, output=DummyOutput()) is None
            assert timeout.is_alive()
        finally:
            flip.cancel()
            timeout.cancel()


def test_large_output_is_bounded_and_marked_in_the_transcript():
    from mariana.terminal_player import _TRIMMED, _append_command, _OutputTail

    captured = _OutputTail(limit=160)
    captured.write("A" * 1000)
    for i in range(10):
        captured.write(f"\nLine {i}")
    assert captured.trimmed
    assert len(captured.text()) == 160
    document = _append_command("prior\n" * 90, "list all", captured, limit=200)
    assert len(document.text) == 200
    assert document.text.startswith(_TRIMMED)
    assert document.text.endswith("Line 9")
    assert "prior" not in document.text
