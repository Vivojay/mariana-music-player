import json
import os
import subprocess
from array import array
from pathlib import Path

import pytest

from mariana import playback
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState


class FakeStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


def test_find_executable_and_missing(tmp_path: Path, monkeypatch):
    executable = tmp_path / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    executable.write_bytes(b"")
    assert playback.find_executable("ffmpeg", str(tmp_path)) == str(executable.resolve())
    monkeypatch.setattr(playback.shutil, "which", lambda _name: None)
    with pytest.raises(playback.PlaybackError, match="was not found"):
        playback.find_executable("missing")


def test_http_retry_option_detection_is_version_aware(monkeypatch):
    playback._ffmpeg_http_options.cache_clear()
    monkeypatch.setattr(
        playback.subprocess,
        "run",
        lambda *_args, **_kwargs: type(
            "Result",
            (),
            {"stdout": "reconnect_max_retries respect_retry_after", "stderr": "reconnect_delay_total_max"},
        )(),
    )
    assert playback._ffmpeg_http_options("new-ffmpeg") == {
        "reconnect_max_retries",
        "reconnect_delay_total_max",
        "respect_retry_after",
    }
    monkeypatch.setattr(
        playback.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("ffmpeg", 5)),
    )
    assert playback._ffmpeg_http_options("unavailable-ffmpeg") == frozenset()
    playback._ffmpeg_http_options.cache_clear()


def test_probe_media_normalizes_metadata_and_capabilities(monkeypatch):
    payload = {
        "format": {"duration": "12.5", "format_name": "mp3", "tags": {"title": "Title"}},
        "streams": [{"codec_type": "audio", "codec_name": "mp3", "tags": {"artist": "Artist"}}],
    }
    monkeypatch.setattr(playback, "find_executable", lambda *_args, **_kwargs: "ffprobe")
    monkeypatch.setattr(
        playback.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    result = playback.probe_media(MediaRef(MediaSource.URL, "https://example.test/song.mp3"))
    assert (result.title, result.artist, result.duration) == ("Title", "Artist", 12.5)
    assert result.capabilities.seekable and not result.capabilities.live


def test_probe_media_failure_is_typed(monkeypatch):
    monkeypatch.setattr(playback, "find_executable", lambda *_args, **_kwargs: "ffprobe")

    def fail(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 1)

    monkeypatch.setattr(playback.subprocess, "run", fail)
    with pytest.raises(playback.PlaybackError, match="could not inspect"):
        playback.probe_media(MediaRef(MediaSource.URL, "https://example.test/broken"))


def test_pcm_scaling_and_crossfade_are_clipped():
    data = array("f", [0.5, -0.5]).tobytes()
    assert list(array("f", playback._scale_pcm(data, 0.5))) == pytest.approx([0.25, -0.25])
    mixed = playback._mix_pcm(data, array("f", [1.0, -1.0]).tobytes(), 1.0, 1.0, len(data))
    assert list(array("f", mixed)) == pytest.approx([1.0, -1.0])


def test_controller_state_volume_pause_and_rejections(monkeypatch):
    controller = playback.PlaybackController(output_factory=FakeStream)
    media = MediaRef(
        MediaSource.RADIO,
        "https://example.test/live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )
    controller._prepared = media
    controller._state = PlaybackState.PLAYING
    controller.set_volume(25)
    controller.set_muted(True)
    controller.pause()
    assert controller.snapshot().state == PlaybackState.PAUSED
    assert controller.snapshot().volume == 0.25
    assert controller.snapshot().muted
    controller.resume()
    with pytest.raises(playback.UnsupportedAction, match="cannot be seeked"):
        class Active:
            def __init__(self):
                self.media = media

        controller._active = Active()
        controller.seek(10)
    with pytest.raises(ValueError, match="between 0 and 100"):
        controller.set_volume(101)
    controller._active = None
    controller.close()


def test_live_metadata_boundary_resets_fingerprint_and_generation():
    controller = playback.PlaybackController(output_factory=FakeStream)
    media = MediaRef(
        MediaSource.RADIO,
        "https://example.test/live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )

    class Active:
        def __init__(self):
            self.media = media
            self.reset = 0

        def reset_fingerprint(self):
            self.reset += 1

    active = Active()
    controller._active = active
    assert controller.notify_metadata_boundary("Artist - Song") == 1
    assert active.reset == 1
    assert media.title == "Artist - Song"
