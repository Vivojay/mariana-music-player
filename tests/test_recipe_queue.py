"""Nested session queue fidelity, portability, and strict legacy migration."""

from __future__ import annotations

import copy
import json

import pytest

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.queueing import PersistentQueue
from mariana.recipe_queue import GroupIdentityMap, flat_tree, restore_snapshot, validate_tree
from mariana.session_recipes import (
    RecipeError,
    RecipeReplayEngine,
    ReplayBlocked,
    ResolvedRecipeMedia,
    effective_state,
    initial_state,
    load_recipe,
    new_recipe,
    required_capabilities,
    validate_recipe,
)


def committed_snapshot():
    return {
        "groups": [
            {"group_id": "private-installation-id", "parent_id": None, "sibling_position": 1,
             "kind": "album", "name": "Private album", "strategy": "shuffle", "shuffle_seed": -8,
             "priority": 3, "atomic": False, "source_ref": "https://private.invalid?token=SECRET",
             "metadata": {"private_path": "C:/private/album"}},
            {"group_id": "nested-installation-id", "parent_id": "private-installation-id", "sibling_position": 1,
             "kind": "playlist", "name": "Private playlist", "strategy": "priority", "priority": 7, "atomic": True},
        ],
        "items": [
            {"stable_id": "a", "group_id": None, "sibling_position": 0},
            {"stable_id": "b", "group_id": "private-installation-id", "sibling_position": 0, "priority": 4},
            {"stable_id": "a", "group_id": "nested-installation-id", "sibling_position": 0, "failure_policy": "stop"},
            {"stable_id": "c", "group_id": None, "sibling_position": 2},
        ],
        "state": {"current_position": 2, "root_strategy": "shuffle", "root_seed": -11, "shuffle_seed": -11},
    }


def reference(key):
    return {"source": "local", "stable_id": key * 24, "fingerprint": key * 64,
            "duration_ms": 60_000, "live": False, "provider_id": None}


def recipe_with_tree():
    payload = GroupIdentityMap().project(committed_snapshot())
    recipe = new_recipe(session_id="nested", media={key: reference(key) for key in "abc"})
    recipe["initial_state"].update({key: payload[key] for key in ("queue", "current_index", "queue_tree")})
    recipe["initial_state"]["shuffle_seed"] = payload["seed"]
    recipe["duration_ms"] = 2000
    return recipe


def test_nested_snapshot_preserves_occurrences_cursor_policies_and_no_private_data():
    snapshot = committed_snapshot()
    original = copy.deepcopy(snapshot)
    payload = GroupIdentityMap().project(snapshot)
    assert payload["queue"] == ["a", "b", "a", "c"] and payload["current_index"] == 2
    assert payload["seed"] == -11
    assert payload["queue_tree"]["root"] == {"strategy": "shuffle", "seed": -11}
    assert payload["queue_tree"]["groups"][0]["seed"] == -8
    assert not payload["queue_tree"]["groups"][0]["atomic"]
    assert payload["queue_tree"]["placements"][2]["failure_policy"] == "stop"
    encoded = json.dumps(payload)
    assert "private" not in encoded and "SECRET" not in encoded and "installation" not in encoded
    assert "name" not in encoded and "metadata" not in encoded and "source_ref" not in encoded
    assert snapshot == original


def test_group_ids_are_stable_for_one_recording_and_mutation_does_not_alias_duplicate_media():
    identities = GroupIdentityMap()
    snapshot = committed_snapshot()
    first = identities.project(snapshot)
    snapshot["groups"].reverse()  # Storage enumeration changes, not the tree's sibling order.
    second = identities.project(snapshot)
    assert {row["id"] for row in first["queue_tree"]["groups"]} == {row["id"] for row in second["queue_tree"]["groups"]}
    assert next(row for row in second["queue_tree"]["groups"] if row["kind"] == "playlist")["parent"] == "g1"
    assert second["current_index"] == 2 and second["queue"][0] == second["queue"][2]


def test_real_queue_restore_keeps_nested_order_and_second_duplicate_cursor(tmp_path, monkeypatch):
    queue = PersistentQueue(MarianaDatabase(tmp_path / "queue.sqlite3"))
    media = {key: MediaRef(MediaSource.LOCAL, str(tmp_path / f"{key}.flac"), stable_id=key * 24) for key in "abc"}
    recipe = recipe_with_tree()
    state = effective_state(recipe, 500)
    state["settings"].update(repeat="all", consume=True, autofill=False)
    monkeypatch.setattr(queue, "_ordered_children", lambda *_a, **_k: pytest.fail("Do not rerun strategy"))
    restored = restore_snapshot(state, media)
    queue.restore_snapshot(restored)
    items = queue.items()
    assert [item.media.stable_id for item in items] == ["a" * 24, "b" * 24, "a" * 24, "c" * 24]
    current = queue.current()
    assert current is not None and current.queue_id == items[2].queue_id
    snapshot = queue.export_snapshot()
    assert snapshot["state"]["root_seed"] == -11
    assert snapshot["state"]["repeat_mode"] == "all" and snapshot["state"]["consume_mode"] == 1
    assert snapshot["items"][2]["failure_policy"] == "stop"
    assert [node["type"] for node in queue.tree()] == ["item", "group", "item"]
    assert all(group["source_ref"] is None and group["metadata"] == {} for group in snapshot["groups"])
    assert {group["name"] for group in snapshot["groups"]} == {"Album group 1", "Playlist group 2"}


