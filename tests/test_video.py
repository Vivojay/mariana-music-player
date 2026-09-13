import json
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from mariana import video
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.sources import ResolvedMedia


def test_presentation_flags_preserve_legacy_arguments_and_reject_conflicts():
    assert video.presentation_arguments(["play", "12"]) == (["play", "12"], None)
    assert video.presentation_arguments(["play", "current", "--video"]) == (["play", "current"], "video")
    assert video.presentation_arguments(["play", "--audio", "12"]) == (["play", "12"], "audio")
    with pytest.raises(video.VideoUnavailable):
        video.presentation_arguments(["--audio", "--video"])
    with pytest.raises(video.VideoUnavailable):
        video.presentation_arguments(["--video", "--video"])


@pytest.mark.parametrize("source", [MediaSource.URL, MediaSource.YOUTUBE, MediaSource.RADIO])
def test_local_slice_never_resolves_network_sources(tmp_path, source):
    media = MediaRef(source, "https://example.invalid/private?token=secret")
    service = video.LocalVideo(tmp_path, lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media), lambda _row: None)
    with pytest.raises(video.VideoUnavailable, match=r"finite local|Live video"):
        service.request("video")
    assert service._worker is None
    service.close()


def test_probe_checks_actual_tracks_not_filename(monkeypatch, tmp_path):
    source = tmp_path / "misleading.mp3"
    source.touch()
    monkeypatch.setattr(video, "find_executable", lambda name: name)
    calls = []
    tracks = [{"codec_type": "audio"}, {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 360}]

    def probe(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(stdout=json.dumps({"streams": tracks, "format": {"duration": "20"}}).encode())

    monkeypatch.setattr(video.subprocess, "run", probe)
    assert video._probe(source) == ("h264", 20)
    assert "file,pipe,http,tcp" in calls[0]
    tracks[:] = [{"codec_type": "audio"}]
    with pytest.raises(video.VideoUnavailable, match="no video"):
        video._probe(source)
    tracks[:] = [{"codec_type": "audio"}, {"codec_type": "video", "disposition": {"attached_pic": 1}}]
    with pytest.raises(video.VideoUnavailable, match="no video"):
        video._probe(source)
    tracks[:] = [{"codec_type": "video"}]
    with pytest.raises(video.VideoUnavailable, match="Silent video"):
        video._probe(source)


def test_local_source_and_probe_enforce_file_shape_and_media_bounds(monkeypatch, tmp_path):
    with pytest.raises(video.VideoUnavailable, match="finite local"):
        video._local_source(MediaRef(MediaSource.URL, "https://example.org/video"))
    directory_media = MediaRef(MediaSource.LOCAL, str(tmp_path))
    with pytest.raises(video.VideoUnavailable, match="unavailable"):
        video._local_source(directory_media)

    media_file = tmp_path / "video.mp4"
    media_file.touch()
    monkeypatch.setattr(video, "find_executable", lambda name: name)
    payload = {"streams": [
        {"codec_type": "audio"},
        {"codec_type": "video", "codec_name": "h264", "width": 640, "height": 360},
    ], "format": {"duration": "20"}}
    monkeypatch.setattr(video.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        stdout=json.dumps(payload).encode(),
    ))
    payload["format"]["duration"] = "nan"
    with pytest.raises(video.VideoUnavailable, match="finite duration"):
        video._probe(media_file)
    payload["format"]["duration"] = "20"
    payload["streams"][1]["width"] = 8000
    with pytest.raises(video.VideoUnavailable, match="dimensions"):
        video._probe(media_file)
    monkeypatch.setattr(video.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout=b"{" * 64_001))
    with pytest.raises(video.VideoUnavailable, match="inspect"):
        video._probe(media_file)


