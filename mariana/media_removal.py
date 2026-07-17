"""Recoverable, trash-only removal of indexed local media."""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from send2trash import send2trash

from .database import MarianaDatabase
from .library import LibraryCatalog, LibraryError
from .media_details import trusted_metadata_text
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
    display_index: int | None = None
    title: str = "Local media"
    file_signature: tuple[int, int, int, int] | None = None


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

    @staticmethod
    def _same_path(left: Path, right: Path) -> bool:
        return os.path.normcase(os.path.abspath(left)).casefold() == os.path.normcase(
            os.path.abspath(right)
        ).casefold()

    @staticmethod
    def _signature(file_stat: os.stat_result) -> tuple[int, int, int, int]:
        return (
            int(getattr(file_stat, "st_dev", 0)),
            int(getattr(file_stat, "st_ino", 0)),
            int(file_stat.st_size),
            int(file_stat.st_mtime_ns),
        )

    def _display_index(self, path: Path) -> int | None:
        return next(
            (
                index
                for index, candidate in enumerate(self.catalog.paths(), start=1)
                if self._same_path(Path(candidate), path)
            ),
            None,
        )

    @staticmethod
    def _display_title(info: dict, path: Path) -> str:
        metadata_value = info.get("metadata")
        metadata = metadata_value if isinstance(metadata_value, dict) else {}
        value = trusted_metadata_text(metadata.get("source_title")) or trusted_metadata_text(
            metadata.get("title")
        )
        value = value or path.stem
        title = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or ""))
        return re.sub(r"\s+", " ", title).strip().replace('"', "'") or "Local media"

    def resolve(self, value: str) -> RemovalTarget:
        if value.isdigit() and int(value) < 1:
            raise MediaRemovalError("Library index must be a positive integer")
        info = self.catalog.info(value)
        if not info or info.get("state") != "available":
            raise MediaRemovalError("Media is not an available indexed library file")
        path = Path(info["canonical_path"])
        try:
            file_stat = path.stat()
        except OSError as error:
            raise MediaRemovalError("Only existing, non-symlink media files can be recycled") from error
        if path.is_symlink() or not stat.S_ISREG(file_stat.st_mode):
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
        display_index = int(value) if value.isdigit() else self._display_index(resolved)
        if display_index is None:
            raise MediaRemovalError("Media is not in the current available-library view")
        return RemovalTarget(
            info["library_id"],
            resolved,
            display_index,
            self._display_title(info, resolved),
            self._signature(file_stat),
        )

    def _validate_bound_target(self, target: RemovalTarget) -> None:
        if target.file_signature is None:
            raise MediaRemovalError("Removal target is not safely bound; resolve it again")
        try:
            current = self.resolve(target.library_id)
        except MediaRemovalError as error:
            raise MediaRemovalError("Removal target changed after confirmation; run the command again") from error
        if (
            current.library_id != target.library_id
            or not self._same_path(current.path, target.path)
            or current.display_index != target.display_index
            or current.title != target.title
            or current.file_signature != target.file_signature
        ):
            raise MediaRemovalError("Removal target changed after confirmation; run the command again")

    def _journal_key(self, operation_id: str) -> str:
        return f"{self.JOURNAL_PREFIX}{operation_id}"

    def remove(self, target: RemovalTarget) -> RemovalTarget:
        self._validate_bound_target(target)
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