@pytest.mark.parametrize("mutation", [
    lambda tree: tree["groups"].append(copy.deepcopy(tree["groups"][0])),
    lambda tree: tree["groups"][0].update(parent="g999"),
    lambda tree: tree["groups"][0].update(parent="g2"),
    lambda tree: tree["groups"][0].update(sibling_position=0),
    lambda tree: tree["placements"][2].update(parent="g999"),
    lambda tree: tree["placements"][1].update(sibling_position=1),
    lambda tree: tree["groups"][0].update(kind="remote-command"),
    lambda tree: tree["groups"][0].update(source_ref="https://private.invalid"),
    lambda tree: tree["groups"][0].update(name="Private title"),
    lambda tree: tree["groups"][0].update(seed=True),
    lambda tree: tree["groups"][0].update(atomic=1),
    lambda tree: tree["root"].update(strategy=[]),
    lambda tree: tree["placements"][0].update(priority=2**63),
    lambda tree: tree.update(version=True),
], ids=["duplicate", "dangling-group", "cycle", "mixed-sibling-collision", "dangling-leaf", "leaf-gap",
        "kind", "source-url", "name", "boolean-seed", "atomic", "strategy", "priority", "version"])
def test_hostile_queue_trees_are_rejected(mutation):
    payload = GroupIdentityMap().project(committed_snapshot())
    mutation(payload["queue_tree"])
    with pytest.raises(RecipeError):
        validate_tree(payload["queue_tree"], payload["queue"])


def test_tree_cannot_reorder_duplicate_occurrences_behind_current_index():
    payload = GroupIdentityMap().project(committed_snapshot())
    tree = payload["queue_tree"]
    tree["placements"][0], tree["placements"][2] = tree["placements"][2], tree["placements"][0]
    with pytest.raises(RecipeError, match="occurrence order"):
        validate_tree(tree, payload["queue"])


def test_tree_depth_and_count_limits_are_checked_before_traversal():
    groups = [{"id": f"g{index + 1}", "parent": f"g{index}" if index else None,
               "sibling_position": 0, "kind": "manual", "strategy": "custom", "seed": None,
               "priority": 0, "atomic": True} for index in range(9)]
    tree = {**flat_tree([]), "groups": groups}
    with pytest.raises(RecipeError, match="nesting"):
        validate_tree(tree, [])
    tree["groups"] = [groups[0]] * 513
    with pytest.raises(RecipeError, match="limits"):
        validate_tree(tree, [])
    with pytest.raises(RecipeError, match="occurrence limit"):
        flat_tree(["a"] * 2049)


def test_tree_change_without_flat_order_change_is_recorded_and_checkpointed():
    recipe = recipe_with_tree()
    changed = copy.deepcopy(recipe["initial_state"]["queue_tree"])
    changed["groups"][0]["atomic"] = True
    changed["groups"][1]["priority"] = 11
    recipe["events"] = [{"seq": 0, "at_ms": 1000, "session_id": "nested", "kind": "queue_set", "reason": "manual",
                         "data": {"queue": ["a", "b", "a", "c"], "current_index": 2, "seed": -11, "queue_tree": changed}}]
    folded = effective_state(recipe, 1500)
    recipe["checkpoints"] = [{"at_ms": 1500, "event_index": 1, "state": folded}]
    assert effective_state(recipe, 1600)["queue_tree"] == changed
    assert effective_state(recipe, 500)["queue_tree"] != changed
    recipe["checkpoints"][0]["state"]["queue_tree"]["groups"][0]["atomic"] = False
    with pytest.raises(RecipeError, match="effective state"):
        validate_recipe(recipe)


