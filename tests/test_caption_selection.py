import copy
import json
import shutil
import subprocess
import threading
import time

import pytest

from mariana import captions, video
from mariana.captions import CaptionError, CaptionPreferences
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


def subtitle(path, text):
    path.write_text(f"1\n00:00:00,000 --> 00:00:10,000\n{text}\n", encoding="utf-8")


def settle(service):
    deadline = time.monotonic() + 3
    while service.status()["captions"]["auto_status"] == "loading":
        assert time.monotonic() < deadline
        time.sleep(0.005)
    return service.status()["captions"]


@pytest.fixture
def local(tmp_path, monkeypatch):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"media fixture")
    subtitle(tmp_path / "movie.en.srt", "English")
    subtitle(tmp_path / "movie.hi.srt", "Hindi")
    monkeypatch.setattr(captions, "_embedded_tracks", lambda *_args: [])
    media = MediaRef(MediaSource.LOCAL, str(source))
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=1)
    saved = {}
    prefs = CaptionPreferences(save=lambda value: saved.update(copy.deepcopy(value)))
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _row: None, caption_preferences=prefs)
    service._media = service._observed = media
    service._start_caption_discovery(source, media, 0, service._cancel, sidecars=True)
    settle(service)
    yield service, source, media, saved, snapshot
    service.close()
    assert all(not worker.is_alive() for worker in service._caption_workers)


def test_catalogue_selection_preferences_reload_and_offsets(local, tmp_path):
    service, source, media, saved, snapshot = local
    state = service.status()["captions"]
    assert [row["language"] for row in state["tracks"]] == ["eng", "hin"]
    assert state["text"] == "English"
    hindi = state["tracks"][1]
    service.select_caption(hindi["id"], state["revision"], expected_media=media)
    assert settle(service)["text"] == "Hindi"
    service.configure_captions("shift", 250, expected_media=media)
    service.configure_captions("off", expected_media=media)
    assert service.status()["captions"]["text"] is None
    assert str(source) not in json.dumps(saved)
    assert media.original_uri not in json.dumps(saved)
    assert "Hindi" not in json.dumps(saved)
    restored = video.LocalVideo(tmp_path / "reload", lambda: snapshot, lambda _row: None,
                               caption_preferences=CaptionPreferences(saved))
    restored._media = restored._observed = media
    try:
        restored._start_caption_discovery(source, media, 0, restored._cancel, sidecars=True)
        state = settle(restored)
        assert state["selected_id"] == hindi["id"]
        assert state["enabled"] is False and state["offset_ms"] == 250
        assert restored.configure_captions("on")["captions"]["text"] == "Hindi"
        assert snapshot.position == 1 and snapshot.state == PlaybackState.PAUSED
    finally:
        restored.close()


def test_language_order_and_explicit_choice_override(local):
    service, _source, media, saved, _snapshot = local
    service.set_caption_languages(["hi", "en"])
    state = settle(service)
    assert state["text"] == "Hindi"
    english = state["tracks"][0]
    service.select_caption(english["id"], state["revision"], expected_media=media)
    assert settle(service)["text"] == "English"
    service.set_caption_languages(["hi"])
    assert service.status()["captions"]["text"] == "English"
    service.caption_automatic(expected_media=media)
    assert settle(service)["text"] == "Hindi"
    assert saved["media choices"] == {}
    assert saved["preferred languages"] == ["hin"]


@pytest.mark.parametrize("replacement", ["sidecar", "container"])
def test_changed_files_do_not_silently_replace_saved_choice(local, replacement):
    service, source, media, _saved, _snapshot = local
    state = service.status()["captions"]
    service.select_caption(state["tracks"][0]["id"], state["revision"], expected_media=media)
    settle(service)
    if replacement == "sidecar":
        subtitle(source.with_suffix(".en.srt"), "Different edition")
    else:
        source.write_bytes(b"different media edition")
    service._caption_discovery = "idle"
    service._start_caption_discovery(source, media, 0, service._cancel, sidecars=True)
    state = settle(service)
    assert not state["available"] and state["selected_id"] is None
    assert "unavailable" in state["message"]
    service.caption_automatic()
    assert settle(service)["available"]


