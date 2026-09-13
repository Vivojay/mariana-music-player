"""Normalized user tagging and tag-only media selection."""

from __future__ import annotations

import sqlite3
import time
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

from .database import MarianaDatabase

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 512
ASSIGNMENT_SOURCES = frozenset({"user", "embedded", "provider"})
_UNSET = object()


class TagError(ValueError):
    """Base error for invalid or unavailable tag operations."""


class TagNotFoundError(TagError):
    """Raised when a tag or tag group cannot be resolved."""


class TagInUseError(TagError):
    """Raised when deletion would silently detach a tag from media or groups."""


@dataclass(frozen=True, slots=True)
class TagDefinition:
    tag_id: str
    name: str
    description: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class TagGroup:
    group_id: str
    name: str
    description: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class MediaTag:
    stable_id: str
    tag: TagDefinition
    assignment_source: str
    assigned_at: float


def _normalized_name(value: str, *, kind: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise TagError(f"{kind} name must be text")
    name = " ".join(unicodedata.normalize("NFKC", value).split())
    if not name:
        raise TagError(f"{kind} name cannot be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise TagError(f"{kind} name cannot exceed {MAX_NAME_LENGTH} characters")
    if any(unicodedata.category(character) == "Cc" for character in name):
        raise TagError(f"{kind} name contains unsupported control characters")
    return name, name.casefold()


def _description(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TagError("Tag description must be text")
    result = " ".join(unicodedata.normalize("NFKC", value).split())
    if len(result) > MAX_DESCRIPTION_LENGTH:
        raise TagError(f"Tag description cannot exceed {MAX_DESCRIPTION_LENGTH} characters")
    return result or None


def _tag(row: Any) -> TagDefinition:
    return TagDefinition(
        str(row["tag_id"]),
        str(row["name"]),
        row["description"],
        float(row["created_at"]),
        float(row["updated_at"]),
    )


def _group(row: Any) -> TagGroup:
    return TagGroup(
        str(row["group_id"]),
        str(row["name"]),
        row["description"],
        float(row["created_at"]),
        float(row["updated_at"]),
    )


class TagStore:
    """Persist explicit tags without modifying the underlying media files."""

    def __init__(self, database: MarianaDatabase):
        self.database = database

    @staticmethod
    def _tag_row(connection, reference: str):
        _, key = _normalized_name(reference, kind="Tag")
        row = connection.execute("SELECT * FROM tags WHERE tag_id=?", (reference,)).fetchone()
        return row or connection.execute("SELECT * FROM tags WHERE name_key=?", (key,)).fetchone()

    @staticmethod
    def _group_row(connection, reference: str):
        _, key = _normalized_name(reference, kind="Tag group")
        row = connection.execute("SELECT * FROM tag_groups WHERE group_id=?", (reference,)).fetchone()
        return row or connection.execute("SELECT * FROM tag_groups WHERE name_key=?", (key,)).fetchone()

    @staticmethod
    def _ensure_tag(connection, name: str, description: str | None = None) -> Any:
        display, key = _normalized_name(name, kind="Tag")
        existing = connection.execute("SELECT * FROM tags WHERE name_key=?", (key,)).fetchone()
        if existing:
            return existing
        now = time.time()
        tag_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO tags(tag_id,name,name_key,description,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (tag_id, display, key, _description(description), now, now),
        )
        return connection.execute("SELECT * FROM tags WHERE tag_id=?", (tag_id,)).fetchone()

    def ensure_tag(self, name: str, *, description: str | None = None) -> TagDefinition:
        with self.database.transaction() as connection:
            return _tag(self._ensure_tag(connection, name, description))

    def update_tag(
        self,
        reference: str,
        *,
        name: str | None = None,
        description: str | None | object = _UNSET,
    ) -> TagDefinition:
        if name is None and description is _UNSET:
            raise TagError("Tag update requires a name or description")
        with self.database.transaction() as connection:
            row = self._tag_row(connection, reference)
            if not row:
                raise TagNotFoundError(f"Unknown tag: {reference}")
            display, key = (
                _normalized_name(name, kind="Tag") if name is not None else (row["name"], row["name_key"])
            )
            details = (
                row["description"]
                if description is _UNSET
                else _description(cast(str | None, description))
            )
            try:
                connection.execute(
                    "UPDATE tags SET name=?,name_key=?,description=?,updated_at=? WHERE tag_id=?",
                    (display, key, details, time.time(), row["tag_id"]),
                )
            except sqlite3.IntegrityError:
                raise TagError(f"Tag already exists: {display}") from None
            return _tag(connection.execute("SELECT * FROM tags WHERE tag_id=?", (row["tag_id"],)).fetchone())

    def delete_tag(self, reference: str, *, detach: bool = False) -> TagDefinition:
        with self.database.transaction() as connection:
            row = self._tag_row(connection, reference)
            if not row:
                raise TagNotFoundError(f"Unknown tag: {reference}")
            assigned = connection.execute(
                "SELECT COUNT(*) FROM media_tags WHERE tag_id=?", (row["tag_id"],)
            ).fetchone()[0]
            grouped = connection.execute(
                "SELECT COUNT(*) FROM tag_group_members WHERE tag_id=?", (row["tag_id"],)
            ).fetchone()[0]
            if (assigned or grouped) and not detach:
                raise TagInUseError(
                    f"Tag is still used by {assigned} media item(s) and {grouped} tag group(s)"
                )
            result = _tag(row)
            connection.execute("DELETE FROM tags WHERE tag_id=?", (row["tag_id"],))
            return result

    def create_group(self, name: str, *, description: str | None = None) -> TagGroup:
        display, key = _normalized_name(name, kind="Tag group")
        with self.database.transaction() as connection:
            existing = connection.execute("SELECT * FROM tag_groups WHERE name_key=?", (key,)).fetchone()
            if existing:
                return _group(existing)
            now = time.time()
            group_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO tag_groups(group_id,name,name_key,description,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)",
                (group_id, display, key, _description(description), now, now),
            )
            return _group(connection.execute("SELECT * FROM tag_groups WHERE group_id=?", (group_id,)).fetchone())

    def update_group(
        self,
        reference: str,
        *,
        name: str | None = None,
        description: str | None | object = _UNSET,
    ) -> TagGroup:
        if name is None and description is _UNSET:
            raise TagError("Tag-group update requires a name or description")
        with self.database.transaction() as connection:
            row = self._group_row(connection, reference)
            if not row:
                raise TagNotFoundError(f"Unknown tag group: {reference}")
            display, key = (
                _normalized_name(name, kind="Tag group")
                if name is not None
                else (row["name"], row["name_key"])
            )
            details = (
                row["description"]
                if description is _UNSET
                else _description(cast(str | None, description))
            )
            try:
                connection.execute(
                    "UPDATE tag_groups SET name=?,name_key=?,description=?,updated_at=? WHERE group_id=?",
                    (display, key, details, time.time(), row["group_id"]),
                )
            except sqlite3.IntegrityError:
                raise TagError(f"Tag group already exists: {display}") from None
            return _group(
                connection.execute("SELECT * FROM tag_groups WHERE group_id=?", (row["group_id"],)).fetchone()
            )

    def delete_group(self, reference: str) -> TagGroup:
        with self.database.transaction() as connection:
            row = self._group_row(connection, reference)
            if not row:
                raise TagNotFoundError(f"Unknown tag group: {reference}")
            result = _group(row)
            connection.execute("DELETE FROM tag_groups WHERE group_id=?", (row["group_id"],))
            return result

    def add_to_group(self, group: str, tags: Iterable[str]) -> tuple[TagDefinition, ...]:
        names = tuple(tags)
        with self.database.transaction() as connection:
            group_row = self._group_row(connection, group)
            if not group_row:
                raise TagNotFoundError(f"Unknown tag group: {group}")
            position = connection.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM tag_group_members WHERE group_id=?",
                (group_row["group_id"],),
            ).fetchone()[0]
            result = []
            for name in names:
                row = self._ensure_tag(connection, name)
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO tag_group_members(group_id,tag_id,position) VALUES(?,?,?)",
                    (group_row["group_id"], row["tag_id"], position),
                )
                if cursor.rowcount:
                    position += 1
                result.append(_tag(row))
            return tuple(result)

    def remove_from_group(self, group: str, tags: Iterable[str]) -> int:
        with self.database.transaction() as connection:
            group_row = self._group_row(connection, group)
            if not group_row:
                raise TagNotFoundError(f"Unknown tag group: {group}")
            removed = 0
            for reference in tags:
                row = self._tag_row(connection, reference)
                if row:
                    removed += connection.execute(
                        "DELETE FROM tag_group_members WHERE group_id=? AND tag_id=?",
                        (group_row["group_id"], row["tag_id"]),
                    ).rowcount
            return removed

    def attach(
        self,
        stable_id: str,
        tags: Iterable[str],
        *,
        assignment_source: str = "user",
    ) -> tuple[MediaTag, ...]:
        if assignment_source not in ASSIGNMENT_SOURCES:
            raise TagError(f"Unknown tag assignment source: {assignment_source}")
        names = tuple(tags)
        with self.database.transaction() as connection:
            media = connection.execute("SELECT stable_id FROM media_items WHERE stable_id=?", (stable_id,)).fetchone()
            if not media:
                raise TagNotFoundError(f"Unknown media identity: {stable_id}")
            assigned = []
            for name in names:
                row = self._ensure_tag(connection, name)
                assigned_at = time.time()
                connection.execute(
                    "INSERT OR IGNORE INTO media_tags(stable_id,tag_id,assignment_source,assigned_at) "
                    "VALUES(?,?,?,?)",
                    (stable_id, row["tag_id"], assignment_source, assigned_at),
                )
                stored = connection.execute(
                    "SELECT assignment_source,assigned_at FROM media_tags WHERE stable_id=? AND tag_id=?",
                    (stable_id, row["tag_id"]),
                ).fetchone()
                assigned.append(
                    MediaTag(stable_id, _tag(row), str(stored["assignment_source"]), float(stored["assigned_at"]))
                )
            return tuple(assigned)

    def detach(self, stable_id: str, tags: Iterable[str]) -> int:
        with self.database.transaction() as connection:
            removed = 0
            for reference in tags:
                row = self._tag_row(connection, reference)
                if row:
                    removed += connection.execute(
                        "DELETE FROM media_tags WHERE stable_id=? AND tag_id=?",
                        (stable_id, row["tag_id"]),
                    ).rowcount
            return removed

    def clear(self, stable_id: str) -> int:
        with self.database.transaction() as connection:
            return connection.execute("DELETE FROM media_tags WHERE stable_id=?", (stable_id,)).rowcount

    def list_tags(self, *, stable_id: str | None = None, group: str | None = None) -> tuple[TagDefinition, ...]:
        parameters: list[Any] = []
        joins = []
        conditions = []
        if stable_id is not None:
            joins.append("JOIN media_tags mt ON mt.tag_id=t.tag_id")
            conditions.append("mt.stable_id=?")
            parameters.append(stable_id)
        if group is not None:
            group_row = self.database.fetchone(
                "SELECT * FROM tag_groups WHERE group_id=? OR name_key=?",
                (group, _normalized_name(group, kind="Tag group")[1]),
            )
            if not group_row:
                raise TagNotFoundError(f"Unknown tag group: {group}")
            joins.append("JOIN tag_group_members gm ON gm.tag_id=t.tag_id")
            conditions.append("gm.group_id=?")
            parameters.append(group_row["group_id"])
        sql = "SELECT DISTINCT t.* FROM tags t"
        if joins:
            sql += " " + " ".join(joins)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY t.name_key,t.tag_id"
        return tuple(_tag(row) for row in self.database.fetchall(sql, tuple(parameters)))

    def list_media_tags(self, stable_id: str) -> tuple[MediaTag, ...]:
        rows = self.database.fetchall(
            "SELECT t.*,mt.assignment_source,mt.assigned_at "
            "FROM media_tags mt JOIN tags t ON t.tag_id=mt.tag_id "
            "WHERE mt.stable_id=? ORDER BY t.name_key,t.tag_id",
            (stable_id,),
        )
        return tuple(
            MediaTag(
                stable_id,
                _tag(row),
                str(row["assignment_source"]),
                float(row["assigned_at"]),
            )
            for row in rows
        )

    def list_groups(self) -> tuple[TagGroup, ...]:
        return tuple(
            _group(row)
            for row in self.database.fetchall("SELECT * FROM tag_groups ORDER BY name_key,group_id")
        )

    def tagged_media(
        self,
        *,
        all_of: Iterable[str] = (),
        any_of: Iterable[str] = (),
        none_of: Iterable[str] = (),
        source: str | None = None,
        limit: int | None = None,
    ) -> tuple[str, ...]:
        all_ids, all_missing = self._tag_ids(all_of)
        any_ids, any_missing = self._tag_ids(any_of)
        none_ids, _ = self._tag_ids(none_of)
        if all_missing or (any_missing and not any_ids):
            return ()
        conditions = []
        parameters: list[Any] = []
        if all_ids:
            placeholders = ",".join("?" for _ in all_ids)
            conditions.append(
                "(SELECT COUNT(DISTINCT mt.tag_id) FROM media_tags mt "
                f"WHERE mt.stable_id=m.stable_id AND mt.tag_id IN ({placeholders}))=?"
            )
            parameters.extend((*all_ids, len(all_ids)))
        if any_ids:
            placeholders = ",".join("?" for _ in any_ids)
            conditions.append(
                f"EXISTS(SELECT 1 FROM media_tags mt WHERE mt.stable_id=m.stable_id "
                f"AND mt.tag_id IN ({placeholders}))"
            )
            parameters.extend(any_ids)
        if none_ids:
            placeholders = ",".join("?" for _ in none_ids)
            conditions.append(
                f"NOT EXISTS(SELECT 1 FROM media_tags mt WHERE mt.stable_id=m.stable_id "
                f"AND mt.tag_id IN ({placeholders}))"
            )
            parameters.extend(none_ids)
        if source is not None:
            conditions.append("m.source=?")
            parameters.append(source)
        sql = "SELECT m.stable_id FROM media_items m"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY COALESCE(m.artist,''),COALESCE(m.title,''),m.stable_id"
        if limit is not None:
            if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
                raise TagError("Tag query limit must be a non-negative integer")
            sql += " LIMIT ?"
            parameters.append(limit)
        return tuple(str(row["stable_id"]) for row in self.database.fetchall(sql, tuple(parameters)))

    def _tag_ids(self, references: Iterable[str]) -> tuple[tuple[str, ...], bool]:
        identifiers = []
        missing = False
        seen = set()
        for reference in references:
            row = self.database.fetchone(
                "SELECT tag_id FROM tags WHERE tag_id=? OR name_key=?",
                (reference, _normalized_name(reference, kind="Tag")[1]),
            )
            if not row:
                missing = True
                continue
            identifier = str(row["tag_id"])
            if identifier not in seen:
                seen.add(identifier)
                identifiers.append(identifier)
        return tuple(identifiers), missing
