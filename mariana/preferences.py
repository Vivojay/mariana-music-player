"""Persistent tri-state media preferences and legacy migration."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .database import MarianaDatabase
from .models import MediaRef, MediaSource
from .sources import sanitized_resolver_data

if TYPE_CHECKING:
    from .library import LibraryCatalog


class PreferenceState(StrEnum):
    FAVORITE = "favorite"
    NEUTRAL = "neutral"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class PreferenceEntry:
    stable_id: str
    state: PreferenceState
    label: str
    uri: str | None
    updated_at: float
    source: MediaSource | None = None


class MediaPreferences:
    def __init__(self, database: MarianaDatabase):
        self.database = database

    def get(self, media_or_id: MediaRef | str) -> PreferenceState:
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else media_or_id
        row = self.database.fetchone("SELECT state FROM media_preferences WHERE stable_id=?", (stable_id,))
        return PreferenceState(row["state"]) if row else PreferenceState.NEUTRAL

    def set(self, media_or_id: MediaRef | str, state: PreferenceState | str) -> bool:
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else media_or_id
        state = PreferenceState(state)
        previous = self.get(stable_id)
        with self.database.transaction() as connection:
            if isinstance(media_or_id, MediaRef):
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
                        media_or_id.stable_id,
                        media_or_id.source.value,
                        media_or_id.original_uri,
                        media_or_id.title,
                        media_or_id.artist,
                        media_or_id.album,
                        media_or_id.duration,
                        media_or_id.capabilities.to_json(),
                        json.dumps(
                            sanitized_resolver_data(media_or_id.resolver_data),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        json.dumps([asdict(chapter) for chapter in media_or_id.chapters], ensure_ascii=False),
                        media_or_id.provenance,
                        time.time(),
                    ),
                )
            if previous != state:
                connection.execute(
                    "INSERT INTO media_preferences(stable_id, state, updated_at) VALUES(?, ?, ?) "
                    "ON CONFLICT(stable_id) DO UPDATE SET state=excluded.state, updated_at=excluded.updated_at",
                    (stable_id, state.value, time.time()),
                )
        return previous != state

    def toggle(self, media_or_id: MediaRef | str, state: PreferenceState | str) -> PreferenceState:
        state = PreferenceState(state)
        target = PreferenceState.NEUTRAL if self.get(media_or_id) == state else state
        self.set(media_or_id, target)
        return target

    def list(self, state: PreferenceState | str, limit: int | None = None) -> list[PreferenceEntry]:
        state = PreferenceState(state)
        sql = (
            "SELECT p.stable_id, p.state, p.updated_at, m.source, m.original_uri, m.title, f.canonical_path "
            "FROM media_preferences p LEFT JOIN media_items m ON m.stable_id=p.stable_id "
            "LEFT JOIN library_files f ON f.library_id=p.stable_id WHERE p.state=? "
            "ORDER BY p.updated_at DESC"
        )
        parameters: tuple = (state.value,)
        if limit is not None:
            sql += " LIMIT ?"
            parameters += (max(0, limit),)
        return [
            PreferenceEntry(
                stable_id=row["stable_id"],
                state=PreferenceState(row["state"]),
                label=row["title"] or (
                    Path(row["canonical_path"] or row["original_uri"]).stem
                    if row["canonical_path"] or row["original_uri"]
                    else "Unknown media"
                ),
                uri=row["canonical_path"] or row["original_uri"],
                updated_at=row["updated_at"],
                source=MediaSource(row["source"]) if row["source"] else None,
            )
            for row in self.database.fetchall(sql, parameters)
        ]

    def migrate_legacy(self, path: Path | str, catalog: LibraryCatalog) -> dict[str, int]:
        path = Path(path)
        marker = f"legacy_preferences:{path.resolve()}"
        prior = self.database.get_state(marker, {})
        if prior.get("complete") or not path.is_file():
            return prior or {"imported": 0, "unresolved": 0, "complete": False}
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, TypeError, yaml.YAMLError):
            result = {"imported": 0, "unresolved": 0, "complete": False, "error": "invalid legacy YAML"}
            self.database.set_state(marker, result)
            return result
        if not isinstance(payload, dict):
            payload = {}
        backup = path.with_suffix(path.suffix + ".pre-mariana-0.7.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        imported = 0
        unresolved = 0
        for media_path, values in payload.items():
            if not isinstance(values, dict) or "isFav" not in values:
                continue
            info = catalog.info(str(media_path))
            if not info:
                unresolved += 1
                continue
            legacy = values.get("isFav")
            state = (
                PreferenceState.BLOCKED
                if legacy is None
                else PreferenceState.FAVORITE
                if legacy is True
                else PreferenceState.NEUTRAL
            )
            if self.set(info["library_id"], state):
                imported += 1
        result = {"imported": imported, "unresolved": unresolved, "complete": unresolved == 0}
        self.database.set_state(marker, result)
        return result
