"""Persistent, sequential, resumable YouTube audio download jobs."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL

from beta.youtube_media import integration_options

from .database import MarianaDatabase
from .models import DownloadItem, DownloadJob, DownloadState, MediaRef, MediaSource, canonical_uri
from .sources import sanitized_resolver_data

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class DownloadJobError(RuntimeError):
    pass


class DownloadInterrupted(RuntimeError):
    pass


class Downloader(Protocol):
    def __enter__(self) -> Downloader: ...

    def __exit__(self, *_args: Any) -> bool | None: ...

    def extract_info(self, url: str, *, download: bool) -> dict[str, Any]: ...


def sanitize_component(value: str, *, fallback: str = "Unknown") -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", normalized)
    normalized = re.sub(r"\s+", " ", normalized).rstrip(" .")
    if not normalized:
        normalized = fallback
    if normalized.upper() in WINDOWS_RESERVED_NAMES:
        normalized = f"_{normalized}"
    return normalized[:180].rstrip(" .") or fallback


def canonical_youtube_url(value: str) -> tuple[str, str]:
    canonical = canonical_uri(MediaSource.YOUTUBE, value)
    parsed = urlparse(canonical)
    host = (parsed.hostname or "").casefold()
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        video_id = (parse_qs(parsed.query).get("v") or [""])[0]
    elif host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    else:
        video_id = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,20}", video_id):
        raise DownloadJobError("A canonical YouTube video URL is required")
    return f"https://www.youtube.com/watch?v={video_id}", video_id


class DownloadManager:
    def __init__(
        self,
        database: MarianaDatabase,
        *,
        ffmpeg_bin: str | None = None,
        browser_profile: str | None = None,
        on_update: Callable[[dict[str, Any]], None] | None = None,
        downloader_factory: Callable[[dict[str, Any]], Downloader] | None = None,
        autostart: bool = True,
    ) -> None:
        self.database = database
        self.ffmpeg_bin = ffmpeg_bin
        self.browser_profile = browser_profile
        self.on_update = on_update
        self.downloader_factory = downloader_factory or cast(Any, YoutubeDL)
        self._closing = threading.Event()
        self._wake = threading.Event()
        self._active_job: str | None = None
        self._last_progress: dict[int, tuple[float, float]] = {}
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE download_jobs SET state='queued',current_position=NULL,updated_at=? "
                "WHERE state='running'",
                (time.time(),),
            )
            connection.execute(
                "UPDATE download_items SET state='queued',updated_at=? WHERE state='running'",
                (time.time(),),
            )
        self._thread = threading.Thread(
            target=self._worker,
            name="mariana-download-worker",
            daemon=True,
        )
        if autostart:
            self._thread.start()

    @staticmethod
    def _safe_media(media: MediaRef) -> tuple[MediaRef, str, str]:
        if media.source != MediaSource.YOUTUBE:
            raise DownloadJobError("YouTube audio downloads require a YouTube media item")
        canonical, video_id = canonical_youtube_url(media.original_uri)
        payload = media.to_dict()
        payload["original_uri"] = canonical
        payload["resolver_data"] = sanitized_resolver_data(media.resolver_data)
        payload["resolver_data"]["youtube"] = True
        payload["resolver_data"]["video_id"] = video_id
        return MediaRef.from_dict(payload), canonical, video_id

    def create(
        self,
        media_items: list[MediaRef],
        *,
        kind: str = "track",
        quality: str = "best",
        destination: Path | str,
        album_id: str | None = None,
        metadata: list[dict[str, Any]] | None = None,
        missing_only: bool = False,
    ) -> DownloadJob:
        if kind not in {"track", "album"}:
            raise DownloadJobError("Download job kind must be track or album")
        if quality not in {"best", "worst"}:
            raise DownloadJobError("Download quality must be best or worst")
        if not media_items:
            raise DownloadJobError("The download job contains no media")
        if metadata is not None and len(metadata) != len(media_items):
            raise DownloadJobError("Download metadata does not align with media items")
        destination_path = Path(destination).expanduser().resolve()
        job_id = uuid.uuid4().hex
        items = []
        for position, media in enumerate(media_items, 1):
            safe_media, canonical, video_id = self._safe_media(media)
            item_metadata = dict(metadata[position - 1] if metadata else {})
            item_metadata["video_id"] = video_id
            expected = self.expected_output(destination_path, safe_media, item_metadata)
            if missing_only and expected.is_file():
                continue
            items.append((position, safe_media, canonical, item_metadata, expected))
        if not items:
            raise DownloadJobError("All selected downloads already exist")
        now = time.time()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO download_jobs(job_id,kind,state,quality,destination,album_id,total_items,"
                "created_at,updated_at) VALUES(?,?,'queued',?,?,?,?,?,?)",
                (
                    job_id,
                    kind,
                    quality,
                    str(destination_path),
                    album_id,
                    len(items),
                    now,
                    now,
                ),
            )
            for item_position, media, canonical, item_metadata, expected in items:
                connection.execute(
                    "INSERT INTO download_items(job_id,position,canonical_url,media_json,state,output_path,"
                    "metadata_json,updated_at) VALUES(?,?,?,?,'queued',?,?,?)",
                    (
                        job_id,
                        item_position,
                        canonical,
                        json.dumps(media.to_dict(), ensure_ascii=False, sort_keys=True),
                        str(expected),
                        json.dumps(item_metadata, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
        self._wake.set()
        self._emit(job_id)
        return self.job(job_id)

    @staticmethod
    def expected_output(destination: Path, media: MediaRef, metadata: dict[str, Any]) -> Path:
        video_id = sanitize_component(str(metadata.get("video_id") or media.resolver_data.get("video_id") or "video"))
        title = sanitize_component(str(metadata.get("title") or media.title or "YouTube audio"))
        artist = sanitize_component(str(metadata.get("artist") or media.artist or "Unknown Artist"))
        album = metadata.get("album")
        album_artist = metadata.get("album_artist") or artist
        if album:
            disc = max(1, int(metadata.get("disc_number") or 1))
            track = max(1, int(metadata.get("track_number") or metadata.get("position") or 1))
            filename = f"{disc:02d}-{track:02d} {artist} - {title} [{video_id}].mp3"
            return (
                destination
                / sanitize_component(str(album_artist))
                / sanitize_component(str(album))
                / filename
            )
        return destination / f"{artist} - {title} [{video_id}].mp3"

    @staticmethod
    def _job(row) -> DownloadJob:
        return DownloadJob(
            job_id=str(row["job_id"]),
            kind=str(row["kind"]),
            state=DownloadState(row["state"]),
            quality=str(row["quality"]),
            destination=str(row["destination"]),
            album_id=row["album_id"],
            total_items=int(row["total_items"]),
            completed_items=int(row["completed_items"]),
            current_position=row["current_position"],
            error=row["error"],
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )

    @staticmethod
    def _item(row) -> DownloadItem:
        return DownloadItem(
            item_id=int(row["item_id"]),
            job_id=str(row["job_id"]),
            position=int(row["position"]),
            media=MediaRef.from_dict(json.loads(row["media_json"])),
            state=DownloadState(row["state"]),
            progress=float(row["progress"]),
            output_path=row["output_path"],
            error=row["error"],
            attempts=int(row["attempts"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def job(self, job_id: str) -> DownloadJob:
        row = self.database.fetchone("SELECT * FROM download_jobs WHERE job_id=?", (job_id,))
        if not row:
            raise DownloadJobError(f"Unknown download job: {job_id}")
        return self._job(row)

    def items(self, job_id: str) -> list[DownloadItem]:
        self.job(job_id)
        return [
            self._item(row)
            for row in self.database.fetchall(
                "SELECT * FROM download_items WHERE job_id=? ORDER BY position", (job_id,)
            )
        ]

    def status(self, job_id: str | None = None) -> list[dict[str, Any]]:
        if job_id:
            jobs = [self.job(job_id)]
        else:
            jobs = [
                self._job(row)
                for row in self.database.fetchall(
                    "SELECT * FROM download_jobs ORDER BY created_at DESC LIMIT 20"
                )
            ]
        return [
            self._status_payload(job)
            for job in jobs
        ]

    def _status_payload(self, job: DownloadJob) -> dict[str, Any]:
        payload = asdict(job)
        payload["state"] = job.state.value
        payload["items"] = []
        for item in self.items(job.job_id):
            item_payload = asdict(item)
            item_payload["state"] = item.state.value
            item_payload["media"] = item.media.to_dict()
            payload["items"].append(item_payload)
        return payload

    def pause(self, job_id: str) -> DownloadJob:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE download_jobs SET state='paused',updated_at=? "
                "WHERE job_id=? AND state IN ('queued','running','failed')",
                (time.time(), job_id),
            )
            if not cursor.rowcount:
                current = self.job(job_id)
                if current.state != DownloadState.PAUSED:
                    raise DownloadJobError(f"Download job cannot be paused from {current.state.value}")
        self._wake.set()
        self._emit(job_id)
        return self.job(job_id)

    def resume(self, job_id: str) -> DownloadJob:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE download_jobs SET state='queued',error=NULL,updated_at=? "
                "WHERE job_id=? AND state IN ('paused','failed')",
                (time.time(), job_id),
            )
            if not cursor.rowcount:
                current = self.job(job_id)
                if current.state != DownloadState.QUEUED:
                    raise DownloadJobError(f"Download job cannot be resumed from {current.state.value}")
            connection.execute(
                "UPDATE download_items SET state='queued',error=NULL,updated_at=? "
                "WHERE job_id=? AND state IN ('failed','running')",
                (time.time(), job_id),
            )
        self._wake.set()
        self._emit(job_id)
        return self.job(job_id)

    def cancel(self, job_id: str) -> DownloadJob:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE download_jobs SET state='cancelled',current_position=NULL,updated_at=? "
                "WHERE job_id=? AND state NOT IN ('completed','cancelled')",
                (time.time(), job_id),
            )
            if not cursor.rowcount:
                current = self.job(job_id)
                if current.state != DownloadState.CANCELLED:
                    raise DownloadJobError(f"Download job cannot be cancelled from {current.state.value}")
            connection.execute(
                "UPDATE download_items SET state='cancelled',updated_at=? "
                "WHERE job_id=? AND state NOT IN ('completed','cancelled')",
                (time.time(), job_id),
            )
        self._wake.set()
        self._emit(job_id)
        return self.job(job_id)

    def _emit(self, job_id: str) -> None:
        if self.on_update:
            with suppress(Exception):
                self.on_update(self.status(job_id)[0])

    def _worker(self) -> None:
        while not self._closing.is_set():
            row = self.database.fetchone(
                "SELECT job_id FROM download_jobs WHERE state='queued' ORDER BY created_at LIMIT 1"
            )
            if not row:
                self._wake.wait(0.5)
                self._wake.clear()
                continue
            self._run_job(str(row["job_id"]))

    def _run_job(self, job_id: str) -> None:
        self._active_job = job_id
        try:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE download_jobs SET state='running',error=NULL,updated_at=? "
                    "WHERE job_id=? AND state='queued'",
                    (time.time(), job_id),
                )
            for item in self.items(job_id):
                state = self.job(job_id).state
                if state != DownloadState.RUNNING or self._closing.is_set():
                    break
                if item.state == DownloadState.COMPLETED:
                    continue
                self._run_item(item)
                if self.job(job_id).state != DownloadState.RUNNING:
                    break
            with self.database.transaction() as connection:
                remaining = connection.execute(
                    "SELECT COUNT(*) AS count FROM download_items WHERE job_id=? AND state!='completed'",
                    (job_id,),
                ).fetchone()["count"]
                state = connection.execute(
                    "SELECT state FROM download_jobs WHERE job_id=?", (job_id,)
                ).fetchone()["state"]
                if not remaining and state == "running":
                    connection.execute(
                        "UPDATE download_jobs SET state='completed',current_position=NULL,"
                        "completed_items=total_items,updated_at=? WHERE job_id=?",
                        (time.time(), job_id),
                    )
                elif self._closing.is_set() and state == "running":
                    connection.execute(
                        "UPDATE download_jobs SET state='queued',current_position=NULL,updated_at=? WHERE job_id=?",
                        (time.time(), job_id),
                    )
        finally:
            self._active_job = None
            self._emit(job_id)

    def _interrupted(self, job_id: str) -> bool:
        if self._closing.is_set():
            return True
        row = self.database.fetchone("SELECT state FROM download_jobs WHERE job_id=?", (job_id,))
        return not row or row["state"] != "running"

    def _progress_hook(self, item: DownloadItem, payload: dict[str, Any]) -> None:
        if self._interrupted(item.job_id):
            raise DownloadInterrupted("Download was paused, cancelled, or interrupted")
        downloaded = float(payload.get("downloaded_bytes") or 0)
        total = float(payload.get("total_bytes") or payload.get("total_bytes_estimate") or 0)
        progress = min(1.0, max(0.0, downloaded / total)) if total else item.progress
        now = time.monotonic()
        previous_progress, previous_time = self._last_progress.get(cast(int, item.item_id), (-1.0, 0.0))
        if progress - previous_progress < 0.01 and now - previous_time < 0.5 and payload.get("status") != "finished":
            return
        self._last_progress[cast(int, item.item_id)] = (progress, now)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE download_items SET progress=?,updated_at=? WHERE item_id=?",
                (progress, time.time(), item.item_id),
            )
        self._emit(item.job_id)

    def _options(self, item: DownloadItem, staging: Path, quality: str) -> dict[str, Any]:
        metadata = item.metadata
        tags = {
            "title": metadata.get("title") or item.media.title,
            "artist": metadata.get("artist") or item.media.artist,
            "album": metadata.get("album") or item.media.album,
            "album_artist": metadata.get("album_artist"),
            "track": metadata.get("track_number"),
            "disc": metadata.get("disc_number"),
            "musicbrainz_recordingid": metadata.get("recording_mbid"),
            "musicbrainz_albumid": metadata.get("release_mbid"),
            "purl": item.media.original_uri,
            "youtube_id": metadata.get("video_id"),
        }
        post_args = []
        for key, value in tags.items():
            if value is not None:
                post_args.extend(("-metadata", f"{key}={value}"))
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": f"{quality}audio/{quality}",
            "outtmpl": str(staging / f"item-{item.position}.%(ext)s"),
            "continuedl": True,
            "progress_hooks": [lambda payload: self._progress_hook(item, payload)],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                },
                {"key": "FFmpegMetadata", "add_metadata": True},
            ],
            "postprocessor_args": {"FFmpegMetadata": post_args},
        }
        options.update(integration_options(self.browser_profile))
        if self.ffmpeg_bin:
            options["ffmpeg_location"] = os.path.expanduser(self.ffmpeg_bin)
        return options

    def _run_item(self, item: DownloadItem) -> None:
        job = self.job(item.job_id)
        destination = Path(job.destination)
        staging = destination / ".mariana-partials" / item.job_id
        staging.mkdir(parents=True, exist_ok=True)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE download_items SET state='running',attempts=attempts+1,error=NULL,updated_at=? "
                "WHERE item_id=?",
                (time.time(), item.item_id),
            )
            connection.execute(
                "UPDATE download_jobs SET current_position=?,updated_at=? WHERE job_id=?",
                (item.position, time.time(), item.job_id),
            )
        try:
            with self.downloader_factory(self._options(item, staging, job.quality)) as downloader:
                info = downloader.extract_info(item.media.original_uri, download=True)
            outputs = [
                path
                for path in staging.glob(f"item-{item.position}.*")
                if path.is_file() and not path.name.endswith((".part", ".ytdl"))
            ]
            output = next((path for path in outputs if path.suffix.casefold() == ".mp3"), None)
            if output is None or output.stat().st_size == 0:
                raise DownloadJobError("yt-dlp completed without producing an MP3 file")
            metadata = dict(item.metadata)
            metadata.setdefault("title", info.get("track") or info.get("title"))
            metadata.setdefault("artist", info.get("artist") or info.get("uploader"))
            metadata.setdefault("video_id", info.get("id"))
            final = self.expected_output(destination, item.media, metadata)
            final.parent.mkdir(parents=True, exist_ok=True)
            temporary = final.with_suffix(final.suffix + ".tmp")
            output.replace(temporary)
            temporary.replace(final)
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE download_items SET state='completed',progress=1,output_path=?,error=NULL,updated_at=? "
                    "WHERE item_id=?",
                    (str(final), time.time(), item.item_id),
                )
                connection.execute(
                    "UPDATE download_jobs SET completed_items=completed_items+1,updated_at=? WHERE job_id=?",
                    (time.time(), item.job_id),
                )
        except DownloadInterrupted:
            state = self.job(item.job_id).state
            next_state = "cancelled" if state == DownloadState.CANCELLED else "queued"
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE download_items SET state=?,updated_at=? WHERE item_id=? AND state='running'",
                    (next_state, time.time(), item.item_id),
                )
        except Exception as error:
            message = str(error).strip() or type(error).__name__
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE download_items SET state='failed',error=?,updated_at=? WHERE item_id=?",
                    (message, time.time(), item.item_id),
                )
                connection.execute(
                    "UPDATE download_jobs SET state='failed',error=?,current_position=NULL,updated_at=? "
                    "WHERE job_id=? AND state='running'",
                    (message, time.time(), item.job_id),
                )
        finally:
            self._last_progress.pop(cast(int, item.item_id), None)
            try:
                if staging.is_dir() and not any(staging.iterdir()):
                    staging.rmdir()
            except OSError:
                pass
            self._emit(item.job_id)

    def wait(self, job_id: str, timeout: float = 30) -> DownloadJob:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.job(job_id)
            if job.state in {DownloadState.COMPLETED, DownloadState.FAILED, DownloadState.CANCELLED}:
                return job
            time.sleep(0.01)
        raise TimeoutError(f"Download job {job_id} did not finish within {timeout:g} seconds")

    def close(self) -> None:
        self._closing.set()
        self._wake.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
