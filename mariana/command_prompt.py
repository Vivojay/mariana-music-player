"""Lazy interactive command input; nonterminal and hidden prompts stay ordinary."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mariana.terminal_prompt import TerminalCommandReader

_reader: TerminalCommandReader | None = None
_unavailable = False


def read_command(prompt: str) -> str:
    global _reader, _unavailable
    if _unavailable or not sys.stdin.isatty() or not sys.stdout.isatty():
        return input(prompt)
    if _reader is None:
        try:
            from mariana.terminal_prompt import TerminalCommandReader

            _reader = TerminalCommandReader()
        except (ImportError, OSError, RuntimeError, ValueError):
            # Only fall back before consuming any input. Never replay partial
            # input or mask interrupts/errors from an already active reader.
            _unavailable = True
            return input(prompt)
    return _reader.read(prompt)
