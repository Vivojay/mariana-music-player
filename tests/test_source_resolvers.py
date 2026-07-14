import time
from pathlib import Path

import pytest
import requests

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.sources import (
    BaseResolver,
    ExtractorPageResolver,
    FailureCode,
    HttpResolver,
    LocalResolver,
    MediaFailure,
    ResolvedMedia,
    ResolverRegistry,
    YouTubeResolver,
    is_extractor_page_url,
    redacted_uri,
    sanitized_resolver_data,
)


class Response:
    def __init__(self, status=200, *, url="https://cdn.test/audio", headers=None):
        self.status_code = status
        self.url = url
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(str(self.status_code))
            error.response = self
            raise error


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def head(self, url, **kwargs):
        self.calls.append(("head", url, kwargs))
        return self.response

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.response


def test_local_resolver_validates_and_describes_file(tmp_path: Path):
    song = tmp_path / "song.flac"
    song.write_bytes(b"audio")
    resolved = LocalResolver().resolve(MediaRef(MediaSource.LOCAL, str(song)))
    assert resolved.playback_uri == str(song.resolve())
    assert resolved.capabilities.seekable
    assert resolved.metadata["size"] == 5
    with pytest.raises(MediaFailure) as failure:
        LocalResolver().resolve(MediaRef(MediaSource.LOCAL, str(tmp_path / "missing.flac")))
    assert failure.value.code == FailureCode.UNAVAILABLE


@pytest.mark.parametrize(
    ("headers", "source", "seekable", "live"),
    [
        ({"content-length": "42", "accept-ranges": "bytes", "content-type": "audio/mpeg"}, MediaSource.URL, True, False),
        ({"icy-name": "Radio", "content-type": "audio/mpeg"}, MediaSource.RADIO, False, True),
        ({"content-type": "application/vnd.apple.mpegurl"}, MediaSource.URL, True, False),
    ],
)
def test_http_capability_probe(headers, source, seekable, live):
    session = Session(Response(headers=headers))
    media = MediaRef(
        source,
        "https://example.test/media",
        capabilities=MediaCapabilities(finite=source != MediaSource.RADIO, live=source == MediaSource.RADIO),
    )
    resolved = HttpResolver(session).resolve(media)
    assert resolved.capabilities.seekable is seekable
    assert resolved.capabilities.live is live
    assert session.calls[0][2]["headers"]["Icy-MetaData"] == "1"


def test_http_probe_preserves_normalized_icy_station_metadata():
    session = Session(Response(headers={
        "content-type": "audio/mpeg",
        "icy-name": "Test Station",
        "icy-genre": "Ambient",
        "icy-url": "https://station.test",
        "icy-br": "128",
        "icy-metaint": "16000",
    }))
    resolved = HttpResolver(session).resolve(MediaRef(MediaSource.RADIO, "https://station.test/live"))
    assert resolved.metadata["icy"] == {
        "name": "Test Station",
        "genre": "Ambient",
        "url": "https://station.test",
        "br": "128",
        "metaint": "16000",
        "bitrate_kbps": 128,
        "metadata_interval": 16000,
    }


def test_private_radio_resolution_keeps_only_credential_references():
    session = Session(Response(401))
    media = MediaRef(
        MediaSource.RADIO,
        "https://station.test/private",
        resolver_data={"credential_ref": "radio:station", "credential_username": "listener"},
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )
    resolved = HttpResolver(session).resolve(media)
    assert session.calls == []
    assert resolved.metadata["credential_ref"] == "radio:station"
    assert sanitized_resolver_data(media.resolver_data) == {
        "credential_ref": "radio:station",
        "credential_username": "listener",
    }


