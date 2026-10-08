from __future__ import annotations

import asyncio
import builtins
from types import SimpleNamespace

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mariana import command_prompt
from mariana.command_completion import MAX_COMPLETIONS, command_completions
from mariana.terminal_prompt import SessionHistory, TerminalCommandReader


@pytest.mark.parametrize(("prefix", "expected"), [
    ("eq b", "eq band "), ("hotspots st", "hotspots status "),
    ("chapters cu", "chapters current "), ("media inf", "media info "),
    ("  EQ   b", "eq band "), ("eq preset ap", "eq preset apply "),
])
def test_shared_catalogue_completes_command_names_and_literal_forms(prefix, expected):
    suggestions = command_completions(prefix, len(prefix))
    assert suggestions[0].text == expected
    assert suggestions[0].replace_length == len(prefix.lstrip())
    assert suggestions[0].summary


@pytest.mark.parametrize("prefix", [
    "", " ", "\teq", "eq\nb", 'eq preset apply "Private', "eq band 100 5", "play 5",
    "C:\\Private", "ml https://private/?token=secret", "x" * 129, "no-such-command",
])
def test_completion_never_guesses_arguments_or_private_input(prefix):
    assert command_completions(prefix, len(prefix)) == ()


@pytest.mark.parametrize(("text", "cursor"), [("eq band", 4), ("eq", -1), ("eq", 3)])
def test_cursor_inside_a_token_or_outside_input_is_not_replaced(text, cursor):
    assert command_completions(text, cursor) == ()


def test_midline_completion_preserves_existing_arguments():
    text = "eq b 100 2"
    suggestion = command_completions(text, 4)[0]
    assert text[:4-suggestion.replace_length] + suggestion.text + text[4:] == "eq band 100 2"


def test_completions_are_bounded_deterministic_and_do_not_add_confirmation_flags():
    suggestions = command_completions("h", 1, limit=MAX_COMPLETIONS)
    assert 0 < len(suggestions) <= MAX_COMPLETIONS
    assert suggestions == command_completions("h", 1, limit=MAX_COMPLETIONS)
    assert command_completions("h", 1, limit=0) == ()
    assert command_completions("h", 1, limit=MAX_COMPLETIONS + 1) == ()
    assert command_completions("hotspots clear", 14)[0].text == "hotspots clear "
    assert "destructive" in command_completions("hotspots clear", 14)[0].summary
    assert not command_completions("hotspots clear --", 16)


def test_history_is_bounded_memory_only_and_not_loaded_into_a_new_session():
    history = SessionHistory()
    for value in range(150):
        history.append_string(f"progress {value}")
    history.append_string("progress 149")
    history.append_string("x" * 4097)
    history.append_string(" ")
    assert len(history.get_strings()) == 100
    assert history.get_strings()[0] == "progress 50"
    assert next(iter(history.load_history_strings())) == "progress 149"
    history.store_string("never persisted")
    assert SessionHistory().get_strings() == []


def test_terminal_tab_only_completes_and_enter_submits():
    async def scenario():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            completed = asyncio.Event()
            reader.session.default_buffer.on_text_changed += lambda buffer: (
                completed.set() if buffer.text == "hotspots status " else None
            )
            task = asyncio.create_task(reader.session.prompt_async("ready > "))
            try:
                source.send_text("hotspots st\t")
                await asyncio.wait_for(completed.wait(), 5)
                assert not task.done(), "Tab must never execute the command"
                source.send_text("\r")
                assert await asyncio.wait_for(task, 5) == "hotspots status "
            finally:
                if not task.done():
                    task.cancel()
    asyncio.run(scenario())


@pytest.mark.parametrize(("entered", "expected"), [
    ("eq b\t100 2\r", "eq band 100 2"),
    ("unknown\t\r", "unknown"),
    ("hotspots st\x1b\r", "hotspots st"),
    ("play \x1b[200~Nancy نجوى\x1b[201~\r", "play Nancy نجوى"),
])
def test_real_line_editor_preserves_arguments_escape_and_unicode(entered, expected):
    async def scenario():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            source.send_text(entered)
            assert await asyncio.wait_for(reader.session.prompt_async(), 5) == expected
    asyncio.run(scenario())


@pytest.mark.parametrize(("keys", "error"), [("\x03", KeyboardInterrupt), ("\x04", EOFError)])
def test_terminal_interrupt_and_eof_are_not_converted_to_commands(keys, error):
    async def scenario():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            source.send_text(keys)
            with pytest.raises(error):
                await asyncio.wait_for(reader.session.prompt_async(), 5)
    asyncio.run(scenario())


@pytest.fixture
def reset_reader(monkeypatch):
    monkeypatch.setattr(command_prompt, "_reader", None)
    monkeypatch.setattr(command_prompt, "_unavailable", False)
    terminal = SimpleNamespace(isatty=lambda: True)
    monkeypatch.setattr(command_prompt, "sys", SimpleNamespace(stdin=terminal, stdout=terminal))


def test_nonterminal_input_uses_builtin_input_without_initializing_editor(monkeypatch):
    monkeypatch.setattr(command_prompt.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(builtins, "input", lambda prompt: f"plain:{prompt}")
    assert command_prompt.read_command("ready") == "plain:ready"


def test_initialization_failure_falls_back_once_before_reading(monkeypatch, reset_reader):
    attempts = []

    def broken():
        attempts.append(True)
        raise OSError("no console")

    monkeypatch.setattr("mariana.terminal_prompt.TerminalCommandReader", broken)
    monkeypatch.setattr(builtins, "input", lambda _prompt: "fallback")
    assert command_prompt.read_command("ready") == "fallback"
    assert command_prompt.read_command("ready") == "fallback"
    assert attempts == [True]


def test_initialized_reader_is_reused_and_errors_never_reread_partial_input(monkeypatch, reset_reader):
    prompts = []

    def read(prompt):
        prompts.append(prompt)
        if len(prompts) == 2:
            raise OSError("input stopped after reading")
        return "help"

    monkeypatch.setattr("mariana.terminal_prompt.TerminalCommandReader", lambda: SimpleNamespace(read=read))
    monkeypatch.setattr(builtins, "input", lambda _prompt: pytest.fail("must not reread input"))
    assert command_prompt.read_command("first") == "help"
    with pytest.raises(OSError, match="input stopped"):
        command_prompt.read_command("second")
    assert prompts == ["first", "second"]
