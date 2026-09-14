"""Atomic bulk transfers between playlists and saved favourites, preserving stars."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .models import MediaRef
from .playlists import PlaylistError, PlaylistMutationTarget, PlaylistStore
from .preferences import MediaPreferences, PreferenceState

MAX_TRANSFER_ITEMS = 5_000
_FAVOURITE_NAMES = {"fav", "favs", "favorite", "favorites", "favourite", "favourites"}


class CollectionTransferError(PlaylistError):
    """Raised when a bulk collection transfer is invalid or stale."""


class TransferOperation(StrEnum):
    COPY = "copy"
    MOVE = "move"


class CollectionKind(StrEnum):
    PLAYLIST = "playlist"
    FAVOURITES = "favs"


@dataclass(frozen=True, slots=True)
class CollectionTarget:
    kind: CollectionKind
    name: str | None = None

    @property
    def label(self) -> str:
        return f'playlist "{self.name}"' if self.kind == CollectionKind.PLAYLIST else "favourites"


@dataclass(frozen=True, slots=True)
class CollectionSelection:
    target: CollectionTarget
    indexes: tuple[int, ...] | None

    @property
    def selection_label(self) -> str:
        return "all" if self.indexes is None else ",".join(str(value) for value in self.indexes)


@dataclass(frozen=True, slots=True)
class TransferRequest:
    operation: TransferOperation
    destination: CollectionTarget
    sources: tuple[CollectionSelection, ...]
    dry_run: bool = False
    assume_yes: bool = False


@dataclass(frozen=True, slots=True)
class PlannedItem:
    source: CollectionTarget
    source_index: int
    media: MediaRef


@dataclass(slots=True)
class TransferPlan:
    request: TransferRequest
    items: tuple[PlannedItem, ...]
    playlist_targets: dict[str, PlaylistMutationTarget]
    playlist_trees: dict[str, dict[str, Any]]
    favourite_removals: tuple[str, ...]
    favourite_targets: tuple[str, ...] = ()

    @property
    def selected_count(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class TransferResult:
    operation: TransferOperation
    selected_count: int
    destination: CollectionTarget
    playlist_revisions: tuple[tuple[str, int], ...]


def _kind(value: str) -> CollectionKind:
    normalized = value.casefold()
    if normalized == CollectionKind.PLAYLIST:
        return CollectionKind.PLAYLIST
    if normalized in _FAVOURITE_NAMES:
        return CollectionKind.FAVOURITES
    raise CollectionTransferError("A collection must be 'playlist' or 'favs'")


def _parse_target(values: Sequence[str], offset: int) -> tuple[CollectionTarget, int]:
    if offset >= len(values):
        raise CollectionTransferError("Missing collection after 'to' or 'from'")
    kind = _kind(values[offset])
    offset += 1
    if kind == CollectionKind.PLAYLIST:
        if offset >= len(values):
            raise CollectionTransferError("A playlist collection requires a playlist name")
        return CollectionTarget(kind, values[offset]), offset + 1
    return CollectionTarget(kind), offset


def parse_item_selection(value: str) -> tuple[int, ...] | None:
    """Parse one-based indexes, inclusive ranges, or ``all``."""
    value = value.strip().casefold()
    if value == "all":
        return None
    if not value:
        raise CollectionTransferError("Item selection cannot be empty")
    result: list[int] = []
    seen: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise CollectionTransferError(
                "Item selections use one-based indexes such as 1,2,6, 3-5, or all"
            )
        try:
            start = int(match.group(1))
            end = int(match.group(2) or start)
        except ValueError as error:
            raise CollectionTransferError("Item selection indexes are too large") from error
        if start < 1 or end < start:
            raise CollectionTransferError("Item ranges must be positive and ascending")
        for index in range(start, end + 1):
            if index in seen:
                raise CollectionTransferError(f"Item {index} is selected more than once")
            result.append(index)
            seen.add(index)
            if len(result) > MAX_TRANSFER_ITEMS:
                raise CollectionTransferError(
                    f"A single transfer cannot select more than {MAX_TRANSFER_ITEMS} items"
                )
    return tuple(result)


def parse_transfer_request(arguments: Sequence[str]) -> TransferRequest:
    """Parse the explicit multi-source transfer grammar."""
    values = list(arguments)
    dry_run = values.count("--dry-run") == 1
    assume_yes = values.count("--yes") == 1
    if values.count("--dry-run") > 1 or values.count("--yes") > 1:
        raise CollectionTransferError("Each transfer flag may be supplied only once")
    unknown_flags = [value for value in values if value.startswith("--") and value not in {"--dry-run", "--yes"}]
    if unknown_flags:
        raise CollectionTransferError(f"Unknown transfer option: {unknown_flags[0]}")
    values = [value for value in values if value not in {"--dry-run", "--yes"}]
    if assume_yes and dry_run:
        raise CollectionTransferError("--yes is unnecessary with --dry-run")
    if len(values) < 6:
        raise CollectionTransferError(
            'Usage: transfer copy|move to playlist "<name>"|favs '
            'from playlist "<name>"|favs items <1,2,6|3-5|all> [...] [--dry-run] [--yes]'
        )
    try:
        operation = TransferOperation(values[0].casefold())
    except ValueError as error:
        raise CollectionTransferError("Transfer operation must be copy or move") from error
    if values[1].casefold() != "to":
        raise CollectionTransferError("Expected 'to' after transfer operation")
    destination, offset = _parse_target(values, 2)
    sources: list[CollectionSelection] = []
    source_keys: set[tuple[CollectionKind, str | None]] = set()
    while offset < len(values):
        if values[offset].casefold() != "from":
            raise CollectionTransferError("Expected 'from' before each source collection")
        source, offset = _parse_target(values, offset + 1)
        if offset >= len(values) or values[offset].casefold() != "items":
            raise CollectionTransferError("Each source requires 'items' followed by indexes, a range, or all")
        if offset + 1 >= len(values):
            raise CollectionTransferError("Missing item selection after 'items'")
        selection = parse_item_selection(values[offset + 1])
        offset += 2
        key = (source.kind, source.name.casefold() if source.name else None)
        if key in source_keys:
            raise CollectionTransferError(
                f"Source {source.label} appears more than once; combine its indexes in one items clause"
            )
        source_keys.add(key)
        sources.append(CollectionSelection(source, selection))
    if not sources:
        raise CollectionTransferError("At least one source collection is required")
    destination_key = (
        destination.kind,
        destination.name.casefold() if destination.name else None,
    )
    if destination_key in source_keys:
        raise CollectionTransferError(
            "Source and destination cannot be the same collection; use playlist move for reordering"
        )
    if operation == TransferOperation.COPY and assume_yes:
        raise CollectionTransferError("--yes applies only to destructive move transfers")
    return TransferRequest(operation, destination, tuple(sources), dry_run, assume_yes)


class CollectionTransferService:
    """Plan and atomically apply transfers using the shared Mariana database."""

    def __init__(
        self,
        playlists: PlaylistStore,
        preferences: MediaPreferences,
        *,
        favourite_binder: Callable[[MediaRef], tuple[MediaRef | None, str | None]] | None = None,
    ) -> None:
        if playlists.database is not preferences.database:
            raise ValueError("Playlist and preference stores must share one database")
        self.playlists = playlists
        self.preferences = preferences
        self.database = playlists.database
        self.favourite_binder = favourite_binder

    @staticmethod
    def _selected_indexes(indexes: tuple[int, ...] | None, count: int, label: str) -> tuple[int, ...]:
        if (count if indexes is None else len(indexes)) > MAX_TRANSFER_ITEMS:
            raise CollectionTransferError(
                f"A single transfer cannot select more than {MAX_TRANSFER_ITEMS} items"
            )
        selected = tuple(range(1, count + 1)) if indexes is None else indexes
        if not selected:
            raise CollectionTransferError(f"{label} is empty")
        if any(isinstance(index, bool) or not isinstance(index, int) or index < 1 for index in selected):
            raise CollectionTransferError("Item indexes must be positive integers")
        if len(set(selected)) != len(selected):
            raise CollectionTransferError("An item cannot be selected more than once")
        invalid = next((index for index in selected if index > count), None)
        if invalid is not None:
            raise CollectionTransferError(f"{label} has no item {invalid}; it contains {count} items")
        return selected

    def _playlist_items(self, tree: dict[str, Any]) -> list[tuple[int, MediaRef]]:
        result: list[tuple[int, MediaRef]] = []
        for node in self.playlists._children(tree, None):
            for item_index in self.playlists._descendant_item_indexes(tree, node):
                payload = tree["items"][item_index].get("media")
                if isinstance(payload, dict):
                    result.append((item_index, MediaRef.from_dict(payload)))
        return result

    def plan(self, request: TransferRequest) -> TransferPlan:
        targets: dict[str, PlaylistMutationTarget] = {}
        trees: dict[str, dict[str, Any]] = {}
        selected_items: list[PlannedItem] = []
        source_playlist_item_indexes: dict[str, set[int]] = {}
        source_playlist_ids: set[str] = set()
        favourite_removals: list[str] = []

        destination_playlist_id: str | None = None
        if request.destination.kind == CollectionKind.PLAYLIST:
            destination = self.playlists.get(request.destination.name or "")
            destination_playlist_id = destination.playlist_id
            targets[destination.playlist_id] = PlaylistMutationTarget(
                destination.playlist_id, destination.name, destination.revision,
            )
            trees[destination.playlist_id] = self.playlists._normalized_tree(destination.tree)

        for selection in request.sources:
            if selection.target.kind == CollectionKind.PLAYLIST:
                playlist = self.playlists.get(selection.target.name or "")
                if playlist.playlist_id == destination_playlist_id:
                    raise CollectionTransferError(
                        "Source and destination resolve to the same playlist; use playlist move for reordering"
                    )
                if playlist.playlist_id in source_playlist_ids:
                    raise CollectionTransferError(
                        "Selections resolve to the same source playlist; combine their indexes"
                    )
                source_playlist_ids.add(playlist.playlist_id)
                target = PlaylistMutationTarget(playlist.playlist_id, playlist.name, playlist.revision)
                targets[playlist.playlist_id] = target
                tree = self.playlists._normalized_tree(playlist.tree)
                trees[playlist.playlist_id] = tree
                available = self._playlist_items(tree)
                indexes = self._selected_indexes(selection.indexes, len(available), selection.target.label)
                for display_index in indexes:
                    item_index, media = available[display_index - 1]
                    selected_items.append(PlannedItem(selection.target, display_index, media))
                    source_playlist_item_indexes.setdefault(playlist.playlist_id, set()).add(item_index)
            else:
                entries = self.preferences.list(PreferenceState.FAVORITE)
                indexes = self._selected_indexes(selection.indexes, len(entries), selection.target.label)
                for display_index in indexes:
                    entry = entries[display_index - 1]
                    media = self.preferences.media(entry.stable_id)
                    if media is None:
                        raise CollectionTransferError(
                            f"Favourite item {display_index} no longer has usable media metadata"
                        )
                    selected_items.append(PlannedItem(selection.target, display_index, media))
                    favourite_removals.append(media.stable_id)

        if not selected_items:
            raise CollectionTransferError("The transfer did not select any media")
        if len(selected_items) > MAX_TRANSFER_ITEMS:
            raise CollectionTransferError(
                f"A single transfer cannot select more than {MAX_TRANSFER_ITEMS} items"
            )

        if destination_playlist_id is not None:
            tree = trees[destination_playlist_id]
            children = self.playlists._children(tree, None)
            for item in selected_items:
                tree["items"].append(
                    {
                        "stable_id": item.media.stable_id,
                        "media": item.media.to_dict(),
                        "priority": 0,
                        "attempts": 0,
                        "failure_policy": "skip",
                        "group_id": None,
                        "sibling_position": len(children),
                    }
                )
                children.append(("item", str(len(tree["items"]) - 1)))
            self.playlists._renumber(tree, None, children)
        else:
            validated_items: list[PlannedItem] = []
            for item in selected_items:
                bound, reason = (
                    self.favourite_binder(item.media)
                    if self.favourite_binder
                    else (item.media, None)
                )
                if bound is None or reason:
                    raise CollectionTransferError(
                        f"Cannot add {item.source.label} item {item.source_index} to favourites: "
                        f"{reason or 'rating is unavailable'}"
                    )
                validated_items.append(
                    PlannedItem(item.source, item.source_index, bound)
                )
            selected_items = validated_items

        if request.operation == TransferOperation.MOVE:
            for playlist_id, indexes in source_playlist_item_indexes.items():
                tree = trees[playlist_id]
                tree["items"] = [
                    item for index, item in enumerate(tree["items"]) if index not in indexes
                ]
                parent_ids = {None, *(str(group["group_id"]) for group in tree["groups"])}
                for parent_id in parent_ids:
                    self.playlists._renumber(tree, parent_id, self.playlists._children(tree, parent_id))

        for tree in trees.values():
            self.playlists._tree_nodes(tree)
        modified_playlist_ids = (
            set(trees)
            if request.operation == TransferOperation.MOVE
            else ({destination_playlist_id} if destination_playlist_id else set())
        )
        return TransferPlan(
            request,
            tuple(selected_items),
            targets,
            {
                playlist_id: trees[playlist_id]
                for playlist_id in modified_playlist_ids
            },
            tuple(dict.fromkeys(favourite_removals)) if request.operation == TransferOperation.MOVE else (),
            tuple(dict.fromkeys(favourite_removals)),
        )

    def apply(self, plan: TransferPlan) -> TransferResult:
        if plan.request.dry_run:
            raise CollectionTransferError("A dry-run plan cannot be applied")
        now = time.time()
        with self.database.transaction() as connection:
            try:
                bound_playlists = {
                    playlist_id: self.playlists._bound_mutation_playlist(connection, target)
                    for playlist_id, target in plan.playlist_targets.items()
                }
            except PlaylistError as error:
                raise CollectionTransferError(str(error)) from error
            for stable_id in plan.favourite_targets:
                if connection.execute(
                    "SELECT 1 FROM media_preferences WHERE stable_id=? AND state='favorite'",
                    (stable_id,),
                ).fetchone() is None:
                    raise CollectionTransferError("Favourites changed after confirmation; retry the command")
            for playlist_id, tree in plan.playlist_trees.items():
                playlist = bound_playlists[playlist_id]
                payload = json.dumps(tree, ensure_ascii=False)
                connection.execute(
                    "INSERT OR IGNORE INTO playlist_revisions(playlist_id,revision,tree_json,created_at) "
                    "VALUES(?,?,?,?)",
                    (playlist_id, playlist.revision, json.dumps(playlist.tree, ensure_ascii=False), now),
                )
                cursor = connection.execute(
                    "UPDATE playlists SET tree_json=?,revision=revision+1,updated_at=? "
                    "WHERE playlist_id=? AND revision=?",
                    (payload, now, playlist_id, playlist.revision),
                )
                if cursor.rowcount != 1:
                    raise CollectionTransferError("A playlist changed after confirmation; retry the command")

            if plan.request.destination.kind == CollectionKind.FAVOURITES:
                for item in plan.items:
                    self.preferences._upsert_media(connection, item.media)
                    connection.execute(
                        "INSERT INTO media_preferences(stable_id,state,rating,updated_at) VALUES(?,?,0,?) "
                        "ON CONFLICT(stable_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
                        (item.media.stable_id, PreferenceState.FAVORITE.value, now),
                    )

            if plan.request.operation == TransferOperation.MOVE:
                for stable_id in plan.favourite_removals:
                    cursor = connection.execute(
                        "UPDATE media_preferences SET state=?,updated_at=? "
                        "WHERE stable_id=? AND state='favorite'",
                        (PreferenceState.NEUTRAL.value, now, stable_id),
                    )
                    if cursor.rowcount != 1:
                        raise CollectionTransferError(
                            "Favourites changed after confirmation; retry the command"
                        )

            revisions = tuple(
                (bound_playlists[playlist_id].name, bound_playlists[playlist_id].revision + 1)
                for playlist_id in sorted(plan.playlist_trees)
            )
        return TransferResult(
            plan.request.operation,
            plan.selected_count,
            plan.request.destination,
            revisions,
        )
