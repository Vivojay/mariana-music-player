"""Versioned local playlist persistence."""

from __future__ import annotations

import json
import random
import sqlite3
import time
import unicodedata
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .database import MarianaDatabase
from .models import MediaRef, MediaSource, Playlist, QueueStrategy

MAX_PLAYLIST_DEPTH = 8


class PlaylistError(RuntimeError):
    pass


def playlist_name(value: str) -> str:
    name = unicodedata.normalize("NFC", value).strip()
    if not name:
        raise PlaylistError("Playlist name cannot be empty")
    if len(name) > 160:
        raise PlaylistError("Playlist name cannot exceed 160 characters")
    return name


def playlist_name_key(value: str) -> str:
    return playlist_name(value).casefold()


class PlaylistStore:
    def __init__(self, database: MarianaDatabase):
        self.database = database

    @staticmethod
    def _decode_tree(value: str) -> dict[str, Any]:
        try:
            tree = json.loads(value)
        except (TypeError, json.JSONDecodeError) as error:
            raise PlaylistError("Playlist data is corrupt") from error
        if not isinstance(tree, dict):
            raise PlaylistError("Playlist data must be an object")
        return tree

    @staticmethod
    def snapshot_from_media(media_items: list[MediaRef]) -> dict[str, Any]:
        return {
            "version": 1,
            "groups": [],
            "items": [
                {
                    "stable_id": media.stable_id,
                    "media": media.to_dict(),
                    "priority": 0,
                    "attempts": 0,
                    "failure_policy": "skip",
                    "group_id": None,
                    "sibling_position": position,
                }
                for position, media in enumerate(media_items)
            ],
            "state": {},
        }

    def _playlist(self, row) -> Playlist:
        return Playlist(
            playlist_id=str(row["playlist_id"]),
            name=str(row["name"]),
            description=row["description"],
            tree=self._decode_tree(row["tree_json"]),
            revision=int(row["revision"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    def list(self) -> list[Playlist]:
        return [
            self._playlist(row)
            for row in self.database.fetchall("SELECT * FROM playlists ORDER BY name_key")
        ]

    def get(self, name_or_id: str) -> Playlist:
        value = playlist_name(name_or_id)
        row = self.database.fetchone(
            "SELECT * FROM playlists WHERE playlist_id=? OR name_key=?",
            (value, value.casefold()),
        )
        if not row:
            raise PlaylistError(f"Unknown playlist: {name_or_id}")
        return self._playlist(row)

    def create(
        self,
        name: str,
        *,
        description: str | None = None,
        tree: dict[str, Any] | None = None,
    ) -> Playlist:
        normalized = playlist_name(name)
        now = time.time()
        normalized_tree = self._normalized_tree(
            tree or {"version": 1, "groups": [], "items": [], "state": {}}
        )
        self._tree_nodes(normalized_tree)
        payload = json.dumps(normalized_tree, ensure_ascii=False)
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO playlists(playlist_id,name,name_key,description,tree_json,revision,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,1,?,?)",
                    (uuid.uuid4().hex, normalized, normalized.casefold(), description, payload, now, now),
                )
        except sqlite3.IntegrityError as error:
            raise PlaylistError(f"Playlist already exists: {normalized}") from error
        return self.get(normalized)

    def save_snapshot(
        self,
        name: str,
        tree: dict[str, Any],
        *,
        description: str | None = None,
    ) -> Playlist:
        normalized = playlist_name(name)
        existing = self.database.fetchone("SELECT * FROM playlists WHERE name_key=?", (normalized.casefold(),))
        if not existing:
            return self.create(normalized, description=description, tree=tree)
        now = time.time()
        normalized_tree = self._normalized_tree(tree)
        self._tree_nodes(normalized_tree)
        payload = json.dumps(normalized_tree, ensure_ascii=False)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO playlist_revisions(playlist_id,revision,tree_json,created_at) "
                "VALUES(?,?,?,?)",
                (existing["playlist_id"], existing["revision"], existing["tree_json"], now),
            )
            connection.execute(
                "UPDATE playlists SET tree_json=?,description=COALESCE(?,description),revision=revision+1,updated_at=? "
                "WHERE playlist_id=?",
                (payload, description, now, existing["playlist_id"]),
            )
        return self.get(str(existing["playlist_id"]))

    def rename(self, name_or_id: str, new_name: str) -> Playlist:
        playlist = self.get(name_or_id)
        normalized = playlist_name(new_name)
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE playlists SET name=?,name_key=?,updated_at=? WHERE playlist_id=?",
                    (normalized, normalized.casefold(), time.time(), playlist.playlist_id),
                )
        except sqlite3.IntegrityError as error:
            raise PlaylistError(f"Playlist already exists: {normalized}") from error
        return self.get(playlist.playlist_id)

    def delete(self, name_or_id: str) -> Playlist:
        playlist = self.get(name_or_id)
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM playlists WHERE playlist_id=?", (playlist.playlist_id,))
        return playlist

    def clear(self, name_or_id: str) -> Playlist:
        playlist = self.get(name_or_id)
        return self.save_snapshot(
            playlist.name,
            {"version": 1, "groups": [], "items": [], "state": {}},
        )

    def revisions(self, name_or_id: str) -> list[int]:
        playlist = self.get(name_or_id)
        values = [
            int(row["revision"])
            for row in self.database.fetchall(
                "SELECT revision FROM playlist_revisions WHERE playlist_id=? ORDER BY revision DESC",
                (playlist.playlist_id,),
            )
        ]
        return [playlist.revision, *values]

    def restore(self, name_or_id: str, revision: int) -> Playlist:
        playlist = self.get(name_or_id)
        if revision == playlist.revision:
            return playlist
        row = self.database.fetchone(
            "SELECT tree_json FROM playlist_revisions WHERE playlist_id=? AND revision=?",
            (playlist.playlist_id, revision),
        )
        if not row:
            raise PlaylistError(f"Unknown playlist revision: {revision}")
        return self.save_snapshot(playlist.name, self._decode_tree(row["tree_json"]))

    @staticmethod
    def _normalized_tree(tree: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(tree, dict):
            raise PlaylistError("Playlist data must be an object")
        if "legacy_items" in tree:
            items = []
            for position, value in enumerate(tree["legacy_items"]):
                payload = value if "media" in value else {"media": value}
                media = payload.get("media")
                if not isinstance(media, dict):
                    continue
                items.append(
                    {
                        "stable_id": media.get("stable_id"),
                        "media": media,
                        "priority": payload.get("priority", 0),
                        "failure_policy": payload.get("failure_policy", "skip"),
                        "group_id": None,
                        "sibling_position": position,
                    }
                )
            return {"version": 1, "groups": [], "items": items, "state": {}}
        normalized = json.loads(json.dumps(tree, ensure_ascii=False))
        normalized.setdefault("version", 1)
        normalized.setdefault("groups", [])
        normalized.setdefault("items", [])
        normalized.setdefault("state", {})
        if not isinstance(normalized["groups"], list) or not isinstance(normalized["items"], list):
            raise PlaylistError("Playlist groups and items must be lists")
        if not isinstance(normalized["state"], dict):
            raise PlaylistError("Playlist state must be an object")
        return normalized

    @staticmethod
    def _children(tree: dict[str, Any], parent_id: str | None) -> list[tuple[str, str]]:
        values = [
            ("group", str(group["group_id"]), int(group.get("sibling_position", 0)))
            for group in tree["groups"]
            if group.get("parent_id") == parent_id
        ]
        values.extend(
            ("item", str(index), int(item.get("sibling_position", index)))
            for index, item in enumerate(tree["items"])
            if item.get("group_id") == parent_id
        )
        values.sort(key=lambda value: (value[2], value[0], value[1]))
        return [(node_type, node_id) for node_type, node_id, _ in values]

    @staticmethod
    def _renumber(tree: dict[str, Any], parent_id: str | None, children: list[tuple[str, str]]) -> None:
        groups = {str(group["group_id"]): group for group in tree["groups"]}
        for position, (node_type, node_id) in enumerate(children):
            if node_type == "group":
                groups[node_id]["sibling_position"] = position
            else:
                tree["items"][int(node_id)]["sibling_position"] = position

    @classmethod
    def _tree_nodes(cls, tree: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            groups = {str(group["group_id"]): group for group in tree["groups"]}
        except (KeyError, TypeError) as error:
            raise PlaylistError("Playlist groups are malformed") from error
        if len(groups) != len(tree["groups"]):
            raise PlaylistError("Playlist group identifiers must be unique")
        visited_groups: set[str] = set()
        visited_items: set[int] = set()

        def visit(
            parent_id: str | None,
            prefix: tuple[int, ...],
            depth: int,
            ancestors: frozenset[str],
        ) -> list[dict[str, Any]]:
            if depth > MAX_PLAYLIST_DEPTH:
                raise PlaylistError(f"Playlist nesting cannot exceed {MAX_PLAYLIST_DEPTH} levels")
            values = []
            for index, (node_type, node_id) in enumerate(cls._children(tree, parent_id), 1):
                path = ".".join(map(str, (*prefix, index)))
                if node_type == "group":
                    if node_id in ancestors:
                        raise PlaylistError("Playlist groups cannot form a cycle")
                    visited_groups.add(node_id)
                    values.append(
                        {
                            "type": "group",
                            "id": node_id,
                            "path": path,
                            "group": groups[node_id],
                            "children": visit(
                                node_id,
                                (*prefix, index),
                                depth + 1,
                                ancestors | {node_id},
                            ),
                        }
                    )
                else:
                    visited_items.add(int(node_id))
                    values.append(
                        {"type": "item", "id": node_id, "path": path, "item": tree["items"][int(node_id)]}
                    )
            return values

        result = visit(None, (), 0, frozenset())
        if visited_groups != set(groups) or visited_items != set(range(len(tree["items"]))):
            raise PlaylistError("Playlist contains orphaned or cyclic nodes")
        return result

    @classmethod
    def _resolve(cls, tree: dict[str, Any], reference: str) -> dict[str, Any]:
        value = reference.strip()
        nodes = cls._tree_nodes(tree)
        if value and all(part.isdigit() and int(part) > 0 for part in value.split(".")):
            current = None
            children = nodes
            for part in value.split("."):
                index = int(part) - 1
                if index not in range(len(children)):
                    raise PlaylistError(f"Unknown playlist path: {reference}")
                current = children[index]
                children = current.get("children", [])
            if current:
                return current

        def walk(values):
            for node in values:
                if node["id"] == value:
                    return node
                found = walk(node.get("children", []))
                if found:
                    return found
            return None

        if found := walk(nodes):
            return found
        raise PlaylistError(f"Unknown playlist node: {reference}")

    def nodes(self, name_or_id: str) -> list[dict[str, Any]]:
        return self._tree_nodes(self._normalized_tree(self.get(name_or_id).tree))

    def add_media(
        self,
        name_or_id: str,
        media: MediaRef,
        *,
        parent: str | None = None,
        position: int | None = None,
    ) -> Playlist:
        playlist = self.get(name_or_id)
        tree = self._normalized_tree(playlist.tree)
        parent_id = None
        if parent:
            node = self._resolve(tree, parent)
            if node["type"] != "group":
                raise PlaylistError("A playlist parent must reference a group")
            parent_id = node["id"]
        children = self._children(tree, parent_id)
        insert_at = len(children) if position is None else max(0, min(position, len(children)))
        tree["items"].append(
            {
                "stable_id": media.stable_id,
                "media": media.to_dict(),
                "priority": 0,
                "attempts": 0,
                "failure_policy": "skip",
                "group_id": parent_id,
                "sibling_position": len(children),
            }
        )
        children.insert(insert_at, ("item", str(len(tree["items"]) - 1)))
        self._renumber(tree, parent_id, children)
        return self.save_snapshot(playlist.name, tree)

    def add_snapshot(
        self,
        name_or_id: str,
        snapshot: dict[str, Any],
        *,
        group_name: str,
        parent: str | None = None,
        position: int | None = None,
        kind: str = "playlist",
        source_ref: str | None = None,
    ) -> Playlist:
        playlist = self.get(name_or_id)
        tree = self._normalized_tree(playlist.tree)
        incoming = self._normalized_tree(snapshot)
        parent_id = None
        if parent:
            node = self._resolve(tree, parent)
            if node["type"] != "group":
                raise PlaylistError("A playlist parent must reference a group")
            parent_id = node["id"]
        children = self._children(tree, parent_id)
        insert_at = len(children) if position is None else max(0, min(position, len(children)))
        outer_id = uuid.uuid4().hex
        tree["groups"].append(
            {
                "group_id": outer_id,
                "parent_id": parent_id,
                "name": group_name,
                "kind": kind,
                "sibling_position": len(children),
                "strategy": "custom",
                "shuffle_seed": None,
                "priority": 0,
                "atomic": True,
                "source_ref": source_ref,
                "metadata": {},
                "created_at": time.time(),
                "updated_at": time.time(),
            }
        )
        mapping = {str(group["group_id"]): uuid.uuid4().hex for group in incoming["groups"]}
        for group in incoming["groups"]:
            cloned = dict(group)
            cloned["group_id"] = mapping[str(group["group_id"])]
            cloned["parent_id"] = mapping.get(str(group.get("parent_id")), outer_id)
            tree["groups"].append(cloned)
        for item in incoming["items"]:
            cloned = dict(item)
            cloned["group_id"] = mapping.get(str(item.get("group_id")), outer_id)
            tree["items"].append(cloned)
        children.insert(insert_at, ("group", outer_id))
        self._renumber(tree, parent_id, children)
        self._tree_nodes(tree)
        return self.save_snapshot(playlist.name, tree)

    def remove_node(self, name_or_id: str, reference: str) -> Playlist:
        playlist = self.get(name_or_id)
        tree = self._normalized_tree(playlist.tree)
        node = self._resolve(tree, reference)
        if node["type"] == "item":
            item = node["item"]
            parent_id = item.get("group_id")
            tree["items"].remove(item)
        else:
            group_id = node["id"]
            group = node["group"]
            parent_id = group.get("parent_id")
            descendants = {group_id}
            changed = True
            while changed:
                before = len(descendants)
                descendants.update(
                    str(value["group_id"])
                    for value in tree["groups"]
                    if value.get("parent_id") in descendants
                )
                changed = len(descendants) != before
            tree["items"] = [item for item in tree["items"] if item.get("group_id") not in descendants]
            tree["groups"] = [group for group in tree["groups"] if str(group["group_id"]) not in descendants]
        self._renumber(tree, parent_id, self._children(tree, parent_id))
        return self.save_snapshot(playlist.name, tree)

    def move_node(
        self,
        name_or_id: str,
        reference: str,
        *,
        parent: str | None = None,
        position: int | None = None,
    ) -> Playlist:
        playlist = self.get(name_or_id)
        tree = self._normalized_tree(playlist.tree)
        node = self._resolve(tree, reference)
        parent_id = None
        if parent:
            target = self._resolve(tree, parent)
            if target["type"] != "group":
                raise PlaylistError("A playlist parent must reference a group")
            parent_id = target["id"]
        if node["type"] == "group":
            group_id = node["id"]
            current = parent_id
            while current:
                if current == group_id:
                    raise PlaylistError("Playlist groups cannot form a cycle")
                parent_group = next(group for group in tree["groups"] if str(group["group_id"]) == current)
                current = parent_group.get("parent_id")
            old_parent = node["group"].get("parent_id")
            node["group"]["parent_id"] = parent_id
            node_key = ("group", group_id)
        else:
            old_parent = node["item"].get("group_id")
            node["item"]["group_id"] = parent_id
            node_key = ("item", node["id"])
        old_children = [child for child in self._children(tree, old_parent) if child != node_key]
        self._renumber(tree, old_parent, old_children)
        new_children = old_children if old_parent == parent_id else self._children(tree, parent_id)
        insert_at = len(new_children) if position is None else max(0, min(position, len(new_children)))
        new_children.insert(insert_at, node_key)
        self._renumber(tree, parent_id, new_children)
        self._tree_nodes(tree)
        return self.save_snapshot(playlist.name, tree)

    def order(
        self,
        name_or_id: str,
        strategy: QueueStrategy | str,
        *,
        group: str | None = None,
        seed: int | None = None,
        media_ranks: dict[str, int] | None = None,
    ) -> Playlist:
        playlist = self.get(name_or_id)
        tree = self._normalized_tree(playlist.tree)
        try:
            strategy = QueueStrategy(strategy)
        except ValueError as error:
            raise PlaylistError(f"Unknown playlist strategy: {strategy}") from error
        parent_id = None
        if group:
            node = self._resolve(tree, group)
            if node["type"] != "group":
                raise PlaylistError("Playlist order scope must reference a group")
            parent_id = node["id"]
        children = self._children(tree, parent_id)
        if strategy == QueueStrategy.SHUFFLE:
            seed = seed if seed is not None else random.SystemRandom().randrange(2**31)
            random.Random(seed).shuffle(children)
        elif strategy == QueueStrategy.PRIORITY:
            groups = {str(value["group_id"]): value for value in tree["groups"]}
            children.sort(
                key=lambda node: -int(
                    groups[node[1]].get("priority", 0)
                    if node[0] == "group"
                    else tree["items"][int(node[1])].get("priority", 0)
                )
            )
        elif strategy == QueueStrategy.ARTIST_FAIR:
            buckets: dict[str, deque] = defaultdict(deque)
            keys = []
            for index, node in enumerate(children):
                item_indexes = self._descendant_item_indexes(tree, node)
                media = [tree["items"][item]["media"] for item in item_indexes]
                artist = next((str(value.get("artist")).casefold() for value in media if value.get("artist")), f"unknown:{index}")
                if artist not in buckets:
                    keys.append(artist)
                buckets[artist].append(node)
            children = []
            while any(buckets.values()):
                for key in keys:
                    if buckets[key]:
                        children.append(buckets[key].popleft())
        elif strategy == QueueStrategy.SMART:
            if media_ranks is None:
                raise PlaylistError("Smart playlist ordering requires recommendation ranks")
            children.sort(
                key=lambda node: min(
                    (
                        media_ranks.get(tree["items"][index]["stable_id"], 10**9)
                        for index in self._descendant_item_indexes(tree, node)
                    ),
                    default=10**9,
                )
            )
        elif strategy not in {QueueStrategy.CUSTOM, QueueStrategy.SEQUENTIAL}:
            raise PlaylistError(f"Unknown playlist strategy: {strategy}")
        self._renumber(tree, parent_id, children)
        if parent_id:
            target = next(group for group in tree["groups"] if str(group["group_id"]) == parent_id)
            target["strategy"] = strategy.value
            target["shuffle_seed"] = seed
        else:
            tree["state"]["root_strategy"] = strategy.value
            tree["state"]["root_seed"] = seed
        return self.save_snapshot(playlist.name, tree)

    @classmethod
    def _descendant_item_indexes(cls, tree: dict[str, Any], node: tuple[str, str]) -> list[int]:
        if node[0] == "item":
            return [int(node[1])]
        result = []
        for child in cls._children(tree, node[1]):
            result.extend(cls._descendant_item_indexes(tree, child))
        return result

    @classmethod
    def flattened_media(cls, tree: dict[str, Any]) -> list[MediaRef]:
        normalized = cls._normalized_tree(tree)
        result = []
        for node in cls._children(normalized, None):
            for index in cls._descendant_item_indexes(normalized, node):
                payload = normalized["items"][index].get("media")
                if isinstance(payload, dict):
                    result.append(MediaRef.from_dict(payload))
        return result

    def import_m3u(self, name: str, source: Path | str) -> Playlist:
        path = Path(source).expanduser().resolve()
        if path.suffix.casefold() not in {".m3u", ".m3u8"} or not path.is_file():
            raise PlaylistError("Playlist import requires an existing .m3u or .m3u8 file")
        media_items = []
        title = None
        for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            value = raw.strip()
            if value.startswith("#EXTINF:"):
                title = value.partition(",")[2].strip() or None
                continue
            if not value or value.startswith("#"):
                continue
            parsed = urlparse(value)
            if parsed.scheme in {"http", "https"}:
                source_type = MediaSource.YOUTUBE if "youtu" in parsed.netloc.casefold() else MediaSource.URL
                uri = value
            else:
                target = Path(value).expanduser()
                uri = str((path.parent / target).resolve() if not target.is_absolute() else target.resolve())
                source_type = MediaSource.LOCAL
            media = MediaRef(source_type, uri, title=title)
            media_items.append(media)
            title = None
        return self.create(name, tree=self.snapshot_from_media(media_items))

    def export_m3u(self, name_or_id: str, destination: Path | str) -> Path:
        playlist = self.get(name_or_id)
        path = Path(destination).expanduser().resolve()
        if path.suffix.casefold() not in {".m3u", ".m3u8"}:
            raise PlaylistError("Playlist export path must end in .m3u or .m3u8")
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["#EXTM3U"]
        for media in self.flattened_media(playlist.tree):
            duration = int(media.duration) if media.duration is not None else -1
            lines.extend((f"#EXTINF:{duration},{media.artist + ' - ' if media.artist else ''}{media.title or ''}", media.original_uri))
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path
