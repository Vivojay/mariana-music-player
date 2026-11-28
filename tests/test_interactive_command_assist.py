"""Check the editor boundaries shared by the native CLI, desktop PTY and TUI."""
import asyncio
import os
import selectors
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mariana.terminal_player import run_player
from mariana.terminal_prompt import TerminalCommandReader


def test_mid_token_tab_replaces_full_token_and_preserves_later_unicode():
    async def edit():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            source.send_text('hotspots stST "東京"\x01' + '\x1b[C' * 11 + '\t\r')
            return await asyncio.wait_for(reader.session.prompt_async(), 4)
    assert asyncio.run(edit()) == 'hotspots status "東京"'



def test_escape_allows_explicit_submission_of_original_spelling():
    async def edit():
        with create_pipe_input() as source:
            reader = TerminalCommandReader(input=source, output=DummyOutput())
            source.send_text('jam cuue !Room:server\r\x1b\r')
            return await asyncio.wait_for(reader.session.prompt_async(), 4)
    assert asyncio.run(edit()) == 'jam cuue !Room:server'


def test_tui_accepts_nested_repair_before_dispatch():
    sent = []
    with create_pipe_input() as source:
        source.send_text(':jam cuue !ID:server seek 3 "C’est ici"\r\t\r')
        def state():
            return SimpleNamespace(display_state='Stopped', media_id=None, source='local', title='',
                                   position_seconds=0, duration_seconds=0, volume=1, queue_count=0)
        def dispatch(line):
            sent.append(line)
            return False
        assert run_player(state, dict, dispatch, input=source, output=DummyOutput()) is False
    assert sent == ['jam cue !ID:server seek 3 "C’est ici"']


@pytest.mark.skipif(os.name != "posix", reason="Uses a POSIX pseudoterminal")
def test_real_pty_offer_edit_then_submit():
    import pty
    import termios

    primary, secondary = pty.openpty()
    termios.tcsetwinsize(secondary, (30, 110))
    reader = subprocess.Popen(
        [sys.executable, "-c", "from mariana.command_prompt import read_command; "
         "print('SUBMITTED=' + read_command('jam-editor-ready> '), flush=True)"],
        stdin=secondary, stdout=secondary, stderr=secondary,
        env={**os.environ, "TERM": "xterm-256color", "PROMPT_TOOLKIT_NO_CPR": "1"},
    )
    os.close(secondary)
    output = bytearray()
    def until(marker):
        with selectors.DefaultSelector() as selector:
            selector.register(primary, selectors.EVENT_READ)
            deadline = time.monotonic() + 5
            while marker not in output and time.monotonic() < deadline:
                if selector.select(0.1):
                    output.extend(os.read(primary, 16384))
            assert marker in output, output[-2500:]
    try:
        until(b"jam-editor-ready")
        os.write(primary, b"tonne sine 440\r")
        until(b"Did you mean")
        assert reader.poll() is None and b"SUBMITTED=" not in output
        os.write(primary, b"\t\r")
        until(b"SUBMITTED=tone sine 440")
        assert reader.wait(timeout=4) == 0
    finally:
        reader.kill()
        reader.wait(timeout=4)
        os.close(primary)