def test_http_fallback_rejects_protocols_and_classifies_status():
    session = Session(Response(405, headers={"content-length": "1"}))
    session.response = Response(200, headers={"content-length": "1"})
    resolver = HttpResolver(session)
    resolver.resolve(MediaRef(MediaSource.URL, "https://example.test/media"))
    assert session.calls[0][0] == "head"
    with pytest.raises(MediaFailure) as failure:
        resolver.resolve(MediaRef(MediaSource.URL, "rtsp://example.test/media"))
    assert failure.value.code == FailureCode.UNSUPPORTED_PROTOCOL


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("This video is DRM protected", FailureCode.DRM),
        ("not available in your country", FailureCode.GEO_BLOCKED),
        ("Sign in to confirm your age", FailureCode.AUTH_REQUIRED),
        ("HTTP 429 rate limit", FailureCode.RATE_LIMITED),
    ],
)
def test_youtube_failure_classification(text, code):
    media = MediaRef(MediaSource.YOUTUBE, "https://youtube.com/watch?v=test")
    assert YouTubeResolver().classify_failure(RuntimeError(text), media).code == code


def test_youtube_auth_failure_and_registry_profile_update_are_actionable():
    media = MediaRef(MediaSource.YOUTUBE, "https://youtube.com/watch?v=test")
    anonymous = YouTubeResolver().classify_failure(RuntimeError("Sign in to confirm you're not a bot"), media)
    configured = YouTubeResolver("edge:Default").classify_failure(
        RuntimeError("cookies-from-browser failed"), media
    )
    assert anonymous.code == FailureCode.AUTH_REQUIRED
    assert "youtube auth set firefox" in str(anonymous)
    assert configured.code == FailureCode.AUTH_REQUIRED
    assert "edge:Default" in str(configured)

    registry = ResolverRegistry()
    registry.set_youtube_browser_profile("firefox:default-release")
    resolver = registry.for_source(MediaSource.YOUTUBE)
    assert isinstance(resolver, YouTubeResolver)
    assert resolver.browser_profile == "firefox:default-release"


def test_recommendation_delegates_and_transient_values_are_not_persisted(tmp_path: Path):
    song = tmp_path / "song.mp3"
    song.touch()
    registry = ResolverRegistry()
    media = MediaRef(
        MediaSource.RECOMMENDATION,
        str(song),
        resolver_data={"underlying_source": "local", "resolved_uri": "https://signed", "authorization": "secret"},
    )
    assert registry.resolve(media).playback_uri == str(song.resolve())
    assert sanitized_resolver_data(media.resolver_data) == {"underlying_source": "local"}


def test_redacted_uri_hides_credentials_and_secret_query_values():
    value = redacted_uri("https://user:pass@example.test/a?token=secret&track=1#fragment")
    assert "user" not in value and "pass" not in value and "secret" not in value
    assert "track=1" in value and "REDACTED" in value


def test_resolved_expiry_redaction_and_sanitization_edges():
    media = MediaRef(MediaSource.URL, "https://example.test")
    resolved = ResolvedMedia(media, media.original_uri, media.original_uri, media.capabilities, expires_at=time.time())
    assert resolved.expired
    resolved.expires_at = time.time() + 3600
    assert not resolved.expired
    assert redacted_uri("file:///track.mp3") == "file:///track.mp3"
    assert "example.test:8443" in redacted_uri("https://u:p@example.test:8443/a?x=1")
    assert sanitized_resolver_data({"youtube": True, "resolved_uri": "secret", "station_id": "id"}) == {
        "youtube": True,
        "station_id": "id",
    }


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (requests.Timeout("slow"), FailureCode.TIMEOUT, True),
        (RuntimeError("bad"), FailureCode.UNAVAILABLE, False),
    ],
)
def test_base_failure_classification(error, code, retryable):
    media = MediaRef(MediaSource.URL, "https://example.test")
    failure = HttpResolver(Session(Response())).classify_failure(error, media)
    assert (failure.code, failure.retryable) == (code, retryable)


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, FailureCode.AUTH_REQUIRED, False),
        (403, FailureCode.AUTH_REQUIRED, False),
        (429, FailureCode.RATE_LIMITED, True),
        (503, FailureCode.UNAVAILABLE, True),
    ],
)
def test_http_status_classification(status, code, retryable):
    resolver = HttpResolver(Session(Response(status)))
    media = MediaRef(MediaSource.URL, "https://example.test/media")
    if retryable:
        resolved = resolver.resolve(media)
        assert resolved.metadata["probe_warning"]
    else:
        with pytest.raises(MediaFailure) as captured:
            resolver.resolve(media)
        assert (captured.value.code, captured.value.retryable) == (code, retryable)


