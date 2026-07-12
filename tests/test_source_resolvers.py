from pathlib import Path
import pytest
import requests

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.sources import (
    FailureCode,
    HttpResolver,
    LocalResolver,
    MediaFailure,
    ResolverRegistry,
    YouTubeResolver,
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
