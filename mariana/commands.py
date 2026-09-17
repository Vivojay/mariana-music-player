"""Machine-readable compatibility aliases retained from Mariana's 2022 testing snapshot."""

from __future__ import annotations

import re
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
    AliasCompatibility(("rate",), "rating", "token", "native"),
    AliasCompatibility(("chapter", ".chapter", ".chapters"), "chapters", "token", "native"),
    AliasCompatibility(("caption",), "captions", "token", "native"),
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
    AliasCompatibility(("dl-ml",), "download-ml", "token", "compatibility-only"),
    AliasCompatibility(("lv", "libri"), "librivox", "token", "native"),
    AliasCompatibility(("/ysq",), "queue ys", "token", "native"),
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
    REGEX = "regex"


class SearchAction(StrEnum):
    LIST = "list"
    FIRST = "first"
    INDEXED = "indexed"
    RANDOM = "random"


class SearchScope(StrEnum):
    CATALOGUE = "catalogue"
    LIBRARY = "library"
    FAVORITES = "favorites"
    BLOCKED = "blocked"
    QUEUE = "queue"
    PLAYLIST = "playlist"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    mode: SearchMode
    action: SearchAction
    query: tuple[str, ...]
    limit: int | None = None
    result_index: int | None = None
    scope: SearchScope = SearchScope.LIBRARY
    scope_name: str | None = None


SEARCH_NAMES = {"find", "f", "rfind", "rf", "lfind", "lf"}
SEARCH_COMMANDS = SEARCH_NAMES | {f"{prefix}{name}" for prefix in (".", "/") for name in SEARCH_NAMES}
_INDEXED_SEARCH_COMMAND = re.compile(r"\.(find|f|rfind|rf|lfind|lf)([0-9]+)", re.IGNORECASE)


def is_search_command(command: str) -> bool:
    """Return whether a token is a fixed or 1-indexed search command."""
    return command.casefold() in SEARCH_COMMANDS or _INDEXED_SEARCH_COMMAND.fullmatch(command) is not None


def normalize_command(command: str) -> str:
    stripped = command.strip()
    if not stripped:
        return stripped
    exact = EXACT_ALIASES.get(stripped.casefold())
    if exact:
        return exact
    token, separator, remainder = stripped.partition(" ")
    compact_navigation = re.fullmatch(r"(\.?)([+-])(\d+)", token)
    if compact_navigation:
        dotted, direction, count = compact_navigation.groups()
        canonical = f"{dotted}{'next' if direction == '+' else 'prev'}"
        suffix = f" {remainder}" if separator else ""
        return f"{canonical} {count}{suffix}"
    canonical = TOKEN_ALIASES.get(token.casefold())
    return f"{canonical}{separator}{remainder}" if canonical else stripped


def parse_search(tokens: list[str]) -> SearchRequest:
    if not tokens or not is_search_command(tokens[0]):
        raise ValueError("Unknown search command")
    command = tokens[0].casefold()
    indexed = _INDEXED_SEARCH_COMMAND.fullmatch(command)
    result_index = None
    if indexed:
        result_index = int(indexed.group(2))
        if result_index < 1:
            raise ValueError("Search result index must be 1 or greater")
        command = f".{indexed.group(1).casefold()}"
    prefix = command[0] if command[0] in {".", "/"} else ""
    name = command[1:] if prefix else command
    mode = SearchMode.RAW if name.startswith("r") else SearchMode.LOOSE if name.startswith("l") else SearchMode.ALL
    action = (
        SearchAction.INDEXED if result_index is not None
        else SearchAction.FIRST if prefix == "."
        else SearchAction.RANDOM if prefix == "/"
        else SearchAction.LIST
    )
    query = list(tokens[1:])
    regex_flags = [index for index, value in enumerate(query) if value.casefold() in {"--regex", "--re"}]
    if len(regex_flags) > 1:
        raise ValueError("Search accepts only one --regex flag")
    if regex_flags:
        del query[regex_flags[0]]
        mode = SearchMode.REGEX
    scope = SearchScope.LIBRARY
    scope_name = None
    scope_flags = [index for index, value in enumerate(query) if value.casefold() == "--in"]
    if len(scope_flags) > 1:
        raise ValueError("Search accepts only one --in scope")
    if scope_flags:
        scope_index = scope_flags[0]
        if scope_index + 1 >= len(query):
            raise ValueError("Search --in requires library, favs, blocked, queue, or playlist <name>")
        raw_scope = query[scope_index + 1].casefold()
        aliases = {
            "catalogue": SearchScope.CATALOGUE,
            "catalog": SearchScope.CATALOGUE,
            "library": SearchScope.LIBRARY,
            "lib": SearchScope.LIBRARY,
            "favorites": SearchScope.FAVORITES,
            "favourites": SearchScope.FAVORITES,
            "favs": SearchScope.FAVORITES,
            "blocked": SearchScope.BLOCKED,
            "blacklist": SearchScope.BLOCKED,
            "queue": SearchScope.QUEUE,
            "playlist": SearchScope.PLAYLIST,
        }
        if raw_scope not in aliases:
            raise ValueError(f"Unknown search scope: {query[scope_index + 1]}")
        scope = aliases[raw_scope]
        consumed = 2
        if scope == SearchScope.PLAYLIST:
            if scope_index + 2 >= len(query):
                raise ValueError("Playlist search requires a playlist name after --in playlist")
            scope_name = query[scope_index + 2].strip()
            if not scope_name:
                raise ValueError("Playlist search requires a non-empty playlist name")
            consumed += 1
        del query[scope_index : scope_index + consumed]
    limit = result_index
    if action == SearchAction.LIST and mode != SearchMode.RAW and query and query[-1].isdigit():
        limit = int(query[-1])
        query = query[:-1]
    if not query:
        raise ValueError("Search requires one or more query terms")
    if mode == SearchMode.REGEX:
        pattern = " ".join(query)
        _compile_search_regex(pattern)
        query = [pattern]
    return SearchRequest(mode, action, tuple(query), limit, result_index, scope, scope_name)


def _normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return "".join(character for character in decomposed if character.isalnum() or character.isspace())


def _compile_search_regex(pattern: str) -> re.Pattern[str]:
    if not pattern.strip():
        raise ValueError("Search regular expression must not be empty")
    if len(pattern) > 512:
        raise ValueError("Search regular expression must be 512 characters or fewer")
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise ValueError(f"Invalid find regular expression: {error.msg}") from error


def search_rows(rows: Iterable[tuple[int, str]], request: SearchRequest) -> list[tuple[int, str]]:
    expression = _compile_search_regex(request.query[0]) if request.mode == SearchMode.REGEX else None
    terms = [_normalized(term) for term in request.query]
    matches = []
    for index, label in rows:
        if expression is not None:
            accepted = expression.search(label) is not None
        else:
            candidate = _normalized(label)
            accepted = any(term in candidate for term in terms) if request.mode == SearchMode.LOOSE else all(
                term in candidate for term in terms
            )
        if accepted:
            matches.append((index, label))
            if request.limit is not None and len(matches) >= request.limit:
                break
    return matches
