"""Fail builds when Python and Electron version metadata diverge."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mariana.version import __version__  # noqa: E402


def main() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    canonical = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    if len({package, canonical, __version__}) != 1:
        raise SystemExit(f"Version mismatch: package={package}, version.json={canonical}, python={__version__}")
    print(canonical)


if __name__ == "__main__":
    main()
