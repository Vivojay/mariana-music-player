"""Configuration loading and additive migration helpers."""

from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import toml
from ruamel.yaml import YAML

from mariana.paths import runtime_paths

yaml = YAML(typ="safe")


def save_user_settings(settings: dict[str, Any], settings_path: Path | None = None) -> Path:
    """Atomically persist writable user settings without touching resources."""
    settings_path = settings_path or runtime_paths().settings
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{settings_path.name}.", suffix=".tmp", dir=settings_path.parent
    )
    temporary = Path(temporary_name)
    try:
        writer = YAML()
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            writer.dump(settings, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, settings_path)
    finally:
        temporary.unlink(missing_ok=True)
    return settings_path


def deep_merge_defaults(current: dict[str, Any], defaults: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    merged = deepcopy(current)
    changed = False
    for key, default_value in defaults.items():
        if key not in merged:
            merged[key] = deepcopy(default_value)
            changed = True
        elif isinstance(default_value, dict) and isinstance(merged[key], dict):
            merged_value, nested_changed = deep_merge_defaults(merged[key], default_value)
            merged[key] = merged_value
            changed = changed or nested_changed
    return merged, changed


def load_user_settings(
    settings_path: Path | None = None,
    defaults_path: Path | None = None,
    *,
    persist_migration: bool = True,
) -> dict[str, Any]:
    settings_path = settings_path or runtime_paths().settings
    defaults_path = defaults_path or runtime_paths().settings_defaults
    with defaults_path.open(encoding="utf-8") as stream:
        defaults = yaml.load(stream) or {}
    if not isinstance(defaults, dict):
        raise ValueError(f"Default settings must contain a mapping: {defaults_path}")
    if settings_path.exists():
        with settings_path.open(encoding="utf-8") as stream:
            current = yaml.load(stream) or {}
    else:
        current = {}
    if not isinstance(current, dict):
        raise ValueError(f"User settings must contain a mapping: {settings_path}")
    merged, changed = deep_merge_defaults(current, defaults)
    if changed and persist_migration:
        save_user_settings(merged, settings_path)
    return merged


def load_system_settings(path: Path | None = None) -> dict[str, Any]:
    path = path or runtime_paths().system_settings
    with path.open(encoding="utf-8") as stream:
        return toml.load(stream)
