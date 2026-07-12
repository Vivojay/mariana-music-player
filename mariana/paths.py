"""Immutable resource and writable user-data paths for source and packaged runs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path

APP_NAME = "Mariana"
APP_AUTHOR = "Vivojay"
MIGRATION_VERSION = 1


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    resources: Path
    data: Path

    @property
    def settings(self) -> Path:
        return self.data / "settings" / "settings.yml"

    @property
    def settings_defaults(self) -> Path:
        return self.resources / "settings" / "settings.yml.default"

    @property
    def system_settings(self) -> Path:
        return self.resources / "settings" / "system.toml"

    @property
    def library_file(self) -> Path:
        return self.data / "lib.lib"

    @property
    def database(self) -> Path:
        return self.data / "data" / "mariana.db"

    @property
    def user_data(self) -> Path:
        return self.data / "user" / "user_data.yml"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def temporary(self) -> Path:
        return self.data / "temp"

    @property
    def tools(self) -> Path:
        return self.data / "tools"

    def resource(self, *parts: str) -> Path:
        return self.resources.joinpath(*parts)

    def state(self, *parts: str) -> Path:
        return self.data.joinpath(*parts)


_runtime_paths: RuntimePaths | None = None


def discover_runtime_paths() -> RuntimePaths:
    repository = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
    configured_resources = Path(os.environ.get("MARIANA_RESOURCE_DIR", repository)).expanduser().resolve()
    resources = configured_resources if (configured_resources / "settings" / "system.toml").is_file() else repository
    configured_data = os.environ.get("MARIANA_DATA_DIR")
    data = (
        Path(configured_data).expanduser().resolve()
        if configured_data
        else Path(user_data_path(APP_NAME, APP_AUTHOR, roaming=True)).resolve()
    )
    return RuntimePaths(resources, data)


def runtime_paths() -> RuntimePaths:
    global _runtime_paths
    if _runtime_paths is None:
        _runtime_paths = discover_runtime_paths()
    return _runtime_paths


def set_runtime_paths(paths: RuntimePaths) -> None:
    """Override paths for tests and embedded hosts before services are created."""
    global _runtime_paths
    _runtime_paths = paths


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        if _digest(source) != _digest(temporary):
            raise OSError(f"Verification failed while copying {source}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_runtime_paths(paths: RuntimePaths | None = None) -> RuntimePaths:
    """Create writable state and copy legacy state without removing the originals."""
    paths = paths or runtime_paths()
    paths.data.mkdir(parents=True, exist_ok=True)
    for directory in (paths.logs, paths.temporary, paths.tools, paths.state("data"), paths.state("user")):
        directory.mkdir(parents=True, exist_ok=True)

    migrations = (
        (paths.resource("settings", "settings.yml"), paths.settings),
        (paths.resource("lib.lib"), paths.library_file),
        (paths.resource("user", "user_data.yml"), paths.user_data),
        (paths.resource("data", "mariana.db"), paths.database),
    )
    copied: list[str] = []
    for source, destination in migrations:
        if source.is_file() and not destination.exists() and source.resolve() != destination.resolve():
            _copy_atomic(source, destination)
            copied.append(str(destination.relative_to(paths.data)))

    if not paths.settings.exists():
        _copy_atomic(paths.settings_defaults, paths.settings)
    if not paths.library_file.exists():
        paths.library_file.write_text("# Add one music-library directory per line.\n", encoding="utf-8")
    if not paths.user_data.exists():
        paths.user_data.write_text("default_user_data: {}\n", encoding="utf-8")

    marker = paths.data / ".migration.json"
    if not marker.exists():
        payload = {
            "migration_version": MIGRATION_VERSION,
            "created_at": time.time(),
            "source": str(paths.resources),
            "copied": copied,
        }
        temporary = marker.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, marker)
    return paths
