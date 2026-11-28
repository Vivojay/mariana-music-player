"""Synchronous native command I/O hosted by the running full-screen terminal."""
from __future__ import annotations

import builtins
import getpass
import io
import sys
import threading
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass, field

from .windows_com import command_apartment, prepare_command_host

_local = threading.local()


def current_session():
    """The foreground workspace that owns the calling native command, if any."""
    return getattr(_local, "session", None)


def secret_input(prompt="Password: ", *args, **kwargs):
    # main.py imports this facade at boot. Resolve stdlib getpass at call time
    # so normal terminal input and callers' existing getpass overrides still work.
    return getpass.getpass(prompt, *args, **kwargs)


@dataclass(eq=False)
class Dialog:
    kind: str
    title: str = ""
    secret: bool = False
    container: object = None
    focus: object = None
    bindings: object = None
    style: object = None
    interval: float = 0.2
    response: Future = field(default_factory=Future)


class CommandInput(io.TextIOBase):
    """Foreground line reads use the UI. Other threads cannot consume its PTY."""

    def __init__(self, original, session):
        self._original = original
        self._session = session
        self._remainder = ""

    def isatty(self):
        return self._original.isatty()

    @property
    def encoding(self):
        return self._original.encoding

    def readable(self):
        return True

    def readline(self, size=-1):
        self._session.require_foreground()
        if size == 0:
            return ""
        line = self._remainder or self._session.prompt("") + "\n"
        if size >= 0:
            self._remainder = line[size:]
            return line[:size]
        self._remainder = ""
        return line


class CommandOutput(io.TextIOBase):
    """Keep conventional stream attributes without writing through to the display."""

    def __init__(self, original, write: Callable[[str], None]):
        self._original = original
        self._write = write

    def write(self, text):
        if not isinstance(text, str):
            raise TypeError("Expected text")
        self._write(text)
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def writable(self):
        return True

    def flush(self):
        pass

    def isatty(self):
        return self._original.isatty()

    @property
    def encoding(self):
        return self._original.encoding

    @property
    def errors(self):
        return self._original.errors


class TerminalIO:
    def __init__(self, invalidate, write, clear_output=None):
        prepare_command_host()
        self.clear_output = clear_output if clear_output is not None else lambda: None
        self.invalidate = invalidate
        self.write = write
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._dialog = None

    @property
    def dialog(self):
        with self._lock:
            return self._dialog

    def _wait(self, request):
        with self._lock:
            if self.cancelled.is_set():
                raise KeyboardInterrupt
            if self._dialog is not None:
                raise RuntimeError("Another input request is open")
            self._dialog = request
        self.invalidate()
        try:
            return request.response.result()
        finally:
            with self._lock:
                if self._dialog is request:
                    self._dialog = None
            self.invalidate()

    def require_foreground(self):
        if current_session() is not self:
            raise EOFError("Terminal input belongs to the foreground workspace command.")

    def prompt(self, title, *, secret=False):
        return self._wait(Dialog("prompt", title=str(title), secret=secret))

    def run_view(self, container, *, focus=None, bindings=None, style=None, refresh_interval=0.2):
        return self._wait(Dialog("view", container=container, focus=focus, bindings=bindings,
                                 style=style, interval=refresh_interval))

    def answer(self, dialog, value):
        with self._lock:
            if dialog is not self._dialog or dialog is None or dialog.response.done():
                return
            self._dialog = None
            dialog.response.set_result(value)
        self.invalidate()

    def close_view(self, result=None):
        dialog = self.dialog
        if dialog is not None and dialog.kind == "view":
            self.answer(dialog, result)

    def cancel(self):
        with self._lock:
            self.cancelled.set()
            if self._dialog is not None:
                request, self._dialog = self._dialog, None
                if not request.response.done():
                    request.response.set_exception(KeyboardInterrupt())
        self.invalidate()

    @contextmanager
    def worker(self):
        previous = current_session()
        _local.session = self
        try:
            with command_apartment():
                yield
        finally:
            _local.session = previous

    @contextmanager
    def capture(self):
        original_in, original_out, original_err = sys.stdin, sys.stdout, sys.stderr
        normal_input, hidden_input = builtins.input, getpass.getpass

        def read(prompt="", /):
            self.require_foreground()
            return self.prompt(prompt)

        def read_secret(prompt="Password: ", *args, **kwargs):
            self.require_foreground()
            return self.prompt(prompt, secret=True)

        try:
            sys.stdin = CommandInput(original_in, self)
            sys.stdout = CommandOutput(original_out, self.write)
            sys.stderr = CommandOutput(original_err, self.write)
            builtins.input, getpass.getpass = read, read_secret
            yield
        finally:
            builtins.input, getpass.getpass = normal_input, hidden_input
            sys.stdin, sys.stdout, sys.stderr = original_in, original_out, original_err
