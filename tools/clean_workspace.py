"""Remove reproducible local outputs while preserving source and user media."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
from pathlib import Path

DEFAULT_DIRECTORIES = {
    ".audit-tmp",
    ".hypothesis",
    ".mypy_cache",
    ".pyright",
    ".pytest_cache",
    ".ruff_cache",
    ".test-artifacts",
    "__pycache__",
    "build",
    "data",
    "dist",
    "dist-backend",
    "dist-electron",
    "htmlcov",
    "logs",
    "mutants",
    "playwright-report",
    "temp",
    "test-results",
}
DEFAULT_FILES = {
    ".chromaprint-download.zip",
    ".coverage",
    "coverage.json",
    "coverage.xml",
    "critical-coverage.json",
    "junit.xml",
    "live-junit.xml",
    "playback-coverage.json",
    "res/style.css",
}
SOURCE_DIRECTORIES = ("beta", "lyrics_provider", "mariana", "recommendation_engine", "tests", "tools")
STALE_RELEASE_ENTRIES = (
    "release/.icon-ico",
    "release/builder-debug.yml",
    "release/builder-effective-config.yaml",
    "release/published",
    "release/verification",
)


def _make_writable(function, path, _error) -> None:
    os.chmod(path, stat.S_IWRITE)
    function(path)


def candidates(root: Path, *, dependencies: bool = False, release: bool = False) -> list[Path]:
    paths: set[Path] = set()
    for child in root.iterdir():
        if child.name in DEFAULT_DIRECTORIES or child.name.startswith((".test-", "pytest-cache-files-")):
            paths.add(child)
        if child.name in DEFAULT_FILES:
            paths.add(child)
    for relative in DEFAULT_FILES | set(STALE_RELEASE_ENTRIES):
        path = root / relative
        if path.exists():
            paths.add(path)
    paths.update((root / "user").glob("*.bak"))
    paths.update((root / "user").glob("*.invalid-*.bak"))
    for directory in SOURCE_DIRECTORIES:
        source = root / directory
        if source.is_dir():
            paths.update(source.rglob("__pycache__"))
    if dependencies:
        paths.update(root / name for name in (".venv", ".virtenv", "venv", "node_modules", ".tools"))
    if release:
        paths.add(root / "release")
    existing = [path for path in paths if path.exists()]
    return sorted(existing, key=lambda path: (len(path.parts), path.as_posix()), reverse=True)


def clean(paths: list[Path], *, apply: bool) -> tuple[int, int]:
    removed = 0
    reclaimed = 0
    for path in paths:
        size = path.stat().st_size if path.is_file() else sum(
            item.stat().st_size for item in path.rglob("*") if item.is_file()
        )
        print(f"{'remove' if apply else 'would remove'} {path} ({size} bytes)")
        if not apply:
            continue
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path, onexc=_make_writable)
        else:
            path.unlink(missing_ok=True)
        removed += 1
        reclaimed += size
    return removed, reclaimed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="perform deletion; the default is a dry run")
    parser.add_argument("--dependencies", action="store_true", help="also remove environments, packages, and tools")
    parser.add_argument("--release", action="store_true", help="also remove the latest packaged application")
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = candidates(root, dependencies=arguments.dependencies, release=arguments.release)
    removed, reclaimed = clean(paths, apply=arguments.apply)
    if arguments.apply:
        print(f"Removed {removed} paths and reclaimed {reclaimed / (1024 * 1024):.1f} MiB.")
    else:
        print(f"Dry run: {len(paths)} paths; rerun with --apply to remove them.")


if __name__ == "__main__":
    main()