def test_activation_and_request_lifecycle_boundaries(tmp_path, monkeypatch):
    media_file = tmp_path / "video.mp4"
    media_file.touch()
    media = MediaRef(MediaSource.LOCAL, str(media_file))
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media)

    disabled = video.LocalVideo(tmp_path / "disabled", lambda: snapshot, lambda _row: None)
    monkeypatch.setattr(disabled, "request", lambda *_args, **_kwargs: pytest.fail("Disabled service must stay idle"))
    disabled.activate(media, None)
    disabled.close()

    active = video.LocalVideo(tmp_path / "active", lambda: snapshot, lambda _row: None, enabled=lambda: True)
    active._observed = media
    resolved = ResolvedMedia(media, str(media_file), str(media_file), media.capabilities)
    with monkeypatch.context() as patch:
        patch.setattr(active, "request", lambda *_args, **_kwargs: pytest.fail("Same occurrence must not restart"))
        active.activate(media, resolved)
    assert active._resolved is resolved
    with pytest.raises(video.VideoUnavailable, match="Invalid presentation"):
        active.request("picture")
    active.close()

    idle = video.LocalVideo(tmp_path / "idle", lambda: PlaybackSnapshot(PlaybackState.IDLE), lambda _row: None)
    with pytest.raises(video.VideoUnavailable, match="Start media"):
        idle.request("video")
    idle.close()
    with pytest.raises(video.VideoUnavailable, match="closed"):
        idle.request("audio")

    missing = MediaRef(MediaSource.LOCAL, str(tmp_path / "missing.mp4"))
    unavailable = video.LocalVideo(
        tmp_path / "unavailable", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=missing),
        lambda _row: None,
    )
    with pytest.raises(video.VideoUnavailable, match="unavailable"):
        unavailable.request("video")
    unavailable.close()


def test_window_encoder_reports_cancel_decode_and_cache_failures(monkeypatch, tmp_path):
    service = video.LocalVideo(tmp_path, lambda: PlaybackSnapshot(PlaybackState.IDLE), lambda _row: None)
    monkeypatch.setattr(video, "find_executable", lambda name: name)

    class FinishedProcess:
        def __init__(self, returncode):
            self.returncode = returncode

        def poll(self):
            return self.returncode

    commands = []
    monkeypatch.setattr(video.subprocess, "Popen", lambda command, **_kwargs: (
        commands.append(command) or FinishedProcess(1)
    ))
    with pytest.raises(video.VideoUnavailable, match="could not be decoded"):
        service._encode_window("input", service._window_cache.allocate(), 0, 1, threading.Event(), lambda: True)
    assert "+frag_keyframe+empty_moov+default_base_moof" in commands[0]
    assert "+faststart" not in commands[0]
    assert commands[0][commands[0].index("-tune") + 1] == "zerolatency"

    assert commands[0][-3:] == ["-f", "mp4", "pipe:1"]
    empty = service._window_cache.allocate()
    monkeypatch.setattr(video.subprocess, "Popen", lambda *_args, **_kwargs: FinishedProcess(0))
    with pytest.raises(video.VideoUnavailable, match="cache limit"):
        service._encode_window("input", empty, 0, 1, threading.Event(), lambda: True)

    class RunningProcess(FinishedProcess):
        def __init__(self):
            super().__init__(None)
            self.terminated = False

        def terminate(self):
            self.terminated = True
            self.returncode = 0

        def wait(self, **_kwargs):
            return self.returncode

    running = RunningProcess()
    monkeypatch.setattr(video.subprocess, "Popen", lambda *_args, **_kwargs: running)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(video.WindowSuperseded):
        service._encode_window("input", service._window_cache.allocate(), 0, 1, cancel, lambda: True)
    assert running.terminated
    service.close()


def test_cancelled_preparation_never_publishes_late_result(monkeypatch, tmp_path):
    source = tmp_path / "local.mp4"
    source.touch()
    media = MediaRef(MediaSource.LOCAL, str(source))
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media)
    entered, release = threading.Event(), threading.Event()
    published = []

    def probe(_source):
        entered.set()
        assert release.wait(3)
        return "h264", 2

    monkeypatch.setattr(video, "_probe", probe)
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, published.append)
    try:
        assert service.request("video")["state"] == "preparing"
        assert entered.wait(3)
        assert service.request("audio")["state"] == "off"
        release.set()
    finally:
        release.set()
        service.close()
    assert service.status()["state"] == "off"
    assert not published
    assert not service._worker.is_alive()
    assert not list((tmp_path / "cache").glob("*.mp4"))


