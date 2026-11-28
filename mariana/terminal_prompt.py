"""Interactive-only line editing, isolated from playback and Electron input."""

from __future__ import annotations

import sys
from collections.abc import Iterable

from prompt_toolkit import ANSI, PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding.bindings.named_commands import get_by_name
from prompt_toolkit.output import Output
from prompt_toolkit.patch_stdout import patch_stdout

from mariana.command_assist import Suggestion, ValueProvider, command_corrections, command_suggestions
from mariana.terminal_history import SessionHistory


def _windows_word_erase_key(input: Input) -> str:
    # Both encodings become the same Backspace key in the editor, but retain
    # their original data. Legacy console records reverse the VT byte mapping.
    # The win32 reader module is resolved at runtime so prompts keep working
    # wherever prompt_toolkit ships a different console backend.
    from prompt_toolkit.input import win32 as win32_backend

    win32_input = getattr(win32_backend, 'Win32Input', ())
    console_reader = getattr(win32_backend, 'ConsoleInputReader', ())
    reader = getattr(input, 'console_input_reader', None)
    if isinstance(input, win32_input) and isinstance(reader, console_reader):
        return "\x7f"
    return "\x08"


class _MenuCompletion(Completion):
    mariana_choice: Suggestion


class CommandCompleter(Completer):
    """One editor behavior for CLI, Electron PTY and the TUI command line."""

    def __init__(self, value_provider: ValueProvider | None = None):
        self.value_provider = value_provider
        self.offered_for: str | None = None
        self.declined_for: str | None = None
        self.corrections: tuple[Suggestion, ...] = ()

    def choices(self, document):
        if document.text == self.offered_for:
            return self.corrections
        choices = command_suggestions(document.text, document.cursor_position, value_provider=self.value_provider)
        return choices or command_corrections(document.text)

    def get_completions(self, document: Document, complete_event: CompleteEvent) -> Iterable[Completion]:
        for choice in self.choices(document):
            line, _ = choice.apply(document.text)
            # The menu's preview supports edits to the left of the caret.
            # Tab also handles edits replacing a suffix under the caret.
            right = document.text_after_cursor
            if choice.start > document.cursor_position or (right and not line.endswith(right)):
                continue
            end = len(line) - len(right)
            meta = ("Did you mean " + choice.label + "? Tab to edit · Esc to keep text"
                    if choice.kind == "correction" else choice.summary)
            candidate = _MenuCompletion(line[choice.start:end], start_position=choice.start - document.cursor_position,
                                   display=choice.label, display_meta=meta)
            candidate.mariana_choice = choice
            yield candidate

    def accept(self, buffer: Buffer):
        state = buffer.complete_state
        original = state.original_document if state else buffer.document
        selected = getattr(state.current_completion, "mariana_choice", None) if state else None
        if selected is None:
            selected = next(iter(self.choices(original)), None)
        if selected is not None:
            buffer.cancel_completion()
            line, cursor = selected.apply(original.text)
            buffer.document = Document(line, cursor)
        self.offered_for = self.declined_for = None

    def previous(self, buffer: Buffer):
        if buffer.complete_state:
            buffer.complete_previous()
        else:
            buffer.start_completion(select_last=True)

    def dismiss(self, buffer: Buffer):
        buffer.cancel_completion()
        self.declined_for = buffer.text
        self.offered_for = None

    def offer(self, buffer: Buffer) -> bool:
        """Enter offers a repair. Tab edits, Escape keeps the original available."""
        state = buffer.complete_state
        selected = getattr(state.current_completion, "mariana_choice", None) if state else None
        if selected is not None and selected.kind == "correction":
            self.accept(buffer)
            return True
        if buffer.text == self.declined_for:
            self.declined_for = None
            return False
        choices = command_corrections(buffer.text)
        if not choices:
            self.offered_for = None
            return False
        buffer.cancel_completion()
        self.offered_for, self.corrections = buffer.text, choices
        buffer.start_completion()
        return True

    def notice(self, text):
        if self.offered_for == text and self.corrections:
            names = ", ".join(row.label for row in self.corrections)
            return f"Did you mean {names}?  Tab to edit · Esc to keep your text"
        return ""


class TerminalCommandReader:
    def __init__(self, *, input: Input | None = None, output: Output | None = None, value_provider=None) -> None:
        completer = CommandCompleter(value_provider)
        bindings = KeyBindings()

        if sys.platform == "win32":
            @bindings.add("backspace")
            def erase_backwards(event: KeyPressEvent) -> None:
                command = ("backward-kill-word" if event.data == _windows_word_erase_key(event.app.input)
                           else "backward-delete-char")
                get_by_name(command).call(event)

        @bindings.add("tab")
        def accept_completion(event: KeyPressEvent) -> None:
            completer.accept(event.current_buffer)

        @bindings.add("s-tab")
        def previous_completion(event: KeyPressEvent) -> None:
            completer.previous(event.current_buffer)

        @bindings.add("enter")
        def submit(event: KeyPressEvent) -> None:
            if not completer.offer(event.current_buffer):
                event.current_buffer.validate_and_handle()

        @bindings.add("escape")
        def dismiss_completion(event: KeyPressEvent) -> None:
            completer.dismiss(event.current_buffer)

        self.session: PromptSession[str] = PromptSession(
            completer=completer, key_bindings=bindings, history=SessionHistory(),
            complete_while_typing=True, reserve_space_for_menu=4,
            bottom_toolbar=lambda: completer.notice(get_app().current_buffer.text),
            enable_system_prompt=False, enable_suspend=False, enable_open_in_editor=False,
            mouse_support=False, input=input, output=output,
        )

    def read(self, prompt: str) -> str:
        # Route background messages around the active input line. The library
        # restores stdout and terminal mode on Enter, EOF, and interruption.
        with patch_stdout(raw=True):
            return self.session.prompt(ANSI(prompt))
