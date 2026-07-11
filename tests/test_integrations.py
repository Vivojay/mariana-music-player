from pathlib import Path

import beta.YT_query as yt_query
import beta.podcasts as podcasts
import beta.redditsessions as reddit
import beta.youtube_media as youtube_media
from beta.mediadl import media_DL
from lyrics_provider.detect_song import normalize_song_info


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


def test_podcast_feed_is_normalized(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(podcasts.requests, "get", lambda *_args, **_kwargs: FakeResponse())
    output = tmp_path / "feed.json"
    result = podcasts.refresh_podcast_data("https://example.test/feed.xml", str(output))
    assert result[0]["title"] == "Episode"
    assert result[0]["enclosure_url"] == "https://example.test/episode.mp3"
    assert result[0]["published_timestamp"] > 0


def test_shazam_response_is_normalized():
    response = {
        "matches": [{"id": "match"}],
        "track": {
            "key": "123",
            "title": "Track",
            "share": {"subject": "Artist - Track"},
            "hub": {"explicit": False},
            "genres": {"primary": "Pop"},
            "sections": [
                {"type": "SONG", "metadata": [{"title": "Album", "text": "Album"}]},
                {"type": "LYRICS", "text": ["line one", "line two"]},
            ],
        },
    }
    normalized = normalize_song_info(response)
    assert normalized["display_name"] == "Artist - Track"
    assert normalized["lyrics"] == ["line one", "line two"]


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


def test_reddit_commands_have_a_graceful_retirement_contract():
    assert "retired" in reddit.RETIRED_MESSAGE.lower()
    assert reddit.get_redditsessions() == []
