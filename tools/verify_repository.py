"""Fail when generated, private, obsolete, or oversized files are tracked."""

from __future__ import annotations

import subprocess
from pathlib import Path

MAX_TRACKED_BYTES = 5 * 1024 * 1024

FORBIDDEN_ROOTS = {
    ".audit-tmp",
    ".eggs",
    ".hypothesis",
    ".mypy_cache",
    ".nox",
    ".npm",
    ".pnpm-store",
    ".pyright",
    ".pytest_cache",
    ".ruff_cache",
    ".test-artifacts",
    ".tools",
    ".tox",
    ".venv",
    ".virtenv",
    ".vite",
    "build",
    "data",
    "dist",
    "dist-backend",
    "dist-electron",
    "htmlcov",
    "logs",
    "mutants",
    "node_modules",
    "playwright-report",
    "release",
    "temp",
    "test-results",
    "venv",
}
FORBIDDEN_PREFIXES = (".test-", "pytest-cache-files-")
FORBIDDEN_PARTS = {"__pycache__"}
FORBIDDEN_NAMES = {
    ".coverage",
    ".ds_store",
    ".env",
    "builder-debug.yml",
    "builder-effective-config.yaml",
    "coverage.json",
    "coverage.xml",
    "critical-coverage.json",
    "desktop.ini",
    "junit.xml",
    "live-junit.xml",
    "playback-coverage.json",
    "thumbs.db",
}
FORBIDDEN_SUFFIXES = {
    ".7z",
    ".appimage",
    ".bak",
    ".blockmap",
    ".db",
    ".dll",
    ".dmg",
    ".exe",
    ".gz",
    ".key",
    ".log",
    ".msi",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tmp",
    ".zip",
}
REMOVED_LEGACY_PATHS = {
    "beta/redditsessions.py",
    "beta/yt_urls.yml",
    "downgrade.txt",
    "help_future.md",
    "res/font-faces/fira_code/firacode-variablefont_wght.ttf",
    "res/font-faces/fira_code/readme.txt",
    "res/font-faces/fira_code/static/firacode-bold.ttf",
    "res/font-faces/fira_code/static/firacode-light.ttf",
    "res/font-faces/fira_code/static/firacode-regular.ttf",
    "res/font-faces/fira_code/static/firacode-semibold.ttf",
    "settings/settings.yml",
    "user/reddit_credentials.json",
}


def tracked_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [Path(value.decode("utf-8")) for value in result.stdout.split(b"\0") if value]


def ignored_tracked_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-ci", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [Path(value.decode("utf-8")) for value in result.stdout.split(b"\0") if value]


def inspect(root: Path, paths: list[Path], ignored: list[Path] | None = None) -> list[str]:
    failures: list[str] = []
    ignored_set = {path.as_posix().casefold() for path in (ignored or [])}
    for relative in paths:
        normalized = relative.as_posix()
        folded = normalized.casefold()
        absolute = root / relative
        if not absolute.is_file():
            continue
        parts = tuple(part.casefold() for part in relative.parts)
        first = parts[0] if parts else ""
        name = relative.name.casefold()
        suffix = relative.suffix.casefold()
        if folded in ignored_set:
            failures.append(f"{normalized}: tracked file is also ignored")
        if first in FORBIDDEN_ROOTS or first.startswith(FORBIDDEN_PREFIXES):
            failures.append(f"{normalized}: generated/runtime root must not be tracked")
        if FORBIDDEN_PARTS.intersection(parts):
            failures.append(f"{normalized}: generated cache directory must not be tracked")
        if name in FORBIDDEN_NAMES or suffix in FORBIDDEN_SUFFIXES:
            failures.append(f"{normalized}: generated, private, or binary artifact must not be tracked")
        if folded in REMOVED_LEGACY_PATHS:
            failures.append(f"{normalized}: retired legacy artifact must not be reintroduced")
        size = absolute.stat().st_size
        if size > MAX_TRACKED_BYTES:
            failures.append(f"{normalized}: {size} bytes exceeds the {MAX_TRACKED_BYTES}-byte tracked-file limit")
    return failures


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = tracked_paths(root)
    failures = inspect(root, paths, ignored_tracked_paths(root))
    if failures:
        raise SystemExit("Repository-hygiene check failed:\n- " + "\n- ".join(failures))
    print(f"Repository hygiene is valid across {len(paths)} tracked paths.")


if __name__ == "__main__":
    main()
