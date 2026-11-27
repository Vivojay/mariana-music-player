"""Accept the native workspace on a controlling pseudo-terminal, including its DEC screen ownership."""

import errno
import os
import re
import select
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a POSIX controlling pseudo-terminal")
ROOT = Path(__file__).resolve().parents[1]
ENTER_SCREEN = b"\x1b[?1049h"
LEAVE_SCREEN = b"\x1b[?1049l"
CSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
SECRET = "kiwi-9r-QW7-5a"
READY = "BASE_SHELL_READY"
RETURNED = "BASE_SHELL_RETURNED"


def _child(directory: Path) -> None:
    """Use actual stdin/out, the stdlib getpass function and the full prompt_toolkit application."""
    import fcntl
    import getpass
    import termios
    import threading

    # Popen made this process a new session leader. Attach its controlling
    # terminal so the genuine stdlib fallback to /dev/tty is observable.
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    from prompt_toolkit import Application

    from mariana import terminal_player

    def snapshot(app):
        screen = app.renderer.last_rendered_screen
        if screen is None:
            return
        size = app.output.get_size()
        lines = []
        for y in range(size.rows):
            row = screen.data_buffer.get(y, {})
            lines.append("".join(row[x].char if x in row else " " for x in range(size.columns)).rstrip())
        pending = directory / "next-frame"
        pending.write_text("\n".join(lines), encoding="utf-8")
        pending.replace(directory / "frame")

    class ObservedApplication(Application):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.after_render += snapshot

    # Also inspect the current composed screen, since the VT renderer only
    # transmits changed cells. DEC lifecycle assertions use the raw PTY bytes.
    terminal_player.Application = ObservedApplication

    def event(label):
        with (directory / "events").open("a", encoding="utf-8") as stream:
            stream.write(label + "\n")

    def dispatch(command):
        event("begin " + command)
        if command == "tone help":
            print("\x1b[34mOVERTURE\x1b[0m", flush=True)
            print("STAGEMIC", file=sys.stderr, flush=True)
            # The test controls release after observing live output on screen.
            while not (directory / "continue").exists():
                time.sleep(.015)
            print("ENCORE", file=sys.stderr, flush=True)
        elif command == "accounts list":
            print("\n".join(f"Option {n:02d} / input channel" for n in range(60)), flush=True)
            first = input("First selection: ")
            protected = getpass.getpass("Microphone PIN: ")
            from mariana.terminal_io import secret_input

            confirmation = secret_input("Stage confirmation: ")
            last = input("Final selection: ")
            event("answers matched" if (first, protected, confirmation, last) == ("first answer", SECRET, SECRET, "last answer")
                  else "wrong answers")
            print("MELODY", flush=True)
        elif command == "fanroom read":
            try:
                input("CancelHere: ")
            except (KeyboardInterrupt, EOFError):
                event("cancelled")
                raise
            raise AssertionError("Cancelled input was delivered to dispatch")
        elif command == "speech live":
            from mariana.speech_capture import show_live

            # Exercise the actual live caption view without requiring a microphone.
            take = SimpleNamespace(engine=True, lock=threading.RLock(), cues=[],
                                   partial="VOCALISE", status=lambda: "Listening")
            show_live(take, {})
            print("BACKSTAGE", flush=True)
        elif command == "speech status":
            raise RuntimeError("CUEFAULT")
        elif command == "help":
            print("QUARTET", flush=True)
        elif command == "quit":
            if input("LeaveNow: ").casefold() == "y":
                event("confirmed")
                return False
            print("STAYING", flush=True)
        event("end " + command)
        return None

    def project():
        return SimpleNamespace(title="Fixture", artist="Jay", queue_position=None, queue_count=0,
                               live=False, display_state="Paused", position_seconds=0, duration_seconds=60)
    print(READY, flush=True)
    result = terminal_player.run_player(project, dict, dispatch)
    print(f"{RETURNED} {result!r}", flush=True)


