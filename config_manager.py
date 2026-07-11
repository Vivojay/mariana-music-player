"""Configuration loading and additive migration helpers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import toml
from ruamel.yaml import YAML


APP_DIR = Path(__file__).resolve().parent
SETTINGS_PATH = APP_DIR / "settings" / "settings.yml"
DEFAULT_SETTINGS_PATH = APP_DIR / "settings" / "settings.yml.default"
SYSTEM_SETTINGS_PATH = APP_DIR / "settings" / "system.toml"

yaml = YAML(typ="safe")


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
    settings_path: Path = SETTINGS_PATH,
    defaults_path: Path = DEFAULT_SETTINGS_PATH,
    *,
    persist_migration: bool = True,
) -> dict[str, Any]:
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
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        writer = YAML()
        with settings_path.open("w", encoding="utf-8") as stream:
            writer.dump(merged, stream)
    return merged


def load_system_settings(path: Path = SYSTEM_SETTINGS_PATH) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return toml.load(stream)
