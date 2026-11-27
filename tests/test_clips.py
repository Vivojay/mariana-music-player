import json
import math
import shutil
import struct
import subprocess
import threading
import time
import wave
from dataclasses import replace
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from mariana.clip_share import start_handoff
from mariana.clips import ClipSession, render_clip, source_for
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def playing(tmp_path):
    path = tmp_path / "Duo clip.wav"
    with wave.open(str(path), "wb") as sound:
        sound.setparams((1, 2, 8000, 0, "NONE", ""))
        # Distinct constant PCM segments make accurate seeks measurable.
        sound.writeframes(b"".join(struct.pack("<h", 1100 if i < 4000 else -2100) for i in range(8000)))
    return PlaybackSnapshot(PlaybackState.PAUSED, position=0.25, duration=1.0,
                            media=MediaRef(MediaSource.LOCAL, str(path), title="Duo"))


@pytest.fixture
def tools_available():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for actual clip rendering")


def test_marks_follow_current_identity_and_restore_after_invalid_range(playing, tmp_path):
    clips = ClipSession()
    assert "0:00.250" in clips.command(["start"], playing, tmp_path)
    clips.command(["end", "0:00.750"], playing, tmp_path)
    for value in ("0", "999", "nan", "-1"):
        with pytest.raises(ValueError):
            clips.command(["end", value], playing, tmp_path)
    assert clips.project(playing)["end_seconds"] == 0.75
    second = replace(playing, media=replace(playing.media, stable_id="second-recording"))
    assert clips.project(second)["start_seconds"] is None
    with pytest.raises(ValueError, match="both clip marks"):
        clips.command(["export"], second, tmp_path)


def test_unavailable_or_blocked_sources(playing, tmp_path):
    for source in [MediaSource.YOUTUBE, MediaSource.RECOMMENDATION, MediaSource.RADIO]:
        media = MediaRef(source, "https://example.org/track.mp3", duration=1)
        assert not ClipSession().project(replace(playing, media=media))["available"]
    for settings in [dict(live=True), dict(finite=False), dict(seekable=False), dict(downloadable=False)]:
        media = MediaRef(MediaSource.URL, "https://example.org/audio.ogg", capabilities=MediaCapabilities(**settings))
        assert not ClipSession().project(replace(playing, media=media))["available"]
    recommended = replace(playing.media, source=MediaSource.RECOMMENDATION)
    assert source_for(replace(playing, media=recommended)).uri == playing.media.original_uri
    assert not ClipSession().project(replace(playing, media=None))["available"]
    protected = MediaRef(MediaSource.PODCAST, "https://example.org/a.mp3", resolver_data={"drm": True})
    assert not ClipSession().project(replace(playing, media=protected))["available"]


def test_render_exact_trim_without_touching_audio_or_existing_destination(playing, tmp_path, tools_available):
    original = Path(playing.media.original_uri).read_bytes()
    source = source_for(playing)
    dest = tmp_path / "selected audio.wav"
    output = render_clip(source, 0.25, 0.75, "auto", tmp_path, destination=dest)
    with wave.open(str(output)) as sound:
        assert sound.getnframes() == 4000
        samples = struct.unpack("<4000h", sound.readframes(4000))
        assert set(samples[:2000]) == {1100}
        assert set(samples[2000:]) == {-2100}
    assert Path(source.uri).read_bytes() == original
    with pytest.raises(ValueError, match="already exists"):
        render_clip(source, 0.25, 0.75, "auto", tmp_path, destination=dest)
    with pytest.raises(ValueError, match="requires"):
        render_clip(source, 0.25, 0.75, "mp3", tmp_path, destination=dest)
    assert not list(tmp_path.glob(".mariana-clip-*"))


@pytest.mark.parametrize(("fmt", "video"), [("auto", False), ("mp3", False), ("story", True)])
def test_real_encoded_clip_and_audio_story(playing, tmp_path, tools_available, fmt, video):
    path = render_clip(source_for(playing), 0.12, 0.82, fmt, tmp_path)
    metadata = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]))
    assert math.isclose(float(metadata["format"]["duration"]), 0.7, abs_tol=0.25)
    assert any(s["codec_type"] == "audio" for s in metadata["streams"])
    if video:
        track = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        assert (track["width"], track["height"]) == (720, 1280)


def test_video_export_keeps_source_picture_and_audio(playing, tmp_path, tools_available):
    movie = tmp_path / "source.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=96x64:d=1",
                    "-i", playing.media.original_uri, "-c:v", "libx264", "-c:a", "aac", "-shortest", str(movie)], check=True)
    current = replace(playing, media=MediaRef(MediaSource.LOCAL, str(movie)))
    path = render_clip(source_for(current), 0.1, 0.6, "auto", tmp_path)
    streams = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)]))["streams"]
    assert [(s["codec_type"], s.get("width")) for s in streams] == [("video", 96), ("audio", None)]


