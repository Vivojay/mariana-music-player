"""Portable queue hierarchy: committed order, no paths or source bindings."""

from __future__ import annotations

import copy
import re
from collections import defaultdict
from collections.abc import Mapping
from typing import Any

from .models import MediaRef
from .recipe_errors import RecipeError

MAX_LEAVES = 2048
MAX_GROUPS = 512
MAX_NODES = MAX_LEAVES + MAX_GROUPS
MAX_DEPTH = 8
MAX_GROUP_IDENTITIES = 2048
MIN_INTEGER = -(2**63)
MAX_INTEGER = 2**63 - 1
GROUP_ID = re.compile(r"g[1-9][0-9]{0,3}\Z")
MEDIA_KEY = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
KINDS = frozenset({"manual", "album", "playlist"})
STRATEGIES = frozenset({"sequential", "shuffle", "priority", "artist-fair", "smart", "custom"})


def _object(value: Any, fields: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise RecipeError("Invalid recipe queue fields")
    return value


def _integer(value: Any, minimum: int = MIN_INTEGER, maximum: int = MAX_INTEGER) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise RecipeError("Invalid recipe queue integer")
    return value


def _choice(value: Any, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise RecipeError("Unsupported recipe queue policy")
    return value


def _group(value: Any) -> str:
    if not isinstance(value, str) or not GROUP_ID.fullmatch(value):
        raise RecipeError("Invalid recipe group identity")
    return value


def flat_tree(queue: list[str]) -> dict:
    if len(queue) > MAX_LEAVES:
        raise RecipeError("Recipe queue exceeds its occurrence limit")
    return {
        "version": 1, "groups": [],
        "placements": [{"parent": None, "sibling_position": index, "priority": 0, "failure_policy": "skip"}
                       for index in range(len(queue))],
        "root": {"strategy": "custom", "seed": None},
    }


def validate_tree(value: Any, queue: list[str]) -> dict:
    """Require one complete bounded tree whose DFS equals recorded occurrences."""
    tree = _object(value, {"version", "groups", "placements", "root"})
    if type(tree["version"]) is not int or tree["version"] != 1:
        raise RecipeError("Unsupported recipe queue version")
    if not isinstance(queue, list) or len(queue) > MAX_LEAVES or any(
        not isinstance(key, str) or not MEDIA_KEY.fullmatch(key) for key in queue
    ):
        raise RecipeError("Invalid recipe queue media keys")
    if not isinstance(tree["groups"], list) or len(tree["groups"]) > MAX_GROUPS \
            or not isinstance(tree["placements"], list) or len(tree["placements"]) != len(queue) \
            or len(tree["placements"]) + len(tree["groups"]) > MAX_NODES:
        raise RecipeError("Recipe queue exceeds its node limits")
    root = _object(tree["root"], {"strategy", "seed"})
    _choice(root["strategy"], STRATEGIES)
    if root["seed"] is not None:
        _integer(root["seed"])
    groups: dict[str, dict] = {}
    children: dict[str | None, list[tuple[int, str, str | int]]] = defaultdict(list)
    for value in tree["groups"]:
        group = _object(value, {"id", "parent", "sibling_position", "kind", "strategy", "seed", "priority", "atomic"})
        identifier = _group(group["id"])
        if identifier in groups:
            raise RecipeError("Duplicate recipe group identity")
        if group["parent"] is not None:
            _group(group["parent"])
        position = _integer(group["sibling_position"], 0, MAX_NODES - 1)
        _choice(group["kind"], KINDS)
        _choice(group["strategy"], STRATEGIES)
        if group["seed"] is not None:
            _integer(group["seed"])
        _integer(group["priority"])
        if type(group["atomic"]) is not bool:
            raise RecipeError("Invalid recipe group atomic policy")
        groups[identifier] = group
        children[group["parent"]].append((position, "group", identifier))
    for index, value in enumerate(tree["placements"]):
        placement = _object(value, {"parent", "sibling_position", "priority", "failure_policy"})
        if placement["parent"] is not None:
            _group(placement["parent"])
        position = _integer(placement["sibling_position"], 0, MAX_NODES - 1)
        _integer(placement["priority"])
        _choice(placement["failure_policy"], frozenset({"skip", "retry", "stop"}))
        children[placement["parent"]].append((position, "item", index))
    for parent, siblings in children.items():
        if parent is not None and parent not in groups:
            raise RecipeError("Recipe queue has a dangling parent")
        if sorted(position for position, _, _ in siblings) != list(range(len(siblings))):
            raise RecipeError("Recipe queue sibling positions collide or are incomplete")
    visited: set[str] = set()
    occurrences: list[int] = []

    def visit(parent: str | None, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise RecipeError("Recipe queue exceeds its nesting limit")
        for _, kind, identifier in sorted(children.get(parent, [])):
            if kind == "group":
                if not isinstance(identifier, str) or identifier in visited:
                    raise RecipeError("Recipe queue contains cyclic groups")
                visited.add(identifier)
                visit(identifier, depth + 1)
            else:
                assert isinstance(identifier, int)
                occurrences.append(identifier)

    visit(None, 0)
    if visited != set(groups):
        raise RecipeError("Recipe queue contains orphaned or cyclic groups")
    if occurrences != list(range(len(queue))):
        raise RecipeError("Recipe hierarchy changes the recorded occurrence order")
    return copy.deepcopy(tree)


class GroupIdentityMap:
    """Per-recording opaque IDs; never export installation group identifiers."""

    def __init__(self) -> None:
        self._ids: dict[str, str] = {}

    def project(self, snapshot: dict) -> dict:
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("items"), list) \
                or not isinstance(snapshot.get("groups"), list) or not isinstance(snapshot.get("state"), dict):
            raise RecipeError("Invalid committed queue snapshot")
        items, raw_groups, state = snapshot["items"], snapshot["groups"], snapshot["state"]
        if len(items) > MAX_LEAVES or len(raw_groups) > MAX_GROUPS:
            raise RecipeError("Recipe queue exceeds its node limits")
        mapping = dict(self._ids)
        present = set()
        for group in raw_groups:
            if not isinstance(group, dict) or not isinstance(group.get("group_id"), str) \
                    or not 1 <= len(group["group_id"]) <= 128 or group["group_id"] in present:
                raise RecipeError("Invalid committed group identity")
            identifier = group["group_id"]
            present.add(identifier)
            if identifier not in mapping:
                if len(mapping) >= MAX_GROUP_IDENTITIES:
                    raise RecipeError("Recipe group identity budget exhausted")
                mapping[identifier] = f"g{len(mapping) + 1}"

        def parent(value: Any) -> str | None:
            if value is None:
                return None
            if not isinstance(value, str) or value not in present:
                raise RecipeError("Committed queue has a dangling parent")
            return mapping[value]

        queue = []
        placements = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise RecipeError("Invalid committed queue occurrence")
            queue.append(item.get("stable_id"))
            placements.append({
                "parent": parent(item.get("group_id")), "sibling_position": item.get("sibling_position", index),
                "priority": item.get("priority", 0), "failure_policy": item.get("failure_policy", "skip"),
            })
        groups = [{
            "id": mapping[group["group_id"]], "parent": parent(group.get("parent_id")),
            "sibling_position": group.get("sibling_position", 0), "kind": group.get("kind", "manual"),
            "strategy": group.get("strategy", "custom"), "seed": group.get("shuffle_seed"),
            "priority": group.get("priority", 0), "atomic": group.get("atomic", True),
        } for group in raw_groups]
        groups.sort(key=lambda group: int(group["id"][1:]))
        tree = validate_tree({
            "version": 1, "groups": groups, "placements": placements,
            "root": {"strategy": state.get("root_strategy", "custom"), "seed": state.get("root_seed")},
        }, queue)
        current = state.get("current_position")
        if current is not None:
            _integer(current, 0, len(queue) - 1)
        seed = state.get("shuffle_seed")
        if seed is not None:
            _integer(seed)
        self._ids = mapping
        return {"queue": queue, "current_index": current, "seed": seed, "queue_tree": tree}


def restore_snapshot(state: dict, resolved: Mapping[str, object]) -> dict:
    """Build one safe local restore snapshot after exact source preflight.

    This does no database mutation. The root submits it to the existing queue's
    transactional restore only after all sources and policy checks succeed.
    """
    queue = state["queue"]
    tree = validate_tree(state["queue_tree"], queue)
    current = state["current_index"]
    if current is not None:
        _integer(current, 0, len(queue) - 1)
    items = []
    for key, placement in zip(queue, tree["placements"], strict=True):
        media = resolved.get(key)
        if not isinstance(media, MediaRef):
            raise RecipeError("A recipe queue source is unavailable")
        items.append({"stable_id": media.stable_id, "media": media.to_dict(),
                      "group_id": placement["parent"], "sibling_position": placement["sibling_position"],
                      "priority": placement["priority"], "failure_policy": placement["failure_policy"], "attempts": 0})
    groups = [{
        "group_id": group["id"], "parent_id": group["parent"], "sibling_position": group["sibling_position"],
        "name": f"{group['kind'].title()} group {group['id'][1:]}", "kind": group["kind"],
        "strategy": group["strategy"], "shuffle_seed": group["seed"], "priority": group["priority"],
        "atomic": group["atomic"], "source_ref": None, "metadata": {},
    } for group in tree["groups"]]
    settings = state["settings"]
    return {"items": items, "groups": groups, "state": {
        "current_position": current, "repeat_mode": settings["repeat"], "consume_mode": settings["consume"],
        "autofill": settings["autofill"], "shuffle_seed": state["shuffle_seed"],
        "root_strategy": tree["root"]["strategy"], "root_seed": tree["root"]["seed"],
    }}
