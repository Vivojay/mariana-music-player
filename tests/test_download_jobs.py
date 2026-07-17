import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.download_jobs import (
    DownloadJobError,
    DownloadManager,
    canonical_youtube_url,
    resolved_download_metadata,
    sanitize_component,
)
from mariana.models import DownloadItem, DownloadState, MediaRef, MediaSource


def youtube_media(video_id: str, title: str = "Song") -> MediaRef:
    return MediaRef(
        MediaSource.YOUTUBE,
        f"https://www.youtube.com/watch?v={video_id}&list=PLsecret&utm_source=test",
        title=title,
        artist="Artist",
        resolver_data={
            "youtube": True,
            "direct_url": "https://signed.test/audio?token=secret",
            "headers": {"Authorization": "secret"},
        },
    )


class SuccessfulDownloader:
    active = 0
    maximum_active = 0
    last_options = None
    lock = threading.Lock()

    def __init__(self, options):
        self.options = options
        type(self).last_options = options

    def __enter__(self):
        with self.lock:
            type(self).active += 1
            type(self).maximum_active = max(type(self).maximum_active, type(self).active)
        return self

    def __exit__(self, *_args):
        with self.lock:
            type(self).active -= 1
        return False

    def extract_info(self, url, *, download):
        assert download and "list=" not in url
        hook = self.options["progress_hooks"][0]
        hook({"status": "downloading", "downloaded_bytes": 5, "total_bytes": 10})
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp3"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp3")
        hook({"status": "finished", "downloaded_bytes": 10, "total_bytes": 10})
        video_id = canonical_youtube_url(url)[1]
        return {"id": video_id, "title": f"Title {video_id}", "artist": "Artist"}


class FailingDownloader(SuccessfulDownloader):
    def extract_info(self, _url, *, download):
        assert download
        raise OSError("network failed")


class BlockingDownloader(SuccessfulDownloader):
    started = threading.Event()

    def extract_info(self, _url, *, download):
        assert download
        hook = self.options["progress_hooks"][0]
        type(self).started.set()
        while True:
            hook({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 10})
            time.sleep(0.01)


def test_schema_eight_creates_download_tables_and_backup(tmp_path: Path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES('schema_version','7');"
    )
    connection.close()
    with MarianaDatabase(path) as database:
        assert database.fetchone("SELECT name FROM sqlite_master WHERE name='download_jobs'")
        assert database.fetchone("SELECT name FROM sqlite_master WHERE name='download_items'")
        assert database.fetchone("SELECT value FROM schema_meta")[0] == str(SCHEMA_VERSION)
    assert path.with_suffix(f".db.pre-schema-{SCHEMA_VERSION}.bak").is_file()


def test_canonical_urls_and_portable_filename_sanitization():
    assert canonical_youtube_url(
        "https://youtu.be/abc123?si=secret&utm_source=test"
    ) == ("https://www.youtube.com/watch?v=abc123", "abc123")
    assert canonical_youtube_url(
        "https://www.youtube.com/watch?v=abc123&list=private"
    ) == ("https://www.youtube.com/watch?v=abc123", "abc123")
    with pytest.raises(DownloadJobError, match="canonical YouTube"):
        canonical_youtube_url("https://example.test/video")
    assert sanitize_component('A<B>:"Song"?*') == "A_B___Song___"
    assert sanitize_component("CON") == "_CON"
    assert sanitize_component("...") == "Unknown"


