"""Current-media desktop intents over the existing download engines."""

from __future__ import annotations

import math
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mariana.download import DownloadError, download_media, prepare_download_target
from mariana.download_jobs import DownloadJobError, DownloadManager, sanitize_component
from mariana.models import MediaRef, MediaSource


def progress_numbers(payload: dict[str, Any]) -> dict[str, float | None]:
    def bounded(value: object) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and 0 <= value <= 1e15 and math.isfinite(value):
            return float(value)
        return None
    return {
        "downloaded_bytes": bounded(payload.get("downloaded_bytes")),
        "total_bytes": bounded(payload.get("total_bytes") or payload.get("total_bytes_estimate")),
        "speed_bytes_per_second": bounded(payload.get("speed")),
        "eta_seconds": bounded(payload.get("eta")),
    }


class DesktopDownloads:
    """One bounded custom-media worker; YouTube uses persistent sequential jobs.

    No renderer-supplied URL, output path, or command is accepted. Custom jobs are
    session-only; existing YouTube jobs retain their normal persistence/resume.
    """

    def __init__(self, manager: DownloadManager, destination: Callable[[], Path],
                 *, ffmpeg_bin: str | None = None, download: Callable[..., Path] = download_media) -> None:
        self.manager = manager
        self.destination = destination
        self.ffmpeg_bin = ffmpeg_bin
        self.download = download
        self._lock = threading.RLock()
        self._custom: dict[str, dict[str, Any]] = {}
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None

    def start(self, media: MediaRef, output_format: str) -> None:
        if output_format not in {"mp3", "mp4"}:
            raise DownloadError("Choose MP3 audio or MP4 video")
        if media.source not in {MediaSource.YOUTUBE, MediaSource.URL, MediaSource.PODCAST}:
            raise DownloadError("Only finite online media can be downloaded; local files are already on disk")
        if media.capabilities.live or not media.capabilities.finite or not media.capabilities.downloadable:
            raise DownloadError("The active media is not downloadable as a finite item")
        with self._lock:
            if self._cancel.is_set():
                raise DownloadError("Downloads are shutting down")
            if any(row["media_id"] == media.stable_id and row["format"] == output_format
                   and row["state"] in {"queued", "running"}
                   for row in self.status()):
                raise DownloadError("This media already has an active download")
            if media.source == MediaSource.YOUTUBE:
                self.manager.create([media], destination=self.destination(), output_format=output_format,
                                    metadata=[{"title": media.title, "artist": media.artist}])
                return
            if self._worker and self._worker.is_alive():
                raise DownloadError("Another custom-media download is running")
            root = self.destination().expanduser()
            root.mkdir(parents=True, exist_ok=True)
            name = sanitize_component(media.title or "Online media")
            target = prepare_download_target(root / f"{name}.{output_format}", output_format=output_format)
            if target.existed:
                raise DownloadError("Download already exists; use the existing command for explicit overwrite approval")
            job_id = uuid.uuid4().hex
            self._custom = dict(list(self._custom.items())[-19:])
            self._custom[job_id] = {"job_id": job_id, "media_id": media.stable_id,
                                   "state": "running", "format": output_format, "progress": 0.0,
                                   "error": None, **progress_numbers({})}
            deadline = time.monotonic() + 1800

            def progress(payload: dict[str, Any]) -> None:
                if self._cancel.is_set() or time.monotonic() >= deadline:
                    raise DownloadError("Download interrupted")
                numbers = progress_numbers(payload)
                total = numbers["total_bytes"]
                percent = min(1.0, (numbers["downloaded_bytes"] or 0) / total) if total else None
                with self._lock:
                    self._custom[job_id].update(numbers, progress=percent)

            def work() -> None:
                try:
                    self.download(media.original_uri, target.path, output_format=output_format,
                                  ffmpeg_bin=self.ffmpeg_bin, output_target=target, progress_hook=progress)
                    with self._lock:
                        self._custom[job_id].update(state="completed", progress=1.0, speed_bytes_per_second=None)
                except Exception:
                    with self._lock:
                        self._custom[job_id].update(state="failed", speed_bytes_per_second=None,
                                                   error="Download unavailable or interrupted; no completed file was activated")

            self._worker = threading.Thread(target=work, name="mariana-custom-download", daemon=True)
            self._worker.start()

    def start_and_snapshot(self, media: MediaRef, output_format: str) -> list[dict[str, Any]]:
        self.start(media, output_format)
        return self.status()

    def status(self) -> list[dict[str, Any]]:
        rows = []
        for job in self.manager.status():
            for item in job.get("items", []):
                try:
                    media = MediaRef.from_dict(item["media"])
                    transfer = item.get("transfer") or {}
                    rows.append({"job_id": job["job_id"], "media_id": media.stable_id,
                                 "state": item["state"], "format": item["metadata"].get("download_format", "mp3"),
                                 "progress": item["progress"],
                                 "error": "Download failed; inspect download status" if item.get("error") else None,
                                 **{key: transfer.get(key) for key in progress_numbers({})}})
                except (KeyError, TypeError, ValueError, DownloadJobError):
                    continue
        with self._lock:
            rows += [dict(row) for row in self._custom.values()]
        return rows[-20:]

    def close(self) -> None:
        self._cancel.set()
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout=3)
