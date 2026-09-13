"""Malformed optional provider facts must not break inspection or downloads."""

import pytest

from mariana.database import MarianaDatabase
from mariana.download_jobs import DownloadManager
from mariana.media_details import format_file_size, normalized_provider_metadata
from mariana.models import MediaRef, MediaSource


@pytest.mark.parametrize("value", ["\u00b2", "9" * 5000, 10**5000], ids=["non-decimal", "long-text", "large-integer"])
def test_invalid_provider_counts_do_not_break_trusted_metadata(value):
    assert normalized_provider_metadata({"publisher": "A publisher", "views": value}) == {
        "publisher": "A publisher",
    }


def test_oversized_numeric_provider_identifier_is_ignored():
    assert normalized_provider_metadata({"publisher_id": 10**5000, "provider": "Example"}) == {
        "provider": "Example",
    }


def test_provider_counts_preserve_json_integer_precision_boundary():
    largest = (1 << 53) - 1
    assert normalized_provider_metadata({"views": largest, "likes": str(largest)}) == {
        "views": largest, "likes": largest,
    }
    assert normalized_provider_metadata({"views": largest + 1, "likes": str(largest + 1)}) == {}


@pytest.mark.parametrize("value", [10**400, "9" * 5000, float("inf")], ids=["large-integer", "long-text", "infinite"])
def test_unrepresentable_file_sizes_are_unknown(value):
    assert format_file_size(value) == "Unknown"


@pytest.mark.parametrize("value", [10**400, float("nan"), float("inf"), -1, True], ids=["large-integer", "nan", "infinite", "negative", "boolean"])
def test_invalid_transfer_facts_do_not_interrupt_download(tmp_path, value):
    with MarianaDatabase(tmp_path / "downloads.db") as database:
        manager = DownloadManager(database, autostart=False)
        try:
            media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abc12345678", title="Track")
            job = manager.create([media], destination=tmp_path / "output")
            with database.transaction() as connection:
                connection.execute("UPDATE download_jobs SET state='running' WHERE job_id=?", (job.job_id,))
                connection.execute("UPDATE download_items SET state='running' WHERE job_id=?", (job.job_id,))
            item = manager.items(job.job_id)[0]
            manager._progress_hook(item, {
                "status": "downloading", "downloaded_bytes": value, "total_bytes": value,
                "speed": value, "eta": value,
            })
            projected = manager.status(job.job_id)[0]["items"][0]
            assert projected["state"] == "running"
            assert projected["progress"] == 0
            assert projected["transfer"] == {
                "downloaded_bytes": 0, "total_bytes": None,
                "speed_bytes_per_second": None, "eta_seconds": None,
            }
        finally:
            manager.close()
