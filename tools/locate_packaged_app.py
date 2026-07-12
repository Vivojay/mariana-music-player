"""Locate an unpacked Electron executable and expose it to GitHub Actions."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def candidates(root: Path) -> list[Path]:
    if sys.platform == "win32":
        return list(root.rglob("Mariana.exe"))
    if sys.platform == "darwin":
        return list(root.rglob("Mariana.app/Contents/MacOS/Mariana"))
    return [path for path in root.rglob("mariana") if path.is_file() and os.access(path, os.X_OK)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", type=Path, default=Path("release"))
    parser.add_argument("--github-env", action="store_true")
    arguments = parser.parse_args()
    matches = candidates(arguments.root)
    if not matches:
        raise SystemExit(f"No unpacked Mariana application was found under {arguments.root}")
    executable = min(matches, key=lambda path: len(path.parts)).resolve()
    if arguments.github_env:
        environment = os.getenv("GITHUB_ENV")
        if not environment:
            raise SystemExit("GITHUB_ENV is not set")
        with Path(environment).open("a", encoding="utf-8") as output:
            output.write(f"MARIANA_PACKAGED_EXE={executable}\n")
    print(executable)


if __name__ == "__main__":
    main()
