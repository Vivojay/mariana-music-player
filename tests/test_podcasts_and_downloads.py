import json
from pathlib import Path

import pytest

import beta.mediadl as mediadl
import beta.podcasts as podcasts


class Response:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def test_refresh_podcast_data_creates_parent_and_normalizes_feed(monkeypatch, tmp_path, fixture_dir):
    content = (fixture_dir / "podcast_feed.xml").read_bytes()
    monkeypatch.setattr(podcasts.requests, "get", lambda *_a, **_k: Response(content))
    output = tmp_path / "nested" / "feed.json"

    episodes = podcasts.refresh_podcast_data("https://example.test/feed", output)

    assert output.is_file()
    assert episodes[0]["title"] == "Older Episode"
    assert episodes[1]["enclosure_url"].endswith("newest.mp3")
    assert episodes[1]["published_timestamp"] > episodes[0]["published_timestamp"]


def test_refresh_podcast_data_rejects_invalid_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(podcasts.requests, "get", lambda *_a, **_k: Response(b"not xml"))
    with pytest.raises(ValueError, match="Invalid podcast feed"):
        podcasts.refresh_podcast_data("https://example.test/bad", tmp_path / "feed.json")


def test_podcast_cache_is_reused_and_sorted(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    cache = {
        "last_write_date": podcasts.dt.today().strftime("%d-%m-%Y"),
        "podcasts_raw": [
            {"title": "Old", "enclosure_url": "old", "published_timestamp": 1},
            {"title": "New", "enclosure_url": "new", "published_timestamp": 2},
        ],
    }
    (tmp_path / "data" / "podbean_podnews.json").write_text(json.dumps(cache), encoding="utf-8")
    monkeypatch.setattr(podcasts, "refresh_podcast_data", lambda *_a, **_k: pytest.fail("cache should be reused"))

    result = podcasts.get_latest_podbean_data("podnews")
    assert [item["title"] for item in result] == ["New", "Old"]


def test_stale_or_corrupt_podcast_cache_is_refreshed(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    cache_path = tmp_path / "data" / "podbean_podnews.json"
    cache_path.write_text('{"last_write_date":"01-01-2000","podcasts_raw":[]}', encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        podcasts,
        "refresh_podcast_data",
        lambda **kwargs: calls.append(kwargs) or [{"title": "Fresh", "published_timestamp": 1}],
    )
    assert podcasts.get_latest_podbean_data("podnews")[0]["title"] == "Fresh"
    assert calls[0]["rss_link"] == podcasts.vendors["podnews"]

    cache_path.write_text("broken", encoding="utf-8")
    assert podcasts.get_latest_podbean_data("podnews")[0]["title"] == "Fresh"


def test_custom_and_unknown_podcast_sources(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(
        podcasts,
        "refresh_podcast_data",
        lambda **_kwargs: [{"title": "Custom", "published_timestamp": 1}],
    )
    assert podcasts.get_latest_podbean_data(rss_link="https://example.test/rss")[0]["title"] == "Custom"
    assert podcasts.get_latest_podbean_data("does-not-exist") is None


def download_settings(path: Path, *, separate=False, media_type="audio"):
    return {
        "download": {
            "downloads folder": str(path),
            'make a separate mariana folder within "downloads folder"': separate,
            "type": media_type,
            "quality": {"audio only": 1, "video with audio": {"audio": 0, "video": 1}},
        }
    }


@pytest.mark.parametrize(
    ("settings", "expected"),
    [({}, 1), ({"download": {"downloads folder": "Z:/does-not-exist"}}, 0)],
)
def test_setup_download_directory_error_codes(monkeypatch, settings, expected):
    monkeypatch.setattr(mediadl, "SAY", lambda **_kwargs: None)
    assert mediadl.setup_dl_dir(settings, {}) == expected


def test_setup_download_directory_creates_mariana_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(mediadl, "SAY", lambda **_kwargs: None)
    result = mediadl.setup_dl_dir(
        download_settings(tmp_path, separate=True),
        {"system_settings": {"mariana_dl_dir": "Mariana"}},
    )
    assert Path(result).name == "Mariana"
    assert Path(result).is_dir()


def test_setup_download_directory_reports_missing_separate_setting(monkeypatch, tmp_path):
    monkeypatch.setattr(mediadl, "SAY", lambda **_kwargs: None)
    settings = {"download": {"downloads folder": str(tmp_path)}}
    assert mediadl.setup_dl_dir(settings, {}) == 2


def test_media_download_builds_audio_and_video_options(monkeypatch, tmp_path):
    profiles = []
    monkeypatch.setattr(
        mediadl,
        "integration_options",
        lambda profile=None: profiles.append(profile) or {"socket_timeout": 30},
    )
    settings = download_settings(tmp_path)
    settings["media tools"] = {"ffmpeg bin": str(tmp_path / "ffmpeg-bin")}
    settings["sources"] = {"youtube": {"browser profile": "edge:Default"}}

    audio = mediadl.media_DL(settings, {}, "url", dry_run=True)
    assert audio["format"] == "bestaudio/best"
    assert audio["postprocessors"][0]["preferredcodec"] == "mp3"
    assert audio["socket_timeout"] == 30
    assert audio["ffmpeg_location"] == str(tmp_path / "ffmpeg-bin")
    assert profiles == ["edge:Default"]

    video = mediadl.media_DL(settings, {}, ["url"], typ=1, quality={"audio": 0, "video": 1}, dry_run=True)
    assert video["format"] == "bestvideo+worstaudio/best"
    assert "postprocessors" not in video
    assert profiles == ["edge:Default", "edge:Default"]


def test_media_download_executes_and_reports_success(monkeypatch, tmp_path):
    captured = {}

    class FakeYDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def download(self, urls):
            captured["urls"] = urls

    monkeypatch.setattr(mediadl, "YoutubeDL", FakeYDL)
    assert mediadl.media_DL(download_settings(tmp_path), {}, "url") == 4
    assert captured["urls"] == ["url"]


def test_media_download_reports_failure_without_raising(monkeypatch, tmp_path):
    messages = []

    class FailingYDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            raise OSError("offline")

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(mediadl, "YoutubeDL", FailingYDL)
    monkeypatch.setattr(mediadl, "SAY", lambda **kwargs: messages.append(kwargs))
    assert mediadl.media_DL(download_settings(tmp_path), {}, "url") == 5
    assert "offline" in messages[0]["log_message"]
    assert "detailed log" in messages[0]["display_message"]


@pytest.mark.parametrize(
    ("error", "profile", "expected"),
    [
        (OSError("CERTIFICATE_VERIFY_FAILED: self-signed certificate"), None, "trusted root certificate"),
        (RuntimeError("Sign in to confirm you're not a bot"), None, "youtube auth set firefox"),
        (RuntimeError("Sign in to confirm you're not a bot"), "edge:Default", "edge:Default"),
    ],
)
def test_media_download_classifies_actionable_failures(error, profile, expected):
    assert expected in mediadl._download_failure_message(error, profile)