def test_local_caption_discovery_is_async_nonfatal_and_identity_bound(monkeypatch, tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"video")
    manual = tmp_path / "chosen.srt"
    manual.write_text("1\n00:00:00,000 --> 00:00:01,000\nManual\n", encoding="utf-8")
    media = MediaRef(MediaSource.LOCAL, str(source))
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media)
    entered, release = threading.Event(), threading.Event()

    def discover(*_args, **_kwargs):
        entered.set()
        assert release.wait(3)
        return ()

    monkeypatch.setattr(video, "discover_caption_tracks", discover)
    monkeypatch.setattr(video, "_probe", lambda _source: ("h264", 10))
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _row: None)
    monkeypatch.setattr(service, "_local_windows", lambda *_args: None)
    try:
        assert service.request("video")["state"] == "preparing"
        assert entered.wait(3)
        assert service.status()["captions"]["auto_status"] == "loading"
        service.load_captions(manual, expected_media=media)
        release.set()
        assert service.status()["captions"]["label"] == "chosen.srt"
        assert service.status()["captions"]["source"] == "manual"
    finally:
        release.set()
        service.close()

    failing = video.LocalVideo(tmp_path / "failure-cache", lambda: snapshot, lambda _row: None)
    monkeypatch.setattr(failing, "_local_windows", lambda *_args: None)
    monkeypatch.setattr(video, "discover_caption_tracks", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError()))
    try:
        failing.request("video")
        deadline = time.monotonic() + 3
        while failing.status()["captions"]["auto_status"] not in {"error", "loaded", "none"}:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert failing.status()["captions"]["auto_status"] == "error"
        assert failing.status()["state"] != "error"
    finally:
        failing.close()


def test_media_change_and_stop_revoke_presentation(tmp_path):
    source = tmp_path / "local.mp4"
    source.touch()
    first = MediaRef(MediaSource.LOCAL, str(source))
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=first, position=4)
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _row: None)
    service._media = first
    service._state = {"revision": 1, "state": "ready", "handle": "a" * 32, "error": None}
    assert service.status()["position_seconds"] == 4
    assert not service.status()["playing"]
    snapshot = PlaybackSnapshot(PlaybackState.IDLE, media=first)
    assert service.status()["state"] == "off"
    service._media = first
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=MediaRef(MediaSource.LOCAL, str(source)))
    assert service.status()["state"] == "off"  # Same identity, different playback occurrence.
    service.close()


def test_mode_request_rechecks_captured_playback_occurrence(tmp_path):
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "first.mp4"))
    other = MediaRef(MediaSource.LOCAL, media.original_uri)
    service = video.LocalVideo(tmp_path, lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=other), lambda _row: None)
    with pytest.raises(video.VideoUnavailable, match="changed"):
        service.request("video", expected_media=media)
    assert service._worker is None
    service.close()




