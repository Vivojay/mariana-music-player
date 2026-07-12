"""Small platform adapters used by both the CLI and desktop host."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


class PlatformCapabilityError(RuntimeError):
    pass


def reveal_path(path: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(target)])
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            raise PlatformCapabilityError("No Linux file-manager opener (xdg-open) is available")
        subprocess.Popen([opener, str(target if target.is_dir() else target.parent)])


def open_path(path: str | Path) -> None:
    target = Path(path).expanduser().resolve()
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            raise PlatformCapabilityError("No Linux opener (xdg-open) is available")
        subprocess.Popen([opener, str(target)])


def _run_text(arguments: list[str]) -> str:
    try:
        return subprocess.run(arguments, capture_output=True, check=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        raise PlatformCapabilityError(str(error)) from error


def get_master_volume() -> int:
    if sys.platform == "win32":
        from pycaw.pycaw import AudioUtilities

        return int(round(AudioUtilities.GetSpeakers().EndpointVolume.GetMasterVolumeLevelScalar() * 100))
    if sys.platform == "darwin":
        return int(_run_text(["osascript", "-e", "output volume of (get volume settings)"]))
    if wpctl := shutil.which("wpctl"):
        output = _run_text([wpctl, "get-volume", "@DEFAULT_AUDIO_SINK@"]).split()
        return round(float(next(value for value in output if value.replace(".", "", 1).isdigit())) * 100)
    if pactl := shutil.which("pactl"):
        output = _run_text([pactl, "get-sink-volume", "@DEFAULT_SINK@"])
        return int(output.split("%", 1)[0].rsplit(None, 1)[-1])
    raise PlatformCapabilityError("Master volume requires wpctl or pactl on Linux")


def set_master_volume(value: float) -> None:
    percent = max(0, min(100, round(float(value))))
    if sys.platform == "win32":
        from pycaw.pycaw import AudioUtilities

        AudioUtilities.GetSpeakers().EndpointVolume.SetMasterVolumeLevelScalar(percent / 100, None)
        return
    if sys.platform == "darwin":
        _run_text(["osascript", "-e", f"set volume output volume {percent}"])
        return
    if wpctl := shutil.which("wpctl"):
        _run_text([wpctl, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"])
        return
    if pactl := shutil.which("pactl"):
        _run_text([pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])
        return
    raise PlatformCapabilityError("Master volume requires wpctl or pactl on Linux")
