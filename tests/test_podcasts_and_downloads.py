import hashlib
import json
from pathlib import Path

import pytest

import beta.mediadl as mediadl
import beta.podcasts as podcasts
from mariana.models import podcast_episode_identity
from mariana.podcast_feeds import PodcastFeedError


class Response:
    def __init__(self, content: bytes):
        self.content = content
        self.closed = False

    def raise_for_status(self):
        return None

    def close(self):
        self.closed = True


def test_refresh_podcast_data_creates_parent_and_normalizes_feed(monkeypatch, tmp_path, fixture_dir):
    content = (fixture_dir / "podcast_feed.xml").read_bytes()
    monkeypatch.setattr(podcasts.requests, "get", lambda *_a, **_k: Response(content))
    output = tmp_path / "nested" / "feed.json"

    episodes = podcasts.refresh_podcast_data("https://example.test/feed?token=private-feed-key", output)

    assert output.is_file()
    assert json.loads(output.read_text(encoding="utf-8"))["feed_identity"] is None
    assert "private-feed-key" not in output.read_text(encoding="utf-8")
    assert episodes[0]["title"] == "Older Episode"
    assert episodes[0]["episode_guid"] == "mariana-test-episode-older"
    assert episodes[0]["identity_kind"] == "guid"
    assert len(episodes[0]["stable_id"]) == 24
    assert episodes[1]["enclosure_url"].endswith("newest.mp3")
    assert episodes[1]["published_timestamp"] > episodes[0]["published_timestamp"]


def test_podcast_guid_identity_survives_enclosure_changes_and_same_titles_are_distinct():
    first = podcast_episode_identity(
        "https://example.test/feed.xml",
        guid="episode-one",
        enclosure_url="https://cdn.test/old.mp3?signature=old",
        title="Repeated title",
    )
    moved = podcast_episode_identity(
        "https://example.test/feed.xml",
        guid="episode-one",
        enclosure_url="https://other-cdn.test/new.mp3?signature=new",
        title="Repeated title",
    )
    different = podcast_episode_identity(
        "https://example.test/feed.xml",
        guid="episode-two",
        enclosure_url="https://cdn.test/two.mp3",
        title="Repeated title",
    )

    assert first is not None and first[1] == "guid"
    assert moved == first
    assert different is not None and different[0] != first[0]
    assert podcast_episode_identity(
        "https://example.test/feed.xml",
        enclosure_url="https://cdn.test/transient.mp3?signature=temporary",
        title="No publication identity",
    ) is None


@pytest.mark.parametrize("existing_cache", [False, True])
@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"not xml", "Podcast feed is malformed"),
        (b"<rss version='2.0'><channel><title>Articles</title></channel></rss>",
         "This feed has no supported playable media enclosures"),
    ],
)
def test_refresh_podcast_data_rejects_invalid_feed(monkeypatch, tmp_path, existing_cache, payload, message):
    response = Response(payload)
    monkeypatch.setattr(podcasts.requests, "get", lambda *_a, **_k: response)
    output = tmp_path / "feed.json"
    saved = '{"podcasts_raw": [{"title": "Previously loaded episode"}]}'
    if existing_cache:
        output.write_text(saved, encoding="utf-8")

    with pytest.raises(PodcastFeedError) as error:
        podcasts.refresh_podcast_data("https://example.test/bad?token=private", output)

    assert str(error.value) == message
    assert "private" not in str(error.value)
    assert response.closed
    if existing_cache:
        assert output.read_text(encoding="utf-8") == saved
    else:
        assert not output.exists()


