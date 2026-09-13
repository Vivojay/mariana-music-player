import io
import json
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import replace
from types import SimpleNamespace

import pytest

from mariana import video, video_cache, video_sources
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.video_cache import CachedVideoProxy, VideoByteCache
from mariana.video_sources import VideoSourceError, VideoTrack, VideoTracks


class Response(io.BytesIO):
    def __init__(self, data, headers, status=206):
        super().__init__(data)
        self.status = status
        self.headers = headers

    def getheader(self, key):
        return self.headers.get(key)


def origin(monkeypatch, data=b"0123456789abcdef", *, etag='"version1"'):
    requests = []
    state = {"etag": etag, "data": data}

    def connect(_url):
        connection = SimpleNamespace()

        def request(method, _target, *, headers):
            assert method == "GET"
            start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
            requests.append((start, end))
            body = state["data"]
            end = min(end, len(body) - 1)
            response_headers = {"Content-Type": "video/mp4", "Content-Length": str(end - start + 1),
                                "Content-Range": f"bytes {start}-{end}/{len(body)}"}
            if state["etag"]:
                response_headers["ETag"] = state["etag"]
            connection.response = Response(body[start:end + 1], response_headers)

        connection.request = request
        connection.getresponse = lambda: connection.response
        connection.close = lambda: None
        return connection, "/media"

    monkeypatch.setattr(video_sources, "_connection", connect)
    return requests, state


def track(uri="https://cdn.example/video?signature=private"):
    return VideoTrack(uri, codec="avc1.640028", format_id="137", container="mp4", width=1920, height=1080, fps=60)


def test_cache_reuses_overlapping_ranges_across_viewers_and_signed_url_refresh(monkeypatch):
    requests, _ = origin(monkeypatch)
    cache = VideoByteCache()
    cancel = threading.Event()
    cache.bind(track(), cancel)
    first = cache.block(0, cancel)
    assert first == b"0123456789abcdef"
    cache.bind(track("https://cdn.example/refreshed?signature=other"), cancel)
    assert cache.block(0, cancel) == first
    assert len(requests) == 3  # Two one-byte validations, one body.
    assert cache.statistics()["downloaded_bytes"] == 18
    assert cache.statistics()["reused_bytes"] == 16


def test_cache_does_not_mix_unvalidated_changed_or_different_quality_sources(monkeypatch):
    requests, state = origin(monkeypatch, etag=None)
    cache = VideoByteCache()
    cancel = threading.Event()
    cache.bind(track(), cancel)
    cache.block(0, cancel)
    cache.bind(track("https://cdn.example/new"), cancel)
    assert cache.size == 0  # No strong validator: renewed URLs cannot reuse old bytes.
    cache.block(0, cancel)
    state["etag"] = '"changed"'
    cache.bind(track(), cancel)
    assert cache.size == 0
    cache.block(0, cancel)
    cache.bind(replace(track(), format_id="399", codec="av01", height=2160), cancel)
    assert cache.size == 0
    assert len(requests) == 7


def test_byte_budget_lru_expiry_clear_and_cancellation(monkeypatch):
    monkeypatch.setattr(video_cache, "BLOCK_BYTES", 4)
    requests, _ = origin(monkeypatch)
    clock = [0.0]
    cache = VideoByteCache(clock=lambda: clock[0])
    cache.limit = 8
    cancel = threading.Event()
    cache.bind(track(), cancel)
    for index in (0, 1, 0, 2):
        cache.block(index, cancel)
    assert list(cache.blocks) == [0, 2] and cache.size == 8
    cache.block(1, cancel)
    assert len(requests) == 5
    clock[0] = 601
    assert cache.expired()
    cache.bind(track(), cancel)
    assert not cache.blocks
    cache.block(0, cancel)
    cache.clear()
    assert cache.statistics()["cached_bytes"] == 0
    cancel.set()
    before = len(requests)
    with pytest.raises(VideoSourceError, match="cancelled"):
        cache.block(0, cancel)
    assert len(requests) == before


@pytest.mark.parametrize("headers,status", [
    ({"Content-Range": "bytes 1-1/5", "Content-Length": "1"}, 206),
    ({"Content-Range": "bytes 0-0/5", "Content-Length": "5"}, 206),
    ({"Content-Range": "bytes 0-0/5", "Content-Length": "1"}, 200),
    ({"Content-Range": "bytes 0-0/5", "Content-Length": "1", "Content-Type": "text/html"}, 206),
])
def test_hostile_range_descriptors_are_rejected(headers, status):
    with pytest.raises(VideoSourceError):
        VideoByteCache._descriptor(Response(b"x", headers, status), 0, 0)


