"""Chapter-level favourites: hearts bound to (media, chapter_index).

Whole-media favouriting remains the default. Chapter hearts are opt-in via
`fav --chapter [N]` and never imply a whole-media heart (or vice versa).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .database import MarianaDatabase
from .models import MediaRef


@dataclass(frozen=True, slots=True)
class ChapterFavorite:
    stable_id: str
    chapter_index: int
    chapter_title: str | None
    start_seconds: float | None
    updated_at: float


def ensure_schema(database: MarianaDatabase) -> None:
    with database.transaction() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS favorite_chapters("
            "stable_id TEXT NOT NULL, chapter_index INTEGER NOT NULL, "
            "chapter_title TEXT, start_ms INTEGER, updated_at REAL NOT NULL, "
            "PRIMARY KEY(stable_id, chapter_index))"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_favorite_chapters_updated ON favorite_chapters(updated_at DESC)"
        )


class ChapterFavoriteStore:
    def __init__(self, database: MarianaDatabase) -> None:
        self.database = database
        ensure_schema(database)

    def toggle(
        self, media_or_id: MediaRef | str, index: int, *, title: str | None = None, start_seconds: float | None = None
    ) -> bool:
        """Toggle one chapter heart; return True when now favorited."""
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
        if index < 0 or index > 10000:
            raise ValueError("Chapter number is out of range")
        row = self.database.fetchone(
            "SELECT 1 FROM favorite_chapters WHERE stable_id=? AND chapter_index=?", (stable_id, index)
        )
        with self.database.transaction() as connection:
            if row is None:
                connection.execute(
                    "INSERT INTO favorite_chapters(stable_id, chapter_index, chapter_title, start_ms, updated_at)"
                    " VALUES(?,?,?,?,?)",
                    (
                        stable_id,
                        index,
                        (title or "")[:256] or None,
                        None if start_seconds is None else round(float(start_seconds) * 1000),
                        time.time(),
                    ),
                )
                return True
            connection.execute(
                "DELETE FROM favorite_chapters WHERE stable_id=? AND chapter_index=?", (stable_id, index)
            )
            return False

    def set(
        self,
        media_or_id: MediaRef | str,
        index: int,
        favorited: bool,
        *,
        title: str | None = None,
        start_seconds: float | None = None,
    ) -> bool:
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
        row = self.database.fetchone(
            "SELECT 1 FROM favorite_chapters WHERE stable_id=? AND chapter_index=?", (stable_id, index)
        )
        exists = row is not None
        if exists == favorited:
            return False
        return self.toggle(media_or_id, index, title=title, start_seconds=start_seconds) == favorited

    def is_favorite(self, media_or_id: MediaRef | str, index: int) -> bool:
        stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
        return (
            self.database.fetchone(
                "SELECT 1 FROM favorite_chapters WHERE stable_id=? AND chapter_index=?", (stable_id, index)
            )
            is not None
        )

    def list(self, media_or_id: MediaRef | str | None = None, *, limit: int = 200) -> list[ChapterFavorite]:
        if media_or_id is None:
            rows = self.database.fetchall(
                "SELECT stable_id, chapter_index, chapter_title, start_ms, updated_at FROM favorite_chapters"
                " ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(1000, limit)),),
            )
        else:
            stable_id = media_or_id.stable_id if isinstance(media_or_id, MediaRef) else str(media_or_id)
            rows = self.database.fetchall(
                "SELECT stable_id, chapter_index, chapter_title, start_ms, updated_at FROM favorite_chapters"
                " WHERE stable_id=? ORDER BY chapter_index ASC",
                (stable_id,),
            )
        return [
            ChapterFavorite(
                str(row["stable_id"]),
                int(row["chapter_index"]),
                row["chapter_title"],
                None if row["start_ms"] is None else row["start_ms"] / 1000.0,
                float(row["updated_at"]),
            )
            for row in rows
        ]
