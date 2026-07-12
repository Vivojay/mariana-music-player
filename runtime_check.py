"""Runtime prerequisite checks for Mariana's FFmpeg media platform."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
from dataclasses import dataclass


SUPPORTED_PYTHON = (3, 12)
SUPPORTED_PLATFORMS = {"win32": "Windows", "darwin": "macOS", "linux": "Linux"}


@dataclass(frozen=True)
class RuntimeReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    executables: dict[str, str | None]

    @property
    def supported(self) -> bool:
        return not self.errors


def _configured_executable(name: str, directory: str | None = None) -> str | None:
    if directory:
        candidate = Path(directory).expanduser()
        if candidate.is_dir():
            candidate /= f"{name}.exe" if os.name == "nt" else name
        if candidate.is_file():
            return str(candidate.resolve())
    return shutil.which(name)


def inspect_ffmpeg(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "-version"], capture_output=True, text=True, timeout=5, check=True
        )
        return (result.stdout.splitlines() or [None])[0]
    except (OSError, subprocess.SubprocessError):
        return None


def has_audio_output() -> bool:
    try:
        import sounddevice

        return any(device.get("max_output_channels", 0) > 0 for device in sounddevice.query_devices())
    except Exception:
        return False


def check_runtime(
    configured_ffmpeg_path: str | None = None,
    configured_fpcalc_path: str | None = None,
) -> RuntimeReport:
    errors: list[str] = []
    warnings: list[str] = []
    if sys.version_info[:2] != SUPPORTED_PYTHON:
        errors.append(
            "Mariana Player currently supports Python 3.12.x; "
            f"detected {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}."
        )
    if sys.platform not in SUPPORTED_PLATFORMS:
        errors.append(f"Mariana Player does not support this operating system ({sys.platform}).")
    if ctypes.sizeof(ctypes.c_void_p) * 8 != 64:
        errors.append("Mariana Player requires 64-bit Python.")

    executables = {
        name: _configured_executable(name, configured_ffmpeg_path)
        for name in ("ffmpeg", "ffprobe", "ffplay")
    }
    from mariana.paths import runtime_paths

    local_fpcalc = runtime_paths().tools
    fpcalc_name = "fpcalc.exe" if os.name == "nt" else "fpcalc"
    local_matches = list(local_fpcalc.rglob(fpcalc_name)) if local_fpcalc.exists() else []
    executables["fpcalc"] = _configured_executable("fpcalc", configured_fpcalc_path) or (
        str(local_matches[0]) if local_matches else None
    )
    for executable in ("ffmpeg", "ffprobe"):
        if not executables[executable]:
            errors.append(f"{executable} is required for playback and media inspection.")
    if not executables["ffplay"]:
        warnings.append("ffplay is unavailable; diagnostic/video fallback commands are disabled.")
    if not executables["fpcalc"]:
        warnings.append("Chromaprint fpcalc 1.6.0 is unavailable; install or repair the managed media tools.")
    if executables["ffmpeg"] and not inspect_ffmpeg(executables["ffmpeg"]):
        errors.append("The configured FFmpeg executable could not be started.")
    if not any(shutil.which(executable) for executable in ("deno", "node", "qjs")):
        warnings.append("No JavaScript runtime was found; install Node 22+ for reliable YouTube extraction.")
    if not has_audio_output():
        warnings.append("No usable output device was detected; playback will remain unavailable until one appears.")
    return RuntimeReport(tuple(errors), tuple(warnings), executables)


def format_runtime_report(report: RuntimeReport) -> list[str]:
    messages = [f"ERROR: {message}" for message in report.errors]
    messages.extend(f"WARNING: {message}" for message in report.warnings)
    return messages
