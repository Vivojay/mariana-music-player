"""Exercise real playback entry points with controlled provider responses."""
import os
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from beta import extractor_fallback, youtube_media
from mariana import video, video_cache
from mariana.cli_video import _picture_sample
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.sources import ResolverRegistry
from mariana.video_sources import VideoAccessExpired, VideoTracks
from tests.test_youtube_video_switching import origin, track, wait_ready

URL = "https://www.youtube.com/watch?v=abcdefghijk"


def formats():
    return {"id": "abcdefghijk", "url": "https://cdn.example/audio", "duration": 20, "formats": [
        {"url": "https://cdn.example/video", "acodec": "none", "vcodec": "avc1", "ext": "mp4",
             "protocol": "https", "format_id": "137", "height": 1080}]}


def test_audio_and_video_share_single_extraction_for_exact_account_and_recording(monkeypatch):
    calls = []
    def extract(url, **options):
        calls.append((url, options))
        return formats()
    monkeypatch.setattr(youtube_media, "_extract", extract)
    registry = ResolverRegistry(browser_profile="firefox")
    media = MediaRef(MediaSource.YOUTUBE, URL, duration=20)
    active = registry.resolve(media)
    assert "https://cdn.example/video" not in str(active.metadata)
    result = registry.resolve_video(media, active)
    assert result.from_audio_selection and result.video.format_id == "137" and len(calls) == 1
    assert youtube_media._take_available_picture(URL, "firefox") is None
    registry.resolve(media)
    assert youtube_media._take_available_picture(URL, "chrome") is None
    assert youtube_media._take_available_picture(URL.replace("abcdefghijk", "xxxxxxxxxxx"), "firefox") is None
    assert youtube_media._take_available_picture(URL, "firefox") is not None


def test_hint_cannot_outlive_expiry_or_supply_drm(monkeypatch):
    for extra in ({"has_drm": True}, {"is_live": True}, {"id": "xxxxxxxxxxx"}, {"expires": 1}):
        youtube_media._remember_available_picture(URL, None, dict(formats(), **extra))
        assert youtube_media._take_available_picture(URL, None) is None


def test_expired_audio_hint_resolves_fresh_once_and_keeps_audio(monkeypatch, tmp_path):
    origin(monkeypatch)
    media = MediaRef(MediaSource.YOUTUBE, URL, duration=20)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=9)
    attempts = []
    def resolve(*_):
        attempts.append(1)
        return VideoTracks(track(), duration=20, from_audio_selection=len(attempts) == 1)
    bind = video_cache.VideoByteCache.bind
    def bind_or_expire(cache, source, cancel):
        if len(attempts) == 1:
            raise VideoAccessExpired("expired")
        bind(cache, source, cancel)
    monkeypatch.setattr(video_cache.VideoByteCache, "bind", bind_or_expire)
    monkeypatch.setattr(video, "_probe", lambda *_, **__: ("h264", 20))
    svc = video.LocalVideo(tmp_path, lambda: snapshot, lambda _: None, resolve_video=resolve)
    try:
        svc.request("video")
        wait_ready(svc)
        assert attempts == [1, 1] and snapshot.position == 9
    finally:
        svc.close()


def test_seek_keeps_nearby_blocks_and_old_reader_cannot_move_new_cursor(monkeypatch):
    monkeypatch.setattr(video_cache, "BLOCK_BYTES", 4)
    origin(monkeypatch, data=bytes(range(96)))
    store, cancel = video_cache.VideoByteCache(), threading.Event()
    store.bind(track(), cancel)
    store.limit = 20
    old = store.focus(4)
    new = store.focus(10)
    store.advance(new, 11)
    store.advance(old, 3)
    assert store._cursor == 11
    for block in (0, 11, 12, 2, 3, 4, 5):
        store.block(block, cancel)
    assert {0, 11, 12}.issubset(store.blocks)
    assert store.size == 20
    store._miss.acquire()
    done = threading.Event()
    worker = threading.Thread(target=lambda: (store.block(12, cancel), done.set()))
    worker.start()
    try:
        assert done.wait(1), "cached seek blocked on an unrelated fetch"
    finally:
        store._miss.release()
        worker.join()


def test_stalled_provider_progress_is_available_before_result_and_disappears_when_closed(tmp_path):
    entered, release = threading.Event(), threading.Event()
    media = MediaRef(MediaSource.YOUTUBE, URL, duration=20)
    snap = PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=3)
    def resolve(*_):
        entered.set()
        assert release.wait(3)
        return VideoTracks(track(), duration=20)
    svc = video.LocalVideo(tmp_path, lambda: snap, lambda _: None, resolve_video=resolve)
    try:
        svc.request("video")
        assert entered.wait(1)
        state = svc.host_status()
        sample = _picture_sample(state, tmp_path, 0)
        assert state["stage"] == "Resolving the video format"
        assert "Resolving the video" in sample["message"]
        assert "http" not in str(sample) and sample["source"] is None
        svc.request("audio")
        assert "stage" not in svc.status()
    finally:
        release.set()
        svc.close()


