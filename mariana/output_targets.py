"""Bound, revalidated activation targets for generated files."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OutputTargetError(RuntimeError):
    """Raised when a generated-file destination is unsafe or has changed."""


def _file_signature(path: Path) -> tuple[int, int, int, int, int]:
    details = path.stat(follow_symlinks=False)
    return (
        int(details.st_dev),
        int(details.st_ino),
        int(details.st_mode),
        int(details.st_size),
        int(details.st_mtime_ns),
    )


def _directory_signature(path: Path) -> tuple[int, int, int]:
    details = path.stat(follow_symlinks=False)
    return int(details.st_dev), int(details.st_ino), int(details.st_mode)


@dataclass(frozen=True, slots=True)
class BoundOutputTarget:
    """An output path and the filesystem identity approved for activation."""

    path: Path
    parent_signature: tuple[int, int, int]
    file_signature: tuple[int, int, int, int, int] | None

    @property
    def existed(self) -> bool:
        return self.file_signature is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "parent_signature": list(self.parent_signature),
            "file_signature": list(self.file_signature) if self.file_signature else None,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BoundOutputTarget:
        try:
            path = Path(str(value["path"]))
            parent = tuple(int(part) for part in value["parent_signature"])
            raw_file = value.get("file_signature")
            file_signature = tuple(int(part) for part in raw_file) if raw_file else None
        except (KeyError, TypeError, ValueError) as error:
            raise OutputTargetError("Stored output approval is invalid; refusing activation") from error
        if len(parent) != 3 or (file_signature is not None and len(file_signature) != 5):
            raise OutputTargetError("Stored output approval is invalid; refusing activation")
        parent_value = parent[0], parent[1], parent[2]
        file_value = None
        if file_signature is not None:
            file_value = (
                file_signature[0],
                file_signature[1],
                file_signature[2],
                file_signature[3],
                file_signature[4],
            )
        return cls(path, parent_value, file_value)

    def revalidate(self) -> None:
        try:
            if self.path.parent.is_symlink() or not self.path.parent.is_dir():
                raise OutputTargetError("Output destination changed after approval; refusing activation")
            if _directory_signature(self.path.parent) != self.parent_signature:
                raise OutputTargetError("Output destination changed after approval; refusing activation")
            if self.path.is_symlink():
                raise OutputTargetError("Symbolic-link output destinations are not supported")
            exists = self.path.exists()
            if self.file_signature is None:
                if exists:
                    raise OutputTargetError("Output destination appeared after approval; refusing overwrite")
                return
            if not exists or not self.path.is_file():
                raise OutputTargetError("Output destination changed after approval; refusing overwrite")
            if _file_signature(self.path) != self.file_signature:
                raise OutputTargetError("Output destination changed after approval; refusing overwrite")
        except OSError as error:
            raise OutputTargetError(
                "Output destination could not be revalidated safely"
            ) from error

    def activate(self, staged: Path | str) -> Path:
        """Activate a complete staged file without redirecting the approved target."""
        temporary = Path(staged)
        if temporary.is_symlink() or not temporary.is_file():
            raise OutputTargetError("Generated output is unavailable for activation")
        self.revalidate()
        if self.existed:
            try:
                os.replace(temporary, self.path)
            except OSError as error:
                raise OutputTargetError("Could not replace the approved output safely") from error
            return self.path
        try:
            os.link(temporary, self.path)
        except FileExistsError as error:
            raise OutputTargetError(
                "Output destination appeared after approval; refusing overwrite"
            ) from error
        except OSError as error:
            raise OutputTargetError("Could not activate generated output safely") from error
        temporary.unlink()
        return self.path


def bind_output_target(destination: Path | str) -> BoundOutputTarget:
    """Capture a canonical output path and its current filesystem identity."""
    requested = Path(destination).expanduser()
    if ".." in requested.parts:
        raise OutputTargetError("Output destination cannot contain parent traversal")
    try:
        if requested.is_symlink():
            raise OutputTargetError("Symbolic-link output destinations are not supported")
        requested.parent.mkdir(parents=True, exist_ok=True)
        path = requested.resolve(strict=False)
        if path.parent.is_symlink() or not path.parent.is_dir():
            raise OutputTargetError("Output destination parent must be an existing directory")
        if path.is_symlink():
            raise OutputTargetError("Symbolic-link output destinations are not supported")
        file_signature = None
        if path.exists():
            if not path.is_file() or not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
                raise OutputTargetError("Output destination must be a regular file")
            file_signature = _file_signature(path)
        return BoundOutputTarget(path, _directory_signature(path.parent), file_signature)
    except OSError as error:
        raise OutputTargetError("Output destination could not be bound safely") from error
