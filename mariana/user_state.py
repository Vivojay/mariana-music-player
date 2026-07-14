"""Validated, interruption-safe persistence for legacy user statistics."""

from __future__ import annotations

import copy
import io
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

_YAML = YAML(typ="safe")
_WRITE_YAML = YAML()
_WRITE_LOCK = threading.RLock()

_FALLBACK_USER_DATA: dict[str, Any] = {
    "default_user_data": {
        "name": "guest_001",
        "pwd": None,
        "stats": {
            "log_ins": 0,
            "play_count": {
                "general": 0,
                "local": 0,
                "radio": 0,
                "redditsession": 0,
                "total": 0,
                "youtube": 0,
            },
            "times_spent": [],
        },
    }
}


def _merge_defaults(defaults: Mapping[str, Any], value: object) -> dict[str, Any]:
    """Recursively fill missing or structurally invalid mappings."""
    supplied = value if isinstance(value, Mapping) else {}
    merged: dict[str, Any] = {}
    for key, default in defaults.items():
        candidate = supplied.get(key)
        if isinstance(default, Mapping):
            merged[key] = _merge_defaults(default, candidate)
        elif candidate is None and default is not None:
            merged[key] = copy.deepcopy(default)
        else:
            merged[key] = copy.deepcopy(candidate if key in supplied else default)
    for key, candidate in supplied.items():
        if key not in merged:
            merged[key] = copy.deepcopy(candidate)
    return merged


def _read_mapping(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = _YAML.load(stream)
    except (OSError, UnicodeError, YAMLError):
        return None
    return dict(payload) if isinstance(payload, Mapping) else None


def default_user_data(template: Path | None = None) -> dict[str, Any]:
    """Load packaged defaults when valid, otherwise use embedded safe defaults."""
    packaged = _read_mapping(template) if template and template.is_file() else None
    return _merge_defaults(_FALLBACK_USER_DATA, packaged)


def normalize_user_data(payload: object, template: Path | None = None) -> dict[str, Any]:
    """Return a complete usable mapping while retaining unknown user fields."""
    return _merge_defaults(default_user_data(template), payload)


def _serialized(payload: Mapping[str, Any]) -> str:
    stream = io.StringIO()
    _WRITE_YAML.dump(dict(payload), stream)
    return stream.getvalue()


def _replace_with_windows_retry(source: Path, destination: Path) -> None:
    """Tolerate brief scanner/indexer locks without hiding persistent failures."""
    delays = (0.02, 0.05, 0.1, 0.2, 0.4)
    attempt = 0
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == len(delays):
                raise
            time.sleep(delays[attempt])
            attempt += 1


def write_user_data_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Replace user data atomically so process interruption cannot truncate it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = _serialized(payload)
    with _WRITE_LOCK:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
            _replace_with_windows_retry(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _retain_invalid_backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.invalid-{time.time_ns()}.bak")
    try:
        shutil.copy2(path, backup)
    except OSError:
        return None
    return backup


def load_user_data(path: Path, template: Path | None = None) -> tuple[dict[str, Any], Path | None]:
    """Load and repair user data, returning the retained invalid backup if any."""
    current = _read_mapping(path) if path.exists() else None
    recovered = current is None
    backup = _retain_invalid_backup(path) if recovered else None
    normalized = normalize_user_data(current, template)
    if recovered or normalized != current:
        write_user_data_atomic(path, normalized)
    return normalized, backup