def test_http_get_fallback_and_embedded_credentials():
    class FallbackSession(Session):
        def head(self, url, **kwargs):
            self.calls.append(("head", url, kwargs))
            return Response(405, url=url)

        def get(self, url, **kwargs):
            self.calls.append(("get", url, kwargs))
            return Response(206, url=url, headers={"content-range": "bytes 0-0/10"})

    session = FallbackSession(None)
    result = HttpResolver(session).resolve(MediaRef(MediaSource.URL, "https://example.test/media"))
    assert result.capabilities.seekable and [call[0] for call in session.calls] == ["head", "get"]
    with pytest.raises(MediaFailure) as captured:
        HttpResolver(session).resolve(MediaRef(MediaSource.URL, "https://user:pass@example.test/media"))
    assert captured.value.code == FailureCode.AUTH_REQUIRED


def test_local_directory_and_youtube_resolution(monkeypatch, tmp_path):
    with pytest.raises(MediaFailure):
        LocalResolver().resolve(MediaRef(MediaSource.LOCAL, str(tmp_path)))
    monkeypatch.setattr(
        "beta.youtube_media.resolve_stream",
        lambda *_args, **_kwargs: {
            "url": "https://signed.test/audio",
            "http_headers": {"User-Agent": "test"},
            "is_live": True,
            "expires_at": time.time() + 60,
            "title": "Live",
            "artist": "Artist",
            "album": None,
            "duration": None,
            "categories": ["Music"],
            "track": "Live",
            "chapters": [],
        },
    )
    resolved = YouTubeResolver("edge:Default").resolve(
        MediaRef(MediaSource.YOUTUBE, "https://youtube.com/watch?v=test")
    )
    assert resolved.capabilities.live and not resolved.capabilities.seekable
    assert resolved.metadata["title"] == "Live"
    assert resolved.metadata["categories"] == ["Music"]
    assert resolved.headers == {"User-Agent": "test"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://soundcloud.com/artist/track", True),
        ("https://m.soundcloud.com/artist/track", True),
        ("https://artist.bandcamp.com/track/song", True),
        ("https://vimeo.com/123", True),
        ("https://soundcloud.example/artist/track", False),
        ("https://cdn.test/audio.mp3", False),
        ("ftp://soundcloud.com/artist/track", False),
        ("https://user:password@soundcloud.com/artist/track", False),
    ],
)
def test_extractor_page_url_detection_is_bounded(url, expected):
    assert is_extractor_page_url(url) is expected


def test_extractor_page_resolution_is_transient_and_does_not_forward_youtube_auth(monkeypatch):
    captured = {}

    def resolve_stream(url, **kwargs):
        captured.update(url=url, kwargs=kwargs)
        return {
            "url": "https://signed.cdn.test/audio?token=secret",
            "http_headers": {"User-Agent": "extractor"},
            "is_live": False,
            "expires_at": time.time() + 60,
            "title": "Track",
            "artist": "Artist",
            "album": "Album",
            "duration": 123,
            "categories": ["Music"],
            "track": "Track",
            "chapters": [],
        }

    monkeypatch.setattr("beta.youtube_media.resolve_stream", resolve_stream)
    original = (
        "https://soundcloud.com/artist/track?si=share"
        "&utm_source=clipboard&utm_medium=text&utm_campaign=social_sharing"
    )
    media = MediaRef(MediaSource.URL, original)
    registry = ResolverRegistry(browser_profile="firefox:Default")
    resolved = registry.resolve(media)

    assert captured == {
        "url": "https://soundcloud.com/artist/track?si=share",
        "kwargs": {"audio_only": True},
    }
    assert resolved.playback_uri.startswith("https://signed.cdn.test/")
    assert resolved.canonical_uri == captured["url"]
    assert resolved.headers == {"User-Agent": "extractor"}
    assert resolved.metadata["title"] == "Track"
    assert resolved.capabilities.seekable and resolved.capabilities.downloadable
    assert media.original_uri == original
    assert "signed.cdn.test" not in str(media.to_dict())


