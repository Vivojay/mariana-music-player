"""Recoverable, trash-only removal of indexed local media."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from send2trash import send2trash

from .database import MarianaDatabase
from .library import LibraryCatalog, LibraryError
from .models import MediaSource
from .queueing import PersistentQueue


class MediaRemovalError(RuntimeError):
    pass


class MediaRemovalPartialError(MediaRemovalError):
    pass


@dataclass(frozen=True, slots=True)
class RemovalTarget:
    library_id: str
    path: Path


class MediaRemovalService:
    JOURNAL_PREFIX = "media_removal:"

    def __init__(
        self,
        database: MarianaDatabase,
        catalog: LibraryCatalog,
        queue: PersistentQueue,
        controller,
        *,
        trash: Callable[[str], None] = send2trash,
    ) -> None:
        self.database = database
        self.catalog = catalog
        self.queue = queue
        self.controller = controller
        self.trash = trash

    def resolve(self, value: str) -> RemovalTarget:
        if value.isdigit() and int(value) < 1:
            raise MediaRemovalError("Library index must be a positive integer")
        info = self.catalog.info(value)
        if not info or info.get("state") != "available":
            raise MediaRemovalError("Media is not an available indexed library file")
        path = Path(info["canonical_path"])
        if path.is_symlink() or not path.is_file():
            raise MediaRemovalError("Only existing, non-symlink media files can be recycled")
        resolved = path.resolve()
        roots = [
            Path(root["path"]).resolve()
            for root in self.catalog.roots()
            if root.get("available")
        ]
        if not any(resolved.is_relative_to(root) for root in roots):
            raise MediaRemovalError("Media is outside the configured library roots")
        if self.catalog.supported_extensions and resolved.suffix.casefold() not in self.catalog.supported_extensions:
            raise MediaRemovalError("File type is not supported media")
        return RemovalTarget(info["library_id"], resolved)

    def _journal_key(self, operation_id: str) -> str:
        return f"{self.JOURNAL_PREFIX}{operation_id}"

    def remove(self, target: RemovalTarget) -> RemovalTarget:
        operation_id = uuid.uuid4().hex
        key = self._journal_key(operation_id)
        payload = {
            "operation_id": operation_id,
            "library_id": target.library_id,
            "path": str(target.path),
            "status": "planned",
            "created_at": time.time(),
        }
        self.database.set_state(key, payload)
        snapshot = self.controller.snapshot()
        if (
            snapshot.media
            and snapshot.media.source == MediaSource.LOCAL
            and os.path.normcase(os.path.abspath(snapshot.media.original_uri)).casefold()
            == os.path.normcase(os.path.abspath(target.path)).casefold()
        ):
            self.controller.stop()
        try:
            self.trash(str(target.path))
        except OSError as error:
            self.database.delete_state(key)
            raise MediaRemovalError(f"Could not move media to trash: {error}") from error
        payload["status"] = "trashed"
        self.database.set_state(key, payload)
        try:
            self.catalog.mark_missing(target.library_id)
            self.queue.remove_media(target.library_id, str(target.path))
            self.database.delete_state(key)
        except Exception as error:
            raise MediaRemovalPartialError(
                "Media was moved to trash, but database reconciliation remains pending"
            ) from error
        return target

    def recover(self) -> int:
        rows = self.database.fetchall(
            "SELECT key, value_json FROM app_state WHERE key LIKE ? ORDER BY updated_at",
            (f"{self.JOURNAL_PREFIX}%",),
        )
        recovered = 0
        for row in rows:
            try:
                payload = json.loads(row["value_json"])
                path = Path(payload["path"])
                library_id = str(payload["library_id"])
            except (KeyError, TypeError, ValueError):
                self.database.delete_state(row["key"])
                continue
            if path.exists():
                self.database.delete_state(row["key"])
                continue
            try:
                self.catalog.mark_missing(library_id)
                self.queue.remove_media(library_id, str(path))
            except LibraryError:
                continue
            self.database.delete_state(row["key"])
            recovered += 1
        return recovered
