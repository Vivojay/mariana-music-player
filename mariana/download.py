"""Bounded FFmpeg downloads for custom, non-DRM media URLs."""

from __future__ import annotations

from pathlib import Path
import subprocess
from urllib.parse import urlparse

from .playback import CREATE_NO_WINDOW, find_executable


FORMATS = {
    "mp3": ["-vn", "-c:a", "libmp3lame", "-q:a", "2"],
    "flac": ["-vn", "-c:a", "flac"],
    "wav": ["-vn", "-c:a", "pcm_s16le"],
    "m4a": ["-vn", "-c:a", "aac", "-b:a", "256k"],
    "opus": ["-vn", "-c:a", "libopus", "-b:a", "160k"],
}


class DownloadError(RuntimeError):
    pass


def download_media(
    url: str,
    destination: Path | str,
    *,
    output_format: str = "mp3",
    ffmpeg_bin: str | None = None,
    timeout: float = 1800,
) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DownloadError("A valid HTTP or HTTPS media URL is required")
    output_format = output_format.lower().lstrip(".")
    if output_format not in FORMATS:
        raise DownloadError(f"Unsupported output format: {output_format}; choose {', '.join(FORMATS)}")
    destination = Path(destination).expanduser()
    if destination.suffix.lower() != f".{output_format}":
        destination = destination.with_suffix(f".{output_format}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.stem}.partial{destination.suffix}")
    temporary.unlink(missing_ok=True)
    executable = find_executable("ffmpeg", ffmpeg_bin)
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-rw_timeout",
        "30000000",
        "-i",
        url,
        *FORMATS[output_format],
        str(temporary),
    ]
    try:
        subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            check=True,
            creationflags=CREATE_NO_WINDOW,
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise DownloadError("FFmpeg completed without producing a media file")
        temporary.replace(destination)
        return destination
    except subprocess.TimeoutExpired as error:
        temporary.unlink(missing_ok=True)
        raise DownloadError(f"Download exceeded the {timeout:g}-second limit") from error
    except (OSError, subprocess.CalledProcessError) as error:
        temporary.unlink(missing_ok=True)
        detail = getattr(error, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise DownloadError(f"FFmpeg download failed: {str(detail).strip() or error}") from error
