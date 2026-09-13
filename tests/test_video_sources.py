import io
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from mariana import video_sources as source
from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.sources import ResolvedMedia, ResolverRegistry


class Response(io.BytesIO):
    def __init__(self, data=b"video", *, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(data)), "Content-Type": "video/mp4"}

    def getheader(self, name):
        return self.headers.get(name)


def connections(monkeypatch, responses):
    calls = []
    closed = []

    def connect(url):
        response = responses.pop(0)
        return SimpleNamespace(request=lambda *args, **kwargs: calls.append((url, args, kwargs)),
                               getresponse=lambda: response, close=lambda: closed.append(url)), "/file"

    monkeypatch.setattr(source, "_connection", connect)
    return calls, closed


def test_file_retrieval_is_bounded_and_strips_headers_across_origins(monkeypatch, tmp_path):
    calls, closed = connections(monkeypatch, [
        Response(status=302, headers={"Location": "https://second.example/file"}), Response(),
    ])
    output = tmp_path / "input"
    source.fetch_video_file(source.VideoTrack("https://first.example/file", {"Referer": "https://first.example/private"}),
                            output, threading.Event())
    assert output.read_bytes() == b"video"
    assert calls[0][2]["headers"]["Referer"] == "https://first.example/private"
    assert "Referer" not in calls[1][2]["headers"]
    assert len(closed) == 2


@pytest.mark.parametrize("response", [
    Response(status=403),
    Response(status=500),
    Response(headers={"Content-Length": str(source.MAX_INPUT_BYTES + 1)}),
    Response(headers={"Content-Length": "invalid"}),
    Response(headers={"Content-Length": "10"}),
    Response(headers={"Content-Type": "application/vnd.apple.mpegurl"}),
    Response(status=302, headers={"Location": "http://insecure.example/file"}),
])
def test_refuses_expired_oversized_incomplete_and_manifest_sources(monkeypatch, tmp_path, response):
    _, closed = connections(monkeypatch, [response])
    with pytest.raises(source.VideoSourceError) as error:
        source.fetch_video_file(source.VideoTrack("https://provider.example/file?secret=hidden"),
                                tmp_path / "input", threading.Event())
    assert "secret" not in str(error.value) and "provider.example" not in str(error.value)
    assert len(closed) == 1


def test_cancel_and_credentials_refuse_before_connection(monkeypatch, tmp_path):
    monkeypatch.setattr(source, "_connection", lambda _url: pytest.fail("Must not connect"))
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(source.VideoSourceError, match="cancelled"):
        source.fetch_video_file(source.VideoTrack("https://example.org/file"), tmp_path / "input", cancel)
    with pytest.raises(source.VideoSourceError, match="authenticated"):
        source.fetch_video_file(source.VideoTrack("https://example.org/file", {"Cookie": "secret"}),
                                tmp_path / "input", threading.Event())


@pytest.mark.parametrize("url", [
    "file:///private/video.mp4",
    "https://user:password@example.org/video.mp4",
    "https://example.org/video.mp4\nInjected: value",
])
def test_transport_rejects_non_public_or_credential_bearing_references(url):
    with pytest.raises(source.VideoSourceError, match="public HTTP or HTTPS"):
        source._connection(url)


def test_request_metadata_and_ranges_are_strictly_validated(monkeypatch):
    headers = source._request_headers(source.VideoTrack(
        "https://example.org/video", {"X-Private": "ignored", "Origin": "https://public.example"},
    ))
    assert headers["Origin"] == "https://public.example" and "X-Private" not in headers
    with pytest.raises(source.VideoSourceError, match="metadata"):
        source._request_headers(source.VideoTrack("https://example.org/video", {"Referer": "bad\nvalue"}))
    with pytest.raises(source.VideoSourceError, match="metadata"):
        source._request_headers(source.VideoTrack("https://example.org/video", {"Referer": "x" * 8193}))
    monkeypatch.setattr(source, "_connection", lambda _url: pytest.fail("Invalid range must not connect"))
    with pytest.raises(source.VideoSourceError, match="range"):
        source._open_response(
            source.VideoTrack("https://example.org/video"), "GET", threading.Event(),
            source.time.monotonic() + 1, byte_range="items=1-2",
        )
    with pytest.raises(source.VideoSourceError, match="timed out"):
        source._open_response(
            source.VideoTrack("https://example.org/video"), "GET", threading.Event(), 0,
        )


def test_redirect_without_a_location_is_refused_and_closed(monkeypatch):
    _, closed = connections(monkeypatch, [Response(status=302, headers={})])
    with pytest.raises(source.VideoSourceError, match="redirected"):
        source._open_response(
            source.VideoTrack("https://example.org/video"), "GET", threading.Event(),
            source.time.monotonic() + 1,
        )
    assert closed == ["https://example.org/video"]


