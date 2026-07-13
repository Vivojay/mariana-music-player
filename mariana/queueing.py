"""Transactional, persistent queue operations."""

from __future__ import annotations

import json
import os
import random
import time
from collections.abc import Iterable
from typing import cast

from .database import MarianaDatabase
from .models import MediaCapabilities, MediaRef, MediaSource, QueueItem
from .sources import sanitized_resolver_data

VALID_REPEAT_MODES = {"off", "one", "all"}
VALID_FAILURE_POLICIES = {"skip", "retry", "stop"}
QUEUE_ORIGIN_KEY = "queue_origin"
DEFAULT_LIBRARY_ORIGIN = "default-library"
CUSTOM_ORIGIN = "custom"


class QueueError(RuntimeError):
    pass


class PersistentQueue:
    def __init__(self, database: MarianaDatabase):
        self.database = database

    def _upsert_media(self, connection, media: MediaRef) -> None:
        connection.execute(
            """
            INSERT INTO media_items(
                stable_id, source, original_uri, title, artist, album, duration,
                capabilities_json, resolver_json, provenance, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(stable_id) DO UPDATE SET
                source=excluded.source,
                original_uri=excluded.original_uri,
                title=COALESCE(excluded.title, media_items.title),
                artist=COALESCE(excluded.artist, media_items.artist),
                album=COALESCE(excluded.album, media_items.album),
                duration=COALESCE(excluded.duration, media_items.duration),
                capabilities_json=excluded.capabilities_json,
                resolver_json=excluded.resolver_json,
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
            if [row["stable_id"] for row in existing] == desired:
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
            inserted: dict[str, int] = {}
            for position, item in enumerate(media):
                cursor = connection.execute(
                    "INSERT INTO queue_items(stable_id, position, priority, added_at, failure_policy) "
                    "VALUES(?, ?, 0, ?, 'skip')",
                    (item.stable_id, position, time.time()),
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
            "SELECT id, stable_id, priority, attempts, failure_policy FROM queue_items ORDER BY position"
        ).fetchall()
        state = connection.execute("SELECT * FROM queue_state WHERE singleton = 1").fetchone()
        current_position = next(
            (index for index, row in enumerate(rows) if row["id"] == state["current_id"]),
            None,
        )
        return {
            "items": [
                {key: row[key] for key in ("stable_id", "priority", "attempts", "failure_policy")}
                for row in rows
            ],
            "state": {
                "current_position": current_position,
                "repeat_mode": state["repeat_mode"],
                "shuffle_seed": state["shuffle_seed"],
                "consume_mode": state["consume_mode"],
                "autofill": state["autofill"],
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
        restored_ids = []
        for position, item in enumerate(snapshot.get("items", [])):
            cursor = connection.execute(
                "INSERT INTO queue_items(stable_id, position, priority, added_at, attempts, failure_policy) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    item["stable_id"],
                    position,
                    item.get("priority", 0),
                    time.time(),
                    item.get("attempts", 0),
                    item.get("failure_policy", "skip"),
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
            "UPDATE queue_state SET current_id=?, repeat_mode=?, shuffle_seed=?, consume_mode=?, "
            "autofill=?, updated_at=? WHERE singleton=1",
            (
                current_id,
                state.get("repeat_mode", "off"),
                state.get("shuffle_seed"),
                int(state.get("consume_mode", 0)),
                int(state.get("autofill", 0)),
                time.time(),
            ),
        )

    def _renumber(self, connection, ordered_ids: list[int]) -> None:
        connection.execute("UPDATE queue_items SET position = position + 1000000")
        for position, queue_id in enumerate(ordered_ids):
            connection.execute("UPDATE queue_items SET position=? WHERE id=?", (position, queue_id))

    def items(self) -> list[QueueItem]:
        rows = self.database.fetchall(
            """
            SELECT q.*, m.source, m.original_uri, m.title, m.artist, m.album, m.duration,
                   m.capabilities_json, m.resolver_json, m.provenance
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
            existing_ids = [
                row["id"]
                for row in connection.execute("SELECT id FROM queue_items ORDER BY position").fetchall()
            ]
            count = len(existing_ids)
            insert_at = count if position is None else max(0, min(position, count))
            cursor = connection.execute(
                "INSERT INTO queue_items(stable_id, position, priority, added_at, failure_policy) "
                "VALUES(?, ?, ?, ?, ?)",
                (media.stable_id, count, priority, time.time(), failure_policy),
            )
            queue_id = cursor.lastrowid
            existing_ids.insert(insert_at, queue_id)
            self._renumber(connection, existing_ids)
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
            remaining = [cast(int, item.queue_id) for item in items if item.queue_id != selected.queue_id]
            self._renumber(connection, remaining)
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
        remaining = [cast(int, item.queue_id) for item in items if item.queue_id not in selected_ids]
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            placeholders = ",".join("?" for _ in selected_ids)
            connection.execute(f"DELETE FROM queue_items WHERE id IN ({placeholders})", tuple(selected_ids))
            self._renumber(connection, remaining)
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
        ordered = [cast(int, item.queue_id) for item in items]
        moved = ordered.pop(source)
        ordered.insert(destination, moved)
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            self._renumber(connection, ordered)

    def swap(self, first: int, second: int) -> None:
        items = self.items()
        if first not in range(len(items)) or second not in range(len(items)):
            raise QueueError("Queue position is out of range")
        ordered = [cast(int, item.queue_id) for item in items]
        ordered[first], ordered[second] = ordered[second], ordered[first]
        with self.database.transaction() as connection:
            self._record_history(connection)
            self._renumber(connection, ordered)

    def clear(self) -> None:
        with self.database.transaction() as connection:
            self._set_origin(connection, CUSTOM_ORIGIN)
            self._record_history(connection)
            connection.execute("DELETE FROM queue_items")
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
        if not name.strip():
            raise QueueError("Queue name cannot be empty")
        payload = [
            {
                "media": item.media.to_dict(),
                "priority": item.priority,
                "failure_policy": item.failure_policy,
            }
            for item in self.items()
        ]
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO named_queues(name, items_json, updated_at) VALUES(?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET items_json=excluded.items_json, updated_at=excluded.updated_at",
                (name.strip(), json.dumps(payload, ensure_ascii=False), time.time()),
            )

    def load(self, name: str, *, replace: bool = True) -> list[QueueItem]:
        row = self.database.fetchone("SELECT items_json FROM named_queues WHERE name=?", (name.strip(),))
        if not row:
            raise QueueError(f"Unknown saved queue: {name}")
        if replace:
            self.clear()
        added = []
        for item in json.loads(row["items_json"]):
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