def test_concurrent_misses_download_one_block(monkeypatch):
    requests, _ = origin(monkeypatch)
    cache = VideoByteCache()
    cancel = threading.Event()
    cache.bind(track(), cancel)
    results = []
    workers = [threading.Thread(target=lambda: results.append(cache.block(0, cancel))) for _ in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(2)
        assert not worker.is_alive()
    assert len(results) == 4 and len(requests) == 2


def test_native_proxy_preserves_original_bytes_and_revokes_cancelled_capability(monkeypatch):
    origin(monkeypatch)
    cache = VideoByteCache()
    cancel = threading.Event()
    cache.bind(track(), cancel)
    proxy = CachedVideoProxy(cache, cancel)
    proxy.start()
    try:
        for start, end in ((2, 5), (4, 9)):
            request = urllib.request.Request(proxy.url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(request, timeout=2) as response:
                assert response.read() == b"0123456789abcdef"[start:end + 1]
                assert response.status == 206
                assert response.headers["Content-Range"] == f"bytes {start}-{end}/16"
        assert cache.downloaded == 17
        cancel.set()
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(proxy.url, timeout=2)
        assert error.value.code == 404
    finally:
        proxy.close()


def wait_ready(service):
    deadline = time.monotonic() + 3
    while service.status()["state"] == "preparing":
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert service.status()["state"] == "ready", service.status()


def test_repeated_toggles_keep_playback_position_session_and_source_bytes(monkeypatch, tmp_path):
    requests, _ = origin(monkeypatch)
    selected = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", duration=200)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=selected, position=81.125)
    probes = []
    resolves = []
    monkeypatch.setattr(video, "_probe", lambda *args, **kwargs: probes.append(args) or ("h264", 200))
    service = video.LocalVideo(tmp_path, lambda: snapshot, lambda _row: None,
        resolve_video=lambda *_: resolves.append(True) or VideoTracks(track(), duration=200))
    try:
        assert service.request("video")["state"] == "preparing"
        wait_ready(service)
        first = service.status()
        assert first["transport"] == "source"
        assert "resource" not in first and "signature" not in str(first)
        assert service.host_status()["resource"].startswith("http://127.0.0.1:")
        service._youtube_cache.block(0, threading.Event())
        assert service.request("video")["handle"] == first["handle"]
        assert service.request("audio")["state"] == "off"
        assert "resource" not in service.host_status()
        snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=selected, position=86.75)
        service.request("video")
        wait_ready(service)
        assert service.status()["position_seconds"] == 86.75
        assert service.status()["handle"] != first["handle"]
        assert service.status()["playing"]
        assert len(resolves) == 1 and len(probes) == 1
        assert service._youtube_cache.block(0, threading.Event()) == b"0123456789abcdef"
        assert len(requests) == 2
        assert not list(tmp_path.iterdir())  # No transcode files or persistent URLs.
    finally:
        service.close()
    assert service._youtube_cache is None


def test_slow_resolution_is_nonblocking_and_cancelled_result_cannot_open_picture(monkeypatch, tmp_path):
    entered, release = threading.Event(), threading.Event()
    selected = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", duration=20)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=selected, position=6)

    def resolve(*_):
        entered.set()
        assert release.wait(3)
        return VideoTracks(track(), duration=20)

    monkeypatch.setattr(video_sources, "_connection", lambda *_: pytest.fail("Cancelled work must not connect"))
    published = []
    service = video.LocalVideo(tmp_path, lambda: snapshot, published.append, resolve_video=resolve)
    try:
        assert service.request("video")["state"] == "preparing"
        assert entered.wait(2)
        assert service.request("audio")["state"] == "off"
        release.set()
        assert snapshot.position == 6 and snapshot.state == PlaybackState.PLAYING
    finally:
        release.set()
        service.close()
    assert not any(row["state"] == "ready" for row in published)


def test_native_source_keeps_resolution_frame_rate_and_video_only_packets(monkeypatch, tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Native FFmpeg/FFprobe are required")
    source = tmp_path / "picture.mp4"
    subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=1920x1080:rate=60", "-t", "3", "-an", "-c:v", "libx264",
                    "-preset", "ultrafast", "-movflags", "+faststart", str(source)],
                   check=True, capture_output=True, timeout=30)
    original = source.read_bytes()
    requests, _ = origin(monkeypatch, original)
    selected = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", duration=3)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=selected, position=1.5)
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _row: None,
                              resolve_video=lambda *_: VideoTracks(track(), duration=3))
    try:
        service.request("video")
        wait_ready(service)
        url = service.host_status()["resource"]
        info = json.loads(subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", url],
                                        check=True, capture_output=True, timeout=10).stdout)
        assert [(row["codec_type"], row["width"], row["height"], row["r_frame_rate"])
                for row in info["streams"]] == [("video", 1920, 1080, "60/1")]
        with urllib.request.urlopen(url, timeout=5) as response:
            assert response.read() == original
        assert service.status()["position_seconds"] == 1.5
        assert service.status()["playing"] is False
        assert not (tmp_path / "cache").exists()
        assert all(end - start < video_cache.BLOCK_BYTES for start, end in requests)
    finally:
        service.close()