@pytest.mark.parametrize(("media_source", "mode"), [
    (MediaSource.LOCAL, "video"), (MediaSource.LOCAL, "auto"),
    (MediaSource.URL, "auto"),
])
def test_native_preparation_produces_video_without_audio_and_cleans_up(tmp_path, monkeypatch, media_source, mode):
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Native FFmpeg/FFprobe are required for video preparation acceptance")
    source = tmp_path / "fixture.mkv"
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24",
         "-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", "-c:v", "libx264", "-c:a", "aac", str(source)],
        check=True, capture_output=True, timeout=20,
    )
    media = MediaRef(media_source, str(source) if media_source == MediaSource.LOCAL else "https://example.org/video", duration=2)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=0.5)
    completed = threading.Event()
    from mariana.video_sources import VideoTrack, VideoTracks

    @contextmanager
    def local_transport(_track, _cancel):
        yield str(source)

    monkeypatch.setattr(video, "video_track_proxy", local_transport)
    service = video.LocalVideo(
        tmp_path / "cache", lambda: snapshot,
        lambda row: completed.set() if row.get("state") in {"ready", "error"} else None,
        resolve_video=lambda _media, _resolved: VideoTracks(VideoTrack("https://example.org/video")),
    )
    try:
        service.request(mode)
        assert completed.wait(20)
        state = service.status()
        assert state["state"] == "ready", state
        assert state["position_seconds"] == 0.5 and state["playing"] is False
        output = tmp_path / "cache" / f'{state["handle"]}.mp4'
        info = json.loads(subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)],
            check=True, capture_output=True, timeout=10,
        ).stdout)
        assert [track["codec_type"] for track in info["streams"]] == ["video"]
        assert float(info["streams"][0]["duration"]) == pytest.approx(2, abs=0.1)
        assert "fixture" not in str(state) and str(tmp_path) not in str(state)
    finally:
        service.close()
    assert not list((tmp_path / "cache").glob("*.mp4"))
    assert not list((tmp_path / "cache").glob("*.input"))


@pytest.mark.parametrize(("source", "expected"), [
    (MediaSource.YOUTUBE, "audio"), (MediaSource.LOCAL, "auto"),
    (MediaSource.URL, "auto"), (MediaSource.PODCAST, "auto"), (MediaSource.RADIO, "audio"),
])
def test_default_presentation_is_source_sensitive(source, expected):
    assert video.default_presentation(MediaRef(source, "reference")) == expected


def test_automatic_local_audio_is_quiet_and_explicit_video_reports_missing_track(monkeypatch, tmp_path):
    source = tmp_path / "looks-like-video.mp4"
    source.touch()
    media = MediaRef(MediaSource.LOCAL, str(source))
    completed = threading.Event()

    def probe(_path):
        raise video.NoVideoTrack("This media has no video track")

    monkeypatch.setattr(video, "_probe", probe)
    service = video.LocalVideo(tmp_path / "cache", lambda: PlaybackSnapshot(PlaybackState.PAUSED, media=media),
                               lambda _state: completed.set())
    try:
        service.request("auto")
        assert completed.wait(3)
        assert service.status()["state"] == "off"
        assert service.status()["error"] is None
        completed.clear()
        service.request("video")
        assert completed.wait(3)
        assert service.status()["state"] == "error"
        assert service.status()["error"] == "This media has no video track"
    finally:
        service.close()


def test_youtube_default_never_resolves_video_but_explicit_intent_does(monkeypatch, tmp_path):
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk")
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media)
    called = threading.Event()

    def resolve(_media, _resolved):
        called.set()
        raise video.VideoSourceError("No video available")

    service = video.LocalVideo(tmp_path, lambda: snapshot, lambda _state: None,
                               resolve_video=resolve, enabled=lambda: True)
    try:
        service.activate(media, None)
        assert service.status()["state"] == "off"
        assert not called.is_set()
        service.request("video")
        assert called.wait(3)
    finally:
        service.close()


