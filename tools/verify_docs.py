"""Verify local Markdown links and the documented top-level command surface."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mariana.commands import ALIAS_COMPATIBILITY  # noqa: E402

LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
REQUIRED_COMMAND_FAMILIES = {
    "broadcast",
    "download-ml",
    "discord",
    "library",
    "queue",
    "radio",
    "recommend",
    "replaygain",
    "setup",
    "sleep",
    "tools",
    "youtube",
}


def markdown_files(root: Path) -> list[Path]:
    ignored = {"node_modules", "release", "dist", "dist-electron", "build", "temp", ".venv"}
    return [
        path
        for path in root.rglob("*.md")
        if not ignored.intersection(path.relative_to(root).parts)
        and not any(
            part.startswith((".test-", "pytest-cache-files-"))
            for part in path.relative_to(root).parts
        )
    ]


def verify(root: Path) -> list[str]:
    failures: list[str] = []
    for path in markdown_files(root):
        text = path.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            target = target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith(("mailto:", "#")):
                continue
            if not (path.parent / target).resolve().exists():
                failures.append(f"{path.relative_to(root)}: broken local link {target!r}")
    readme = (root / "README.md").read_text(encoding="utf-8").casefold()
    help_text = (root / "help.md").read_text(encoding="utf-8").casefold()
    for command in sorted(REQUIRED_COMMAND_FAMILIES):
        if command not in readme or command not in help_text:
            failures.append(f"command family {command!r} is missing from README.md or help.md")
    for entry in ALIAS_COMPATIBILITY:
        for alias in entry.aliases:
            if f"`{alias}`" not in help_text:
                failures.append(f"registered compatibility alias {alias!r} is missing from help.md")
    return failures


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures = verify(root)
    if failures:
        raise SystemExit("Documentation verification failed:\n- " + "\n- ".join(failures))
    print("Documentation links and command-family references are consistent.")


if __name__ == "__main__":
    main()