@pytest.mark.parametrize("during_response", [False, True])
def test_refresh_podcast_data_keeps_provider_failure_distinct_and_preserves_cache(
    monkeypatch, tmp_path, during_response,
):
    response = Response(b"not a successful feed response")
    failure = podcasts.requests.HTTPError("Provider request rejected")
    output = tmp_path / "feed.json"
    saved = '{"podcasts_raw": [{"title": "Previously loaded episode"}]}'
    output.write_text(saved, encoding="utf-8")

    def reject(*_args, **_kwargs):
        raise failure

    if during_response:
        monkeypatch.setattr(response, "raise_for_status", reject)
        monkeypatch.setattr(podcasts.requests, "get", lambda *_a, **_k: response)
    else:
        monkeypatch.setattr(podcasts.requests, "get", reject)

    with pytest.raises(podcasts.requests.HTTPError) as error:
        podcasts.refresh_podcast_data("https://example.test/feed", output)

    assert error.value is failure
    assert response.closed is during_response
    assert output.read_text(encoding="utf-8") == saved


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
    assert all(item["identity_kind"] == "published-metadata" for item in result)
    assert len({item["stable_id"] for item in result}) == 2


def test_verified_programme_aliases_have_distinct_feeds():
    assert podcasts.vendors["maintenance_phase"] == "https://feeds.buzzsprout.com/1411126.rss"
    assert podcasts.vendors["storytime_with_seth_rogen"] == "https://feeds.simplecast.com/ZK9BGVQN"
    assert len(set(podcasts.vendors.values())) == len(podcasts.vendors)


@pytest.mark.parametrize("bound_old_feed", [False, True])
@pytest.mark.parametrize("offline", [False, True])
def test_corrected_programme_never_reuses_wrong_same_day_feed_cache(
    monkeypatch, tmp_path, fixture_dir, bound_old_feed, offline,
):
    cache_path = tmp_path / "data" / "podbean_maintenance_phase.json"
    cache_path.parent.mkdir()
    old_cache = {
        "last_write_date": podcasts.dt.today().strftime("%d-%m-%Y"),
        "podcasts_raw": [{"title": "Storytime episode", "episode_guid": "storytime-guid", "published_timestamp": 1}],
    }
    if bound_old_feed:
        old_cache["feed_identity"] = hashlib.sha256(
            podcasts.vendors["storytime_with_seth_rogen"].encode(),
        ).hexdigest()
    original = json.dumps(old_cache)
    cache_path.write_text(original, encoding="utf-8")
    payload = (fixture_dir / "podcast_feed.xml").read_bytes().replace(
        b"Mariana Test Feed", b"Maintenance Phase",
    )
    calls = []
    def request(url, **_kwargs):
        calls.append(url)
        if offline:
            raise podcasts.requests.ConnectionError("Provider unavailable")
        return Response(payload)
    monkeypatch.setattr(podcasts.requests, "get", request)

    with monkeypatch.context() as cwd:
        cwd.chdir(tmp_path)
        if offline:
            with pytest.raises(podcasts.requests.ConnectionError, match="Provider unavailable"):
                podcasts.get_latest_podbean_data("maintenance_phase")
            assert cache_path.read_text(encoding="utf-8") == original
        else:
            result = podcasts.get_latest_podbean_data("maintenance_phase")
            assert [row["title"] for row in result] == ["Newest Episode", "Older Episode"]
            assert all(row["programme"] == "Maintenance Phase" for row in result)
            assert json.loads(cache_path.read_text(encoding="utf-8"))["feed_identity"] == hashlib.sha256(
                podcasts.vendors["maintenance_phase"].encode(),
            ).hexdigest()
            assert podcasts.get_latest_podbean_data("maintenance_phase") == result
    assert calls == [podcasts.vendors["maintenance_phase"]]


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


def test_media_download_redacts_provider_logs_before_legacy_reporting(monkeypatch, tmp_path, caplog):
    messages = []
    stream = "https://listener:secret-pass@media.test/audio?signature=private-token&unusual=private-value"
    class RejectedDownloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            message = f"HTTP 403 opening {stream}"
            self.options["logger"].error(message)
            raise OSError(message)

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(mediadl, "YoutubeDL", RejectedDownloader)
    monkeypatch.setattr(mediadl, "SAY", lambda **kwargs: messages.append(kwargs))
    assert mediadl.media_DL(download_settings(tmp_path), {}, "https://provider.test/recording") == 5
    assert "403" in messages[0]["log_message"]
    assert "query omitted" in messages[0]["log_message"]
    for private in ("listener", "secret-pass", "private-token", "private-value"):
        assert private not in json.dumps(messages) + caplog.text


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