def test_finite_direct_url_render(playing, tmp_path, tools_available):
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/Duo%20clip.wav"
            snapshot = replace(playing, media=MediaRef(MediaSource.PODCAST, url))
            path = render_clip(source_for(snapshot), 0.25, 0.5, "wav", tmp_path)
            with wave.open(str(path)) as output:
                assert output.getnframes() == 2000
        finally:
            server.shutdown()
            thread.join(timeout=1)


def test_private_file_share_read_and_expiry(playing, tmp_path):
    path = Path(playing.media.original_uri)
    url = start_handoff(path, lifetime=2)
    browser = build_opener(ProxyHandler({}))
    with browser.open(url, timeout=2) as opened:
        page = opened.read()
        assert b"Share file" in page and b"navigator.canShare" in page
        assert opened.headers["Referrer-Policy"] == "no-referrer"
    with browser.open(url + "file", timeout=2) as opened:
        assert opened.read() == path.read_bytes()
        assert opened.headers["Content-Type"] == "audio/wav"
    for request in (url + "../file", Request(url, headers={"Host": "elsewhere.example"})):
        with pytest.raises(HTTPError) as caught:
            browser.open(request, timeout=2)
        assert caught.value.code == 404
    path.write_bytes(b"changed")
    with pytest.raises(HTTPError) as caught:
        browser.open(url + "file", timeout=2)
    assert caught.value.code == 410


def test_desktop_validates_media_and_renders_asynchronously(playing, tmp_path, tools_available):
    clips = ClipSession()
    payload = {"media_id": playing.media.stable_id, "start_seconds": 0.1, "end_seconds": 0.3, "format": "wav"}
    with pytest.raises(ValueError, match="changed"):
        clips.desktop("clip.export", {**payload, "media_id": "stale"}, playing, tmp_path)
    with pytest.raises(ValueError):
        clips.desktop("clip.export", {**payload, "start_seconds": True}, playing, tmp_path)
    with pytest.raises(ValueError):
        clips.desktop("clip.share", {**payload, "path": "/tmp/no"}, playing, tmp_path)
    result = clips.desktop("clip.export", payload, playing, tmp_path)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = clips.desktop("clip.job", {"job_id": result["job_id"]}, playing, tmp_path)
        if result["phase"] != "rendering":
            break
        time.sleep(0.05)
    assert result["phase"] == "ready", result
    assert Path(result["path"]).is_file()


def test_timestamp_link_uses_real_recording_and_selected_start(playing, tmp_path):
    media = MediaRef(MediaSource.YOUTUBE, "https://music.youtube.com/watch?v=abcdefghijk&list=private-list&si=secret")
    selected = replace(playing, media=media, position=36.75, duration=110)
    clips = ClipSession()
    assert clips.project(selected)["link_available"] and not clips.project(selected)["available"]
    assert clips.command(["link"], selected, tmp_path) == "https://www.youtube.com/watch?v=abcdefghijk&t=36s"
    clips.command(["range", "0:15.5", "0:21"], selected, tmp_path)
    assert clips.desktop("clip.link", {"media_id": media.stable_id}, selected, tmp_path) == {
        "ok": True, "url": "https://www.youtube.com/watch?v=abcdefghijk&t=15s"}
    assert "clip link" in clips.command(["share"], selected, tmp_path)
    with pytest.raises(ValueError, match="changed"):
        clips.desktop("clip.link", {"media_id": "stale"}, selected, tmp_path)
    updated = replace(selected, media=MediaRef(MediaSource.YOUTUBE, "https://youtu.be/zzzzzzzzzzz?si=hidden"))
    assert clips.link(updated).endswith("v=zzzzzzzzzzz&t=36s")
    live = replace(selected, media=replace(media, capabilities=MediaCapabilities(live=True)), duration=None)
    assert clips.link(live) == "https://www.youtube.com/watch?v=abcdefghijk"


@pytest.mark.parametrize("url", ["https://youtube.com.example/watch?v=abcdefghijk",
                                  "https://a:password@www.youtube.com/watch?v=abcdefghijk",
                                  "https://youtu.be/abcdefghijk?v=zzzzzzzzzzz",
                                  "https://www.youtube.com/watch?v=abcdefghijk&v=zzzzzzzzzzz",
                                  "https://www.youtube.com/watch?v=bad%20id",
                                  "https://www.youtube.com/playlist?list=abcdefghijk"])
def test_timestamp_link_rejects_ambiguous_or_uncanonical_media(playing, url):
    with pytest.raises(ValueError, match="YouTube"):
        ClipSession().link(replace(playing, media=MediaRef(MediaSource.YOUTUBE, url)))
