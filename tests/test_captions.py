import json
import shutil
import subprocess
import threading

import pytest

from mariana import captions as caption_module
from mariana.captions import (
    CaptionError,
    autodetect_local_captions,
    load_captions,
    matching_sidecars,
    parse_captions,
)
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.video import LocalVideo, VideoUnavailable


def test_parses_plain_srt_and_vtt_cues_without_markup():
    srt = parse_captions(
        "1\n00:00:01,000 --> 00:00:02,500\n<b>Hello</b> &amp; welcome\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\nSecond line\n",
        label="Example.srt",
    )
    assert srt.cue_at(0.9) is None
    assert srt.cue_at(1.25) == "Hello & welcome"
    assert srt.cue_at(2.5) is None
    assert srt.cue_at(3.5) == "Second line"

    vtt = parse_captions("WEBVTT\n\n00:01.000 --> 00:02.000 align:center\nVTT cue")
    assert vtt.cue_at(1.5) == "VTT cue"
    assert parse_captions(
        "1\n00:00:00,000 --> 00:00:01,000\nSafe\n", label="C:\\private\\name.srt",
    ).label == "Captions"


def test_caption_files_are_bounded_utf8_and_supported(tmp_path):
    path = tmp_path / "captions.srt"
    path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
    assert load_captions(path).label == "captions.srt"
    with pytest.raises(CaptionError, match=r"\.srt or \.vtt"):
        load_captions(tmp_path / "missing.txt")
    path.write_bytes(b"\xff")
    with pytest.raises(CaptionError, match="UTF-8"):
        load_captions(path)
    with pytest.raises(CaptionError, match="no usable"):
        parse_captions("WEBVTT\n\nNo timing")


def test_matching_sidecar_caption_is_preferred_and_keeps_its_origin(tmp_path):
    media = tmp_path / "Movie.mp4"
    media.write_bytes(b"video")
    exact = tmp_path / "Movie.srt"
    exact.write_text("1\n00:00:01,000 --> 00:00:02,000\nExact\n", encoding="utf-8")
    translated = tmp_path / "Movie.en.vtt"
    translated.write_text("WEBVTT\n\n00:01.000 --> 00:02.000\nEnglish\n", encoding="utf-8")
    (tmp_path / "Other.srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nWrong\n", encoding="utf-8",
    )

    assert matching_sidecars(media) == (exact.resolve(), translated.resolve())
    track = autodetect_local_captions(
        media, tmp_path / "cache", ffprobe_bin="ffprobe", ffmpeg_bin="ffmpeg",
        cancel=threading.Event(),
    )
    assert track is not None
    assert track.label == "Movie.srt"
    assert track.source == "sidecar"
    assert track.cue_at(1.5) == "Exact"


def test_embedded_text_caption_selection_prefers_default_and_has_safe_label(monkeypatch, tmp_path):
    media = tmp_path / "Movie.mkv"
    media.write_bytes(b"video")
    rows = [
        {"index": 2, "codec_name": "subrip", "tags": {"title": "English", "language": "eng"},
         "disposition": {"default": 1}},
        {"index": 4, "codec_name": "ass", "tags": {"language": "fr"}, "disposition": {}},
    ]
    calls = []
    monkeypatch.setattr(caption_module, "matching_sidecars", lambda _path: ())
    monkeypatch.setattr(caption_module, "_embedded_tracks", lambda *_args: rows)

    def convert(*args, **kwargs):
        calls.append((args, kwargs))
        return parse_captions(
            "1\n00:00:00,000 --> 00:00:01,000\nEmbedded\n",
            label=kwargs["label"], source=kwargs["origin"],
        )

    monkeypatch.setattr(caption_module, "_converted_track", convert)
    track = autodetect_local_captions(
        media, tmp_path / "cache", ffprobe_bin="ffprobe", ffmpeg_bin="ffmpeg",
        cancel=threading.Event(),
    )
    assert track is not None
    assert track.source == "embedded"
    assert track.label == "English [eng]"
    assert calls[0][1]["stream_index"] == 2


