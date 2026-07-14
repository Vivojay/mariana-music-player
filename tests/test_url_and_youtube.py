import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from yt_dlp.utils import DownloadError

import beta.youtube_media as youtube_media
import beta.YT_query as yt_query
import url_validate

YOUTUBE_ID = st.text(alphabet=st.sampled_from(list("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")), min_size=11, max_size=11)


@given(video_id=YOUTUBE_ID)
@pytest.mark.parametrize(
    "template",
    [
        "https://www.youtube.com/watch?v={}",
        "https://youtu.be/{}",
        "https://www.youtube.com/embed/{}",
        "https://youtube.com/shorts/{}",
        "https://music.youtube.com/live/{}",
        "https://youtube.com/redirect?url=https%3A%2F%2Fyoutu.be%2F{}",
    ],
)
def test_youtube_id_parser_handles_supported_shapes(video_id, template):
    assert url_validate.id_if_url_is_of_yt_format(template.format(video_id)) == video_id


@pytest.mark.parametrize(
    "value",
    [None, "", "not a url", "https://example.com/watch?v=abc12345678", "https://example.com/file.mp3"],
)
def test_youtube_id_parser_rejects_non_youtube_values(value):
    assert url_validate.id_if_url_is_of_yt_format(value) is None


def test_url_validation_uses_head_for_regular_urls(monkeypatch):
    calls = {}

    class Response:
        status_code = 204

    def fake_head(url, **kwargs):
        calls.update(url=url, kwargs=kwargs)
        return Response()

    monkeypatch.setattr(url_validate.requests, "head", fake_head)
    assert url_validate.url_is_valid("https://example.test/audio.mp3") is True
    assert calls["kwargs"] == {"allow_redirects": True, "timeout": url_validate.HTTP_TIMEOUT}


def test_url_validation_uses_youtube_adapter_without_head(monkeypatch):
    captured = {}
    monkeypatch.setattr(url_validate.requests, "head", lambda *_a, **_k: pytest.fail("HEAD should not run"))
    monkeypatch.setattr(
        youtube_media,
        "is_resolvable",
        lambda url, **kwargs: captured.update(url=url, **kwargs) or url.endswith("abc12345678"),
    )
    assert url_validate.url_is_valid("https://youtu.be/abc12345678", browser_profile="firefox") is True
    assert captured == {
        "url": "https://www.youtube.com/watch?v=abc12345678",
        "browser_profile": "firefox",
    }


def test_url_validation_defers_extractor_pages_without_head(monkeypatch):
    monkeypatch.setattr(url_validate.requests, "head", lambda *_a, **_k: pytest.fail("HEAD should not run"))
    assert url_validate.url_is_valid("https://soundcloud.com/artist/track?utm_source=clipboard") is True


def test_url_validation_returns_false_on_network_error(monkeypatch):
    monkeypatch.setattr(url_validate.requests, "head", lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")))
    assert url_validate.url_is_valid("https://example.test") is False


def test_youtube_options_and_extract_contract(monkeypatch):
    captured = {}

    class FakeYDL:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, query, download):
            captured.update(query=query, download=download)
            return {"id": "abc12345678"}

    monkeypatch.setattr(youtube_media, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(youtube_media, "integration_options", lambda: {"socket_timeout": 9})

    assert youtube_media._extract("query", playlistend=2) == {"id": "abc12345678"}
    assert captured["options"]["playlistend"] == 2
    assert captured["options"]["socket_timeout"] == 9
    assert captured["download"] is False


def test_youtube_extract_normalizes_failures(monkeypatch):
    class FailingYDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, *_args, **_kwargs):
            raise DownloadError("offline")

    monkeypatch.setattr(youtube_media, "YoutubeDL", FailingYDL)
    with pytest.raises(youtube_media.YouTubeError, match="offline"):
        youtube_media._extract("query")


