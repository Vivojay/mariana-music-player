"""Opt-in probes for contracts that mocks cannot validate.

Run with ``$env:MARIANA_LIVE_TESTS='1'; python -m pytest -m live`` on Windows.
These probes are intentionally excluded from normal CI because public services can
rate-limit, change responses, or be unavailable independently of Mariana Player.
"""

import os
import shutil
from pathlib import Path

import pytest

from beta.podcasts import refresh_podcast_data
from beta.youtube_media import search, stream_url
from mariana.identity import fingerprint_file
from mariana.database import MarianaDatabase
from mariana.radio import RadioCatalog


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("MARIANA_LIVE_TESTS") != "1", reason="set MARIANA_LIVE_TESTS=1"),
]


def test_live_multimedia_tools_are_discoverable():
    assert shutil.which("ffmpeg")
    assert shutil.which("ffprobe")
    assert shutil.which("ffplay")
    assert any(shutil.which(runtime) for runtime in ("deno", "node", "qjs"))


def test_live_youtube_search_and_stream_resolution():
    results = search("Rick Astley Never Gonna Give You Up official", limit=1)
    assert results and results[0]["url"].startswith("https://")
    assert stream_url(results[0]["url"], audio_only=True).startswith("http")


def test_live_podcast_feed_refresh(tmp_path):
    output = tmp_path / "podcast.json"
    episodes = refresh_podcast_data("https://feeds.simplecast.com/54nAGcIl", output)
    assert episodes
    assert any(item.get("enclosure_url") for item in episodes)
    assert output.is_file()


def test_live_chromaprint_returns_a_fingerprint():
    sample = Path(__file__).resolve().parents[1] / "res" / "first_boot_startup_sound.mp3"
    duration, fingerprint = fingerprint_file(sample)
    assert duration > 0
    assert fingerprint


def test_live_official_radio_endpoint_decodes(tmp_path):
    with MarianaDatabase(tmp_path / "radio.db") as database:
        result = RadioCatalog(database).health(
            "groove-salad",
            ffmpeg_bin=str(Path(shutil.which("ffmpeg")).parent),
            force=True,
        )
    assert result["status"] == "healthy", result
