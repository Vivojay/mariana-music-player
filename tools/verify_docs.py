"""Verify local Markdown links and the documented top-level command surface."""

from __future__ import annotations

import re
from pathlib import Path

LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
REQUIRED_COMMAND_FAMILIES = {
    "broadcast",
    "download-ml",
    "library",
    "queue",
    "radio",
    "recommend",
    "replaygain",
    "sleep",
    "tools",
}


def markdown_files(root: Path) -> list[Path]:
    ignored = {"node_modules", "release", "dist", "dist-electron", "build", ".venv"}
    return [path for path in root.rglob("*.md") if not ignored.intersection(path.parts)]


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
    return failures


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    failures = verify(root)
    if failures:
        raise SystemExit("Documentation verification failed:\n- " + "\n- ".join(failures))
    print("Documentation links and command-family references are consistent.")


if __name__ == "__main__":
    main()