def test_online_worker_rejects_invalid_duration_and_mismatched_recording(monkeypatch, tmp_path):
    from mariana.video_sources import VideoTrack, VideoTracks

    media = MediaRef(MediaSource.URL, "https://example.org/video", duration=30)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media)

    invalid_published = []
    invalid = video.LocalVideo(
        tmp_path / "invalid", lambda: snapshot, invalid_published.append,
        resolve_video=lambda *_args: VideoTracks(VideoTrack("https://cdn.example/video"), duration=8000),
        enabled=lambda: True,
    )
    try:
        invalid.request("video")
        for _ in range(100):
            if invalid.status()["state"] == "error":
                break
            threading.Event().wait(0.01)
        assert invalid.status()["error"] == "Video must have a finite duration of at most two hours"
    finally:
        invalid.close()

    @contextmanager
    def proxy(_track, _cancel):
        yield "bounded-proxy"

    monkeypatch.setattr(video, "video_track_proxy", proxy)
    monkeypatch.setattr(video, "_probe", lambda *_args, **_kwargs: ("h264", 45))
    mismatch = video.LocalVideo(
        tmp_path / "mismatch", lambda: snapshot, lambda _row: None,
        resolve_video=lambda *_args: VideoTracks(VideoTrack("https://cdn.example/video"), duration=30),
        enabled=lambda: True,
    )
    try:
        mismatch.request("video")
        for _ in range(100):
            if mismatch.status()["state"] == "error":
                break
            threading.Event().wait(0.01)
        assert "differs from the active recording" in str(mismatch.status()["error"])
    finally:
        mismatch.close()


def test_local_explicit_audio_suppresses_automatic_probe(monkeypatch, tmp_path):
    source = tmp_path / "real-video.mp4"
    source.touch()
    media = MediaRef(MediaSource.LOCAL, str(source))
    snapshot = PlaybackSnapshot(PlaybackState.BUFFERING, media=media)
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _state: None, enabled=lambda: True)
    monkeypatch.setattr(video, "_probe", lambda *_args: pytest.fail("Explicit audio must not probe video"))
    try:
        service.expect(media, "audio")
        service.activate(None, None)  # The controller stops the previous session first.
        service.activate(media, None)
        assert service.status()["state"] == "off"
    finally:
        service.close()






def test_long_local_media_prefetches_windows_and_rebases_paused_seeks(monkeypatch, tmp_path):
    source = tmp_path / "long.mp4"
    source.write_bytes(b"source")
    media = MediaRef(MediaSource.LOCAL, str(source), duration=4800)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media)
    condition = threading.Condition()
    updates, jobs = [], []
    prefetched = threading.Event()
    monkeypatch.setattr(video, "_probe", lambda _source: ("hevc", 4800))

    def publish(row):
        with condition:
            updates.append(row)
            condition.notify_all()

    def encode(_source, output, start, length, _cancel, still_needed):
        if not still_needed():
            raise video.WindowSuperseded()
        output.write_bytes(b"picture")
        jobs.append((start, length))
        if len(jobs) == 2:
            prefetched.set()

    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, publish)
    monkeypatch.setattr(service, "_encode_window", encode)
    try:
        service.request("auto")
        assert prefetched.wait(3)
        assert jobs[:2] == [
            (0, video.FIRST_WINDOW_SECONDS),
            (video.FIRST_WINDOW_SECONDS - video.WINDOW_OVERLAP_SECONDS, video.WINDOW_SECONDS),
        ]  # Never a whole 80-minute conversion.
        assert service.status()["window_start_seconds"] == 0
        snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=7)
        with condition:
            assert condition.wait_for(lambda: any(
                row.get("window_start_seconds") == video.FIRST_WINDOW_SECONDS - video.WINDOW_OVERLAP_SECONDS
                for row in updates
            ), timeout=3)
        assert service.status()["playing"] is False
        snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=4000)
        assert service.status()["state"] == "preparing"
        assert service.status()["handle"] is None
        with condition:
            assert condition.wait_for(lambda: any(row.get("window_start_seconds") == 3999 for row in updates), timeout=3)
        assert service.status()["position_seconds"] == 4000
        assert not service.status()["playing"]
        assert all(length <= video.WINDOW_SECONDS for _start, length in jobs)
        assert all(row["state"] != "error" for row in updates)
    finally:
        service.close()
    assert not list((tmp_path / "cache").iterdir())