def test_fetch_cancellation_and_streaming_size_limit_are_enforced(monkeypatch, tmp_path):
    cancel = threading.Event()

    class CancellingResponse(Response):
        def read1(self, size=-1):
            value = super().read1(size)
            cancel.set()
            return value

    connections(monkeypatch, [CancellingResponse(b"first", headers={"Content-Type": "video/mp4"})])
    with pytest.raises(source.VideoSourceError, match="cancelled"):
        source.fetch_video_file(source.VideoTrack("https://example.org/video"), tmp_path / "cancelled", cancel)

    monkeypatch.setattr(source, "MAX_INPUT_BYTES", 3)
    connections(monkeypatch, [Response(b"video", headers={"Content-Type": "video/mp4"})])
    with pytest.raises(source.VideoSourceError, match="512 MiB"):
        source.fetch_video_file(source.VideoTrack("https://example.org/video"), tmp_path / "oversized", threading.Event())


def test_loopback_proxy_serves_ranges_without_exposing_the_remote_reference(monkeypatch):
    calls, closed = connections(monkeypatch, [
        Response(b"deo", status=206, headers={
            "Content-Length": "3", "Content-Type": "video/mp4", "Content-Range": "bytes 2-4/5",
        }),
    ])
    track = source.VideoTrack("https://provider.example/video?signature=private", {"Referer": "https://provider.example"})
    with source.video_track_proxy(track, threading.Event()) as url:
        assert "provider.example" not in url and "signature" not in url
        request = urllib.request.Request(url, headers={"Range": "bytes=2-4"})
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 206
            assert response.read() == b"deo"
    assert calls[0][2]["headers"]["Range"] == "bytes=2-4"
    assert calls[0][2]["headers"]["Referer"] == "https://provider.example"
    assert len(closed) == 1


def test_loopback_proxy_refuses_provider_that_ignores_nonzero_range(monkeypatch):
    connections(monkeypatch, [Response(status=200)])
    with source.video_track_proxy(source.VideoTrack("https://provider.example/video"), threading.Event()) as url:
        request = urllib.request.Request(url, headers={"Range": "bytes=100-"})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=2)
    assert error.value.code == 502


def test_loopback_proxy_supports_head_and_refuses_unknown_paths_and_ranges(monkeypatch):
    calls, _closed = connections(monkeypatch, [Response()])
    with source.video_track_proxy(source.VideoTrack("https://provider.example/video"), threading.Event()) as url:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request, timeout=2) as response:
            assert response.status == 200 and response.read() == b""
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(url.replace("/media", "/missing"), timeout=2)
        with pytest.raises(urllib.error.HTTPError) as invalid_range:
            urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "items=1-2"}), timeout=2)
    assert missing.value.code == 404 and invalid_range.value.code == 416
    assert calls[0][1][0] == "GET"


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_private_destinations_rejected_before_socket_connection(monkeypatch, address):
    monkeypatch.setattr(source.socket, "getaddrinfo", lambda *_args, **_kwargs: [(0, 0, 0, "", (address, 443))])
    monkeypatch.setattr(source.socket, "create_connection", lambda *_args, **_kwargs: pytest.fail("Must not connect"))
    with pytest.raises(source.VideoSourceError, match="Private network"):
        source._connection("https://provider.example/file")


