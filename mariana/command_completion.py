"""Bounded command-name completion from the shared, read-only catalogue."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from mariana.command_catalog import COMMAND_CATALOG

_COMMAND_TEXT = re.compile(r"[a-zA-Z0-9_.*+/? -]+\Z")
MAX_COMPLETIONS = 20
MAX_PREFIX_LENGTH = 128


@dataclass(frozen=True, slots=True)
class CommandCompletion:
    text: str
    replace_length: int
    summary: str


@lru_cache(maxsize=1)
def _names() -> tuple[tuple[str, str], ...]:
    names: dict[str, str] = {}
    for spec in COMMAND_CATALOG:
        if not spec.suggest:
            continue
        spellings = (
            spec.canonical,
            *(alias.spelling for alias in spec.aliases if alias.status in {"native", "compatibility-only"}),
        )
        flag_hint = ""
        flag_seen: list[str] = []
        for form in spec.forms:
            for flag in form.flags:
                if flag not in flag_seen:
                    flag_seen.append(flag)
        if flag_seen:
            flag_hint = " [" + " ".join(flag_seen[:6]) + "]"
        summary = f"{spec.summary}{flag_hint} [{spec.risk.value}]"
        for spelling in spellings:
            names.setdefault(spelling, summary)
            for form in spec.forms:
                if form.tokens:
                    name = " ".join((spelling, *form.tokens))
                    if _COMMAND_TEXT.fullmatch(name):
                        names.setdefault(name, summary)
    return tuple(sorted(names.items(), key=lambda item: item[0].casefold()))


def _rank(name: str, normalized: str) -> int | None:
    folded = name.casefold()
    if folded == normalized:
        return 0
    if folded.startswith(normalized):
        return 1
    if normalized and normalized in folded:
        return 2
    return None


def command_completions(text: str, cursor: int, *, limit: int = 12) -> tuple[CommandCompletion, ...]:
    """Complete only a command prefix, preserving arguments after the cursor.

    Never inspect files, history, providers, or argument values. Refuse a cursor
    inside a token rather than replacing/truncating its unconsumed suffix.
    """
    if not 0 <= cursor <= len(text) or not 0 < limit <= MAX_COMPLETIONS:
        return ()
    before, after = text[:cursor], text[cursor:]
    prefix = before.lstrip(" ")
    if (
        not prefix
        or len(prefix) > MAX_PREFIX_LENGTH
        or not _COMMAND_TEXT.fullmatch(prefix)
        or (after and not after.startswith(" "))
    ):
        return ()
    normalized = " ".join(prefix.split()).casefold() + (" " if prefix.endswith(" ") else "")
    ranked = []
    for name, summary in _names():
        rank = _rank(name, normalized)
        if rank is not None:
            ranked.append((rank, name, summary))
    ranked.sort(key=lambda item: (item[0], item[1].casefold(), item[1]))
    return tuple(
        CommandCompletion(name + ("" if after else " "), len(prefix), summary) for _, name, summary in ranked[:limit]
    )