def test_youtube_search_normalizes_and_filters_entries(monkeypatch, fixture_dir: Path):
    response = json.loads((fixture_dir / "yt_search.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(youtube_media, "_extract", lambda *_a, **_k: response)

    results = youtube_media.search("query", limit=3)
    assert [item["title"] for item in results] == ["First Result", "[Untitled YouTube result]"]
    assert results[0]["url"].endswith("abc12345678")
    assert youtube_media.search(" ") == []
    assert youtube_media.search("query", limit=0) == []


def test_media_info_normalizes_detailed_fields(monkeypatch):
    monkeypatch.setattr(
        youtube_media,
        "_extract",
        lambda *_a, **_k: {"title": "Media", "duration": 12, "view_count": 5, "formats": ({"id": "1"},)},
    )
    monkeypatch.setattr(
        youtube_media,
        "stream_url",
        lambda _url, *, audio_only: "audio" if audio_only else "video",
    )

    result = youtube_media.media_info("url", detailed=True)
    assert result["streams"] == {"bestaudurl": "audio", "bestvidurl": "video"}
    assert result["views"] == 5
    assert result["formats"] == [{"id": "1"}]


def test_stream_url_uses_requested_format_fallback(monkeypatch):
    monkeypatch.setattr(
        youtube_media,
        "_extract",
        lambda *_a, **_k: {"requested_formats": [{"url": None}, {"url": "https://media.test/audio"}]},
    )
    assert youtube_media.stream_url("url") == "https://media.test/audio"

    monkeypatch.setattr(youtube_media, "_extract", lambda *_a, **_k: {})
    with pytest.raises(youtube_media.YouTubeError, match="playable stream"):
        youtube_media.stream_url("url")


def test_youtube_resolvable_and_compatibility_facade(monkeypatch, capsys):
    monkeypatch.setattr(youtube_media, "_extract", lambda *_a, **_k: {"id": "ok"})
    assert youtube_media.is_resolvable("url") is True
    monkeypatch.setattr(youtube_media, "_extract", lambda *_a, **_k: (_ for _ in ()).throw(youtube_media.YouTubeError("bad")))
    assert youtube_media.is_resolvable("url") is False

    monkeypatch.setattr(
        yt_query,
        "search_media",
        lambda *_a, **_k: [{"title": "One", "url": "u1"}, {"title": "Two", "url": "u2"}],
    )
    assert yt_query.search_youtube("q", rescount=2, display_results=False) == [(1, "One", "u1"), (2, "Two", "u2")]
    assert yt_query.search_youtube("q", extra_output=True) == ("One", "u1")
    assert "One" in capsys.readouterr().out


def test_youtube_compatibility_facade_forwards_browser_profile(monkeypatch):
    calls = []
    monkeypatch.setattr(
        yt_query,
        "search_media",
        lambda *args, **kwargs: calls.append(("search", args, kwargs))
        or [{"title": "One", "url": "u1"}],
    )
    monkeypatch.setattr(
        yt_query,
        "media_info",
        lambda *args, **kwargs: calls.append(("info", args, kwargs)) or {"title": "One"},
    )
    yt_query.configure(browser_profile="firefox:default-release")
    try:
        assert yt_query.search_youtube("q") == ("One", "u1")
        assert yt_query.vid_info("u1") == {"title": "One"}
    finally:
        yt_query.configure(browser_profile=None)

    assert calls[0][2]["browser_profile"] == "firefox:default-release"
    assert calls[1][2]["browser_profile"] == "firefox:default-release"


def test_youtube_compatibility_facade_translates_errors(monkeypatch):
    monkeypatch.setattr(yt_query, "media_info", lambda *_a, **_k: (_ for _ in ()).throw(youtube_media.YouTubeError("bad")))
    with pytest.raises(OSError, match="bad"):
        yt_query.vid_info("url")
    monkeypatch.setattr(yt_query, "search_media", lambda *_a, **_k: [])
    with pytest.raises(OSError, match="No YouTube results"):
        yt_query.search_youtube("query")


@pytest.mark.parametrize("value", [":profile", "chrome\nprofile", "chrome\0profile"])
def test_browser_profile_rejects_unsafe_references(value):
    with pytest.raises(youtube_media.YouTubeError, match="Invalid browser profile"):
        youtube_media._browser_profile(value)


def test_browser_profile_and_runtime_options(monkeypatch):
    assert youtube_media._browser_profile(None) is None
    assert youtube_media._browser_profile("chrome:Default") == ("chrome", "Default")
    monkeypatch.setattr(youtube_media, "find_javascript_runtime", lambda: ("deno", "C:/deno.exe"))
    options = youtube_media.integration_options("chrome:Default")
    assert options["js_runtimes"] == {"deno": {"path": "C:/deno.exe"}}
    assert options["cookiesfrombrowser"] == ("chrome", "Default")
    assert youtube_media._options(browser_profile="firefox", quiet=False)["quiet"] is False


@pytest.mark.parametrize(
    ("detail", "profile", "expected"),
    [
        ("Sign in to confirm you're not a bot", None, "youtube auth set firefox"),
        ("cookies-from-browser failed", "edge:Default", 'rejected browser profile "edge:Default"'),
        ("HTTP Error 429: Too Many Requests", None, "rate-limited"),
        ("CERTIFICATE_VERIFY_FAILED", None, "certificate is not trusted"),
    ],
)
def test_youtube_error_messages_are_actionable(detail, profile, expected):
    assert expected in youtube_media.youtube_error_message(RuntimeError(detail), profile)


def test_youtube_operations_forward_browser_profile(monkeypatch):
    calls = []

    def extract(query, **options):
        calls.append((query, options))
        if query.startswith("ytsearch"):
            return {"entries": [{"id": "abc12345678", "title": "One"}]}
        return {"url": "https://media.test/audio"}

    monkeypatch.setattr(youtube_media, "_extract", extract)
    youtube_media.search("query", browser_profile="firefox")
    youtube_media.stream_url("url", browser_profile="firefox")
    assert youtube_media.is_resolvable("url", browser_profile="firefox")

    assert all(options["browser_profile"] == "firefox" for _query, options in calls)


def test_extract_rejects_non_mapping_response(monkeypatch):
    class FakeYDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, *_args, **_kwargs):
            return ["not", "a", "mapping"]

    monkeypatch.setattr(youtube_media, "YoutubeDL", FakeYDL)
    with pytest.raises(youtube_media.YouTubeError, match="unsupported response"):
        youtube_media._extract("query")


def test_youtube_url_fallbacks_and_compact_media_info(monkeypatch):
    assert youtube_media._webpage_url({"url": "https://media.test/direct"}) == "https://media.test/direct"
    assert youtube_media._webpage_url({}) == ""
    monkeypatch.setattr(youtube_media, "_extract", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(youtube_media, "stream_url", lambda _url, *, audio_only: "a" if audio_only else "v")
    result = youtube_media.media_info("url")
    assert result == {
        "title": "[Untitled YouTube media]",
        "duration": None,
        "streams": {"bestaudurl": "a", "bestvidurl": "v"},
    }


def test_resolve_stream_normalizes_headers_expiry_and_live_metadata(monkeypatch):
    monkeypatch.setattr(
        youtube_media,
        "_extract",
        lambda *_args, **_kwargs: {
            "requested_formats": [{"url": None}, {"url": "https://media.test/audio"}],
            "http_headers": {"User-Agent": "test", "Empty": None},
            "expires": "2000000000",
            "live_status": "is_live",
            "title": "Title",
            "uploader": "Uploader",
            "duration": 10,
            "chapters": [{"title": "Intro", "start_time": 0, "end_time": 10}],
        },
    )
    result = youtube_media.resolve_stream("url", browser_profile="chrome")
    assert result["url"] == "https://media.test/audio"
    assert result["http_headers"] == {"User-Agent": "test"}
    assert result["expires_at"] == 2_000_000_000.0
    assert result["is_live"] is True
    assert result["artist"] == "Uploader"
    assert result["chapters"] == [{"title": "Intro", "start_time": 0.0, "end_time": 10.0}]

    monkeypatch.setattr(youtube_media, "_extract", lambda *_args, **_kwargs: {})
    with pytest.raises(youtube_media.YouTubeError, match="playable stream"):
        youtube_media.resolve_stream("url", audio_only=False)


def test_youtube_chapter_normalization_sorts_derives_and_discards_malformed_ranges():
    chapters = youtube_media.normalize_chapters(
        [
            {"title": "Second", "start_time": 10},
            {"title": "Intro", "start_time": 0, "end_time": 99},
            {"title": "", "start_time": 2},
            {"title": "Bad", "start_time": "nope"},
            {"title": "Reverse", "start_time": 30, "end_time": 29},
            None,
        ],
        40,
    )
    assert chapters == [
        {"title": "Intro", "start_time": 0.0, "end_time": 10.0},
        {"title": "Second", "start_time": 10.0, "end_time": 30.0},
    ]
    assert youtube_media.normalize_chapters("invalid", 10) == []
    assert youtube_media.normalize_chapters([{"title": "Open", "start_time": 0}], "invalid") == []
    assert youtube_media.normalize_chapters([{"title": "Open", "start_time": 0}], float("inf")) == []
