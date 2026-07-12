"""Fail closed when a production release is not versioned and signed correctly."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mariana.version import __version__  # noqa: E402


def require(*names: str) -> None:
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"Missing release secrets: {', '.join(missing)}")


def main() -> None:
    expected_tag = os.environ.get("MARIANA_RELEASE_TAG", "")
    if "dev" in __version__ or expected_tag != f"v{__version__}":
        raise SystemExit(f"Release tag/version mismatch: tag={expected_tag}, version={__version__}")
    manifest = json.loads((Path(__file__).resolve().parent / "manifest.json").read_text(encoding="utf-8"))
    required_artifacts = {"win32-x64", "darwin-x64", "darwin-arm64", "linux-x64"}
    missing_artifacts = required_artifacts - set(manifest.get("artifacts", {}))
    if missing_artifacts:
        raise SystemExit(f"Managed tool artifacts are not published: {', '.join(sorted(missing_artifacts))}")
    if sys.platform == "win32":
        require("WIN_CSC_LINK", "WIN_CSC_KEY_PASSWORD")
    elif sys.platform == "darwin":
        require("CSC_LINK", "CSC_KEY_PASSWORD", "APPLE_ID", "APPLE_APP_SPECIFIC_PASSWORD", "APPLE_TEAM_ID")
    elif sys.platform.startswith("linux"):
        require("GPG_PRIVATE_KEY")


if __name__ == "__main__":
    main()
