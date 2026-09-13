import json
import threading
import time
from pathlib import Path
from typing import TypedDict, cast

import pytest

from mariana import captions, video
from mariana.captions import CaptionError, parse_captions
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.provider_captions import provider_caption_tracks
from mariana.video_sources import VideoTrack, VideoTracks

SUBTITLE = "1\n00:00:00,000 --> 00:01:00,000\nExisting captions\n"


class CaptionChoice(TypedDict):
    id: str


class CaptionState(TypedDict):
    revision: int
    tracks: list[CaptionChoice]
    auto_status: str
    available: bool
    enabled: bool
    offset_ms: int
    selected_id: str | None
    text: str | None
    message: str | None


def caption_state(service: video.LocalVideo) -> CaptionState:
    state = service.status()["captions"]
    assert isinstance(state, dict)
    return cast(CaptionState, state)


def refuse_caption_threads(monkeypatch: pytest.MonkeyPatch) -> list[threading.Thread]:
    original = threading.Thread.start
    attempts: list[threading.Thread] = []

    def start(worker: threading.Thread):
        if worker.name == "mariana-caption-selection":
            attempts.append(worker)
            raise RuntimeError("private operating-system diagnostic")
        return original(worker)

    monkeypatch.setattr(threading.Thread, "start", start)
    return attempts


def existing_caption_service(tmp_path: Path, *, local: bool = False):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"bounded media fixture")
    media = MediaRef(
        MediaSource.LOCAL if local else MediaSource.YOUTUBE,
        str(source) if local else "https://youtube.com/watch?v=abcdefghijk",
        duration=60,
    )
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=12)
    published = []
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, published.append)
    service._media = service._observed = media
    service._state = {"revision": 0, "state": "ready", "handle": "existing-picture", "error": None}
    tracks = VideoTracks(VideoTrack("https://provider.example/picture"), captions=provider_caption_tracks({
        "subtitles": {"en": [{"ext": "vtt", "url": "https://provider.example/text?sig=private"}]},
    }))
    if not local:
        service._publish_provider_captions(tracks, media, 0, service._cancel)
    manual = tmp_path / "manual.srt"
    manual.write_text(SUBTITLE, encoding="utf-8")
    service.load_captions(manual)
    service.configure_captions("shift", 500)
    service.configure_captions("off")
    if local:
        service._caption_source = source
    return service, media, snapshot, published, source


def test_selected_worker_start_refusal_preserves_captions_and_allows_explicit_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    service, media, snapshot, published, _source = existing_caption_service(tmp_path)
    previous = service._captions
    initial = caption_state(service)
    fetched = []

    def retrieve(candidate, cancel):
        assert not cancel.is_set()
        fetched.append(candidate.key)
        return parse_captions(SUBTITLE.replace("Existing", "Selected"), source="provider")

    monkeypatch.setattr(video, "load_provider_caption", retrieve)
    try:
        with monkeypatch.context() as patch:
            attempts = refuse_caption_threads(patch)
            with pytest.raises(CaptionError, match="worker could not start") as caught:
                service.select_caption(initial["tracks"][0]["id"], initial["revision"], expected_media=media)
            assert len(attempts) == 1 and not attempts[0].is_alive()
            assert "private" not in str(caught.value)
            failed = caption_state(service)
            assert failed["revision"] > initial["revision"]
            assert failed["auto_status"] == "error" and failed["available"]
            assert failed["enabled"] is False and failed["offset_ms"] == 500
            assert failed["selected_id"] == initial["selected_id"]
            assert service._captions is previous
            assert service._caption_pending is None and service._caption_cancel.is_set()
            assert service._caption_workers == set() and fetched == []
            assert published[-1]["captions"]["auto_status"] == "error"
            assert "private" not in json.dumps(published[-1])
            assert service.status()["state"] == "ready"
            # Neither status reads nor stale selection retries start another worker.
            with pytest.raises(CaptionError, match="list changed"):
                service.select_caption(initial["tracks"][0]["id"], initial["revision"])
            service.status()
            assert len(attempts) == 1
        service.select_caption(failed["tracks"][0]["id"], failed["revision"])
        deadline = time.monotonic() + 3
        while caption_state(service)["auto_status"] == "loading":
            assert time.monotonic() < deadline
            time.sleep(0.005)
        loaded = caption_state(service)
        assert loaded["auto_status"] == "loaded" and loaded["text"] == "Selected captions"
        assert len(service._caption_workers) == 1 and len(fetched) == 1
        assert snapshot.state == PlaybackState.PLAYING and snapshot.position == 12
    finally:
        service.close()
    assert all(not worker.is_alive() for worker in service._caption_workers)


