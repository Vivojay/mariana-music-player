"""Word erasure edits the command buffer without submitting it."""

import asyncio
import sys
from types import SimpleNamespace

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mariana import terminal_prompt
from mariana.terminal_prompt import TerminalCommandReader, _windows_word_erase_key


@pytest.mark.skipif(sys.platform != "win32", reason="Windows terminal key encoding")
@pytest.mark.parametrize(("entered", "expected"), [
    ("find Nancy Ajram\x08\r", "find Nancy "),
    ("find Nancy Ajram\x08\x08\r", "find "),
    ("find Nancy   \x08\r", "find "),
    ("find نجوى\x08\r", "find "),
    ("\x08\r", ""),
    ("find Nancy Ajram\x1b[D\x1b[D\x08\r", "find Nancy am"),
    ("find Nancy\x7f\r", "find Nanc"),
    ("find Nancy Ajram\x17\r", "find Nancy "),
    ("find Nancy Ajram\x1b\x7f\r", "find Nancy "),
])
def test_windows_virtual_terminal_word_and_character_erasure(entered, expected):
    async def scenario():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            source.send_text(entered)
            assert await asyncio.wait_for(reader.session.prompt_async(), 5) == expected
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows terminal key encoding")
def test_word_erasure_does_not_submit_and_preserves_yank():
    async def scenario():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            entered = asyncio.Event()
            edited = asyncio.Event()
            reader.session.default_buffer.on_text_changed += lambda buffer: (
                entered.set() if buffer.text == "find Nancy Ajram" else None
            )
            task = asyncio.create_task(reader.session.prompt_async())
            try:
                source.send_text("find Nancy Ajram")
                await asyncio.wait_for(entered.wait(), 5)
                reader.session.default_buffer.on_text_changed += lambda buffer: (
                    edited.set() if buffer.text == "find Nancy " else None
                )
                source.send_text("\x08")
                await asyncio.wait_for(edited.wait(), 5)
                assert not task.done()
                assert reader.session.history.get_strings() == []
                source.send_text("\x19\r")
                assert await asyncio.wait_for(task, 5) == "find Nancy Ajram"
            finally:
                if not task.done():
                    task.cancel()
    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console input records")
@pytest.mark.parametrize(("character", "modifiers", "word_erase"), [
    ("\x08", 0, False),
    ("\x7f", 0x0008, True),
    ("\x7f", 0x0004, True),
])
def test_legacy_console_preserves_character_and_word_erasure(character, modifiers, word_erase):
    from prompt_toolkit.input.win32 import ConsoleInputReader, Win32Input
    from prompt_toolkit.keys import Keys
    from prompt_toolkit.win32_types import KEY_EVENT_RECORD

    # Exercise the installed console parser without acquiring a console handle
    # or changing the console mode of another running application.
    source = object.__new__(Win32Input)
    source.console_input_reader = object.__new__(ConsoleInputReader)
    record = KEY_EVENT_RECORD()
    record.KeyDown = True
    record.RepeatCount = 1
    record.VirtualKeyCode = 8
    record.uChar.UnicodeChar = character
    record.ControlKeyState = modifiers
    keys = source.console_input_reader._event_to_key_presses(record)
    assert len(keys) == 1
    assert keys[0].key == Keys.Backspace
    assert (keys[0].data == _windows_word_erase_key(source)) is word_erase


@pytest.mark.parametrize("backspace", ["\x08", "\x7f"])
def test_non_windows_backspace_keeps_existing_terminal_behavior(monkeypatch, backspace):
    # Unix terminal configurations may use either byte for plain Backspace.
    monkeypatch.setattr(terminal_prompt, "sys", SimpleNamespace(platform="linux"))

    async def scenario():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            source.send_text(f"find Nancy{backspace}\r")
            assert await asyncio.wait_for(reader.session.prompt_async(), 5) == "find Nanc"
    asyncio.run(scenario())
