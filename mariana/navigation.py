"""Validated collection-relative playback navigation."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum

from mariana.models import MediaRef


class NavigationScope(StrEnum):
    """Collections that can provide an ordered playback-navigation sequence."""

    AUTO = "auto"
    LIBRARY = "library"
    QUEUE = "queue"
    FAVORITES = "favorites"
    PLAYLIST = "playlist"
    RESULTS = "results"


_SCOPE_ALIASES = {
    "auto": NavigationScope.AUTO,
    "current": NavigationScope.AUTO,
    "library": NavigationScope.LIBRARY,
    "lib": NavigationScope.LIBRARY,
    "queue": NavigationScope.QUEUE,
    "q": NavigationScope.QUEUE,
    "favorites": NavigationScope.FAVORITES,
    "favourites": NavigationScope.FAVORITES,
    "favs": NavigationScope.FAVORITES,
    "fav": NavigationScope.FAVORITES,
    "playlist": NavigationScope.PLAYLIST,
    "playlists": NavigationScope.PLAYLIST,
    "results": NavigationScope.RESULTS,
    "result": NavigationScope.RESULTS,
}


@dataclass(frozen=True, slots=True)
class NavigationRequest:
    """One validated next/previous request."""

    offset: int
    immediate: bool
    scope: NavigationScope = NavigationScope.AUTO
    scope_name: str | None = None


@dataclass(frozen=True, slots=True)
class NavigationEntry:
    """One immutable occurrence in a collection navigation snapshot."""

    media: MediaRef | None
    stable_id: str
    position: int
    label: str
    source_scope: NavigationScope
    occurrence_id: str | int | None = None


@dataclass(frozen=True, slots=True)
class NavigationContext:
    """An ordered collection and the occurrence that is currently playing."""

    scope: NavigationScope
    entries: tuple[NavigationEntry, ...]
    cursor: int
    name: str | None = None

    def matches(self, media: MediaRef | None) -> bool:
        return (
            media is not None
            and self.cursor in range(len(self.entries))
            and self.entries[self.cursor].stable_id == media.stable_id
        )

    def target(self, offset: int) -> tuple[int, NavigationEntry] | None:
        position = self.cursor + offset
        if position not in range(len(self.entries)):
            return None
        return position, self.entries[position]

    def at(self, cursor: int) -> NavigationContext:
        if cursor not in range(len(self.entries)):
            raise ValueError("Navigation cursor is outside the collection")
        return replace(self, cursor=cursor)


def parse_relative_reference(value: str) -> NavigationRequest | None:
    """Recognize a signed item offset, never an ordinary path or numeric setting."""
    match = re.fullmatch(r"([+-])\s*([0-9]+)(?:\s+(--in\s+.+))?", value.strip())
    if match is None:
        return None
    direction, count, scope = match.groups()
    return parse_navigation(
        'next' if direction == '+' else 'prev',
        [count, *(scope.split() if scope else [])],
    )


def join_relative_references(values: list[str]) -> list[str]:
    """Join spaced signs only in a list of media references, not general arguments."""
    result = []
    index = 0
    while index < len(values):
        value = values[index]
        if value in {'+', '-'} and index + 1 < len(values) and values[index + 1].isdigit():
            value += values[index + 1]
            index += 1
        result.append(value)
        index += 1
    return result


def parse_navigation(command: str, arguments: list[str]) -> NavigationRequest:
    """Parse relative navigation with optional ``[--in] collection`` selection."""

    normalized = command.casefold()
    if normalized not in {"next", "prev", ".next", ".prev"}:
        raise ValueError(f"Unknown navigation command: {command}")

    values = list(arguments)
    # A collection operand abbreviates the established flag, including after a
    # count: ``next 2 library`` means ``next 2 --in library``.
    if "--in" not in [value.casefold() for value in values]:
        collection_index = 1 if values and values[0].isdigit() else 0
        if len(values) > collection_index and values[collection_index].casefold() in _SCOPE_ALIASES:
            values.insert(collection_index, "--in")
    scope = NavigationScope.AUTO
    scope_name = None
    if "--in" in [value.casefold() for value in values]:
        indices = [index for index, value in enumerate(values) if value.casefold() == "--in"]
        if len(indices) != 1:
            raise ValueError("Navigation accepts only one --in collection")
        scope_index = indices[0]
        count_values = values[:scope_index]
        scope_values = values[scope_index + 1 :]
        if not scope_values:
            raise ValueError("--in requires library, queue, favorites, playlist, or results")
        scope = _SCOPE_ALIASES.get(scope_values[0].casefold())
        if scope is None:
            raise ValueError(f"Unknown navigation collection: {scope_values[0]}")
        trailing = scope_values[1:]
        if scope == NavigationScope.PLAYLIST:
            scope_name = " ".join(trailing).strip() or None
        elif trailing:
            raise ValueError(f"{scope.value} navigation does not accept a collection name")
    else:
        count_values = values

    if len(count_values) > 1 or (count_values and not count_values[0].isdigit()):
        raise ValueError(
            "Usage: next|prev [positive-count] [[--in] library|queue|favorites|playlist [name]|results]"
        )
    count = int(count_values[0]) if count_values else 1
    if count <= 0:
        raise ValueError("Navigation count must be a positive integer")
    direction = -1 if normalized.endswith("prev") else 1
    return NavigationRequest(
        offset=direction * count,
        immediate=normalized.startswith("."),
        scope=scope,
        scope_name=scope_name,
    )
