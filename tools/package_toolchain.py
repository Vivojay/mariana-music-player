"""Validate and package native tools into Mariana's managed archive shape."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

TOOLCHAIN_VERSION = "0.7.0-tools.2"
TOOLS_DIR = Path(__file__).resolve().parent


def executable_name(name: str, key: str) -> str:
    return f"{name}.exe" if key.startswith("win32-") else name


def validate(path: Path, arguments: list[str]) -> None:
    subprocess.run([str(path), *arguments], capture_output=True, check=True, timeout=15)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", required=True)
    parser.add_argument("--ffmpeg-dir", type=Path, required=True)
    parser.add_argument("--fpcalc", type=Path, required=True)
    parser.add_argument("--deno", type=Path, required=True)
    parser.add_argument("--rsgain-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    staging = args.output / "staging" / "bin"
    shutil.rmtree(staging.parent, ignore_errors=True)
    staging.mkdir(parents=True)
    if not args.rsgain_dir.is_dir():
        raise SystemExit(f"Missing rsgain directory: {args.rsgain_dir}")
    shutil.copytree(args.rsgain_dir, staging, dirs_exist_ok=True)

    sources = {
        "ffmpeg": args.ffmpeg_dir / executable_name("ffmpeg", args.platform),
        "ffprobe": args.ffmpeg_dir / executable_name("ffprobe", args.platform),
        "ffplay": args.ffmpeg_dir / executable_name("ffplay", args.platform),
        "fpcalc": args.fpcalc,
        "deno": args.deno,
        "rsgain": staging / executable_name("rsgain", args.platform),
    }
    executables: dict[str, str] = {}
    for name, source in sources.items():
        if not source.is_file():
            raise SystemExit(f"Missing {name}: {source}")
        destination = staging / executable_name(name, args.platform)
        if source.resolve() != destination.resolve():
            shutil.copy2(source, destination)
        destination.chmod(0o755)
        validate(destination, ["--version"] if name in {"deno", "rsgain"} else ["-version"])
        executables[name] = destination.relative_to(staging.parent).as_posix()

    metadata = staging.parent / "metadata"
    metadata.mkdir()
    shutil.copy2(TOOLS_DIR / "toolchain-sources.json", metadata / "toolchain-sources.json")
    shutil.copy2(TOOLS_DIR / "TOOLCHAIN-NOTICES.md", metadata / "THIRD-PARTY-NOTICES.md")

    archive = args.output / f"mariana-tools-{TOOLCHAIN_VERSION}-{args.platform}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
        for item in staging.parent.rglob("*"):
            if item.is_file():
                package.write(item, item.relative_to(staging.parent).as_posix())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    entry = {
        "key": args.platform,
        "value": {
            "url": f"https://github.com/Vivojay/mariana-music-player/releases/download/{TOOLCHAIN_VERSION}/{archive.name}",
            "sha256": digest,
            "archive": "zip",
            "executables": executables,
        },
    }
    (args.output / f"entry-{args.platform}.json").write_text(json.dumps(entry, indent=2, sort_keys=True))
    print(archive)


if __name__ == "__main__":
    main()
