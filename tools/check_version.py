"""Fail builds when Python and Electron version metadata diverge."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mariana.integrations.discord_presence import is_valid_discord_application_id  # noqa: E402
from mariana.version import __version__  # noqa: E402


def configured_discord_application_id(root: Path = ROOT) -> str:
    """Return the public Discord application ID shipped in system settings."""

    with (root / "settings" / "system.toml").open("rb") as stream:
        settings = tomllib.load(stream)
    return str(settings.get("system_settings", {}).get("discord_application_id") or "").strip()


def validate_discord_application(root: Path = ROOT) -> str:
    """Fail release checks when the public Discord application ID is unusable."""

    application_id = configured_discord_application_id(root)
    if not is_valid_discord_application_id(application_id):
        raise SystemExit("Discord application ID is missing, malformed, or a placeholder")
    return application_id


def main() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    canonical = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]
    if len({package, canonical, __version__}) != 1:
        raise SystemExit(f"Version mismatch: package={package}, version.json={canonical}, python={__version__}")
    validate_discord_application()
    print(canonical)


if __name__ == "__main__":
    main()
