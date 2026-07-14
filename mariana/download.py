"""Bounded FFmpeg downloads for custom, non-DRM media URLs."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from .playback import CREATE_NO_WINDOW, find_executable

FORMATS = {
    "mp3": ["-vn", "-c:a", "libmp3lame", "-q:a", "2"],
    "flac": ["-vn", "-c:a", "flac"],
    "wav": ["-vn", "-c:a", "pcm_s16le"],
    "m4a": ["-vn", "-c:a", "aac", "-b:a", "256k"],
    "opus": ["-vn", "-c:a", "libopus", "-b:a", "160k"],
}

# These URLs identify a page on an extractor-backed service, not an audio file
# that FFmpeg can open directly.  yt-dlp resolves the page to its media stream
# before handing the downloaded audio to FFmpeg for conversion.
EXTRACTOR_HOSTS = (
    "soundcloud.com",
    "youtube.com",
    "youtu.be",
    "bandcamp.com",
    "vimeo.com",
)


class DownloadError(RuntimeError):
    pass


def _uses_extractor(url: str) -> bool:
    host = (urlparse(url).hostname or "").casefold()
    return any(host == service or host.endswith(f".{service}") for service in EXTRACTOR_HOSTS)


def _download_extractor_media(
    url: str,
    destination: Path,
    *,
    output_format: str,
    ffmpeg_bin: str | None,
) -> Path:
    """Download an extractor page URL into an isolated staging directory."""
    staging = destination.parent / f".{destination.stem}.extract-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": str(staging / "media.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": output_format}],
    }
    if ffmpeg_bin:
        options["ffmpeg_location"] = str(Path(ffmpeg_bin).expanduser())
    try:
        with YoutubeDL(cast(Any, options)) as downloader:
            downloader.extract_info(url, download=True)
        output = staging / f"media.{output_format}"
        if not output.is_file() or output.stat().st_size == 0:
            raise DownloadError("yt-dlp completed without producing a media file")
        temporary = destination.with_name(f".{destination.stem}.partial{destination.suffix}")
        temporary.unlink(missing_ok=True)
        output.replace(temporary)
        temporary.replace(destination)
        return destination
    except DownloadError:
        raise
    except Exception as error:
        raise DownloadError(f"Media-page download failed: {str(error).strip() or type(error).__name__}") from error
    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
    if _uses_extractor(url):
        return _download_extractor_media(
            url,
            destination,
            output_format=output_format,
            ffmpeg_bin=ffmpeg_bin,
        )
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
