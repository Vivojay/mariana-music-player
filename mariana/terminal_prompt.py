"""Interactive-only line editing, isolated from playback and Electron input."""

from __future__ import annotations

import sys
from collections import deque
from collections.abc import AsyncGenerator, Iterable

from prompt_toolkit import ANSI, PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import History
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding.bindings.named_commands import get_by_name
from prompt_toolkit.output import Output
from prompt_toolkit.patch_stdout import patch_stdout

from mariana.command_completion import command_completions


def _windows_word_erase_key(input: Input) -> str:
    # Both encodings become the same Backspace key in the editor, but retain
    # their original data. Legacy console records reverse the VT byte mapping.
    from prompt_toolkit.input.win32 import ConsoleInputReader, Win32Input

    if isinstance(input, Win32Input) and isinstance(input.console_input_reader, ConsoleInputReader):
        return "\x7f"
    return "\x08"


class CommandCompleter(Completer):
    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        for candidate in command_completions(document.text, document.cursor_position):
            yield Completion(candidate.text, start_position=-candidate.replace_length,
                             display=candidate.text.rstrip(), display_meta=candidate.summary)


class SessionHistory(History):
    """Last 100 modest input lines, memory only, never a persisted command log."""

    def __init__(self) -> None:
        super().__init__()
        self._entries: deque[str] = deque(maxlen=100)

    async def load(self) -> AsyncGenerator[str, None]:
        for entry in tuple(reversed(self._entries)):
            yield entry

    def get_strings(self) -> list[str]:
        return list(self._entries)

    def append_string(self, string: str) -> None:
        if string.strip() and len(string) <= 4096 and (not self._entries or self._entries[-1] != string):
            self._entries.append(string)

    def load_history_strings(self) -> Iterable[str]:
        return tuple(reversed(self._entries))

    def store_string(self, string: str) -> None:
        # Deliberately no persistent storage, including for signed URL commands.
        pass


class TerminalCommandReader:
    def __init__(self, *, input: Input | None = None, output: Output | None = None) -> None:
        completer = CommandCompleter()
        bindings = KeyBindings()

        if sys.platform == "win32":
            @bindings.add("backspace")
            def erase_backwards(event: KeyPressEvent) -> None:
                command = ("backward-kill-word" if event.data == _windows_word_erase_key(event.app.input)
                           else "backward-delete-char")
                get_by_name(command).call(event)

        @bindings.add("tab")
        def accept_completion(event: KeyPressEvent) -> None:
            buffer = event.current_buffer
            state = buffer.complete_state
            if state is not None and state.current_completion is not None:
                candidate = state.current_completion
            else:
                candidate = next(iter(completer.get_completions(buffer.document, CompleteEvent())), None)
            if candidate is not None:
                buffer.apply_completion(candidate)

        @bindings.add("escape")
        def dismiss_completion(event: KeyPressEvent) -> None:
            event.current_buffer.cancel_completion()

        self.session: PromptSession[str] = PromptSession(
            completer=completer, key_bindings=bindings, history=SessionHistory(),
            complete_while_typing=True, reserve_space_for_menu=4,
            enable_system_prompt=False, enable_suspend=False, enable_open_in_editor=False,
            mouse_support=False, input=input, output=output,
        )

    def read(self, prompt: str) -> str:
        # Route background messages around the active input line. The library
        # restores stdout and terminal mode on Enter, EOF, and interruption.
        with patch_stdout(raw=True):
            return self.session.prompt(ANSI(prompt))
