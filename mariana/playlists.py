"""Versioned local playlist persistence."""

from __future__ import annotations

import json
import time
import unicodedata
import uuid
from typing import Any

from .database import MarianaDatabase
from .models import Playlist


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
        payload = json.dumps(tree or {"version": 1, "groups": [], "items": [], "state": {}}, ensure_ascii=False)
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO playlists(playlist_id,name,name_key,description,tree_json,revision,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,1,?,?)",
                    (uuid.uuid4().hex, normalized, normalized.casefold(), description, payload, now, now),
                )
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise PlaylistError(f"Playlist already exists: {normalized}") from error
            raise
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
        payload = json.dumps(tree, ensure_ascii=False)
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
        except Exception as error:
            if "UNIQUE constraint failed" in str(error):
                raise PlaylistError(f"Playlist already exists: {normalized}") from error
            raise
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
