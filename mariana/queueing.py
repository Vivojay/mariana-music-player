"""Transactional, persistent queue operations."""

from __future__ import annotations

import json
import os
import random
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from typing import cast

from .database import MarianaDatabase
from .models import (
    MediaCapabilities,
    MediaChapter,
    MediaRef,
    MediaSource,
    QueueGroup,
    QueueItem,
    QueueStrategy,
)
from .playlists import PlaylistError, PlaylistStore
from .sources import sanitized_resolver_data

VALID_REPEAT_MODES = {"off", "one", "all"}
VALID_FAILURE_POLICIES = {"skip", "retry", "stop"}
QUEUE_ORIGIN_KEY = "queue_origin"
DEFAULT_LIBRARY_ORIGIN = "default-library"
CUSTOM_ORIGIN = "custom"
MAX_QUEUE_DEPTH = 8


class QueueError(RuntimeError):
    pass


class PersistentQueue:
    def __init__(self, database: MarianaDatabase):
        self.database = database
        self.playlists = PlaylistStore(database)

    @staticmethod
    def _media_from_row(row) -> MediaRef:
        return MediaRef(
            stable_id=row["stable_id"],
            source=MediaSource(row["source"]),
            original_uri=row["original_uri"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
            duration=row["duration"],
            capabilities=MediaCapabilities.from_json(row["capabilities_json"]),
            resolver_data=json.loads(row["resolver_json"]),
            chapters=[MediaChapter.from_dict(item) for item in json.loads(row["chapters_json"] or "[]")],
            provenance=row["provenance"],
        )

    @staticmethod
    def _group_from_row(row) -> QueueGroup:
        return QueueGroup(
            group_id=str(row["group_id"]),
            parent_id=row["parent_id"],
            name=str(row["name"]),
            kind=str(row["kind"]),
            sibling_position=int(row["sibling_position"]),
            strategy=QueueStrategy(row["strategy"]),
            shuffle_seed=row["shuffle_seed"],
            priority=int(row["priority"]),
            atomic=bool(row["atomic_group"]),
            source_ref=row["source_ref"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def _upsert_media(self, connection, media: MediaRef) -> None:
        connection.execute(
            """
            INSERT INTO media_items(
                stable_id, source, original_uri, title, artist, album, duration,
                capabilities_json, resolver_json, chapters_json, provenance, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stable_id) DO UPDATE SET
                source=excluded.source,
                original_uri=excluded.original_uri,
                title=COALESCE(excluded.title, media_items.title),
                artist=COALESCE(excluded.artist, media_items.artist),
                album=COALESCE(excluded.album, media_items.album),
                duration=COALESCE(excluded.duration, media_items.duration),
                capabilities_json=excluded.capabilities_json,
                resolver_json=excluded.resolver_json,
                chapters_json=excluded.chapters_json,
                provenance=excluded.provenance,
                updated_at=excluded.updated_at
            """,
            (
                media.stable_id,
                media.source.value,
                media.original_uri,
                media.title,
                media.artist,
                media.album,
                media.duration,
                media.capabilities.to_json(),
                json.dumps(sanitized_resolver_data(media.resolver_data), ensure_ascii=False, sort_keys=True),
                json.dumps([asdict(chapter) for chapter in media.chapters], ensure_ascii=False),
                media.provenance,
                time.time(),
            ),
        )

    @staticmethod
    def _set_origin(connection, origin: str) -> None:
        connection.execute(
            "INSERT INTO app_state(key, value_json, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (QUEUE_ORIGIN_KEY, json.dumps(origin), time.time()),
        )

    def origin(self) -> str | None:
        value = self.database.get_state(QUEUE_ORIGIN_KEY)
        return value if value in {DEFAULT_LIBRARY_ORIGIN, CUSTOM_ORIGIN} else None

    @staticmethod
    def _children(connection, parent_id: str | None) -> list[tuple[str, str]]:
        rows = connection.execute(
            "SELECT node_type,node_id FROM ("
            "SELECT 'group' AS node_type,group_id AS node_id,sibling_position FROM queue_groups WHERE parent_id IS ? "
            "UNION ALL "
            "SELECT 'item' AS node_type,CAST(id AS TEXT) AS node_id,sibling_position FROM queue_items WHERE group_id IS ?"
            ") ORDER BY sibling_position,node_type,node_id",
            (parent_id, parent_id),
        ).fetchall()
        return [(str(row["node_type"]), str(row["node_id"])) for row in rows]

    @staticmethod
    def _renumber_children(connection, parent_id: str | None, children: list[tuple[str, str]]) -> None:
        for position, (node_type, node_id) in enumerate(children):
            if node_type == "group":
                connection.execute(
                    "UPDATE queue_groups SET sibling_position=?,updated_at=? WHERE group_id=?",
                    (position, time.time(), node_id),
                )
            else:
                connection.execute(
                    "UPDATE queue_items SET sibling_position=? WHERE id=?",
                    (position, int(node_id)),
                )

    def _flatten_ids(self, connection, parent_id: str | None = None, depth: int = 0) -> list[int]:
        if depth > MAX_QUEUE_DEPTH:
            raise QueueError(f"Queue nesting cannot exceed {MAX_QUEUE_DEPTH} levels")
        result: list[int] = []
        for node_type, node_id in self._children(connection, parent_id):
            if node_type == "group":
                result.extend(self._flatten_ids(connection, node_id, depth + 1))
            else:
                result.append(int(node_id))
        return result

    def _recompile(self, connection) -> None:
        ordered_ids = self._flatten_ids(connection)
        connection.execute("UPDATE queue_items SET position=position+1000000")
        for position, queue_id in enumerate(ordered_ids):
            connection.execute("UPDATE queue_items SET position=? WHERE id=?", (position, queue_id))

    def groups(self) -> list[QueueGroup]:
        return [
            self._group_from_row(row)
            for row in self.database.fetchall("SELECT * FROM queue_groups ORDER BY parent_id,sibling_position")
        ]

    def tree(self) -> list[dict]:
        items = {str(item.queue_id): item for item in self.items()}
        groups = {group.group_id: group for group in self.groups()}
        with self.database.transaction() as connection:
            def visit(parent_id: str | None, prefix: tuple[int, ...], depth: int) -> list[dict]:
                if depth > MAX_QUEUE_DEPTH:
                    raise QueueError(f"Queue nesting cannot exceed {MAX_QUEUE_DEPTH} levels")
                result = []
                for index, (node_type, node_id) in enumerate(self._children(connection, parent_id), 1):
                    path = (*prefix, index)
                    if node_type == "group":
                        group = groups[node_id]
                        result.append(
                            {
                                "type": "group",
                                "id": group.group_id,
                                "path": ".".join(map(str, path)),
                                "group": group,
                                "children": visit(group.group_id, path, depth + 1),
                            }
                        )
                    else:
                        result.append(
                            {
                                "type": "item",
                                "id": node_id,
                                "path": ".".join(map(str, path)),
                                "item": items[node_id],
                            }
                        )
                return result

            return visit(None, (), 0)

    def resolve_node(self, reference: str) -> dict:
        value = reference.strip()
        if not value:
            raise QueueError("Queue node reference cannot be empty")
        nodes = self.tree()
        if all(part.isdigit() and int(part) > 0 for part in value.split(".")):
            current = None
            children = nodes
            for part in value.split("."):
                index = int(part) - 1
                if index not in range(len(children)):
                    raise QueueError(f"Unknown queue path: {reference}")
                current = children[index]
                children = current.get("children", [])
            if current is None:
                raise QueueError(f"Unknown queue path: {reference}")
            return current

        def walk(values) -> dict | None:
            for node in values:
                if node["id"] == value or (node["type"] == "item" and f"item:{node['id']}" == value):
                    return node
                if found := walk(node.get("children", [])):
                    return found
            return None

        found = walk(nodes)
        if not found:
            raise QueueError(f"Unknown queue node: {reference}")
        return found

    def create_group(
        self,
        name: str,
        *,
        parent: str | None = None,
        position: int | None = None,
        kind: str = "manual",
        atomic: bool = True,
        source_ref: str | None = None,
        metadata: dict | None = None,
    ) -> QueueGroup:
        normalized = name.strip()
        if not normalized:
            raise QueueError("Queue group name cannot be empty")
        parent_id = None
        if parent:
            node = self.resolve_node(parent)
            if node["type"] != "group":
                raise QueueError("A queue group parent must reference another group")
            parent_id = node["id"]
            if len(node["path"].split(".")) >= MAX_QUEUE_DEPTH:
                raise QueueError(f"Queue nesting cannot exceed {MAX_QUEUE_DEPTH} levels")
        group_id = uuid.uuid4().hex
        now = time.time()
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            children = self._children(connection, parent_id)
            insert_at = len(children) if position is None else max(0, min(position, len(children)))
            connection.execute(
                "INSERT INTO queue_groups(group_id,parent_id,name,kind,sibling_position,atomic_group,source_ref,"
                "metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    group_id,
                    parent_id,
                    normalized,
                    kind,
                    len(children),
                    int(atomic),
                    source_ref,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            children.insert(insert_at, ("group", group_id))
            self._renumber_children(connection, parent_id, children)
            self._recompile(connection)
        return next(group for group in self.groups() if group.group_id == group_id)

    def rename_group(self, reference: str, name: str) -> QueueGroup:
        node = self.resolve_node(reference)
        if node["type"] != "group":
            raise QueueError("Queue group rename requires a group")
        normalized = name.strip()
        if not normalized:
            raise QueueError("Queue group name cannot be empty")
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            connection.execute(
                "UPDATE queue_groups SET name=?,updated_at=? WHERE group_id=?",
                (normalized, time.time(), node["id"]),
            )
        return next(group for group in self.groups() if group.group_id == node["id"])

    def set_group_atomic(self, reference: str, enabled: bool) -> QueueGroup:
        node = self.resolve_node(reference)
        if node["type"] != "group":
            raise QueueError("Queue atomic policy requires a group")
        with self.database.transaction() as connection:
            self._record_history(connection)
            connection.execute(
                "UPDATE queue_groups SET atomic_group=?,updated_at=? WHERE group_id=?",
                (int(enabled), time.time(), node["id"]),
            )
        return next(group for group in self.groups() if group.group_id == node["id"])

    def _group_descendants(self, connection, group_id: str) -> set[str]:
        result: set[str] = set()
        pending = [group_id]
        while pending:
            parent = pending.pop()
            children = [
                str(row["group_id"])
                for row in connection.execute(
                    "SELECT group_id FROM queue_groups WHERE parent_id=?", (parent,)
                ).fetchall()
            ]
            result.update(children)
            pending.extend(children)
        return result

    def _group_depth(self, connection, group_id: str | None) -> int:
        depth = 0
        current = group_id
        seen = set()
        while current:
            if current in seen:
                raise QueueError("Queue group cycle detected")
            seen.add(current)
            row = connection.execute(
                "SELECT parent_id FROM queue_groups WHERE group_id=?", (current,)
            ).fetchone()
            if not row:
                raise QueueError("Queue group parent is missing")
            depth += 1
            current = row["parent_id"]
        return depth

    def _subtree_height(self, connection, group_id: str) -> int:
        children = [
            str(row["group_id"])
            for row in connection.execute(
                "SELECT group_id FROM queue_groups WHERE parent_id=?", (group_id,)
            ).fetchall()
        ]
        return 1 + max((self._subtree_height(connection, child) for child in children), default=0)

    def move_group(
        self,
        reference: str,
        *,
        parent: str | None = None,
        position: int | None = None,
    ) -> QueueGroup:
        node = self.resolve_node(reference)
        if node["type"] != "group":
            raise QueueError("Queue group move requires a group")
        group_id = node["id"]
        parent_id = None
        if parent:
            parent_node = self.resolve_node(parent)
            if parent_node["type"] != "group":
                raise QueueError("A queue group parent must reference another group")
            parent_id = parent_node["id"]
        if parent_id == group_id:
            raise QueueError("A queue group cannot contain itself")
        with self.database.transaction() as connection:
            descendants = self._group_descendants(connection, group_id)
            if parent_id in descendants:
                raise QueueError("Queue groups cannot form a cycle")
            if self._group_depth(connection, parent_id) + self._subtree_height(connection, group_id) > MAX_QUEUE_DEPTH:
                raise QueueError(f"Queue nesting cannot exceed {MAX_QUEUE_DEPTH} levels")
            row = connection.execute(
                "SELECT parent_id FROM queue_groups WHERE group_id=?", (group_id,)
            ).fetchone()
            old_parent = row["parent_id"]
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            old_children = [child for child in self._children(connection, old_parent) if child != ("group", group_id)]
            self._renumber_children(connection, old_parent, old_children)
            new_children = old_children if old_parent == parent_id else self._children(connection, parent_id)
            insert_at = len(new_children) if position is None else max(0, min(position, len(new_children)))
            connection.execute(
                "UPDATE queue_groups SET parent_id=?,sibling_position=?,updated_at=? WHERE group_id=?",
                (parent_id, len(new_children), time.time(), group_id),
            )
            new_children.insert(insert_at, ("group", group_id))
            self._renumber_children(connection, parent_id, new_children)
            self._recompile(connection)
        return next(group for group in self.groups() if group.group_id == group_id)

    def remove_group(self, reference: str, *, flatten: bool = False, recursive: bool = False) -> QueueGroup:
        node = self.resolve_node(reference)
        if node["type"] != "group":
            raise QueueError("Queue group removal requires a group")
        group = node["group"]
        with self.database.transaction() as connection:
            children = self._children(connection, group.group_id)
            if children and not (flatten or recursive):
                raise QueueError("Queue group is not empty; use --flatten or --recursive")
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            parent_children = self._children(connection, group.parent_id)
            index = parent_children.index(("group", group.group_id))
            parent_children.pop(index)
            if flatten:
                for node_type, node_id in children:
                    if node_type == "group":
                        connection.execute(
                            "UPDATE queue_groups SET parent_id=?,updated_at=? WHERE group_id=?",
                            (group.parent_id, time.time(), node_id),
                        )
                    else:
                        connection.execute(
                            "UPDATE queue_items SET group_id=? WHERE id=?",
                            (group.parent_id, int(node_id)),
                        )
                parent_children[index:index] = children
            elif recursive:
                descendants = self._group_descendants(connection, group.group_id) | {group.group_id}
                placeholders = ",".join("?" for _ in descendants)
                connection.execute(
                    f"DELETE FROM queue_items WHERE group_id IN ({placeholders})", tuple(descendants)
                )
            connection.execute("DELETE FROM queue_groups WHERE group_id=?", (group.group_id,))
            self._renumber_children(connection, group.parent_id, parent_children)
            self._recompile(connection)
            current = connection.execute("SELECT current_id FROM queue_state WHERE singleton=1").fetchone()
            if current and current["current_id"] is not None:
                exists = connection.execute(
                    "SELECT 1 FROM queue_items WHERE id=?", (current["current_id"],)
                ).fetchone()
                if not exists:
                    first = connection.execute("SELECT id FROM queue_items ORDER BY position LIMIT 1").fetchone()
                    connection.execute(
                        "UPDATE queue_state SET current_id=?,updated_at=? WHERE singleton=1",
                        (first["id"] if first else None, time.time()),
                    )
        return group

    def sync_library_defaults(self, media_items: Iterable[MediaRef], *, force: bool = False) -> bool:
        """Project the ordered library into a fresh/default queue transactionally.

        A pre-existing or explicitly edited queue is classified as custom and
        never overwritten. ``force`` is used only by the explicit
        ``queue reset`` command.
        """
        media = list(media_items)
        desired = [item.stable_id for item in media]
        with self.database.transaction() as connection:
            origin_row = connection.execute(
                "SELECT value_json FROM app_state WHERE key=?",
                (QUEUE_ORIGIN_KEY,),
            ).fetchone()
            try:
                origin = json.loads(origin_row["value_json"]) if origin_row else None
            except (json.JSONDecodeError, TypeError):
                origin = None
            existing = connection.execute(
                "SELECT id, stable_id FROM queue_items ORDER BY position"
            ).fetchall()
            if force:
                origin = DEFAULT_LIBRARY_ORIGIN
                self._set_origin(connection, origin)
            elif origin not in {DEFAULT_LIBRARY_ORIGIN, CUSTOM_ORIGIN}:
                existing_ids = [row["stable_id"] for row in existing]
                origin = (
                    DEFAULT_LIBRARY_ORIGIN
                    if not existing or existing_ids == desired
                    else CUSTOM_ORIGIN
                )
                self._set_origin(connection, origin)
            if origin == CUSTOM_ORIGIN:
                return False

            for item in media:
                self._upsert_media(connection, item)
            has_groups = connection.execute("SELECT 1 FROM queue_groups LIMIT 1").fetchone()
            if [row["stable_id"] for row in existing] == desired and not has_groups:
                return False

            current = connection.execute(
                "SELECT q.stable_id FROM queue_state s "
                "LEFT JOIN queue_items q ON q.id=s.current_id WHERE s.singleton=1"
            ).fetchone()
            current_stable_id = (
                str(current["stable_id"])
                if current and current["stable_id"] is not None
                else None
            )
            connection.execute("DELETE FROM queue_items")
            connection.execute("DELETE FROM queue_groups")
            inserted: dict[str, int] = {}
            for position, item in enumerate(media):
                cursor = connection.execute(
                    "INSERT INTO queue_items(stable_id,position,priority,added_at,failure_policy,sibling_position) "
                    "VALUES(?,?,0,?,'skip',?)",
                    (item.stable_id, position, time.time(), position),
                )
                inserted[item.stable_id] = cast(int, cursor.lastrowid)
            connection.execute(
                "UPDATE queue_state SET current_id=?, updated_at=? WHERE singleton=1",
                (
                    inserted.get(current_stable_id) if current_stable_id else None,
                    time.time(),
                ),
            )
        return True

    def _snapshot(self, connection) -> dict:
        rows = connection.execute(
            "SELECT q.*,m.source,m.original_uri,m.title,m.artist,m.album,m.duration,m.capabilities_json,"
            "m.resolver_json,m.chapters_json,m.provenance FROM queue_items q "
            "JOIN media_items m ON m.stable_id=q.stable_id ORDER BY q.position"
        ).fetchall()
        groups = connection.execute(
            "SELECT * FROM queue_groups ORDER BY parent_id,sibling_position"
        ).fetchall()
        state = connection.execute("SELECT * FROM queue_state WHERE singleton = 1").fetchone()
        current_position = next(
            (index for index, row in enumerate(rows) if row["id"] == state["current_id"]),
            None,
        )
        return {
            "items": [
                {
                    "stable_id": row["stable_id"],
                    "media": self._media_from_row(row).to_dict(),
                    "priority": row["priority"],
                    "attempts": row["attempts"],
                    "failure_policy": row["failure_policy"],
                    "group_id": row["group_id"],
                    "sibling_position": row["sibling_position"],
                }
                for row in rows
            ],
            "groups": [
                {
                    "group_id": row["group_id"],
                    "parent_id": row["parent_id"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "sibling_position": row["sibling_position"],
                    "strategy": row["strategy"],
                    "shuffle_seed": row["shuffle_seed"],
                    "priority": row["priority"],
                    "atomic": bool(row["atomic_group"]),
                    "source_ref": row["source_ref"],
                    "metadata": json.loads(row["metadata_json"] or "{}"),
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in groups
            ],
            "state": {
                "current_position": current_position,
                "repeat_mode": state["repeat_mode"],
                "shuffle_seed": state["shuffle_seed"],
                "consume_mode": state["consume_mode"],
                "autofill": state["autofill"],
                "root_strategy": state["root_strategy"],
                "root_seed": state["root_seed"],
            },
        }

    def _record_history(self, connection) -> None:
        snapshot = self._snapshot(connection)
        connection.execute(
            "INSERT INTO queue_history(snapshot_json, created_at) VALUES(?, ?)",
            (json.dumps(snapshot, sort_keys=True), time.time()),
        )
        connection.execute(
            "DELETE FROM queue_history WHERE id NOT IN "
            "(SELECT id FROM queue_history ORDER BY id DESC LIMIT 100)"
        )
        connection.execute(
            "INSERT INTO app_state(key, value_json, updated_at) VALUES('queue_redo', '[]', ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json='[]', updated_at=excluded.updated_at",
            (time.time(),),
        )

    def _restore_snapshot(self, connection, snapshot: dict) -> None:
        connection.execute("DELETE FROM queue_items")
        connection.execute("DELETE FROM queue_groups")
        groups = list(snapshot.get("groups", []))
        pending = {str(group["group_id"]): group for group in groups}
        inserted: set[str] = set()
        while pending:
            progressed = False
            for group_id, group in list(pending.items()):
                parent_id = group.get("parent_id")
                if parent_id and parent_id not in inserted:
                    continue
                now = time.time()
                connection.execute(
                    "INSERT INTO queue_groups(group_id,parent_id,name,kind,sibling_position,strategy,shuffle_seed,"
                    "priority,atomic_group,source_ref,metadata_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        group_id,
                        parent_id,
                        group.get("name") or "Group",
                        group.get("kind", "manual"),
                        int(group.get("sibling_position", 0)),
                        group.get("strategy", "custom"),
                        group.get("shuffle_seed"),
                        int(group.get("priority", 0)),
                        int(group.get("atomic", True)),
                        group.get("source_ref"),
                        json.dumps(group.get("metadata") or {}, ensure_ascii=False),
                        float(group.get("created_at", now)),
                        float(group.get("updated_at", now)),
                    ),
                )
                inserted.add(group_id)
                del pending[group_id]
                progressed = True
            if not progressed:
                raise QueueError("Queue snapshot contains orphaned or cyclic groups")
        restored_ids = []
        for position, item in enumerate(snapshot.get("items", [])):
            if isinstance(item.get("media"), dict):
                self._upsert_media(connection, MediaRef.from_dict(item["media"]))
            cursor = connection.execute(
                "INSERT INTO queue_items(stable_id,position,priority,added_at,attempts,failure_policy,group_id,"
                "sibling_position) VALUES(?,?,?,?,?,?,?,?)",
                (
                    item["stable_id"],
                    position,
                    item.get("priority", 0),
                    time.time(),
                    item.get("attempts", 0),
                    item.get("failure_policy", "skip"),
                    item.get("group_id"),
                    int(item.get("sibling_position", position)),
                ),
            )
            restored_ids.append(cursor.lastrowid)
        state = snapshot.get("state", {})
        current_position = state.get("current_position")
        current_id = (
            restored_ids[current_position]
            if isinstance(current_position, int) and current_position in range(len(restored_ids))
            else None
        )
        connection.execute(
            "UPDATE queue_state SET current_id=?,repeat_mode=?,shuffle_seed=?,consume_mode=?,autofill=?,"
            "root_strategy=?,root_seed=?,updated_at=? WHERE singleton=1",
            (
                current_id,
                state.get("repeat_mode", "off"),
                state.get("shuffle_seed"),
                int(state.get("consume_mode", 0)),
                int(state.get("autofill", 0)),
                state.get("root_strategy", "custom"),
                state.get("root_seed"),
                time.time(),
            ),
        )
        self._recompile(connection)

    def export_snapshot(self) -> dict:
        """Return a JSON-safe snapshot of queue ordering and playback cursor."""
        with self.database.transaction() as connection:
            return self._snapshot(connection)

    def restore_snapshot(self, snapshot: dict, *, origin: str = CUSTOM_ORIGIN) -> None:
        """Atomically restore a snapshot previously returned by export_snapshot."""
        if not isinstance(snapshot, dict):
            raise QueueError("Queue snapshot must be an object")
        with self.database.transaction() as connection:
            self._record_history(connection)
            self._restore_snapshot(connection, snapshot)
            self._set_origin(connection, origin)

    def _renumber(self, connection, ordered_ids: list[int]) -> None:
        connection.execute("UPDATE queue_items SET position = position + 1000000")
        for position, queue_id in enumerate(ordered_ids):
            connection.execute("UPDATE queue_items SET position=? WHERE id=?", (position, queue_id))

    def items(self) -> list[QueueItem]:
        rows = self.database.fetchall(
            """
            SELECT q.*, m.source, m.original_uri, m.title, m.artist, m.album, m.duration,
                   m.capabilities_json, m.resolver_json, m.chapters_json, m.provenance
            FROM queue_items q JOIN media_items m ON m.stable_id=q.stable_id
            ORDER BY q.position ASC
            """
        )
        result = []
        for row in rows:
            media = MediaRef(
                stable_id=row["stable_id"],
                source=MediaSource(row["source"]),
                original_uri=row["original_uri"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
                duration=row["duration"],
                capabilities=MediaCapabilities.from_json(row["capabilities_json"]),
                resolver_data=json.loads(row["resolver_json"]),
                chapters=[MediaChapter.from_dict(item) for item in json.loads(row["chapters_json"] or "[]")],
                provenance=row["provenance"],
            )
            result.append(
                QueueItem(
                    queue_id=row["id"],
                    media=media,
                    position=row["position"],
                    priority=row["priority"],
                    added_at=row["added_at"],
                    attempts=row["attempts"],
                    failure_policy=row["failure_policy"],
                    group_id=row["group_id"],
                    sibling_position=int(row["sibling_position"] if row["sibling_position"] is not None else row["position"]),
                )
            )
        return result

    def add(
        self,
        media: MediaRef,
        *,
        position: int | None = None,
        priority: int = 0,
        failure_policy: str = "skip",
        allow_duplicate: bool = False,
        group_id: str | None = None,
        sibling_position: int | None = None,
    ) -> QueueItem:
        if failure_policy not in VALID_FAILURE_POLICIES:
            raise QueueError(f"Unknown failure policy: {failure_policy}")
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            self._upsert_media(connection, media)
            if not allow_duplicate:
                existing = connection.execute(
                    "SELECT id FROM queue_items WHERE stable_id=?", (media.stable_id,)
                ).fetchone()
                if existing:
                    raise QueueError("Media is already queued")
                identity_keys = {
                    str(media.resolver_data.get(key))
                    for key in ("recording_mbid", "fingerprint")
                    if media.resolver_data.get(key)
                }
                if identity_keys:
                    queued = connection.execute(
                        "SELECT m.resolver_json FROM queue_items q JOIN media_items m ON m.stable_id=q.stable_id"
                    ).fetchall()
                    if any(
                        identity_keys.intersection(
                            str(data.get(key))
                            for key in ("recording_mbid", "fingerprint")
                            if data.get(key)
                        )
                        for data in (json.loads(row["resolver_json"]) for row in queued)
                    ):
                        raise QueueError("An identified copy of this media is already queued")
            if group_id and not connection.execute(
                "SELECT 1 FROM queue_groups WHERE group_id=?", (group_id,)
            ).fetchone():
                raise QueueError("Unknown queue group")
            children = self._children(connection, group_id)
            requested = sibling_position if sibling_position is not None else position
            insert_at = len(children) if requested is None else max(0, min(requested, len(children)))
            count = connection.execute("SELECT COUNT(*) AS count FROM queue_items").fetchone()["count"]
            cursor = connection.execute(
                "INSERT INTO queue_items(stable_id,position,priority,added_at,failure_policy,group_id,sibling_position) "
                "VALUES(?,?,?,?,?,?,?)",
                (media.stable_id, count, priority, time.time(), failure_policy, group_id, len(children)),
            )
            queue_id = cursor.lastrowid
            children.insert(insert_at, ("item", str(queue_id)))
            self._renumber_children(connection, group_id, children)
            self._recompile(connection)
        return next(item for item in self.items() if item.queue_id == queue_id)

    def extend(self, media_items: Iterable[MediaRef], *, allow_duplicate: bool = False) -> list[QueueItem]:
        added = []
        for media in media_items:
            try:
                added.append(self.add(media, allow_duplicate=allow_duplicate))
            except QueueError as error:
                if "already queued" not in str(error):
                    raise
        return added

    def remove(self, position: int) -> QueueItem:
        items = self.items()
        if position not in range(len(items)):
            raise QueueError("Queue position is out of range")
        selected = items[position]
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            connection.execute("DELETE FROM queue_items WHERE id=?", (selected.queue_id,))
            children = [
                child
                for child in self._children(connection, selected.group_id)
                if child != ("item", str(selected.queue_id))
            ]
            self._renumber_children(connection, selected.group_id, children)
            self._recompile(connection)
        return selected

    def remove_media(self, stable_id: str, original_uri: str | None = None) -> list[QueueItem]:
        items = self.items()
        uri_key = os.path.normcase(os.path.abspath(original_uri)).casefold() if original_uri else None
        selected = [
            item
            for item in items
            if item.media.stable_id == stable_id
            or (
                uri_key is not None
                and item.media.source == MediaSource.LOCAL
                and os.path.normcase(os.path.abspath(item.media.original_uri)).casefold() == uri_key
            )
        ]
        if not selected:
            return []
        selected_ids = {item.queue_id for item in selected}
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            placeholders = ",".join("?" for _ in selected_ids)
            connection.execute(f"DELETE FROM queue_items WHERE id IN ({placeholders})", tuple(selected_ids))
            for parent_id in {item.group_id for item in selected}:
                self._renumber_children(connection, parent_id, self._children(connection, parent_id))
            self._recompile(connection)
            remaining = [row["id"] for row in connection.execute("SELECT id FROM queue_items ORDER BY position")]
            current = connection.execute("SELECT current_id FROM queue_state WHERE singleton=1").fetchone()
            if current and current["current_id"] in selected_ids:
                connection.execute(
                    "UPDATE queue_state SET current_id=?, updated_at=? WHERE singleton=1",
                    (remaining[0] if remaining else None, time.time()),
                )
        return selected

    def move(self, source: int, destination: int) -> None:
        items = self.items()
        if source not in range(len(items)) or destination not in range(len(items)):
            raise QueueError("Queue position is out of range")
        if source == destination:
            return
        selected = items[source]
        target = items[destination]
        if selected.group_id != target.group_id:
            raise QueueError("Cross-group moves require a hierarchical node move")
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            children = self._children(connection, selected.group_id)
            moved = ("item", str(selected.queue_id))
            target_node = ("item", str(target.queue_id))
            children.remove(moved)
            target_index = children.index(target_node)
            children.insert(target_index + int(source < destination), moved)
            self._renumber_children(connection, selected.group_id, children)
            self._recompile(connection)

    def swap(self, first: int, second: int) -> None:
        items = self.items()
        if first not in range(len(items)) or second not in range(len(items)):
            raise QueueError("Queue position is out of range")
        first_item, second_item = items[first], items[second]
        if first_item.group_id != second_item.group_id:
            raise QueueError("Cross-group swaps require hierarchical node moves")
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            children = self._children(connection, first_item.group_id)
            first_node = ("item", str(first_item.queue_id))
            second_node = ("item", str(second_item.queue_id))
            first_index, second_index = children.index(first_node), children.index(second_node)
            children[first_index], children[second_index] = children[second_index], children[first_index]
            self._renumber_children(connection, first_item.group_id, children)
            self._recompile(connection)

    def clear(self) -> None:
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            connection.execute("DELETE FROM queue_items")
            connection.execute("DELETE FROM queue_groups")
            connection.execute("UPDATE queue_state SET current_id=NULL, updated_at=? WHERE singleton=1", (time.time(),))

    def shuffle(self, seed: int | None = None) -> int:
        items = self.items()
        seed = seed if seed is not None else random.SystemRandom().randrange(2**31)
        ordered = [cast(int, item.queue_id) for item in items]
        random.Random(seed).shuffle(ordered)
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            self._renumber(connection, ordered)
            connection.execute(
                "UPDATE queue_state SET shuffle_seed=?, updated_at=? WHERE singleton=1",
                (seed, time.time()),
            )
        return seed

    def set_repeat(self, mode: str) -> None:
        if mode not in VALID_REPEAT_MODES:
            raise QueueError(f"Unknown repeat mode: {mode}")
        with self.database.transaction() as connection:
            self._record_history(connection)
            connection.execute(
                "UPDATE queue_state SET repeat_mode=?, updated_at=? WHERE singleton=1", (mode, time.time())
            )

    def set_consume(self, enabled: bool) -> None:
        with self.database.transaction() as connection:
            self._record_history(connection)
            connection.execute(
                "UPDATE queue_state SET consume_mode=?, updated_at=? WHERE singleton=1",
                (int(enabled), time.time()),
            )

    def set_autofill(self, enabled: bool) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE queue_state SET autofill=?, updated_at=? WHERE singleton=1",
                (int(enabled), time.time()),
            )

    def state(self) -> dict:
        row = self.database.fetchone("SELECT * FROM queue_state WHERE singleton=1")
        return dict(row) if row else {}

    def jump(self, position: int) -> QueueItem:
        items = self.items()
        if position not in range(len(items)):
            raise QueueError("Queue position is out of range")
        item = items[position]
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE queue_state SET current_id=?, updated_at=? WHERE singleton=1",
                (item.queue_id, time.time()),
            )
        return item

    def current(self) -> QueueItem | None:
        current_id = self.state().get("current_id")
        return next((item for item in self.items() if item.queue_id == current_id), None)

    def next(self) -> QueueItem | None:
        items = self.items()
        if not items:
            return None
        state = self.state()
        current = self.current()
        if current and state.get("repeat_mode") == "one":
            return current
        index = items.index(current) if current in items else -1
        next_index = index + 1
        if next_index >= len(items):
            if state.get("repeat_mode") != "all":
                return None
            next_index = 0
        if current and state.get("consume_mode"):
            self.remove(items.index(current))
            items = self.items()
            next_index = min(next_index - 1, len(items) - 1)
            if not items:
                return None
        return self.jump(next_index)

    def previous(self) -> QueueItem | None:
        items = self.items()
        if not items:
            return None
        current = self.current()
        index = items.index(current) if current in items else 0
        previous = index - 1
        if previous < 0:
            if self.state().get("repeat_mode") != "all":
                return items[0]
            previous = len(items) - 1
        return self.jump(previous)

    def save(self, name: str) -> None:
        try:
            self.playlists.save_snapshot(name, self.export_snapshot())
        except PlaylistError as error:
            raise QueueError(str(error)) from error

    def load(self, name: str, *, replace: bool = True) -> list[QueueItem]:
        try:
            playlist = self.playlists.get(name)
        except PlaylistError as error:
            raise QueueError(str(error).replace("playlist", "saved queue")) from error
        tree = playlist.tree
        if "legacy_items" in tree:
            payload = tree["legacy_items"]
            if replace:
                self.clear()
            added = []
            for item in payload:
                if "media" not in item:  # Version-0 saved queues remain readable.
                    item = {"media": item, "priority": 0, "failure_policy": "skip"}
                added.append(
                    self.add(
                        MediaRef.from_dict(item["media"]),
                        priority=item.get("priority", 0),
                        failure_policy=item.get("failure_policy", "skip"),
                        allow_duplicate=True,
                    )
                )
            return added
        if replace:
            self.restore_snapshot(tree)
            return self.items()
        added = []
        for item in tree.get("items", []):
            media_payload = item.get("media")
            if not isinstance(media_payload, dict):
                continue
            added.append(
                self.add(
                    MediaRef.from_dict(media_payload),
                    priority=item.get("priority", 0),
                    failure_policy=item.get("failure_policy", "skip"),
                    allow_duplicate=True,
                )
            )
        return added

    def mark_failure(self, queue_id: int, *, max_retries: int = 2) -> str:
        item = next((candidate for candidate in self.items() if candidate.queue_id == queue_id), None)
        if item is None:
            raise QueueError("Unknown queue item")
        with self.database.transaction() as connection:
            connection.execute("UPDATE queue_items SET attempts=attempts+1 WHERE id=?", (queue_id,))
        if item.failure_policy == "retry" and item.attempts < max_retries:
            return "retry"
        if item.failure_policy == "skip":
            return "skip"
        return "stop"

    def undo(self) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT * FROM queue_history ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return False
            self._set_origin(connection, CUSTOM_ORIGIN)
            current = self._snapshot(connection)
            redo_row = connection.execute("SELECT value_json FROM app_state WHERE key='queue_redo'").fetchone()
            redo = json.loads(redo_row["value_json"]) if redo_row else []
            redo.append(current)
            connection.execute(
                "INSERT INTO app_state(key, value_json, updated_at) VALUES('queue_redo', ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
                (json.dumps(redo), time.time()),
            )
            self._restore_snapshot(connection, json.loads(row["snapshot_json"]))
            connection.execute("DELETE FROM queue_history WHERE id=?", (row["id"],))
        return True

    def redo(self) -> bool:
        with self.database.transaction() as connection:
            row = connection.execute("SELECT value_json FROM app_state WHERE key='queue_redo'").fetchone()
            redo = json.loads(row["value_json"]) if row else []
            if not redo:
                return False
            self._set_origin(connection, CUSTOM_ORIGIN)
            current = self._snapshot(connection)
            target = redo.pop()
            connection.execute(
                "INSERT INTO queue_history(snapshot_json, created_at) VALUES(?, ?)",
                (json.dumps(current), time.time()),
            )
            self._restore_snapshot(connection, target)
            connection.execute(
                "UPDATE app_state SET value_json=?, updated_at=? WHERE key='queue_redo'",
                (json.dumps(redo), time.time()),
            )
        return True