class _Terminal:
    def __init__(self, directory, size):
        import pty
        import termios

        self.directory = directory
        self.data = bytearray()
        self.eof = False
        self.fd, secondary = pty.openpty()
        try:
            termios.tcsetwinsize(secondary, size)
            self.process = subprocess.Popen(
                [sys.executable, "-u", __file__, "--screen-child", str(directory)],
                stdin=secondary, stdout=secondary, stderr=secondary, start_new_session=True,
                env=dict(os.environ, TERM="xterm-256color", PROMPT_TOOLKIT_NO_CPR="1"),
            )
        finally:
            os.close(secondary)

    def read(self, seconds):
        if self.eof:
            return
        ready, _, _ = select.select([self.fd], [], [], seconds)
        if ready:
            try:
                data = os.read(self.fd, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                data = b""
            self.data.extend(data)
            self.eof = not data

    def wait(self, predicate: Callable[[], bool], label, *, in_workspace=True):
        deadline = time.monotonic() + 6
        while True:
            if in_workspace:
                assert LEAVE_SCREEN not in self.data, f"The workspace exposed the underlying CLI before {label}."
            if predicate():
                return
            if self.eof or time.monotonic() >= deadline:
                screen = self.frame() or CSI.sub(b"", self.data[-1200:]).decode("utf-8", errors="replace")
                pytest.fail(f"Terminal never reached {label}. Last visible frame:\n{screen}")
            self.read(.05)

    def shown(self, token, *, after=0, in_workspace=True):
        marker = token.encode()
        self.wait(lambda: marker in CSI.sub(b"", self.data[after:]), token, in_workspace=in_workspace)

    def seen_event(self, token):
        path = self.directory / "events"
        self.wait(lambda: path.exists() and token in path.read_text(encoding="utf-8").splitlines(), token)

    def frame(self):
        path = self.directory / "frame"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def sees(self, *strings):
        def matched():
            frame = self.frame()
            return all(text in frame for text in strings)
        self.wait(matched, "screen with " + ", ".join(strings))

    def type_secret(self):
        self.send(SECRET)
        # Inspect a frame while the value is still in the field. Submitting it in
        # one write could hide a single-frame unmasked input regression.
        self.sees("*" * len(SECRET))
        assert SECRET not in self.frame()
        assert b"kiwi-9r" not in CSI.sub(b"", self.data)
        self.send("\r")

    def send(self, text):
        os.write(self.fd, text.encode())

    def run_command(self, name):
        self.send(":" + name + "\r")
        self.seen_event("begin " + name)

    def start(self):
        self.shown("Fixture")
        assert self.data.count(ENTER_SCREEN) == 1
        assert 0 <= self.data.find(READY.encode()) < self.data.find(ENTER_SCREEN)

    def exit(self, result):
        self.shown(f"{RETURNED} {result}", in_workspace=False)
        self.wait(lambda: self.eof, "process exit", in_workspace=False)
        assert self.data.count(ENTER_SCREEN) == 1
        assert self.data.count(LEAVE_SCREEN) == 1
        assert self.data.index(LEAVE_SCREEN) < self.data.index(RETURNED.encode())
        assert SECRET.encode() not in self.data
        assert b"Traceback (most recent call last)" not in self.data
        assert self.process.wait(timeout=3) == 0

    def close(self):
        self.process.kill()
        self.process.wait(timeout=3)
        os.close(self.fd)


@pytest.fixture
def terminal(tmp_path, request):
    session = _Terminal(tmp_path, getattr(request, "param", (30, 100)))
    try:
        session.start()
        yield session
    finally:
        session.close()


def test_live_output_prompt_sequence_error_and_confirmed_quit_keep_one_screen(terminal):
    terminal.run_command("tone help")
    terminal.shown("OVERTURE")
    terminal.shown("STAGEMIC")
    # Submit another command while the worker is still busy. It must run once,
    # after the first command, and must receive its own prompt answers.
    terminal.send(":accounts list")
    terminal.shown("accounts list")
    terminal.send("\r")
    assert "begin accounts list" not in (terminal.directory / "events").read_text(encoding="utf-8")
    (terminal.directory / "continue").touch()
    terminal.seen_event("begin accounts list")
    terminal.sees("First selection", "Option 59")
    terminal.send("first")
    terminal.sees("First selection", "first")
    terminal.send("\x1b[5~" * 6)
    terminal.sees("First selection", "first", "Option 00")
    terminal.send("\x1b[6~" * 6)
    terminal.sees("First selection", "first", "Option 59")
    terminal.send(" answer\r")
    terminal.sees("Microphone PIN")
    terminal.type_secret()
    terminal.sees("Stage confirmation")
    terminal.type_secret()
    terminal.sees("Final selection")
    terminal.send("last answer\r")
    terminal.seen_event("answers matched")
    terminal.sees("MELODY")
    events = (terminal.directory / "events").read_text(encoding="utf-8").splitlines()
    assert events.index("end tone help") < events.index("begin accounts list")
    assert events.count("begin accounts list") == 1
    assert SECRET.encode() not in terminal.data

    terminal.run_command("speech live")
    terminal.shown("VOCALISE")
    terminal.send("q")
    terminal.shown("BACKSTAGE")

    terminal.run_command("speech status")
    terminal.shown("CUEFAULT")
    terminal.run_command("help")
    terminal.shown("QUARTET")

    terminal.run_command("quit")
    terminal.shown("LeaveNow")
    terminal.send("n\r")
    terminal.shown("STAYING")
    offset = len(terminal.data)
    terminal.send(":quit\r")
    terminal.shown("LeaveNow", after=offset)
    terminal.send("y\r")
    terminal.exit("False")


@pytest.mark.parametrize("terminal", [(14, 42)], indirect=True)
def test_cancel_pending_question_and_return_to_caller_only_on_explicit_close(terminal):
    terminal.run_command("fanroom read")
    terminal.shown("CancelHere")
    terminal.send("\x03")
    terminal.seen_event("cancelled")
    terminal.run_command("help")
    terminal.shown("QUARTET")
    # Leave the transcript, then close the workspace from browsing mode.
    offset = len(terminal.data)
    terminal.send("\x1b")
    terminal.shown("Track details", after=offset)
    terminal.send("q")
    terminal.exit("None")


def test_palette_finds_and_recalls_without_submitting_or_losing_drafts(terminal):
    terminal.send(":seek +12s")
    terminal.sees("seek +12s")
    terminal.send("\x0b")  # Ctrl+K
    terminal.sees("Command palette")
    terminal.send("video open")
    terminal.sees("video open")
    terminal.send("\x1b")
    terminal.sees("seek +12s")
    assert not (terminal.directory / "events").exists()
    terminal.send("\x0bhelp\r")
    terminal.sees("› help")
    assert not (terminal.directory / "events").exists()
    terminal.send("\r")
    terminal.seen_event("end help")
    terminal.send("\x12")  # Ctrl+R
    terminal.sees("Command history", "help")
    terminal.send("hel\r")
    terminal.sees("› help")
    assert (terminal.directory / "events").read_text().splitlines().count("begin help") == 1
    terminal.send("\r")
    terminal.wait(lambda: (terminal.directory / "events").read_text().splitlines().count("begin help") == 2, "second help")


if __name__ == "__main__" and sys.argv[1:2] == ["--screen-child"]:
    sys.path.insert(0, str(ROOT))
    _child(Path(sys.argv[2]))