def test_single_and_album_jobs_are_sequential_atomic_and_secret_free(tmp_path: Path):
    events = []
    SuccessfulDownloader.maximum_active = 0
    with MarianaDatabase(tmp_path / "downloads.db") as database:
        manager = DownloadManager(
            database,
            downloader_factory=SuccessfulDownloader,
            on_update=events.append,
        )
        try:
            job = manager.create(
                [youtube_media("one"), youtube_media("two")],
                kind="album",
                destination=tmp_path / "downloads",
                album_id="album",
                metadata=[
                    {
                        "album": "Album",
                        "album_artist": "Album Artist",
                        "artist": "Artist",
                        "title": "One",
                        "disc_number": 1,
                        "track_number": 1,
                    },
                    {
                        "album": "Album",
                        "album_artist": "Album Artist",
                        "artist": "Artist",
                        "title": "Two",
                        "disc_number": 2,
                        "track_number": 1,
                    },
                ],
            )
            completed = manager.wait(job.job_id)
            assert completed.state == DownloadState.COMPLETED
            items = manager.items(job.job_id)
            assert [item.progress for item in items] == [1, 1]
            assert Path(items[0].output_path).name == "01-01 Artist - One [one].mp3"
            assert Path(items[1].output_path).name == "02-01 Artist - Two [two].mp3"
            assert SuccessfulDownloader.maximum_active == 1
            persisted = json.dumps(
                [dict(row) for row in database.fetchall("SELECT * FROM download_items")],
                sort_keys=True,
            )
            assert "secret" not in persisted and "signed.test" not in persisted
            assert events[-1]["state"] == "completed"
        finally:
            manager.close()


def test_download_replaces_placeholders_with_extracted_source_metadata(tmp_path: Path):
    placeholder = youtube_media(
        "dYsg37kwCwM",
        "Unknown Artist - YouTube audio [dYsg37kwCwM]",
    )
    placeholder.artist = "Unknown Artist"
    with MarianaDatabase(tmp_path / "metadata.db") as database:
        manager = DownloadManager(database, downloader_factory=SuccessfulDownloader)
        try:
            job = manager.create(
                [placeholder],
                destination=tmp_path / "downloads",
                metadata=[
                    {
                        "title": "YouTube audio [dYsg37kwCwM]",
                        "artist": "Unknown Artist",
                    }
                ],
            )

            assert manager.wait(job.job_id).state == DownloadState.COMPLETED
            item = manager.items(job.job_id)[0]
            assert Path(item.output_path).name == "Artist - Title [dYsg37kwCwM].mp3"
            assert item.metadata["source_title"] == "Title dYsg37kwCwM"
            assert item.metadata["source_artist"] == "Artist"
            assert item.metadata["metadata_source"] == "youtube-download"
            assert item.metadata["metadata_confidence"] == "trusted"
            serialized_options = json.dumps(SuccessfulDownloader.last_options, default=str)
            assert "title=YouTube audio" not in serialized_options
            assert "artist=Unknown Artist" not in serialized_options
        finally:
            manager.close()


def test_download_keeps_trusted_cached_source_metadata_over_generic_extraction(tmp_path: Path):
    media = youtube_media("dYsg37kwCwM", "Generic result")
    with MarianaDatabase(tmp_path / "cached.db") as database:
        manager = DownloadManager(database, downloader_factory=SuccessfulDownloader)
        try:
            job = manager.create(
                [media],
                destination=tmp_path / "downloads",
                metadata=[
                    {
                        "source_title": "Trusted Song",
                        "source_artist": "Trusted Artist",
                    }
                ],
            )

            assert manager.wait(job.job_id).state == DownloadState.COMPLETED
            item = manager.items(job.job_id)[0]
            assert Path(item.output_path).name == "Trusted Artist - Trusted Song [dYsg37kwCwM].mp3"
            assert item.metadata["source_title"] == "Trusted Song"
            assert item.metadata["source_artist"] == "Trusted Artist"
        finally:
            manager.close()


def test_resolved_download_metadata_marks_missing_values_and_keeps_source_attribution():
    placeholder = youtube_media(
        "dYsg37kwCwM",
        "Unknown Artist - YouTube audio [dYsg37kwCwM]",
    )
    placeholder.artist = "Unknown Artist"
    item = DownloadItem(
        1,
        "job",
        1,
        placeholder,
        metadata={
            "video_id": "dYsg37kwCwM",
            "title": "YouTube audio",
            "artist": "Unknown Artist",
        },
    )

    missing = resolved_download_metadata(item, {})
    attributed = resolved_download_metadata(
        item,
        {
            "title": "Actual Song",
            "uploader": "Uploader Name",
            "channel": "Channel Name",
        },
    )

    assert missing["metadata_confidence"] == "placeholder"
    assert "source_title" not in missing and "source_artist" not in missing
    assert attributed["source_title"] == "Actual Song"
    assert attributed["source_artist"] == "Uploader Name"
    assert attributed["source_uploader"] == "Uploader Name"
    assert attributed["source_channel"] == "Channel Name"