def test_resolver_requests_uncapped_picture_only_formats(monkeypatch):
    from beta import youtube_media

    calls = []
    monkeypatch.setattr(youtube_media, "_extract", lambda url, **kwargs: calls.append(kwargs) or {
        "url": "https://cdn.example/video", "protocol": "https", "format_id": "399",
        "ext": "mp4", "vcodec": "av01", "acodec": "none", "width": 3840, "height": 2160,
        "fps": 60, "duration": 300,
    })
    resolved = youtube_media.resolve_video_tracks("https://www.youtube.com/watch?v=abcdefghijk", native=True)
    assert "height<=" not in calls[0]["format"] and "bestaudio" not in calls[0]["format"]
    assert resolved.audio is None
    assert (resolved.video.height, resolved.video.fps, resolved.video.codec) == (2160, 60, "av01")
    from yt_dlp import YoutubeDL

    with YoutubeDL({"quiet": True, "skip_download": True}) as extractor:
        select = extractor.build_format_selector(calls[0]["format"])
        formats = [
            {"format_id": "low", "url": "https://cdn.example/low", "protocol": "https",
             "vcodec": "avc1", "acodec": "none", "ext": "mp4", "height": 720},
            {"format_id": "high", "url": "https://cdn.example/high", "protocol": "https",
             "vcodec": "av01", "acodec": "none", "ext": "mp4", "height": 2160},
        ]
        selected = list(select({"formats": formats, "incomplete_formats": False, "has_merged_format": False}))
        assert selected[0]["format_id"] == "high"


def test_transfer_budget_and_midstream_representation_changes_fail_safely(monkeypatch):
    monkeypatch.setattr(video_cache, "BLOCK_BYTES", 4)
    _, state = origin(monkeypatch)
    cache = VideoByteCache()
    cancel = threading.Event()
    cache.bind(track(), cancel)
    cache.block(0, cancel)
    state["etag"] = '"replaced"'
    with pytest.raises(VideoSourceError, match="source changed"):
        cache.block(1, cancel)
    assert cache.size == 0
    cache.downloaded = video_cache.MAX_PROXY_BYTES
    with pytest.raises(VideoSourceError, match="budget"):
        cache.block(0, cancel)


def test_expired_live_transport_can_be_retried_without_changing_audio(monkeypatch, tmp_path):
    _, state = origin(monkeypatch)
    selected = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", duration=20)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=selected, position=9.5)
    monkeypatch.setattr(video, "_probe", lambda *_args, **_kwargs: ("h264", 20))
    resolutions = []
    service = video.LocalVideo(tmp_path, lambda: snapshot, lambda _row: None,
                              resolve_video=lambda *_: resolutions.append(True) or VideoTracks(track(), duration=20))
    try:
        service.request("video")
        wait_ready(service)
        state["etag"] = '"replacement"'
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(service.host_status()["resource"], timeout=2)
        assert service.status()["state"] == "error"
        assert "resource" not in service.host_status()
        service.request("video")
        wait_ready(service)
        assert len(resolutions) == 2
        assert snapshot.position == 9.5 and snapshot.state == PlaybackState.PLAYING
    finally:
        service.close()


def test_new_media_rejects_stale_picture_and_discards_previous_cache(monkeypatch, tmp_path):
    origin(monkeypatch)
    first = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", duration=20)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=first)
    monkeypatch.setattr(video, "_probe", lambda *_args, **_kwargs: ("h264", 20))
    service = video.LocalVideo(tmp_path, lambda: snapshot, lambda _row: None,
                              resolve_video=lambda *_: VideoTracks(track(), duration=20))
    try:
        service.request("video")
        wait_ready(service)
        service._youtube_cache.block(0, threading.Event())
        snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=MediaRef(MediaSource.YOUTUBE, "different"))
        assert service.host_status()["state"] == "off"
        service._expire_youtube_cache()
        assert service._youtube_cache is None
        assert service._youtube_tracks is None
    finally:
        service.close()
