"""Opt-in probes for contracts that mocks cannot validate.

Run with ``$env:MARIANA_LIVE_TESTS='1'; python -m pytest -m live`` on Windows.
These probes are intentionally excluded from normal CI because public services can
rate-limit, change responses, or be unavailable independently of Mariana Player.
"""

import os
import shutil
import time
from pathlib import Path

import pytest

from beta.podcasts import refresh_podcast_data
from beta.youtube_media import integration_options, search, stream_url
from mariana.database import MarianaDatabase
from mariana.identity import fingerprint_file
from mariana.models import MediaRef, MediaSource, PlaybackState
from mariana.playback import PlaybackController
from mariana.radio import RadioCatalog
from tools.soak_test import NullOutputStream


def media_tool(name):
    if configured := os.environ.get("MARIANA_TEST_FFMPEG_BIN"):
        candidate = Path(configured).expanduser() / (f"{name}.exe" if os.name == "nt" else name)
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def assert_live_decode(media):
    ffmpeg = media_tool("ffmpeg")
    ffprobe = media_tool("ffprobe")
    assert ffmpeg and ffprobe
    controller = PlaybackController(
        ffmpeg_bin=str(Path(ffmpeg).parent),
        ffprobe_bin=str(Path(ffprobe).parent),
        output_factory=NullOutputStream,
    )
    try:
        controller.play(media)
        deadline = time.monotonic() + 10
        while controller.snapshot().state == PlaybackState.BUFFERING and time.monotonic() < deadline:
            time.sleep(0.05)
        assert controller.snapshot().state == PlaybackState.PLAYING
    finally:
        controller.close()


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.environ.get("MARIANA_LIVE_TESTS") != "1", reason="set MARIANA_LIVE_TESTS=1"),
]


def test_live_multimedia_tools_are_discoverable():
    assert media_tool("ffmpeg")
    assert media_tool("ffprobe")
    assert media_tool("ffplay")
    assert integration_options().get("js_runtimes")


def test_live_youtube_search_and_stream_resolution():
    results = search("Rick Astley Never Gonna Give You Up official", limit=1)
    assert results and results[0]["url"].startswith("https://")
    assert stream_url(results[0]["url"], audio_only=True).startswith("http")
    assert_live_decode(MediaRef(MediaSource.YOUTUBE, results[0]["url"]))


def test_live_podcast_feed_refresh(tmp_path):
    output = tmp_path / "podcast.json"
    episodes = refresh_podcast_data("https://feeds.simplecast.com/54nAGcIl", output)
    assert episodes
    assert any(item.get("enclosure_url") for item in episodes)
    assert output.is_file()
    assert_live_decode(MediaRef(MediaSource.PODCAST, next(item["enclosure_url"] for item in episodes if item.get("enclosure_url"))))


def test_live_chromaprint_returns_a_fingerprint():
    sample = Path(__file__).resolve().parents[1] / "res" / "first_boot_startup_sound.mp3"
    duration, fingerprint = fingerprint_file(sample)
    assert duration > 0
    assert fingerprint


def test_live_official_radio_endpoint_decodes(tmp_path):
    with MarianaDatabase(tmp_path / "radio.db") as database:
        result = RadioCatalog(database).health(
            "groove-salad",
            ffmpeg_bin=str(Path(media_tool("ffmpeg")).parent),
            force=True,
        )
    assert result["status"] == "healthy", result