def test_close_after_start_refusal_never_joins_an_unstarted_thread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    service, _media, _snapshot, _published, _source = existing_caption_service(tmp_path)
    initial = caption_state(service)
    attempts = refuse_caption_threads(monkeypatch)
    with pytest.raises(CaptionError, match="worker could not start"):
        service.select_caption(initial["tracks"][0]["id"], initial["revision"])

    service.close()
    service.close()

    assert len(attempts) == 1
    assert service._caption_workers == set()
    assert service._caption_pending is None
    assert service.status()["state"] == "off"


def test_automatic_choice_start_refusal_keeps_existing_display_then_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    service, _media, snapshot, published, source = existing_caption_service(tmp_path, local=True)
    sidecar = source.with_suffix(".srt")
    sidecar.write_text(SUBTITLE.replace("Existing", "Automatic"), encoding="utf-8")
    monkeypatch.setattr(captions, "_embedded_tracks", lambda *_args: [])
    previous = service._captions
    try:
        with monkeypatch.context() as patch:
            attempts = refuse_caption_threads(patch)
            service.caption_automatic()
            failed = caption_state(service)
            assert failed["auto_status"] == "error" and failed["available"]
            assert failed["enabled"] is False and failed["offset_ms"] == 500
            assert service._captions is previous
            assert service._caption_pending is None and service._caption_workers == set()
            assert published[-1]["captions"]["available"]
            assert published[-1]["captions"]["enabled"] is False
            assert len(attempts) == 1
        service.caption_automatic()
        deadline = time.monotonic() + 3
        while caption_state(service)["auto_status"] == "loading":
            assert time.monotonic() < deadline
            time.sleep(0.005)
        current = caption_state(service)
        assert current["auto_status"] == "loaded" and current["text"] == "Automatic captions"
        assert current["enabled"] is True and current["offset_ms"] == 0
        assert snapshot.position == 12 and snapshot.state == PlaybackState.PLAYING
    finally:
        service.close()


def test_automatic_caption_start_failure_does_not_disable_video_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"media fixture")
    media = MediaRef(MediaSource.LOCAL, str(source), duration=60)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=12)
    published = []
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, published.append)
    prepared = threading.Event()
    monkeypatch.setattr(video, "_probe", lambda *_args, **_kwargs: ("h264", 60))

    def prepare_picture(_source, selected, _duration, generation, cancel):
        with service._condition:
            assert selected is media and not cancel.is_set()
            service._state = {"revision": generation, "state": "ready", "handle": "picture", "error": None}
        service._emit()
        prepared.set()

    monkeypatch.setattr(service, "_local_windows", prepare_picture)
    attempts = refuse_caption_threads(monkeypatch)
    try:
        service.request("video", expected_media=media)
        assert prepared.wait(3)
        state = service.status()
        failed = caption_state(service)
        assert state["state"] == "ready" and state["error"] is None
        assert failed["auto_status"] == "error"
        assert not failed["available"]
        assert failed["message"] is not None and "worker could not start" in failed["message"]
        assert len(attempts) == 1 and service._caption_workers == set()
        assert service._caption_pending is None
        assert snapshot.state == PlaybackState.PLAYING and snapshot.position == 12
        assert not any(event["state"] == "error" for event in published)
    finally:
        service.close()
