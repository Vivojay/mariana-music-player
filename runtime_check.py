"""Runtime prerequisite checks for Mariana Player.

The checks intentionally report optional multimedia capabilities without
preventing local-only operation from starting.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
SUPPORTED_PYTHON = (3, 12)


@dataclass(frozen=True)
class RuntimeReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    vlc_directory: Path | None

    @property
    def supported(self) -> bool:
        return not self.errors


def find_vlc_directory(configured_path: str | None = None) -> Path | None:
    candidates = []
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    if os.environ.get("VLC_HOME"):
        candidates.append(Path(os.environ["VLC_HOME"]).expanduser())
    candidates.extend(
        [
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "VideoLAN" / "VLC",
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "VideoLAN" / "VLC",
        ]
    )
    for candidate in candidates:
        if (candidate / "vlc.exe").is_file():
            return candidate.resolve()
    return None


def check_runtime(configured_vlc_path: str | None = None) -> RuntimeReport:
    errors: list[str] = []
    warnings: list[str] = []

    if sys.version_info[:2] != SUPPORTED_PYTHON:
        errors.append(
            "Mariana Player currently supports Python 3.12.x; "
            f"detected {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}."
        )
    if sys.platform != "win32":
        errors.append("Mariana Player currently supports Windows only.")
    if ctypes.sizeof(ctypes.c_void_p) * 8 != 64:
        errors.append("Mariana Player requires 64-bit Python and 64-bit VLC.")

    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            warnings.append(
                f"{executable} is not on PATH; downloads, metadata, and lyrics sampling may be unavailable."
            )

    vlc_directory = find_vlc_directory(configured_vlc_path)
    if vlc_directory is None:
        warnings.append(
            "VLC 3.x was not found. Install 64-bit VLC or set 'vlc path' in settings/settings.yml."
        )

    return RuntimeReport(tuple(errors), tuple(warnings), vlc_directory)


def format_runtime_report(report: RuntimeReport) -> list[str]:
    messages = [f"ERROR: {message}" for message in report.errors]
    messages.extend(f"WARNING: {message}" for message in report.warnings)
    return messages
