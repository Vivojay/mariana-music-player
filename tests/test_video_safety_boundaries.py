"""Video-only failures must not change the authoritative playback snapshot."""

import threading
from dataclasses import replace

import pytest

from mariana import video
from mariana.captions import CaptionError, parse_captions
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def local_video(tmp_path):
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "movie.mp4"))
    state = [PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=12)]
    published = []
    service = video.LocalVideo(tmp_path / "cache", lambda: state[0], published.append)
    service._media = media
    yield service, media, state, published
    service.close()


def caption():
    return parse_captions("1\n00:00:01,000 --> 00:00:20,000\nOriginal\n", label="Selected")


@pytest.mark.parametrize("state", [PlaybackState.IDLE, PlaybackState.FAILED])
def test_inactive_media_cannot_be_configured(local_video, state):
    service, _media, snapshots, published = local_video
    snapshots[0] = replace(snapshots[0], state=state)
    with pytest.raises(video.VideoUnavailable, match="Start media"):
        service.configure_audio_offset(100)
    assert service._audio_offset_ms == 0 and not published


def test_manual_caption_read_finishing_after_track_change_is_discarded(local_video, monkeypatch):
    service, media, snapshots, published = local_video
    original = caption()
    service._captions = original

    def loaded(_path):
        snapshots[0] = replace(snapshots[0], media=MediaRef(MediaSource.LOCAL, "next.mp4"))
        return caption()

    monkeypatch.setattr(video, "load_captions", loaded)
    with pytest.raises(video.VideoUnavailable, match="Current media changed"):
        service.load_captions("private-selection.srt", replace=True, expected_media=media)
    assert service._captions is original and not published


@pytest.mark.parametrize("action", ["on", "off", "shift", "set-offset"])
def test_empty_caption_controls_refuse_without_mutation(local_video, action):
    service, _media, snapshots, published = local_video
    before = service.status()
    with pytest.raises(CaptionError, match="No captions"):
        service.configure_captions(action, 100)
    assert service.status() == before and snapshots[0].position == 12 and not published


@pytest.mark.parametrize("value", [True, 1.5, "100", None])
def test_caption_offsets_reject_non_integer_values(local_video, value):
    service, _media, _snapshots, published = local_video
    service._captions = caption()
    with pytest.raises(CaptionError, match="whole number"):
        service.configure_captions("shift", value)
    assert service._caption_offset_ms == 0 and not published


def test_unknown_caption_operation_preserves_selection(local_video):
    service, _media, _snapshots, published = local_video
    service._captions = original = caption()
    with pytest.raises(CaptionError, match="Invalid caption action"):
        service.configure_captions("remove-everything")
    assert service._captions is original and not published


def test_automatic_captions_require_a_local_source(local_video):
    service, _media, _snapshots, published = local_video
    service._captions = original = caption()
    with pytest.raises(CaptionError, match="Open a local video"):
        service.caption_automatic()
    assert service._captions is original and not published


@pytest.mark.parametrize("value", [True, 1.25, "250", None])
def test_audio_sync_rejects_non_integer_offsets(local_video, value):
    service, _media, snapshots, published = local_video
    with pytest.raises(video.VideoUnavailable, match="whole number"):
        service.configure_audio_offset(value)
    assert service._audio_offset_ms == 0 and snapshots[0].position == 12 and not published


@pytest.mark.parametrize("relative", [False, True])
@pytest.mark.parametrize("explicit_identity", [False, True])
def test_audio_sync_rechecks_media_before_committing(local_video, monkeypatch, relative, explicit_identity):
    service, media, snapshots, published = local_video
    original = snapshots[0]
    replacement = replace(original, media=MediaRef(MediaSource.LOCAL, "next.mp4"))
    reads = 0

    def changed_snapshot():
        nonlocal reads
        reads += 1
        return original if reads == 1 else replacement

    monkeypatch.setattr(service, "snapshot", changed_snapshot)
    with pytest.raises(video.VideoUnavailable, match="Current media changed"):
        service.configure_audio_offset(250, relative=relative, expected_media=media if explicit_identity else None)
    assert service._audio_offset_ms == 0
    assert not published
    assert snapshots[0] is original and original.position == 12


@pytest.mark.parametrize("reason", ["closed", "generation", "manual"])
def test_discovery_cannot_reopen_closed_or_superseded_selection(local_video, monkeypatch, reason):
    service, media, _snapshots, published = local_video
    if reason == "closed":
        service.close()
    elif reason == "generation":
        service._generation += 1
    else:
        service._caption_discovery = "manual"
    monkeypatch.setattr(service, "_queue_caption_work", lambda _work: pytest.fail("No new worker is eligible"))
    assert not service._start_caption_discovery("movie.mp4", media, 0, threading.Event(), sidecars=True)
    assert service._caption_source is None and not published


def test_source_replacement_during_window_encoding_never_publishes(local_video, monkeypatch):
    service, media, snapshots, published = local_video

    def encoded(_source, output, *_args):
        with service._window_cache.writer(output) as target:
            target.write(b"bounded fixture window")

    monkeypatch.setattr(service, "_encode_window", encoded)
    with pytest.raises(video.VideoUnavailable, match="Local media changed"):
        service._windows("movie.mp4", media, 120, 0, threading.Event(), lambda: False)
    assert service.status()["handle"] is None and not published
    assert snapshots[0].position == 12 and not service._owned
    assert not list(service.cache.glob("*.mp4"))
