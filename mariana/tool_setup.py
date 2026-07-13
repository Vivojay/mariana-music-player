"""Discovery, validation, and first-run configuration for external media tools."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config_manager import load_user_settings, save_user_settings

from .paths import RuntimePaths, runtime_paths
from .toolchain import (
    ToolchainError,
    ToolchainManager,
    executable_from_location,
    find_javascript_runtime,
    find_tool_executable,
)

FFMPEG_TOOLS = ("ffmpeg", "ffprobe", "ffplay")
OPTIONAL_TOOLS = ("fpcalc", "rsgain")
ALL_TOOLS = FFMPEG_TOOLS + OPTIONAL_TOOLS
VERSION_ARGUMENTS = {
    "ffmpeg": ("-version",),
    "ffprobe": ("-version",),
    "ffplay": ("-version",),
    "fpcalc": ("-version",),
    "rsgain": ("--version",),
}


class ToolSetupError(RuntimeError):
    """Raised when required media tools cannot be configured safely."""


@dataclass(frozen=True, slots=True)
class MediaToolStatus:
    executables: dict[str, str | None]
    versions: dict[str, str | None]

    @property
    def missing_required(self) -> tuple[str, ...]:
        return tuple(name for name in FFMPEG_TOOLS if not self.executables.get(name))

    @property
    def missing_optional(self) -> tuple[str, ...]:
        return tuple(name for name in OPTIONAL_TOOLS if not self.executables.get(name))

    @property
    def complete(self) -> bool:
        return not self.missing_required and not self.missing_optional


def executable_version(name: str, executable: str | None) -> str | None:
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, *VERSION_ARGUMENTS[name]],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=True,
        )
    except (OSError, subprocess.SubprocessError, KeyError):
        return None
    output = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", result.stdout or result.stderr)
    return next((line.strip() for line in output.splitlines() if line.strip()), None)


def discover_media_tools(settings: dict[str, Any] | None = None) -> MediaToolStatus:
    settings = settings or {}
    configured = settings.get("media tools", settings)
    ffmpeg_location = configured.get("ffmpeg bin")
    locations = {
        "ffmpeg": ffmpeg_location,
        "ffprobe": ffmpeg_location,
        "ffplay": ffmpeg_location,
        "fpcalc": configured.get("fpcalc bin"),
        "rsgain": configured.get("rsgain bin"),
    }
    executables: dict[str, str | None] = {}
    versions: dict[str, str | None] = {}
    for name in ALL_TOOLS:
        candidate = find_tool_executable(name, locations[name])
        version = executable_version(name, candidate)
        executables[name] = candidate if version else None
        versions[name] = version
    return MediaToolStatus(executables, versions)


def _atomic_save_settings(settings: dict[str, Any], paths: RuntimePaths) -> None:
    save_user_settings(settings, paths.settings)


def persist_media_tools(
    status: MediaToolStatus,
    settings: dict[str, Any] | None = None,
    *,
    paths: RuntimePaths | None = None,
) -> dict[str, Any]:
    paths = paths or runtime_paths()
    settings = settings or load_user_settings()
    media_tools = settings.setdefault("media tools", {})
    ffmpeg = status.executables.get("ffmpeg")
    fpcalc = status.executables.get("fpcalc")
    rsgain = status.executables.get("rsgain")
    if ffmpeg:
        media_tools["ffmpeg bin"] = str(Path(ffmpeg).parent)
    if fpcalc:
        media_tools["fpcalc bin"] = str(Path(fpcalc).parent)
    if rsgain:
        media_tools["rsgain bin"] = str(Path(rsgain).parent)
    if javascript := find_javascript_runtime(media_tools.get("javascript bin")):
        media_tools["javascript bin"] = str(Path(javascript[1]).parent)
        os.environ["MARIANA_JAVASCRIPT_RUNTIME"] = javascript[1]
    _atomic_save_settings(settings, paths)
    return settings


def _print_status(status: MediaToolStatus) -> None:
    print("\nMedia tool check:")
    for name in ALL_TOOLS:
        value = status.executables.get(name)
        print(f"  {name:<7} {'OK  ' + value if value else 'NOT FOUND'}")
    javascript = find_javascript_runtime()
    print(f"  {'JS':<7} {'OK  ' + javascript[1] if javascript else 'NOT FOUND'}")


def _manual_settings(settings: dict[str, Any]) -> dict[str, Any]:
    updated = dict(settings)
    media_tools = dict(updated.get("media tools", {}))
    updated["media tools"] = media_tools

    while True:
        value = input("FFmpeg path (ffmpeg executable or its containing/install directory): ").strip()
        found = {name: executable_from_location(name, value) for name in FFMPEG_TOOLS}
        ffmpeg = found["ffmpeg"]
        if ffmpeg and all(found.values()) and all(
            executable_version(name, found[name]) for name in FFMPEG_TOOLS
        ):
            media_tools["ffmpeg bin"] = str(Path(ffmpeg).parent)
            break
        print("That location must contain working ffmpeg, ffprobe, and ffplay executables.")

    for name, setting in (("fpcalc", "fpcalc bin"), ("rsgain", "rsgain bin")):
        while True:
            value = input(f"{name} path ({name} executable or its containing directory): ").strip()
            found = executable_from_location(name, value)
            if found and executable_version(name, found):
                media_tools[setting] = str(Path(found).parent)
                break
            print(f"That location does not contain a working {name} executable.")
    if not find_javascript_runtime(media_tools.get("javascript bin")):
        while True:
            value = input("Deno/Node path (executable or its containing directory): ").strip()
            found = executable_from_location("deno", value) or executable_from_location("node", value)
            if found:
                media_tools["javascript bin"] = str(Path(found).parent)
                break
            print("That location does not contain a working Deno or Node executable.")
    return updated


def setup_media_tools(
    settings: dict[str, Any] | None = None,
    *,
    paths: RuntimePaths | None = None,
    manager: ToolchainManager | None = None,
    interactive: bool = True,
) -> MediaToolStatus:
    """Discover first, then offer verified auto-install as the default choice."""
    paths = paths or runtime_paths()
    settings = settings or load_user_settings()
    status = discover_media_tools(settings)
    javascript = find_javascript_runtime(settings.get("media tools", {}).get("javascript bin"))
    if status.complete and javascript:
        persist_media_tools(status, settings, paths=paths)
        return status
    if not interactive:
        return status

    _print_status(status)
    print("\nMariana needs the missing tools for playback, lyrics identification, loudness analysis, and YouTube.")
    print("  [1] Automatically download verified recommended tools (default)")
    print("  [2] Enter installed tool paths manually")
    if not status.missing_required:
        print("  [3] Continue without optional identification/loudness tools")
    valid = {"", "1", "auto", "automatic", "2", "manual"}
    if not status.missing_required:
        valid.update({"3", "continue", "skip"})
    choice = input("Select an option [1]: ").strip().casefold()
    while choice not in valid:
        choice = input("Please select 1 or 2: ").strip().casefold()

    if choice in {"3", "continue", "skip"}:
        persist_media_tools(status, settings, paths=paths)
        return status
    if choice in {"2", "manual"}:
        settings = _manual_settings(settings)
        status = discover_media_tools(settings)
        if not status.complete or not find_javascript_runtime(
            settings.get("media tools", {}).get("javascript bin")
        ):
            raise ToolSetupError("One or more configured media tools failed validation")
        persist_media_tools(status, settings, paths=paths)
        return status

    manager = manager or ToolchainManager(paths)
    try:
        manager.install_recommended(progress=print)
    except ToolchainError as error:
        raise ToolSetupError(
            f"Automatic tool setup failed: {error}. Resume setup to retry or choose manual paths."
        ) from error
    status = discover_media_tools(settings)
    if not status.complete or not find_javascript_runtime():
        raise ToolSetupError("The verified tool installation completed but one or more executables failed validation")
    persist_media_tools(status, settings, paths=paths)
    return status


def main() -> int:
    try:
        status = setup_media_tools()
    except (ToolSetupError, ToolchainError) as error:
        print(f"Media tool setup failed: {error}")
        return 1
    _print_status(status)
    return 0 if not status.missing_required else 1


if __name__ == "__main__":
    raise SystemExit(main())