def test_failed_job_resumes_without_duplicate_completed_items(tmp_path: Path):
    with MarianaDatabase(tmp_path / "downloads.db") as database:
        manager = DownloadManager(database, downloader_factory=FailingDownloader)
        try:
            job = manager.create([youtube_media("resume")], destination=tmp_path)
            assert manager.wait(job.job_id).state == DownloadState.FAILED
            assert manager.items(job.job_id)[0].attempts == 1
            manager.downloader_factory = SuccessfulDownloader
            manager.resume(job.job_id)
            assert manager.wait(job.job_id).state == DownloadState.COMPLETED
            item = manager.items(job.job_id)[0]
            assert item.attempts == 2 and Path(item.output_path).is_file()
        finally:
            manager.close()


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_running_job_pause_and_cancel_interrupt_cleanly(tmp_path: Path, action: str):
    BlockingDownloader.started.clear()
    with MarianaDatabase(tmp_path / f"{action}.db") as database:
        manager = DownloadManager(database, downloader_factory=BlockingDownloader)
        try:
            job = manager.create([youtube_media(action)], destination=tmp_path)
            assert BlockingDownloader.started.wait(2)
            getattr(manager, action)(job.job_id)
            deadline = time.monotonic() + 2
            expected = DownloadState.PAUSED if action == "pause" else DownloadState.CANCELLED
            while time.monotonic() < deadline and manager.job(job.job_id).state != expected:
                time.sleep(0.01)
            assert manager.job(job.job_id).state == expected
            item = manager.items(job.job_id)[0]
            assert item.state in {
                DownloadState.QUEUED if action == "pause" else DownloadState.CANCELLED,
                DownloadState.RUNNING,
            }
        finally:
            manager.close()


def test_recovery_and_missing_only_do_not_overwrite_existing_output(tmp_path: Path):
    with MarianaDatabase(tmp_path / "downloads.db") as database:
        manager = DownloadManager(database, downloader_factory=SuccessfulDownloader, autostart=False)
        media = youtube_media("existing", "Existing")
        expected = manager.expected_output(
            tmp_path,
            media,
            {"video_id": "existing", "title": "Existing", "artist": "Artist"},
        )
        expected.parent.mkdir(parents=True, exist_ok=True)
        expected.write_bytes(b"keep")
        with pytest.raises(DownloadJobError, match="already exist"):
            manager.create([media], destination=tmp_path, missing_only=True)
        job = manager.create([youtube_media("recover")], destination=tmp_path)
        with database.transaction() as connection:
            connection.execute("UPDATE download_jobs SET state='running' WHERE job_id=?", (job.job_id,))
            connection.execute("UPDATE download_items SET state='running' WHERE job_id=?", (job.job_id,))
        manager.close()

        recovered = DownloadManager(database, downloader_factory=SuccessfulDownloader, autostart=False)
        try:
            assert recovered.job(job.job_id).state == DownloadState.QUEUED
            assert recovered.items(job.job_id)[0].state == DownloadState.QUEUED
        finally:
            recovered.close()


def test_local_media_and_invalid_controls_are_rejected(tmp_path: Path):
    with MarianaDatabase(tmp_path / "downloads.db") as database:
        manager = DownloadManager(database, autostart=False)
        try:
            with pytest.raises(DownloadJobError, match="YouTube"):
                manager.create(
                    [MediaRef(MediaSource.LOCAL, str(tmp_path / "local.mp3"))],
                    destination=tmp_path,
                )
            with pytest.raises(DownloadJobError, match="quality"):
                manager.create([youtube_media("quality")], quality="medium", destination=tmp_path)
            with pytest.raises(DownloadJobError, match="Unknown"):
                manager.status("missing")
        finally:
            manager.close()