@pytest.mark.parametrize(
    ("detail", "code", "retryable"),
    [
        ("private track, please login", FailureCode.AUTH_REQUIRED, False),
        ("not available in your country", FailureCode.GEO_BLOCKED, False),
        ("HTTP Error 429: Too Many Requests", FailureCode.RATE_LIMITED, True),
        ("request timed out", FailureCode.TIMEOUT, True),
        ("extractor returned no formats", FailureCode.UNAVAILABLE, False),
    ],
)
def test_extractor_page_failures_are_safe_and_typed(detail, code, retryable):
    media = MediaRef(MediaSource.URL, "https://soundcloud.com/artist/track?token=secret")
    failure = ExtractorPageResolver().classify_failure(RuntimeError(detail), media)
    assert (failure.code, failure.retryable) == (code, retryable)
    assert "soundcloud.com" not in str(failure)
    assert "secret" not in str(failure)


def test_registry_delegates_all_recommendation_shapes_and_radio_endpoints(monkeypatch, tmp_path):
    song = tmp_path / "song.mp3"
    song.touch()
    session = Session(Response(headers={"content-length": "1"}))
    registry = ResolverRegistry(http_session=session, radio_endpoints=lambda _media: ["https://radio.test/backup"])
    local = registry.resolve(
        MediaRef(MediaSource.RECOMMENDATION, str(song), resolver_data={"underlying_source": "local"})
    )
    assert local.playback_uri == str(song.resolve())
    url = registry.resolve(MediaRef(MediaSource.RECOMMENDATION, "https://example.test/audio"))
    assert url.playback_uri == "https://cdn.test/audio"
    radio = registry.resolve(
        MediaRef(
            MediaSource.RADIO,
            "https://radio.test/live",
            capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
        )
    )
    assert radio.playback_uri.endswith("backup")
    failure = MediaFailure(FailureCode.DRM, MediaSource.URL, "no")
    assert registry.classify_failure(failure, MediaRef(MediaSource.URL, "https://example.test")) is failure


def test_recommendation_soundcloud_page_uses_extractor_resolver(monkeypatch):
    monkeypatch.setattr(
        "beta.youtube_media.resolve_stream",
        lambda *_args, **_kwargs: {
            "url": "https://cdn.test/audio",
            "http_headers": {},
            "is_live": False,
            "title": "Track",
            "artist": "Artist",
            "album": None,
            "duration": 30,
            "categories": [],
            "track": "Track",
            "chapters": [],
        },
    )
    media = MediaRef(MediaSource.RECOMMENDATION, "https://soundcloud.com/artist/track")
    assert ResolverRegistry().resolve(media).playback_uri == "https://cdn.test/audio"


def test_registry_unknown_source_is_typed():
    registry = ResolverRegistry()
    registry._resolvers.pop(MediaSource.URL)
    with pytest.raises(MediaFailure) as captured:
        registry.for_source(MediaSource.URL)
    assert captured.value.code == FailureCode.UNSUPPORTED_PROTOCOL


def test_base_and_youtube_resolver_failure_paths(monkeypatch):
    media = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch?v=broken")
    base = BaseResolver()
    with pytest.raises(NotImplementedError):
        base.resolve(media)
    resolved = ResolvedMedia(media, media.original_uri, media.original_uri, media.capabilities)
    assert base.probe(resolved) is resolved

    monkeypatch.setattr(
        "beta.youtube_media.resolve_stream",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("extractor broke")),
    )
    with pytest.raises(MediaFailure) as captured:
        YouTubeResolver().resolve(media)
    assert captured.value.code == FailureCode.UNAVAILABLE


def test_delegating_local_detection_and_empty_radio_failover(tmp_path):
    local = tmp_path / "track.flac"
    local.write_bytes(b"audio")
    registry = ResolverRegistry(radio_endpoints=lambda _media: [])
    recommendation = MediaRef(MediaSource.RECOMMENDATION, str(local))
    assert registry.resolve(recommendation).media.source == MediaSource.LOCAL

    radio = MediaRef(MediaSource.RADIO, "https://radio.test/live")
    resolved = registry.resolve(radio)
    assert resolved.playback_uri == radio.original_uri and resolved.endpoints == [radio.original_uri]
