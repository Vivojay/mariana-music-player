"""Machine-readable compatibility aliases retained from Mariana's 2022 testing snapshot."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class AliasCompatibility:
    aliases: tuple[str, ...]
    canonical: str
    scope: str
    status: str


ALIAS_COMPATIBILITY = (
    AliasCompatibility((".",), "now", "exact", "compatibility-only"),
    AliasCompatibility((".*",), "now*", "exact", "compatibility-only"),
    AliasCompatibility(("+",), "next", "both", "compatibility-only"),
    AliasCompatibility(("-",), "prev", "both", "compatibility-only"),
    AliasCompatibility((".+",), ".next", "both", "compatibility-only"),
    AliasCompatibility((".-",), ".prev", "both", "compatibility-only"),
    AliasCompatibility((".arand",), ".rand", "exact", "compatibility-only"),
    AliasCompatibility(("=arand",), "=rand", "exact", "compatibility-only"),
    AliasCompatibility(("arand",), "rand", "exact", "compatibility-only"),
    AliasCompatibility(("arand*",), "rand*", "exact", "compatibility-only"),
    AliasCompatibility(("/arand",), "/rand", "exact", "compatibility-only"),
    AliasCompatibility(("mute",), "m", "token", "native"),
    AliasCompatibility(("vh", "volh", "volumeh"), "volume", "token", "compatibility-only"),
    AliasCompatibility(("dl-yv",), "download-yv", "token", "compatibility-only"),
    AliasCompatibility(("dl-ya",), "download-ya", "token", "compatibility-only"),
    AliasCompatibility(
        ("/reddit-session", "/reddit-sessions", "/rpan"),
        "/rs",
        "token",
        "retired",
    ),
)

EXACT_ALIASES = {
    alias: entry.canonical
    for entry in ALIAS_COMPATIBILITY
    if entry.scope in {"exact", "both"}
    for alias in entry.aliases
}
TOKEN_ALIASES = {
    alias: entry.canonical
    for entry in ALIAS_COMPATIBILITY
    if entry.scope in {"token", "both"}
    for alias in entry.aliases
}

DOWNLOAD_TYPOS = {"donwload", "downlaod", "donwlaod", "donload", "donlaod"}


class SearchMode(StrEnum):
    ALL = "all"
    RAW = "raw"
    LOOSE = "loose"


class SearchAction(StrEnum):
    LIST = "list"
    FIRST = "first"
    RANDOM = "random"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    mode: SearchMode
    action: SearchAction
    query: tuple[str, ...]
    limit: int | None = None


SEARCH_NAMES = {"find", "f", "rfind", "rf", "lfind", "lf"}
SEARCH_COMMANDS = SEARCH_NAMES | {f"{prefix}{name}" for prefix in (".", "/") for name in SEARCH_NAMES}


def normalize_command(command: str) -> str:
    stripped = command.strip()
    if not stripped:
        return stripped
    exact = EXACT_ALIASES.get(stripped.casefold())
    if exact:
        return exact
    token, separator, remainder = stripped.partition(" ")
    canonical = TOKEN_ALIASES.get(token.casefold())
    return f"{canonical}{separator}{remainder}" if canonical else stripped


def parse_search(tokens: list[str]) -> SearchRequest:
    if not tokens or tokens[0].casefold() not in SEARCH_COMMANDS:
        raise ValueError("Unknown search command")
    command = tokens[0].casefold()
    prefix = command[0] if command[0] in {".", "/"} else ""
    name = command[1:] if prefix else command
    mode = SearchMode.RAW if name.startswith("r") else SearchMode.LOOSE if name.startswith("l") else SearchMode.ALL
    action = SearchAction.FIRST if prefix == "." else SearchAction.RANDOM if prefix == "/" else SearchAction.LIST
    query = tokens[1:]
    limit = None
    if action == SearchAction.LIST and mode != SearchMode.RAW and query and query[-1].isdigit():
        limit = int(query[-1])
        query = query[:-1]
    if not query:
        raise ValueError("Search requires one or more query terms")
    return SearchRequest(mode, action, tuple(query), limit)


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(character for character in decomposed if character.isalnum() or character.isspace())


def search_rows(rows: Iterable[tuple[int, str]], request: SearchRequest) -> list[tuple[int, str]]:
    terms = [_normalized(term) for term in request.query]
    matches = []
    for index, label in rows:
        candidate = _normalized(label)
        accepted = any(term in candidate for term in terms) if request.mode == SearchMode.LOOSE else all(
            term in candidate for term in terms
        )
        if accepted:
            matches.append((index, label))
            if request.limit is not None and len(matches) >= request.limit:
                break
    return matches
