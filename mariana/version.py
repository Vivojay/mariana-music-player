"""Single Mariana version source shared by the CLI and desktop build."""

from __future__ import annotations

import json
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parents[1] / "version.json"


def read_version(path: Path = VERSION_FILE) -> str:
    value = json.loads(path.read_text(encoding="utf-8")).get("version")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid Mariana version file: {path}")
    return value.strip()


__version__ = read_version()