def test_invalid_stale_selection_and_failed_save_leave_previous_choice(local):
    service, _source, media, _saved, _snapshot = local
    state = service.status()["captions"]
    with pytest.raises(CaptionError, match="changed"):
        service.select_caption(state["tracks"][0]["id"], state["revision"] - 1)
    with pytest.raises(CaptionError, match="unavailable"):
        service.select_caption("f" * 32, state["revision"])
    with pytest.raises(video.VideoUnavailable, match="changed"):
        service.select_caption(state["tracks"][0]["id"], state["revision"],
                               expected_media=MediaRef(MediaSource.LOCAL, "other"))
    service.caption_preferences._save = lambda _value: (_ for _ in ()).throw(OSError("private path"))
    with pytest.raises(CaptionError, match="could not be saved"):
        service.configure_captions("off", expected_media=media)
    assert service.status()["captions"]["enabled"] is True
    service.select_caption(state["tracks"][1]["id"], state["revision"])
    assert settle(service)["text"] == "English"
    assert "private" not in service.status()["captions"]["message"]


def test_latest_selection_bounded_worker_and_manual_override(local, monkeypatch, tmp_path):
    service, _source, _media, _saved, _snapshot = local
    entered, release = threading.Event(), threading.Event()
    original = video.load_caption_candidate

    def delayed(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(video, "load_caption_candidate", delayed)
    state = service.status()["captions"]
    service.select_caption(state["tracks"][1]["id"], state["revision"])
    assert entered.wait(3)
    try:
        with pytest.raises(CaptionError, match="still loading"):
            service.configure_captions("off")
        for _ in range(20):
            current = service.status()["captions"]
            service.select_caption(current["tracks"][0]["id"], current["revision"])
        assert len(service._caption_workers) == 1
        manual = tmp_path / "manual.srt"
        subtitle(manual, "User choice")
        service.load_captions(manual, replace=True)
    finally:
        release.set()
    assert service.status()["captions"]["text"] == "User choice"
    assert service._caption_pending is None


def test_preferences_validate_normalize_and_bound_records():
    prefs = CaptionPreferences({"preferred languages": ["en", "eng", "pt-BR"]})
    assert prefs.languages == ("eng", "por-br")
    for invalid in [["English"], ["en"] * 6, [None], "en", ["../../x"]]:
        with pytest.raises(CaptionError):
            prefs.set_languages(invalid)
    for index in range(140):
        prefs.remember(str(index), "b" * 64, "c" * 32, False, -60000)
    assert len(prefs._choices) == 128
    assert prefs.get("0") is None
    saved = prefs.get("139")
    saved["offset_ms"] = 9
    assert prefs.get("139")["offset_ms"] == -60000
    malformed = CaptionPreferences({"preferred languages": [False], "media choices": {"bad": {"path": "secret"}}})
    assert malformed.languages == () and malformed._choices == {}


def test_real_settings_persistence_preserves_explicit_preferences_and_other_settings(tmp_path):
    from config_manager import load_user_settings, save_user_settings

    path = tmp_path / "settings.yml"
    defaults = tmp_path / "defaults.yml"
    save_user_settings({"captions": {"preferred languages": [], "media choices": {}}, "unrelated": 42}, defaults)
    save_user_settings({"captions": {"preferred languages": ["hi"]}, "unrelated": 73}, path)
    current = load_user_settings(path, defaults)
    prefs = CaptionPreferences(current["captions"],
                               lambda value: save_user_settings({**current, "captions": value}, path))
    prefs.remember("media", "a" * 64, "b" * 32, False, 750)
    reloaded = load_user_settings(path, defaults)
    assert reloaded["unrelated"] == 73
    restored = CaptionPreferences(reloaded["captions"])
    assert restored.languages == ("hin",)
    assert restored.get("media") == {"signature": "a" * 64, "track": "b" * 32, "enabled": False, "offset_ms": 750}


def test_media_change_rejects_late_selection_without_persisting(local, monkeypatch):
    service, _source, _media, saved, _snapshot = local
    entered, release = threading.Event(), threading.Event()
    original = video.load_caption_candidate

    def delayed(*args):
        entered.set()
        assert release.wait(3)
        return original(*args)

    monkeypatch.setattr(video, "load_caption_candidate", delayed)
    state = service.status()["captions"]
    service.select_caption(state["tracks"][1]["id"], state["revision"])
    assert entered.wait(3)
    other = MediaRef(MediaSource.LOCAL, "other.mkv")
    service.snapshot = lambda: PlaybackSnapshot(PlaybackState.PAUSED, media=other)
    service.enabled = lambda: True
    service.expect(other, "audio")
    service.activate(other, None)
    release.set()
    service.close()
    assert not saved.get("media choices")
    assert not service.status()["captions"]["available"]


def test_catalogue_includes_embedded_alternatives_and_drops_private_fields(monkeypatch, tmp_path):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"video")
    subtitle(tmp_path / "movie.srt", "Sidecar")
    monkeypatch.setattr(captions, "_embedded_tracks", lambda *_args: [
        {"index": 2, "codec_name": "subrip", "tags": {"language": "eng", "title": "English"},
         "disposition": {"default": 1}},
        {"index": 3, "codec_name": "ass", "tags": {"language": "hi", "title": "C:\\secret\\name"},
         "disposition": {"forced": 1}},
    ])
    tracks = captions.discover_caption_tracks(source, "ffprobe", threading.Event())
    assert len(tracks) == 3
    assert [row.source for row in tracks] == ["sidecar", "embedded", "embedded"]
    assert captions.rank_caption_tracks(tracks, ("hin",))[0].stream_index == 3
    projection = json.dumps([track.projection() for track in tracks])
    assert "secret" not in projection and str(tmp_path) not in projection
    assert "signature" not in projection and "stream_index" not in projection
    cancelled = threading.Event()
    cancelled.set()
    assert captions.discover_caption_tracks(source, "ffprobe", cancelled) == ()




