import json
import time
from pathlib import Path

import pytest

from mariana.desktop_downloads import DesktopDownloads, progress_numbers
from mariana.download import DownloadError
from mariana.models import MediaCapabilities, MediaRef, MediaSource


class FakeManager:
    def __init__(self):
        self.created = []
        self.rows = []

    def create(self, media, **options):
        self.created.append((media, options))

    def status(self):
        return self.rows


def media(source=MediaSource.URL, *, stable_id="media-1", live=False):
    return MediaRef(
        source,
        "https://example.test/watch?id=private",
        title='A <Very> / Useful Title',
        stable_id=stable_id,
        capabilities=MediaCapabilities(finite=not live, live=live, downloadable=not live),
    )


def test_progress_numbers_accepts_only_bounded_finite_metrics():
    assert progress_numbers({
        "downloaded_bytes": 10,
        "total_bytes_estimate": 20,
        "speed": 4.5,
        "eta": 2,
    }) == {
        "downloaded_bytes": 10.0,
        "total_bytes": 20.0,
        "speed_bytes_per_second": 4.5,
        "eta_seconds": 2.0,
    }
    assert all(value is None for value in progress_numbers({
        "downloaded_bytes": True,
        "total_bytes": float("inf"),
        "speed": -1,
        "eta": "2",
    }).values())



@pytest.mark.parametrize("field", ["downloaded_bytes", "total_bytes", "speed", "eta"])
def test_oversized_transfer_numbers_are_ignored_without_stopping_download(field):
    values = progress_numbers({field: 10**400})
    assert all(value is None for value in values.values())


def test_youtube_download_uses_existing_manager_with_explicit_format(tmp_path: Path):
    manager = FakeManager()
    downloads = DesktopDownloads(manager, lambda: tmp_path)
    item = media(MediaSource.YOUTUBE)

    downloads.start(item, "mp4")

    assert manager.created[0][0] == [item]
    assert manager.created[0][1]["destination"] == tmp_path
    assert manager.created[0][1]["output_format"] == "mp4"
    assert manager.created[0][1]["metadata"] == [{"title": item.title, "artist": None}]


def test_custom_download_reports_real_transfer_without_exposing_references(tmp_path: Path):
    manager = FakeManager()

    def download(url, destination, *, progress_hook, **_options):
        assert url.startswith("https://example.test/")
        progress_hook({"downloaded_bytes": 25, "total_bytes": 100, "speed": 5, "eta": 15})
        destination.write_bytes(b"video")
        return destination

    downloads = DesktopDownloads(manager, lambda: tmp_path, download=download)
    downloads.start(media(), "mp4")
    deadline = time.monotonic() + 2
    while downloads.status()[0]["state"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)

    row = downloads.status()[0]
    assert row["state"] == "completed"
    assert row["format"] == "mp4"
    assert row["progress"] == 1.0
    assert row["speed_bytes_per_second"] is None
    assert "example.test" not in json.dumps(row)
    assert not any("Canonical" in key or "path" in key.lower() or "url" in key.lower() for key in row)
    assert (tmp_path / "A _Very_ _ Useful Title.mp4").read_bytes() == b"video"


def test_download_rejects_live_local_invalid_and_duplicate_requests(tmp_path: Path):
    manager = FakeManager()
    downloads = DesktopDownloads(manager, lambda: tmp_path)
    with pytest.raises(DownloadError, match="finite"):
        downloads.start(media(live=True), "mp3")
    with pytest.raises(DownloadError, match="already on disk"):
        downloads.start(media(MediaSource.LOCAL), "mp3")
    with pytest.raises(DownloadError, match="MP3 audio or MP4 video"):
        downloads.start(media(), "wav")

    item = media(MediaSource.YOUTUBE)
    manager.rows = [{
        "job_id": "a" * 32,
        "state": "running",
        "items": [{"media": item.to_dict(), "state": "running", "metadata": {},
                   "progress": 0.5, "error": None, "transfer": None}],
    }]
    with pytest.raises(DownloadError, match="already has an active download"):
        downloads.start(item, "mp3")
    downloads.start(item, "mp4")
    assert manager.created[-1][1]["output_format"] == "mp4"
