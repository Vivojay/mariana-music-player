import copy
import json
import shutil
import subprocess
import sys
import threading
import time

import pytest

from mariana import captions, video
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def media_tools():
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Native FFmpeg/FFprobe are required for caption format acceptance")
    return ffmpeg, ffprobe


def write_srt(path, text):
    path.write_text(f"1\n00:00:00,000 --> 00:00:01,500\n{text}\n", encoding="utf-8")


def settle(service):
    deadline = time.monotonic() + 10
    while service.status()["captions"]["auto_status"] == "loading":
        assert time.monotonic() < deadline
        time.sleep(0.005)
    return service.status()["captions"]


@pytest.mark.parametrize(("suffix", "codec"), [(".mp4", "mov_text"), (".mkv", "ass")])
def test_native_container_selection_sidecar_precedence_and_reload(tmp_path, media_tools, suffix, codec):
    ffmpeg, ffprobe = media_tools
    english, hindi = tmp_path / "english.srt", tmp_path / "hindi.srt"
    write_srt(english, "Embedded English")
    write_srt(hindi, "Embedded Hindi")
    source = tmp_path / f"recording{suffix}"
    subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=size=160x90:rate=1",
        "-i", str(english), "-i", str(hindi), "-map", "0:v", "-map", "1:s", "-map", "2:s",
        "-t", "2", "-c:v", "libx264", "-c:s", codec, "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:1", "language=hin", "-disposition:s:0", "default", "-disposition:s:1", "0", str(source),
    ], check=True, capture_output=True, timeout=20)
    write_srt(tmp_path / "recording.srt", "Sidecar dialogue")
    tracks = captions.discover_caption_tracks(source, ffprobe, threading.Event())
    assert [track.source for track in tracks] == ["sidecar", "embedded", "embedded"]
    assert [track.codec for track in tracks[1:]] == [codec, codec]
    assert [track.language for track in tracks[1:]] == ["eng", "hin"]
    assert captions.rank_caption_tracks(tracks, ())[0].source == "sidecar"
    assert captions.rank_caption_tracks(tracks, ("hin",))[0].language == "hin"

    media = MediaRef(MediaSource.LOCAL, str(source))
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=0.75)
    saved = {}
    preferences = captions.CaptionPreferences(save=lambda value: saved.update(copy.deepcopy(value)))
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _state: None,
                               caption_preferences=preferences)
    service._media = service._observed = media
    try:
        service._start_caption_discovery(source, media, 0, service._cancel, sidecars=True)
        state = settle(service)
        assert state["text"] == "Sidecar dialogue"
        hindi_track = next(track for track in state["tracks"] if track["language"] == "hin")
        service.select_caption(hindi_track["id"], state["revision"], expected_media=media)
        state = settle(service)
        assert state["text"] == "Embedded Hindi" and state["source"] == "embedded"
        service.configure_captions("shift", 250, expected_media=media)
        service.configure_captions("off", expected_media=media)
        assert service.status()["captions"]["text"] is None
        assert snapshot.state == PlaybackState.PAUSED and snapshot.position == 0.75
        projection = json.dumps(service.status())
        assert str(source) not in projection and str(tmp_path) not in json.dumps(saved)
    finally:
        service.close()

    restored = video.LocalVideo(tmp_path / "restored", lambda: snapshot, lambda _state: None,
                               caption_preferences=captions.CaptionPreferences(saved))
    restored._media = restored._observed = media
    try:
        restored._start_caption_discovery(source, media, 0, restored._cancel, sidecars=True)
        state = settle(restored)
        assert state["selected_id"] == hindi_track["id"]
        assert state["enabled"] is False and state["offset_ms"] == 250
        assert restored.configure_captions("on")["captions"]["text"] == "Embedded Hindi"
    finally:
        restored.close()
    assert not list(tmp_path.rglob("caption-*.srt"))
    assert not any(worker.is_alive() for worker in (*service._caption_workers, *restored._caption_workers))