def test_native_multiple_embedded_tracks_select_real_text_and_clean_conversion(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Native FFmpeg/FFprobe are required for multi-track acceptance")
    english, hindi = tmp_path / "english.srt", tmp_path / "hindi.srt"
    subtitle(english, "English dialogue")
    subtitle(hindi, "Hindi dialogue")
    media = tmp_path / "fixture.mkv"
    subprocess.run([
        ffmpeg, "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=size=160x90:rate=1",
        "-i", str(english), "-i", str(hindi), "-map", "0:v", "-map", "1:s", "-map", "2:s",
        "-t", "2", "-c:v", "libx264", "-c:s", "srt", "-metadata:s:s:0", "language=eng",
        "-metadata:s:s:1", "language=hin", "-disposition:s:0", "default", "-disposition:s:1", "0", str(media),
    ], check=True, capture_output=True, timeout=20)
    cancel = threading.Event()
    tracks = captions.discover_caption_tracks(media, ffprobe, cancel)
    assert len(tracks) == 2
    assert [track.language for track in tracks] == ["eng", "hin"]
    assert tracks[0].default and not tracks[1].default
    for candidate, expected in zip(tracks, ["English dialogue", "Hindi dialogue"], strict=True):
        track = captions.load_caption_candidate(candidate, tmp_path / "cache", ffmpeg, cancel)
        assert track is not None and track.cue_at(0.5) == expected
    assert not list((tmp_path / "cache").glob("caption-*"))