def test_long_online_media_prepares_short_windows_without_whole_file_download(monkeypatch, tmp_path):
    media = MediaRef(MediaSource.URL, "https://example.org/video", duration=4800)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=2400)
    updates, jobs, caption_sources = [], [], []
    ready = threading.Event()
    from mariana.video_sources import VideoTrack, VideoTracks

    @contextmanager
    def transport(track, _cancel):
        assert track.uri == "https://cdn.example/private-video"
        yield "http://127.0.0.1:12345/opaque/media"

    def publish(row):
        updates.append(row)
        if row.get("state") == "ready":
            ready.set()

    service = video.LocalVideo(
        tmp_path / "cache", lambda: snapshot, publish,
        resolve_video=lambda _media, _resolved: VideoTracks(
            VideoTrack("https://cdn.example/private-video"), duration=4800,
        ),
    )
    monkeypatch.setattr(video, "video_track_proxy", transport)
    monkeypatch.setattr(video, "autodetect_embedded_captions", lambda source, *_args, **_kwargs: (
        caption_sources.append(source) or None
    ))
    monkeypatch.setattr(video, "_probe", lambda source, **_kwargs: (
        "h264", 4800,
    ) if source.startswith("http://127.0.0.1:") else pytest.fail("Remote URL escaped the private transport"))

    def encode(source, output, start, length, _cancel, still_needed):
        assert source == "http://127.0.0.1:12345/opaque/media"
        assert still_needed()
        output.write_bytes(b"window")
        jobs.append((start, length))

    monkeypatch.setattr(service, "_encode_window", encode)
    try:
        service.request("video")
        assert ready.wait(3)
        assert jobs[0] == (2399, video.FIRST_WINDOW_SECONDS)
        assert all(length <= video.WINDOW_SECONDS for _start, length in jobs)
        assert service.status()["window_start_seconds"] == 2399
        for _ in range(100):
            if caption_sources:
                break
            threading.Event().wait(0.01)
        assert caption_sources == ["http://127.0.0.1:12345/opaque/media"]
        assert all("cdn.example" not in str(row) for row in updates)
    finally:
        service.close()
    assert not list((tmp_path / "cache").iterdir())


def test_seek_cancels_obsolete_prefetch_without_reporting_playback_failure(monkeypatch, tmp_path):
    source = tmp_path / "movie.mp4"
    source.write_bytes(b"source")
    media = MediaRef(MediaSource.LOCAL, str(source), duration=4800)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media)
    entered, release, ready = threading.Event(), threading.Event(), threading.Event()
    updates = []
    monkeypatch.setattr(video, "_probe", lambda _source: ("hevc", 4800))

    def encode(_source, output, start, _length, _cancel, still_needed):
        if start == video.FIRST_WINDOW_SECONDS - video.WINDOW_OVERLAP_SECONDS:
            entered.set()
            assert release.wait(3)
            assert not still_needed()
            raise video.WindowSuperseded()
        output.write_bytes(b"picture")

    def publish(row):
        updates.append(row)
        if row.get("window_start_seconds") == 2999:
            ready.set()

    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, publish)
    monkeypatch.setattr(service, "_encode_window", encode)
    try:
        service.request("video")
        assert entered.wait(3)
        snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=3000)
        release.set()
        assert ready.wait(3)
        assert all(row["state"] != "error" for row in updates)
        assert service.status()["position_seconds"] == 3000
    finally:
        release.set()
        service.close()
    assert not list((tmp_path / "cache").iterdir())


def test_shutdown_does_not_release_lease_or_remove_window_while_worker_remains_active(tmp_path):
    service = video.LocalVideo(tmp_path / "cache", lambda: PlaybackSnapshot(PlaybackState.IDLE), lambda _row: None)
    window = service._window_cache.allocate()
    service._owned.add(window)
    joined = []
    running = True
    service._worker = SimpleNamespace(join=lambda timeout: joined.append(timeout), is_alive=lambda: running)
    service.close()
    assert joined == [15]
    assert window.exists()
    assert service._window_cache._fd is not None
    other = video.VideoWindowCache(tmp_path / "cache")
    other.allocate()
    assert window.exists()  # A second instance must also respect the live lease.
    other.close()
    running = False
    service.close()
    assert not window.exists()
    assert not list((tmp_path / "cache").iterdir())