@pytest.mark.parametrize("msg", ["HTTP Error 429", "quota exceeded: timed out", "sign in to confirm your age",
                                  "Unavailable in your country", "video is private", "HTTP Error 403",
                                  "SSL certificate verification failed", "DRM required"])
def test_restricted_outcomes_never_fan_out_to_alternate_extractor(monkeypatch, msg):
    calls = []
    def fail(*_, **__):
        calls.append(1)
        raise youtube_media.YouTubeError(msg)
    monkeypatch.setattr(youtube_media, "_extract", fail)
    monkeypatch.setattr(extractor_fallback, "external_info", lambda *a: pytest.fail("unexpected fallback"))
    with pytest.raises(youtube_media.YouTubeError, match=msg):
        youtube_media.resolve_stream(URL)
    assert len(calls) == 1


def test_transient_resolution_retries_once_or_uses_configured_runtime(monkeypatch):
    def try_resolve(*_, **opts):
        calls.append(opts["socket_timeout"])
        if len(calls) == 1:
            raise youtube_media.YouTubeError("connection reset")
        return {"url": "https://cdn.example/ok"}
    monkeypatch.setattr(youtube_media, "_extract", try_resolve)
    monkeypatch.delenv("MARIANA_YTDLP_BINARY", raising=False)
    calls = []
    assert youtube_media.resolve_stream(URL)["url"].endswith("/ok") and len(calls) == 2
    calls.clear()
    used = []
    def alternate(url, selector, profile):
        used.append((url, selector, profile))
        return {"url": "https://cdn.example/alt"}
    monkeypatch.setattr(extractor_fallback, "external_info", alternate)
    assert youtube_media.resolve_stream(URL, browser_profile="firefox:work")["url"].endswith("/alt")
    assert used == [(URL, "bestaudio/best", "firefox:work")] and len(calls) == 1


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
def test_external_runtime_stdin_stdout_and_explicit_browser_profile(tmp_path, monkeypatch):
    executable = tmp_path / "fixture-yt-dlp"
    executable.write_text(f"""#!{sys.executable}
import sys,json
assert sys.argv[-2:]==['--',{URL!r}] and '--ignore-config' in sys.argv
assert sys.argv[sys.argv.index('--cookies-from-browser')+1]=='firefox:work'
print(json.dumps(dict(url='https://cdn.example/fixture')))
""")
    executable.chmod(0o700)
    monkeypatch.setenv("MARIANA_YTDLP_BINARY", str(executable))
    assert extractor_fallback.external_info(URL, "bestaudio/best", "firefox:work")["url"].endswith("fixture")


def test_deadline_abandons_stuck_lookup_and_stale_result_cannot_reopen(monkeypatch, tmp_path):
    monkeypatch.setattr(video, "RESOLVE_TIMEOUT", .12)
    release, entered = threading.Event(), threading.Event()
    calls = []
    media = MediaRef(MediaSource.YOUTUBE, URL, duration=20)
    snap = PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=2)
    def stuck(*_):
        calls.append(1)
        entered.set()
        release.wait(3)
        return VideoTracks(track(), duration=20)
    svc = video.LocalVideo(tmp_path, lambda: snap, lambda _: None, resolve_video=stuck)
    try:
        for _ in range(2):
            svc.request("video")
            assert entered.wait(1)
            until = time.monotonic() + 1
            while svc.status()["state"] == "preparing" and time.monotonic() < until:
                time.sleep(.01)
            assert "timed out" in svc.status()["error"]
        assert len(calls) == 1
        svc.request("audio")
        release.set()
        assert svc.status()["state"] == "off"
    finally:
        release.set()
        svc.close()


def test_electron_terminal_play_current_requests_window_during_preparation(monkeypatch):
    import main

    media = MediaRef(MediaSource.YOUTUBE, URL, duration=20)
    snap = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=8)
    events = []
    host = SimpleNamespace(enabled=True, emit=lambda name, data: events.append((name, data)))
    service = SimpleNamespace(expect=lambda *_: None, request=lambda *_, **__: {"state": "preparing"},
                              host_status=lambda: {"state": "preparing"})
    monkeypatch.setattr(main, "DESKTOP_CONTROL", host)
    monkeypatch.setattr(main, "VIDEO", service)
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(snapshot=lambda: snap))
    main.local_play_commands(["play", "current", "--video"])
    assert ("video-window", {"open": True}) in events
    main.local_play_commands(["play", "current", "--audio"])
    assert ("video-window", {"open": False}) in events
    assert snap.position == 8 and snap.state == PlaybackState.PAUSED



