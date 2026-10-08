"""Versioned local projects for the Strudel composition surface."""

from __future__ import annotations

import json
import os
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
MAX_PROJECTS = 100
MAX_NAME_LENGTH = 120
MAX_CODE_BYTES = 64 * 1024
MIN_PREVIEW_SECONDS = 1
MAX_PREVIEW_SECONDS = 60

STARTER_CODE = '''setcps(0.5)
stack(
  s("bd*4, ~ sd ~ sd, hh*8").gain(0.8),
  note("<c3 eb3 g3 bb3>").s("sawtooth").lpf(900).gain(0.35)
).room(0.15)
'''


class StrudelProjectError(ValueError):
    """A safe project validation or revision error."""


@dataclass(frozen=True, slots=True)
class StrudelProject:
    project_id: str
    name: str
    code: str
    preview_seconds: int
    revision: int
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_project_name(value: object) -> str:
    if not isinstance(value, str):
        raise StrudelProjectError("Project name must be text")
    name = unicodedata.normalize("NFC", value).strip()
    if not name:
        raise StrudelProjectError("Project name cannot be empty")
    if len(name) > MAX_NAME_LENGTH:
        raise StrudelProjectError(f"Project name cannot exceed {MAX_NAME_LENGTH} characters")
    if any(ord(character) < 32 for character in name):
        raise StrudelProjectError("Project name contains unsupported control characters")
    return name


def validate_project_code(value: object) -> str:
    if not isinstance(value, str):
        raise StrudelProjectError("Project code must be text")
    if not value.strip():
        raise StrudelProjectError("Project code cannot be empty")
    if "\0" in value:
        raise StrudelProjectError("Project code contains an unsupported null character")
    if len(value.encode("utf-8")) > MAX_CODE_BYTES:
        raise StrudelProjectError(f"Project code cannot exceed {MAX_CODE_BYTES // 1024} KiB")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def validate_preview_seconds(value: object) -> int:
    if type(value) is not int or value not in range(MIN_PREVIEW_SECONDS, MAX_PREVIEW_SECONDS + 1):
        raise StrudelProjectError(
            f"Preview duration must be a whole number from {MIN_PREVIEW_SECONDS} to {MAX_PREVIEW_SECONDS} seconds"
        )
    return value


class StrudelProjectStore:
    """Persist bounded project source atomically outside the repository."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _project(value: object) -> StrudelProject:
        if not isinstance(value, dict):
            raise StrudelProjectError("Project data is invalid")
        project_id = value.get("project_id")
        revision = value.get("revision")
        created_at = value.get("created_at")
        updated_at = value.get("updated_at")
        if (
            not isinstance(project_id, str)
            or len(project_id) != 32
            or any(character not in "0123456789abcdef" for character in project_id)
            or type(revision) is not int
            or revision < 1
            or isinstance(created_at, bool)
            or not isinstance(created_at, (int, float))
            or isinstance(updated_at, bool)
            or not isinstance(updated_at, (int, float))
        ):
            raise StrudelProjectError("Project data is invalid")
        return StrudelProject(
            project_id=project_id,
            name=normalize_project_name(value.get("name")),
            code=validate_project_code(value.get("code")),
            preview_seconds=validate_preview_seconds(value.get("preview_seconds")),
            revision=revision,
            created_at=float(created_at),
            updated_at=float(updated_at),
        )

    def _read(self) -> list[StrudelProject]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise StrudelProjectError("Saved Strudel projects are unavailable or corrupt") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise StrudelProjectError("Saved Strudel projects use an unsupported format")
        raw_projects = payload.get("projects")
        if not isinstance(raw_projects, list) or len(raw_projects) > MAX_PROJECTS:
            raise StrudelProjectError("Saved Strudel project data is invalid")
        projects = [self._project(value) for value in raw_projects]
        if len({project.project_id for project in projects}) != len(projects):
            raise StrudelProjectError("Saved Strudel project identities are not unique")
        return projects

    def _write(self, projects: list[StrudelProject]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "projects": [project.to_dict() for project in projects],
        }
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def list(self) -> list[StrudelProject]:
        with self._lock:
            return sorted(self._read(), key=lambda project: (-project.updated_at, project.name.casefold()))

    def get(self, project_id_or_name: str) -> StrudelProject:
        target = str(project_id_or_name).strip()
        with self._lock:
            matches = [
                project for project in self._read()
                if project.project_id == target or project.name.casefold() == target.casefold()
            ]
        if not matches:
            raise StrudelProjectError(f"Unknown Strudel project: {target}")
        return matches[0]

    def save(
        self,
        *,
        project_id: str | None,
        name: object,
        code: object,
        preview_seconds: object,
        expected_revision: object,
    ) -> StrudelProject:
        normalized_name = normalize_project_name(name)
        normalized_code = validate_project_code(code)
        normalized_duration = validate_preview_seconds(preview_seconds)
        with self._lock:
            projects = self._read()
            now = time.time()
            if project_id is None:
                if expected_revision is not None:
                    raise StrudelProjectError("A new project cannot have an existing revision")
                if len(projects) >= MAX_PROJECTS:
                    raise StrudelProjectError(f"At most {MAX_PROJECTS} Strudel projects can be saved")
                if any(project.name.casefold() == normalized_name.casefold() for project in projects):
                    raise StrudelProjectError(f"A Strudel project named {normalized_name!r} already exists")
                project = StrudelProject(
                    uuid.uuid4().hex,
                    normalized_name,
                    normalized_code,
                    normalized_duration,
                    1,
                    now,
                    now,
                )
                projects.append(project)
            else:
                if not isinstance(project_id, str):
                    raise StrudelProjectError("Project identity is invalid")
                match = next((item for item in projects if item.project_id == project_id), None)
                if match is None:
                    raise StrudelProjectError("Project changed or was removed; reopen the editor")
                if type(expected_revision) is not int or expected_revision != match.revision:
                    raise StrudelProjectError("Project changed; reopen it before saving")
                if any(
                    item.project_id != project_id and item.name.casefold() == normalized_name.casefold()
                    for item in projects
                ):
                    raise StrudelProjectError(f"A Strudel project named {normalized_name!r} already exists")
                project = StrudelProject(
                    match.project_id,
                    normalized_name,
                    normalized_code,
                    normalized_duration,
                    match.revision + 1,
                    match.created_at,
                    now,
                )
                projects[projects.index(match)] = project
            self._write(projects)
            return project

    def create(self, name: object) -> StrudelProject:
        return self.save(
            project_id=None,
            name=name,
            code=STARTER_CODE,
            preview_seconds=16,
            expected_revision=None,
        )

    def delete(self, project_id: object, expected_revision: object) -> StrudelProject:
        if not isinstance(project_id, str) or type(expected_revision) is not int:
            raise StrudelProjectError("Project deletion request is invalid")
        with self._lock:
            projects = self._read()
            match = next((project for project in projects if project.project_id == project_id), None)
            if match is None or match.revision != expected_revision:
                raise StrudelProjectError("Project changed or was removed; reopen the editor")
            projects.remove(match)
            self._write(projects)
            return match

    def projection(self, *, open_requested: bool = False, selected_id: str | None = None) -> dict[str, Any]:
        projects = self.list()
        return {
            "schema_version": SCHEMA_VERSION,
            "open_requested": open_requested,
            "selected_id": selected_id if any(project.project_id == selected_id for project in projects) else None,
            "projects": [project.to_dict() for project in projects],
            "limits": {
                "max_projects": MAX_PROJECTS,
                "max_code_bytes": MAX_CODE_BYTES,
                "max_preview_seconds": MAX_PREVIEW_SECONDS,
            },
        }