def test_embedded_probe_accepts_text_tracks_and_prefers_default(monkeypatch, tmp_path):
    media = tmp_path / "Movie.mkv"
    media.write_bytes(b"video")
    payload = {"streams": [
        {"index": 7, "codec_name": "hdmv_pgs_subtitle", "disposition": {"default": 1}},
        {"index": 4, "codec_name": "ass", "tags": {"language": "fr"}, "disposition": {}},
        {"index": 2, "codec_name": "subrip", "tags": {"language": "eng"},
         "disposition": {"default": 1}},
    ]}
    calls = []
    monkeypatch.setattr(caption_module, "_caption_probe", lambda command, _cancel: (
        calls.append(command) or json.dumps(payload).encode()
    ))
    rows = caption_module._embedded_tracks(media, "ffprobe", threading.Event())
    assert [row["index"] for row in rows] == [2, 4]
    assert "-select_streams" in calls[0]


def test_native_embedded_text_track_is_extracted(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Native FFmpeg/FFprobe are required for embedded-caption acceptance")
    subtitle = tmp_path / "dialogue.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,500\nEmbedded cue\n", encoding="utf-8")
    media = tmp_path / "movie.mkv"
    subprocess.run(
        [ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=size=160x90:rate=1",
         "-f", "srt", "-i", str(subtitle), "-t", "2", "-c:v", "libx264", "-c:s", "srt",
         "-metadata:s:s:0", "language=eng", "-disposition:s:0", "default", str(media)],
        check=True, capture_output=True, timeout=20,
    )
    track = autodetect_local_captions(
        media, tmp_path / "cache", ffprobe_bin=ffprobe, ffmpeg_bin=ffmpeg,
        cancel=threading.Event(),
    )
    assert track is not None
    assert track.source == "embedded"
    assert track.label == "Embedded subtitles [eng]"
    assert track.cue_at(0.5) == "Embedded cue"
    assert not list((tmp_path / "cache").glob("caption-*.srt"))


def test_video_caption_and_audio_offsets_are_identity_bound_and_reset_on_new_media(tmp_path):
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "video.mp4"))
    other = MediaRef(MediaSource.LOCAL, str(tmp_path / "other.mp4"))
    current = {"snapshot": PlaybackSnapshot(PlaybackState.PAUSED, position=10, media=media)}
    path = tmp_path / "captions.srt"
    path.write_text("1\n00:00:10,000 --> 00:00:12,000\nCurrent cue\n", encoding="utf-8")
    service = LocalVideo(tmp_path / "cache", lambda: current["snapshot"], lambda _row: None)
    service._media = media
    service._observed = media
    service._state = {
        "revision": 1, "state": "ready", "handle": "a" * 32, "error": None,
        "window_start_seconds": 0, "window_end_seconds": 20,
    }
    try:
        state = service.load_captions(path, expected_media=media)
        captions = state["captions"]
        assert isinstance(captions, dict)
        assert captions["text"] == "Current cue"
        assert captions["source"] == "manual"
        with pytest.raises(CaptionError, match="already loaded"):
            service.load_captions(path, expected_media=media)
        shifted = service.configure_captions("shift", 500, expected_media=media)["captions"]
        assert isinstance(shifted, dict)
        assert shifted["offset_ms"] == 500
        assert service.configure_audio_offset(250, expected_media=media)["position_seconds"] == 10.25
        assert service.configure_audio_offset(-50, relative=True, expected_media=media)["audio_offset_ms"] == 200
        with pytest.raises(VideoUnavailable, match="changed"):
            service.configure_audio_offset(0, expected_media=other)
        with pytest.raises(VideoUnavailable, match="between"):
            service.configure_audio_offset(5001, expected_media=media)
        with pytest.raises(CaptionError, match="between"):
            service.configure_captions("set-offset", 60001, expected_media=media)

        current["snapshot"] = PlaybackSnapshot(PlaybackState.PAUSED, media=other)
        service.enabled = lambda: True
        service.request = lambda *_args, **_kwargs: {}  # type: ignore[method-assign]
        service.activate(other, None)
        reset = service.status()
        reset_captions = reset["captions"]
        assert isinstance(reset_captions, dict)
        assert reset_captions["available"] is False
        assert reset["audio_offset_ms"] == 0
    finally:
        service.close()
