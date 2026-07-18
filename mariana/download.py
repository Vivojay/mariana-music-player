"""Bounded FFmpeg downloads for custom, non-DRM media URLs."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from .extractor_urls import has_dedicated_extractor
from .output_targets import BoundOutputTarget, OutputTargetError, bind_output_target
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


def _uses_extractor(url: str) -> bool:
    return has_dedicated_extractor(url)


def _download_extractor_media(
    url: str,
    target: BoundOutputTarget,
    *,
    output_format: str,
    ffmpeg_bin: str | None,
) -> Path:
    """Download an extractor page URL into an isolated staging directory."""
    destination = target.path
    staging = destination.parent / f".{destination.stem}.extract-{uuid.uuid4().hex}"
    temporary: Path | None = None
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
        temporary = destination.with_name(
            f".{destination.stem}.{uuid.uuid4().hex}.partial{destination.suffix}"
        )
        output.replace(temporary)
        return target.activate(temporary)
    except OutputTargetError as error:
        raise DownloadError(str(error)) from error
    except DownloadError:
        raise
    except Exception as error:
        raise DownloadError(f"Media-page download failed: {str(error).strip() or type(error).__name__}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)


def prepare_download_target(
    destination: Path | str,
    *,
    output_format: str = "mp3",
) -> BoundOutputTarget:
    """Normalize and bind a custom-download output before approval."""
    output_format = output_format.lower().lstrip(".")
    if output_format not in FORMATS:
        raise DownloadError(f"Unsupported output format: {output_format}; choose {', '.join(FORMATS)}")
    path = Path(destination).expanduser()
    if path.suffix.lower() != f".{output_format}":
        path = path.with_suffix(f".{output_format}")
    try:
        return bind_output_target(path)
    except OutputTargetError as error:
        raise DownloadError(str(error)) from error


def download_media(
    url: str,
    destination: Path | str,
    *,
    output_format: str = "mp3",
    ffmpeg_bin: str | None = None,
    timeout: float = 1800,
    output_target: BoundOutputTarget | None = None,
) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise DownloadError("A valid HTTP or HTTPS media URL is required")
    output_format = output_format.lower().lstrip(".")
    if output_format not in FORMATS:
        raise DownloadError(f"Unsupported output format: {output_format}; choose {', '.join(FORMATS)}")
    prepared = prepare_download_target(destination, output_format=output_format)
    if output_target is None:
        if prepared.existed:
            raise DownloadError("Download destination already exists; overwrite approval is required")
        output_target = prepared
    elif output_target.path != prepared.path:
        raise DownloadError("Download destination does not match the approved output")
    try:
        output_target.revalidate()
    except OutputTargetError as error:
        raise DownloadError(str(error)) from error
    destination = output_target.path
    if _uses_extractor(url):
        return _download_extractor_media(
            url,
            output_target,
            output_format=output_format,
            ffmpeg_bin=ffmpeg_bin,
        )
    temporary = destination.with_name(
        f".{destination.stem}.{uuid.uuid4().hex}.partial{destination.suffix}"
    )
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
        try:
            return output_target.activate(temporary)
        except OutputTargetError as error:
            raise DownloadError(str(error)) from error
    except subprocess.TimeoutExpired as error:
        temporary.unlink(missing_ok=True)
        raise DownloadError(f"Download exceeded the {timeout:g}-second limit") from error
    except (OSError, subprocess.CalledProcessError) as error:
        temporary.unlink(missing_ok=True)
        detail = getattr(error, "stderr", b"")
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        raise DownloadError(f"FFmpeg download failed: {str(detail).strip() or error}") from error
    finally:
        temporary.unlink(missing_ok=True)