def test_public_connection_pins_address_but_verifies_original_tls_hostname(monkeypatch):
    observed = []
    sock = SimpleNamespace(settimeout=lambda seconds: observed.append(("timeout", seconds)), close=lambda: None)
    monkeypatch.setattr(source.socket, "getaddrinfo", lambda *_args, **_kwargs: [(0, 0, 0, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(source.socket, "create_connection", lambda address, **_kwargs: observed.append(address) or sock)
    monkeypatch.setattr(source.ssl, "create_default_context", lambda: SimpleNamespace(
        wrap_socket=lambda value, *, server_hostname: observed.append(("tls", server_hostname)) or value,
    ))
    connection, target = source._connection("https://provider.example/video?sig=private")
    assert ("8.8.8.8", 443) in observed
    assert ("tls", "provider.example") in observed
    assert connection.host == "provider.example" and connection.sock is sock
    assert target == "/video?sig=private"


def test_public_http_connection_skips_tls_and_tls_setup_failure_closes_socket(monkeypatch):
    observed = []
    sock = SimpleNamespace(settimeout=lambda seconds: observed.append(("timeout", seconds)),
                           close=lambda: observed.append("closed"))
    monkeypatch.setattr(source.socket, "getaddrinfo", lambda *_args, **_kwargs: [(0, 0, 0, "", ("8.8.8.8", 80))])
    monkeypatch.setattr(source.socket, "create_connection", lambda *_args, **_kwargs: sock)
    connection, target = source._connection("http://provider.example/video")
    assert connection.sock is sock and target == "/video"

    monkeypatch.setattr(source.socket, "getaddrinfo", lambda *_args, **_kwargs: [(0, 0, 0, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(source.ssl, "create_default_context", lambda: SimpleNamespace(
        wrap_socket=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("TLS failed")),
    ))
    with pytest.raises(RuntimeError, match="TLS failed"):
        source._connection("https://provider.example/video")
    assert "closed" in observed


def test_same_origin_redirect_retains_range_metadata(monkeypatch):
    calls, closed = connections(monkeypatch, [
        Response(status=302, headers={"Location": "/next"}),
        Response(b"ok", status=206, headers={"Content-Length": "2", "Content-Type": "video/mp4"}),
    ])
    connection, response = source._open_response(
        source.VideoTrack("https://provider.example/video", {"Referer": "https://provider.example/page"}),
        "GET", threading.Event(), source.time.monotonic() + 1, byte_range="bytes=1-2",
    )
    try:
        assert response.status == 206
        assert calls[1][2]["headers"]["Range"] == "bytes=1-2"
        assert calls[1][2]["headers"]["Referer"] == "https://provider.example/page"
    finally:
        connection.close()
    assert len(closed) == 2


def test_cross_origin_redirect_retains_only_the_validated_range(monkeypatch):
    calls, closed = connections(monkeypatch, [
        Response(status=302, headers={"Location": "https://second.example/next"}),
        Response(b"ok", status=206, headers={"Content-Length": "2", "Content-Type": "video/mp4"}),
    ])
    connection, response = source._open_response(
        source.VideoTrack("https://first.example/video", {"Referer": "https://first.example/page"}),
        "GET", threading.Event(), source.time.monotonic() + 1, byte_range="bytes=1-2",
    )
    try:
        assert response.status == 206
        assert calls[1][2]["headers"]["Range"] == "bytes=1-2"
        assert "Referer" not in calls[1][2]["headers"]
    finally:
        connection.close()
    assert len(closed) == 2


def test_fetch_wraps_unexpected_transport_failures(monkeypatch, tmp_path):
    monkeypatch.setattr(source, "_open_response", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private detail")))
    with pytest.raises(source.VideoSourceError, match="audio playback is unchanged") as error:
        source.fetch_video_file(
            source.VideoTrack("https://provider.example/video?token=private"),
            tmp_path / "video", threading.Event(),
        )
    assert "private" not in str(error.value)


def test_extractor_preserves_separate_matched_tracks_and_does_not_mutate_media(monkeypatch):
    from beta import youtube_media

    calls = []
    payload = {"duration": 30, "http_headers": {"User-Agent": "Provider"}, "requested_formats": [
        {"url": "https://cdn.example/audio", "acodec": "opus", "vcodec": "none", "protocol": "https"},
        {"url": "https://cdn.example/video", "acodec": "none", "vcodec": "avc1", "protocol": "https"},
    ]}
    monkeypatch.setattr(youtube_media, "_extract", lambda url, **kwargs: calls.append((url, kwargs)) or payload)
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk")
    original = media.to_dict()
    tracks = ResolverRegistry(browser_profile="firefox").resolve_video(media)
    assert tracks.video.uri.endswith("/video") and tracks.audio.uri.endswith("/audio")
    assert tracks.duration == 30
    assert calls[0][1]["browser_profile"] == "firefox"
    assert media.to_dict() == original
    assert "cdn.example" not in repr(tracks)
    payload["is_live"] = True
    with pytest.raises(source.VideoSourceError, match="Live"):
        ResolverRegistry().resolve_video(media)


def test_direct_resolution_reuses_current_transport_without_changing_identity():
    media = MediaRef(MediaSource.URL, "https://example.org/canonical", title="Known title")
    resolved = ResolvedMedia(media, "https://cdn.example/current?sig=secret", media.original_uri, media.capabilities)
    tracks = ResolverRegistry().resolve_video(media, resolved)
    assert tracks.video.uri == resolved.playback_uri
    assert media.title == "Known title" and media.original_uri == "https://example.org/canonical"


def test_registry_video_resolution_rejects_live_unsupported_and_authenticated_transports(monkeypatch):
    registry = ResolverRegistry()
    live = MediaCapabilities(finite=False, live=True, seekable=False)
    with pytest.raises(source.VideoSourceError, match="Live"):
        registry.resolve_video(MediaRef(MediaSource.URL, "https://example.org/live", capabilities=live))
    with pytest.raises(source.VideoSourceError, match="does not support"):
        registry.resolve_video(MediaRef(MediaSource.LOCAL, __file__))

    media = MediaRef(MediaSource.PODCAST, "https://example.org/episode.mp3")
    authenticated = ResolvedMedia(
        media, "https://cdn.example/episode", media.original_uri, media.capabilities,
        metadata={"credential_ref": "private-reference"},
    )
    with pytest.raises(source.VideoSourceError, match="authenticated"):
        registry.resolve_video(media, authenticated)

    resolved_live = ResolvedMedia(media, "https://cdn.example/live", media.original_uri, live)
    with pytest.raises(source.VideoSourceError, match="Live"):
        registry.resolve_video(media, resolved_live)

    from beta import youtube_media
    monkeypatch.setattr(youtube_media, "resolve_video_tracks", lambda url, **_kwargs: url)
    extractor = MediaRef(MediaSource.URL, "https://soundcloud.com/artist/track")
    assert registry.resolve_video(extractor) == extractor.original_uri