def test_preflight_and_title_lookup_can_use_explicit_alternate(monkeypatch):
    def offline(*_, **__):
        raise youtube_media.YouTubeError("connection reset")
    monkeypatch.setattr(youtube_media, "_extract", offline)
    monkeypatch.setattr(extractor_fallback, "external_info", lambda *_: {"url": "https://cdn.example/mix", "title": "Track"})
    assert youtube_media.is_resolvable(URL)
    assert youtube_media.media_info(URL)["title"] == "Track"


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixtures")
def test_public_youtube_dl_runs_as_distinct_backend_and_validates_identity(tmp_path, monkeypatch):
    binary = tmp_path / "youtube-dl"
    received = tmp_path / "selector"
    binary.write_text(f"""#!{sys.executable}
import sys, json
from pathlib import Path
args = sys.argv[1:]
assert '--ignore-config' in args and '--no-geo-bypass' in args and args[-2]=='--' and args[-1].startswith('https://www.youtube.com/watch?v=')
assert '&' not in args[-1]
assert '--cookies-from-browser' not in args and '--extractor-retries' not in args
assert args[args.index('--retries')+1]=='0'
Path({str(received)!r}).write_text(args[args.index('--format')+1])
print(json.dumps(dict(id='abcdefghijk',url='https://cdn.example/ok',duration=20)))
""")
    binary.chmod(0o700)
    monkeypatch.delenv("MARIANA_YTDLP_BINARY", raising=False)
    monkeypatch.setenv("MARIANA_YOUTUBE_DL_BINARY", str(binary))
    def missing(*a, **kwargs):
        assert kwargs["geo_bypass"] is False
        raise ModuleNotFoundError("yt_dlp unavailable", name="yt_dlp")
    monkeypatch.setattr(youtube_media, "_extract", missing)
    assert youtube_media.resolve_stream(URL + "&extra=ignored")["url"].endswith("/ok")
    assert received.read_text() == "bestaudio/best"
    assert extractor_fallback.external_info(URL, "bestvideo*+bestaudio/best", None)["id"] == "abcdefghijk"
    assert received.read_text() == "bestvideo+bestaudio/best"
    assert extractor_fallback.external_info(URL, 'bestvideo[protocol=https][vcodec~="^(avc1|av01|vp0?9)"]', None)
    assert "vcodec^=vp9" in received.read_text()
    with pytest.raises(ValueError, match="unrestricted recording"):
        extractor_fallback.external_info(URL.replace("abcdefghijk","bbbbbbbbbbb"), "best", None)


def test_legacy_fallback_preserves_selected_browser_and_does_not_receive_non_youtube_urls(monkeypatch):
    monkeypatch.delenv("MARIANA_YTDLP_BINARY", raising=False)
    monkeypatch.setenv("MARIANA_YOUTUBE_DL_BINARY", "/invalid-path-to-a-binary")
    monkeypatch.setattr(extractor_fallback.subprocess, "Popen", lambda *a, **kw: pytest.fail("must not launch"))
    calls = []
    def extract(*a, **kwargs):
        calls.append(kwargs["browser_profile"])
        if len(calls) == 1:
            raise TimeoutError("connection timed out")
        return {"url":"https://cdn.example/ok"}
    monkeypatch.setattr(youtube_media, "_extract", extract)
    assert youtube_media.resolve_stream(URL, browser_profile="firefox:Default")["url"].endswith("/ok")
    assert calls == ["firefox:Default", "firefox:Default"]
    assert extractor_fallback.external_info("https://elsewhere.example/video", "best", None) is None


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable fixture")
def test_ytdlp_priority_and_no_cascade_to_legacy_on_secondary_denial(tmp_path, monkeypatch):
    preferred = tmp_path / "yt-dlp"
    preferred.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(1)\n")
    preferred.chmod(0o700)
    legacy = tmp_path / "youtube-dl"
    touched = tmp_path / "unexpected"
    legacy.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(touched)!r}).touch()\n")
    legacy.chmod(0o700)
    monkeypatch.setenv("MARIANA_YTDLP_BINARY",str(preferred))
    monkeypatch.setenv("MARIANA_YOUTUBE_DL_BINARY",str(legacy))
    with pytest.raises(ValueError,match='yt-dlp could not resolve'):
        extractor_fallback.external_info(URL,'best',None)
    assert not touched.exists()


def test_hung_extractor_attempts_do_not_hold_playback_caller(monkeypatch):
    gate = threading.Event()
    calls = []
    def stuck(*args, **kwargs):
        calls.append(1)
        gate.wait(3)
        return {"url":"late"}
    monkeypatch.setattr(youtube_media, "_extract", stuck)
    monkeypatch.setattr(youtube_media, "_PYTHON_BUDGET", .05)
    monkeypatch.delenv("MARIANA_YTDLP_BINARY", raising=False)
    monkeypatch.delenv("MARIANA_YOUTUBE_DL_BINARY", raising=False)
    try:
        start = time.monotonic()
        with pytest.raises(TimeoutError, match="timed out"):
            youtube_media.resolve_stream(URL)
        assert time.monotonic()-start < 1 and len(calls)==2
    finally:
        gate.set()
