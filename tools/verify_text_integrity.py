"""Reject invalid UTF-8 and common double-decoding artifacts in tracked text."""

from __future__ import annotations

import subprocess
from pathlib import Path

TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".in",
    ".js",
    ".json",
    ".lib",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
MOJIBAKE_MARKERS = ("â€", "â†", "âŒ", "Ã—", "ðŸ", "\ufffd")


def tracked_text_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [
        root / Path(name.decode("utf-8"))
        for name in result.stdout.split(b"\0")
        if name and Path(name.decode("utf-8")).suffix.lower() in TEXT_SUFFIXES
    ]


def inspect(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        # A working-tree deletion is valid while a cleanup commit is being prepared.
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            failures.append(f"{path}: invalid UTF-8 at byte {error.start}")
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for marker in MOJIBAKE_MARKERS:
                if marker in line:
                    failures.append(f"{path}:{line_number}: contains mojibake marker {marker!r}")
    return failures


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures = inspect(tracked_text_files(root))
    if failures:
        raise SystemExit("Text-integrity check failed:\n- " + "\n- ".join(failures))
    print("Tracked text is valid UTF-8 and contains no known mojibake markers.")


if __name__ == "__main__":
    main()