def test_nested_capability_refusal_and_missing_source_do_not_activate_partial_queue():
    class Host:
        capabilities = frozenset({"playback", "queue", "queue_settings", "gain_settings", "crossfade_settings"})

        def __init__(self):
            self.restores = []
            self.halted = 0

        def halt(self):
            self.halted += 1

        def resolve(self, reference):
            if reference["stable_id"].startswith("b"):
                raise ReplayBlocked("missing_source")
            return ResolvedRecipeMedia(object(), reference)

        def restore(self, state, resolved):
            self.restores.append(state)

        def apply(self, event, state, resolved):
            pytest.fail("No event can apply before successful preflight")

        def is_buffering(self):
            return False

    recipe = recipe_with_tree()
    assert "queue_tree" in required_capabilities(recipe)
    host = Host()
    with pytest.raises(ReplayBlocked, match="unsupported host"):
        RecipeReplayEngine(recipe, host).start()
    host.capabilities |= {"queue_tree"}
    with pytest.raises(ReplayBlocked, match="missing source"):
        RecipeReplayEngine(recipe, host).start()
    assert host.restores == [] and host.halted == 2


def legacy_recipe():
    recipe = new_recipe(version=1, session_id="legacy", media={"a": reference("a")})
    recipe["events"] = [{"seq": 0, "at_ms": 0, "session_id": "legacy", "kind": "queue_set", "reason": "manual",
                         "data": {"queue": ["a", "a"], "current_index": 1}}]
    state = initial_state(version=1)
    state.update(queue=["a", "a"], current_index=1, at_ms=500)
    recipe["checkpoints"] = [{"at_ms": 500, "event_index": 1, "state": state}]
    recipe["duration_ms"] = 1000
    return recipe


@pytest.mark.parametrize("journal", [False, True])
def test_legacy_export_and_journal_validate_then_upgrade_without_rewriting(tmp_path, journal):
    recipe = legacy_recipe()
    path = tmp_path / "legacy.jsonl"
    if journal:
        header = new_recipe(version=1, session_id="legacy", media=recipe["media"])
        header.update(complete=False, incomplete_reason="unsealed")
        records = [{"type": "header", "value": header}, {"type": "event", "value": recipe["events"][0]},
                   {"type": "checkpoint", "value": recipe["checkpoints"][0]},
                   {"type": "seal", "value": {"duration_ms": 1000, "complete": True, "incomplete_reason": None, "event_count": 1}}]
        text = "\n".join(json.dumps(record) for record in records) + "\n"
    else:
        text = json.dumps(recipe)
    path.write_text(text)
    loaded = load_recipe(path)
    assert loaded["version"] == 2 and path.read_text() == text
    assert loaded["events"][0]["data"]["seed"] is None
    assert effective_state(loaded, 800)["current_index"] == 1
    assert effective_state(loaded, 800)["queue_tree"] == flat_tree(["a", "a"])
    assert "queue_tree" not in required_capabilities(loaded)


@pytest.mark.parametrize("target", ["initial", "event", "checkpoint"])
def test_legacy_cannot_smuggle_new_fields_and_v2_cannot_omit_tree(target):
    recipe = legacy_recipe()
    selected = (recipe["initial_state"] if target == "initial" else recipe["events"][0]["data"]
                if target == "event" else recipe["checkpoints"][0]["state"])
    selected["queue_tree"] = flat_tree(selected["queue"])
    with pytest.raises(RecipeError, match="fields"):
        validate_recipe(recipe)
    current = validate_recipe(legacy_recipe())
    selected = (current["initial_state"] if target == "initial" else current["events"][0]["data"]
                if target == "event" else current["checkpoints"][0]["state"])
    del selected["queue_tree"]
    with pytest.raises(RecipeError, match="fields"):
        validate_recipe(current)


@pytest.mark.parametrize("field,value", [("priority", 5), ("failure_policy", "stop")])
def test_flat_occurrence_policies_also_require_tree_capability(field, value):
    recipe = validate_recipe(legacy_recipe())
    recipe["checkpoints"] = []
    recipe["events"][0]["data"]["queue_tree"]["placements"][0][field] = value
    assert "queue_tree" in required_capabilities(validate_recipe(recipe))


def test_empty_root_policy_requires_tree_capability():
    recipe = new_recipe()
    recipe["initial_state"]["queue_tree"]["root"] = {"strategy": "priority", "seed": 42}
    assert "queue_tree" in required_capabilities(validate_recipe(recipe))


@pytest.mark.parametrize("version", [2, 3])
def test_imported_recipe_bounds_group_identities_across_separate_events(version):
    recipe = new_recipe(session_id="many-groups", version=version)
    for offset in range(0, 2049, 512):
        groups = [{"id": f"g{index + 1}", "parent": None, "sibling_position": index - offset,
                   "kind": "manual", "strategy": "custom", "seed": None, "priority": 0, "atomic": True}
                  for index in range(offset, min(offset + 512, 2049))]
        tree = {**flat_tree([]), "groups": groups}
        recipe["events"].append({"seq": len(recipe["events"]), "at_ms": 0, "session_id": "many-groups",
                                 "kind": "queue_set", "reason": "manual",
                                 "data": {"queue": [], "current_index": None, "seed": None, "queue_tree": tree}})
    with pytest.raises(RecipeError, match="identity budget"):
        validate_recipe(recipe)