@pytest.mark.parametrize(("suffix", "codec"), [(".ass", "ass"), (".ssa", "ssa"), (".sub", "microdvd")])
def test_native_convertible_sidecar_uses_matching_media_only(tmp_path, media_tools, suffix, codec):
    ffmpeg, ffprobe = media_tools
    source = tmp_path / "recording.mp4"
    source.write_bytes(b"sidecar selection does not need to decode the source")
    original = tmp_path / "text.srt"
    write_srt(original, "Selected sidecar")
    sidecar = tmp_path / f"recording.en{suffix}"
    if codec == "microdvd":
        # FFmpeg decodes this frame-based text format but has no encoder for it.
        # Automatic format detection examines three MicroDVD records.
        sidecar.write_text("{1}{1}25.0\n{0}{38}Selected sidecar\n{50}{75}Second cue\n", encoding="utf-8")
    else:
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", "-i", str(original), "-c:s", codec,
                        "-f", "ass", str(sidecar)], check=True, capture_output=True, timeout=15)
    write_srt(tmp_path / "unrelated.srt", "Wrong recording")
    track = captions.autodetect_local_captions(source, tmp_path / "cache", ffmpeg_bin=ffmpeg,
                                             ffprobe_bin=ffprobe, cancel=threading.Event())
    assert track is not None and track.source == "sidecar"
    assert track.cue_at(0.5) == "Selected sidecar"
    assert not list((tmp_path / "cache").glob("caption-*"))


def test_probe_receives_bounded_output_and_reaps_oversized_child(monkeypatch):
    monkeypatch.setattr(captions, "CAPTION_PROBE_BYTES", 64)
    command = [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000); sys.stdout.flush()"]
    assert captions._caption_probe(command, threading.Event()) is None
    assert not any(thread.name == "mariana-caption-probe-output" for thread in threading.enumerate())
    expected = b"small\r\n" if sys.platform == "win32" else b"small\n"
    assert captions._caption_probe([sys.executable, "-c", "print('small')"], threading.Event()) == expected


@pytest.mark.parametrize("close_output", [False, True])
def test_probe_cancellation_stops_blocked_process_even_after_stdout_closes(tmp_path, monkeypatch, close_output):
    started, cancel = threading.Event(), threading.Event()
    original = captions.subprocess.Popen
    processes = []

    def observe(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(captions.subprocess, "Popen", observe)
    result = []
    ready = tmp_path / "ready"
    program = ("import os,time,sys; from pathlib import Path; " + ("os.close(1); " if close_output else "")
               + "Path(sys.argv[1]).touch(); time.sleep(30)")
    worker = threading.Thread(target=lambda: result.append(captions._caption_probe(
        [sys.executable, "-c", program, str(ready)], cancel,
    )))
    worker.start()
    try:
        assert started.wait(3)
        deadline = time.monotonic() + 3
        while not ready.exists():
            assert time.monotonic() < deadline
            time.sleep(0.005)
        cancel.set()
        worker.join(timeout=4)
        assert not worker.is_alive()
        assert result == [None]
        assert processes[0].poll() is not None
        assert not any(thread.name == "mariana-caption-probe-output" for thread in threading.enumerate())
    finally:
        cancel.set()
        worker.join(timeout=4)


def test_probe_timeout_and_nonzero_exit_are_nonfatal(monkeypatch):
    assert captions._caption_probe([sys.executable, "-c", "raise SystemExit(3)"], threading.Event()) is None
    monkeypatch.setattr(captions, "CAPTION_TOOL_TIMEOUT", 0.05)
    assert captions._caption_probe([sys.executable, "-c", "import time; time.sleep(30)"], threading.Event()) is None
    cancel = threading.Event()
    cancel.set()
    assert captions._caption_probe(["must-not-launch"], cancel) is None


def test_probe_reader_start_failure_still_reaps_child(monkeypatch):
    original_popen = captions.subprocess.Popen
    original_start = captions.threading.Thread.start
    processes = []

    def observe(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    def refuse_reader(thread):
        if thread.name == "mariana-caption-probe-output":
            raise RuntimeError("Reader could not start")
        original_start(thread)

    monkeypatch.setattr(captions.subprocess, "Popen", observe)
    monkeypatch.setattr(captions.threading.Thread, "start", refuse_reader)
    with pytest.raises(RuntimeError, match="could not start"):
        captions._caption_probe([sys.executable, "-c", "import time; time.sleep(30)"], threading.Event())
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed
