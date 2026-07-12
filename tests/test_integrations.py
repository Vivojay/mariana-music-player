import json
from pathlib import Path

import requests

import beta.podcasts as podcasts
import beta.redditsessions as reddit
import beta.youtube_media as youtube_media
import beta.YT_query as yt_query
from beta.mediadl import media_DL


class FakeResponse:
    content = b"""<?xml version='1.0'?><rss version='2.0'><channel><title>Feed</title>
    <item><title>Episode</title><link>https://example.test/episode.mp3</link>
    <pubDate>Tue, 09 Jul 2024 12:00:00 +0000</pubDate>
    <enclosure url='https://example.test/episode.mp3' type='audio/mpeg'/></item>
    </channel></rss>"""
    headers = {}

    def raise_for_status(self):
        return None


def test_youtube_search_preserves_cli_shape(monkeypatch):
    monkeypatch.setattr(
        youtube_media,
        "_extract",
        lambda *_args, **_kwargs: {
            "entries": [{"id": "abc12345678", "title": "Result", "duration": 42}]
        },
    )
    assert yt_query.search_youtube("query") == (
        "Result",
        "https://www.youtube.com/watch?v=abc12345678",
    )


def test_stream_url_normalizes_direct_media(monkeypatch):
    monkeypatch.setattr(youtube_media, "_extract", lambda *_args, **_kwargs: {"url": "https://media.test/audio"})
    assert youtube_media.stream_url("https://youtube.test/watch", audio_only=True) == "https://media.test/audio"


def test_youtube_options_discover_node(monkeypatch):
    monkeypatch.setattr(
        youtube_media.shutil,
        "which",
        lambda executable: "C:/node/node.exe" if executable == "node" else None,
    )
    options = youtube_media.integration_options()
    assert options["js_runtimes"] == {"node": {"path": "C:/node/node.exe"}}
    assert options["retries"] == 5


def test_youtube_browser_profile_is_referenced_not_copied(monkeypatch):
    monkeypatch.setattr(youtube_media.shutil, "which", lambda _executable: None)
    options = youtube_media.integration_options("edge:Default")
    assert options["cookiesfrombrowser"] == ("edge", "Default")
    assert not any("cookie" in str(value).lower() for value in options.values() if isinstance(value, str))


def test_podcast_feed_is_normalized(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(podcasts.requests, "get", lambda *_args, **_kwargs: FakeResponse())
    output = tmp_path / "feed.json"
    result = podcasts.refresh_podcast_data("https://example.test/feed.xml", str(output))
    assert result[0]["title"] == "Episode"
    assert result[0]["enclosure_url"] == "https://example.test/episode.mp3"
    assert result[0]["published_timestamp"] > 0


def test_podcast_uses_stale_cache_when_conditional_refresh_fails(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setitem(podcasts.vendors, "cached", "https://example.test/feed.xml")
    cached = {
        "last_write_date": "01-01-2000",
        "etag": "previous",
        "podcasts_raw": [
            {
                "title": "Cached episode",
                "enclosure_url": "https://example.test/cached.mp3",
                "published_timestamp": 1,
            }
        ],
    }
    (tmp_path / "data" / "podbean_cached.json").write_text(json.dumps(cached), encoding="utf-8")
    monkeypatch.setattr(
        podcasts.requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.Timeout("offline")),
    )
    result = podcasts.get_latest_podbean_data(vendor="cached")
    assert result[0]["title"] == "Cached episode"


def test_downloader_dry_run_preserves_quality_settings(tmp_path: Path):
    settings = {
        "download": {
            "downloads folder": str(tmp_path),
            'make a separate mariana folder within "downloads folder"': False,
            "type": "audio",
            "quality": {"audio only": 1, "video with audio": {"audio": 1, "video": 1}},
        }
    }
    options = media_DL(settings, {"system_settings": {}}, ["https://example.test"], dry_run=True)
    assert options["format"] == "bestaudio/best"
    assert options["postprocessors"][0]["key"] == "FFmpegExtractAudio"
    assert "[audio]" in options["outtmpl"]

    video_options = media_DL(
        settings,
        {"system_settings": {}},
        ["https://example.test"],
        typ=1,
        quality={"audio": 1, "video": 1},
        dry_run=True,
    )
    assert "[video]" in video_options["outtmpl"]


def test_reddit_commands_have_a_graceful_retirement_contract():
    assert "retired" in reddit.RETIRED_MESSAGE.lower()
    assert reddit.get_redditsessions() == []
