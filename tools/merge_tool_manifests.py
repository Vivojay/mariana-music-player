from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    artifacts = {}
    for source in args.directory.rglob("entry-*.json"):
        entry = json.loads(source.read_text(encoding="utf-8"))
        artifacts[entry["key"]] = entry["value"]
    required = {"win32-x64", "darwin-x64", "darwin-arm64", "linux-x64"}
    if missing := required - set(artifacts):
        raise SystemExit(f"Missing toolchain entries: {', '.join(sorted(missing))}")
    args.output.write_text(json.dumps({
        "schema": 1, "toolchain": "0.7.0-tools.1", "artifacts": artifacts,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
