import copy
import io
import json
import threading
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from beta import youtube_media
from mariana import provider_captions as provider
from mariana import video, video_sources
from mariana.captions import CaptionError, CaptionPreferences
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState

VTT = b"WEBVTT\n\n00:00:00.000 --> 00:00:10.000\nHello <b>world</b>\n"


def metadata():
    return {"subtitles": {"en": [
        {"ext": "json3", "url": "https://provider.example/events"},
        {"ext": "srt", "url": "https://provider.example/sub?sig=private", "name": "English"},
        {"ext": "vtt", "url": "https://provider.example/text?sig=secret", "name": "English"},
    ]}, "automatic_captions": {"hi": [
        {"ext": "vtt", "url": "https://provider.example/auto?token=hidden", "name": "Hindi"},
    ]}}


class Response(io.BytesIO):
    def __init__(self, data=VTT, *, status=200, headers=None):
        super().__init__(data)
        self.status = status
        self.headers = headers if headers is not None else {"Content-Length": str(len(data)), "Content-Type": "text/vtt"}

    def getheader(self, name):
        return self.headers.get(name)


def responses(monkeypatch, values):
    requests, closed = [], []

    def connect(url):
        response = values.pop(0)
        return SimpleNamespace(request=lambda *args, **kwargs: requests.append((url, args, kwargs)),
                               getresponse=lambda: response, close=lambda: closed.append(url)), "/captions"

    monkeypatch.setattr(video_sources, "_connection", connect)
    return requests, closed


def settle(service):
    deadline = time.monotonic() + 3
    while service.status()["captions"]["auto_status"] == "loading":
        assert time.monotonic() < deadline
        time.sleep(0.005)
    return service.status()["captions"]


@pytest.fixture
def online(tmp_path):
    media = MediaRef(MediaSource.YOUTUBE, "https://youtube.com/watch?v=abcdefghijk", duration=100)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=1)
    saved = {}
    prefs = CaptionPreferences(save=lambda value: saved.update(copy.deepcopy(value)))
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _event: None, caption_preferences=prefs)
    service._media = service._observed = media
    tracks = video_sources.VideoTracks(video_sources.VideoTrack("https://provider.example/video"),
                                       duration=100, captions=provider.provider_caption_tracks(metadata()))
    service._publish_provider_captions(tracks, media, 0, service._cancel)
    yield service, media, snapshot, tracks, saved
    service.close()
    assert all(not worker.is_alive() for worker in service._caption_workers)


def test_catalogue_is_bounded_private_and_distinguishes_generated_tracks(monkeypatch):
    monkeypatch.setattr(video_sources, "_connection", lambda _uri: pytest.fail("Discovery must not fetch"))
    info = metadata()
    before = copy.deepcopy(info)
    tracks = provider.provider_caption_tracks(info)
    assert info == before
    assert len(tracks) == 2
    assert [(row.codec, row.source, row.language) for row in tracks] == [
        ("vtt", "provider", "eng"), ("vtt", "provider-generated", "hin"),
    ]
    assert "generated" in tracks[1].label
    assert all(secret not in json.dumps([row.projection() for row in tracks]) + repr(tracks)
               for secret in ["secret", "hidden", "provider.example", "https:"])
    assert tracks == provider.provider_caption_tracks(info)
    more = {"subtitles": {f"en-{index:02d}": info["subtitles"]["en"] for index in range(80)}}
    assert len(provider.provider_caption_tracks(more)) == 32


@pytest.mark.parametrize("row", [
    {"ext": "vtt", "url": "file:///secret"},
    {"ext": "vtt", "url": "https://user:pass@example.org/sub"},
    {"ext": "vtt", "url": "https://example.org/sub\nheader"},
    {"ext": "vtt", "url": "https://example.org/sub", "http_headers": {"Cookie": "secret"}},
    {"ext": "vtt", "url": "https://example.org/sub", "http_headers": {"Authorization": "secret"}},
    {"ext": "vtt", "url": "https://example.org/sub", "http_headers": {"Referer": "bad\nvalue"}},
    {"ext": "vtt", "url": "https://example.org/sub", "http_headers": {"Referer": None}},
    {"ext": "ttml", "url": "https://example.org/sub"},
    {"ext": "m3u8", "url": "https://example.org/manifest"},
    {"ext": "vtt", "data": VTT.decode()},
    {"ext": [], "url": "https://example.org/sub"},
])
def test_unsupported_references_do_not_enter_catalogue(row):
    assert provider.provider_caption_tracks({"subtitles": {"en": [row]}}) == ()


def test_extractor_handoff_preserves_tracks_only_on_ephemeral_video_model(monkeypatch):
    info = {**metadata(), "url": "https://provider.example/picture", "vcodec": "avc1", "acodec": "none",
            "protocol": "https", "ext": "mp4", "duration": 100, "title": "Recording"}
    monkeypatch.setattr(youtube_media, "_extract", lambda *_args, **_kwargs: info)
    tracks = youtube_media.resolve_video_tracks("https://youtube.com/watch?v=abcdefghijk", native=True)
    assert len(tracks.captions) == 2
    stream = youtube_media.resolve_stream("https://youtube.com/watch?v=abcdefghijk")
    assert "subtitles" not in stream and "automatic_captions" not in stream and "captions" not in stream
    assert "secret" not in json.dumps(stream)


def test_selected_fetch_parses_text_and_strips_headers_across_redirect(monkeypatch):
    candidate = provider.provider_caption_tracks(metadata())[0]
    candidate = replace(candidate, transport=video_sources.VideoTrack(candidate.transport.uri, {"Referer": "https://origin.example/private"}))
    calls, closed = responses(monkeypatch, [Response(status=302, headers={"Location": "https://cdn.example/sub"}), Response()])
    track = provider.load_provider_caption(candidate, threading.Event())
    assert track.cue_at(1) == "Hello world" and track.source == "provider"
    assert "Referer" in calls[0][2]["headers"] and "Referer" not in calls[1][2]["headers"]
    assert len(closed) == 2


@pytest.mark.parametrize("response", [
    Response(status=403), Response(status=404), Response(status=500),
    Response(headers={"Content-Length": "invalid"}), Response(headers={"Content-Length": "0"}),
    Response(headers={"Content-Length": str(provider.MAX_CAPTION_BYTES + 1)}),
    Response(headers={"Content-Length": "9999"}), Response(headers={"Content-Encoding": "gzip"}),
    Response(headers={"Content-Type": "text/html"}), Response(b"\xff"), Response(b"not timed captions"),
    Response(b"1\n00:99:00,000 --> 00:00:10,000\ninvalid"),
    Response(b"x" * (provider.MAX_CAPTION_BYTES + 1), headers={}),
    Response(status=302, headers={"Location": "http://insecure.example/sub"}),
])
def test_refusals_are_bounded_and_do_not_reveal_private_urls(monkeypatch, response):
    _calls, closed = responses(monkeypatch, [response])
    with pytest.raises(CaptionError) as error:
        provider.load_provider_caption(provider.provider_caption_tracks(metadata())[0], threading.Event())
    assert "secret" not in str(error.value) and "provider.example" not in str(error.value)
    assert len(closed) == 1


def test_private_dns_and_redirect_addresses_are_rejected(monkeypatch):
    monkeypatch.setattr(video_sources.socket, "getaddrinfo", lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 443))])
    monkeypatch.setattr(video_sources.socket, "create_connection", lambda *_args, **_kwargs: pytest.fail("Private DNS must not connect"))
    with pytest.raises(CaptionError, match="could not be retrieved"):
        provider.load_provider_caption(provider.provider_caption_tracks(metadata())[0], threading.Event())


def test_cancel_before_connection_and_while_reading(monkeypatch):
    candidate = provider.provider_caption_tracks(metadata())[0]
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(video_sources, "_connection", lambda _uri: pytest.fail("Cancelled request must not connect"))
    with pytest.raises(CaptionError):
        provider.load_provider_caption(candidate, cancel)
    cancel.clear()

    class Cancelling(Response):
        def read1(self, size):
            cancel.set()
            return super().read1(size)

    _calls, closed = responses(monkeypatch, [Cancelling()])
    with pytest.raises(CaptionError, match="cancelled"):
        provider.load_provider_caption(candidate, cancel)
    assert len(closed) == 1


@pytest.mark.parametrize("during_connect", ["cancel", "deadline", "past-deadline"])
def test_cancel_or_deadline_during_connection_sends_no_request(monkeypatch, during_connect):
    candidate = provider.provider_caption_tracks(metadata())[0]
    cancel = threading.Event()
    clock = [0.0]
    requests, closed = [], []
    monkeypatch.setattr(video_sources.time, "monotonic", lambda: clock[0])

    def connect(_url):
        if during_connect == "cancel":
            cancel.set()
        else:
            clock[0] = provider.PROVIDER_CAPTION_TIMEOUT + (5 if during_connect == "past-deadline" else 0)
        return SimpleNamespace(request=lambda *_args, **_kwargs: requests.append(True),
                               getresponse=lambda: pytest.fail("Cancelled connection must not receive a response"),
                               close=lambda: closed.append(True)), "/caption"

    monkeypatch.setattr(video_sources, "_connection", connect)
    with pytest.raises(CaptionError):
        provider.load_provider_caption(candidate, cancel)
    assert requests == [] and closed == [True]


def test_listing_never_fetches_selection_is_session_only_and_keeps_playback(online, monkeypatch):
    service, media, snapshot, tracks, saved = online
    calls, _closed = responses(monkeypatch, [Response(), Response()])
    state = service.status()["captions"]
    assert len(state["tracks"]) == 2 and not state["available"] and not calls
    assert "Choose a provider track" in state["message"]
    service.select_caption(state["tracks"][1]["id"], state["revision"], expected_media=media)
    state = settle(service)
    assert state["source"] == "provider-generated" and state["text"] == "Hello world"
    service.configure_captions("off", expected_media=media)
    service.configure_captions("shift", 750, expected_media=media)
    service.set_caption_languages(["en"])
    assert len(calls) == 1 and not saved["media choices"]
    service._publish_provider_captions(tracks, media, 0, service._cancel)
    assert service.status()["captions"]["offset_ms"] == 750 and len(calls) == 1
    assert snapshot.state == PlaybackState.PAUSED and snapshot.position == 1
    assert not any(word in json.dumps(service.status()) for word in ["secret", "hidden", "https:"])


def test_stale_selection_and_failed_fetch_retain_previous_captions(online, monkeypatch):
    service, media, _snapshot, _tracks, _saved = online
    responses(monkeypatch, [Response(), Response(status=403)])
    state = service.status()["captions"]
    service.select_caption(state["tracks"][0]["id"], state["revision"], expected_media=media)
    current = settle(service)
    with pytest.raises(CaptionError, match="changed"):
        service.select_caption(state["tracks"][1]["id"], state["revision"])
    service.select_caption(current["tracks"][1]["id"], current["revision"])
    failed = settle(service)
    assert failed["selected_id"] == current["selected_id"] and failed["text"] == "Hello world"
    assert failed["auto_status"] == "error" and "secret" not in failed["message"]


def test_changed_media_cancels_pending_fetch_and_rejects_late_result(online, monkeypatch):
    service, media, snapshot, tracks, saved = online
    entered, release = threading.Event(), threading.Event()
    cancelled = []

    def delayed(candidate, cancel):
        entered.set()
        assert release.wait(3)
        cancelled.append(cancel.is_set())
        return provider.parse_captions(VTT.decode(), source=candidate.source)

    monkeypatch.setattr(video, "load_provider_caption", delayed)
    state = service.status()["captions"]
    service.select_caption(state["tracks"][0]["id"], state["revision"])
    assert entered.wait(3)
    other = MediaRef(MediaSource.URL, "https://example.org/other.mp3")
    service.snapshot = lambda: replace(snapshot, media=other)
    service.enabled = lambda: True
    service.expect(other, "audio")
    service.activate(other, None)
    service._publish_provider_captions(tracks, media, 0, threading.Event())
    release.set()
    service.close()
    assert cancelled == [True] and not saved
    assert service.status()["captions"]["tracks"] == []
    assert not service.status()["captions"]["available"]


def test_clear_cancels_fetch_and_worker_queue_remains_bounded(online, monkeypatch):
    service, _media, _snapshot, _tracks, _saved = online
    entered = threading.Event()
    cancelled = threading.Event()

    def delayed(candidate, cancel):
        entered.set()
        assert cancel.wait(3)
        cancelled.set()
        return provider.parse_captions(VTT.decode(), source=candidate.source)

    monkeypatch.setattr(video, "load_provider_caption", delayed)
    state = service.status()["captions"]
    service.select_caption(state["tracks"][0]["id"], state["revision"])
    assert entered.wait(3)
    for _index in range(20):
        state = service.status()["captions"]
        service.select_caption(state["tracks"][1]["id"], state["revision"])
    service.configure_captions("clear")
    assert cancelled.wait(3)
    service.close()
    assert len(service._caption_workers) == 1
    assert not service.status()["captions"]["available"]
    assert service._caption_pending is None


def test_catalogue_refresh_rejects_previous_reference_without_automatic_fetch(online, monkeypatch):
    service, media, _snapshot, tracks, _saved = online
    calls, _closed = responses(monkeypatch, [Response()])
    original = service.status()["captions"]
    service.select_caption(original["tracks"][0]["id"], original["revision"])
    current = settle(service)
    refreshed = metadata()
    refreshed["subtitles"]["en"][2]["url"] += "-refreshed"
    fresh_tracks = replace(tracks, captions=provider.provider_caption_tracks(refreshed))
    service._publish_provider_captions(fresh_tracks, media, 0, service._cancel)
    state = service.status()["captions"]
    assert len(calls) == 1 and not state["available"] and state["selected_id"] is None
    with pytest.raises(CaptionError, match="changed"):
        service.select_caption(current["tracks"][0]["id"], current["revision"])
    with pytest.raises(CaptionError, match="unavailable"):
        service.select_caption(current["tracks"][0]["id"], state["revision"])
    service._media = None
    with pytest.raises(CaptionError, match="Open the current video"):
        service.select_caption(state["tracks"][0]["id"], state["revision"])


def test_timeout_and_cue_limit_are_enforced(monkeypatch):
    candidate = provider.provider_caption_tracks(metadata())[0]
    clock = [0.0]
    monkeypatch.setattr(provider.time, "monotonic", lambda: clock[0])

    class Slow(Response):
        def read1(self, size):
            clock[0] += 16
            return super().read1(size)

    responses(monkeypatch, [Slow()])
    with pytest.raises(CaptionError, match="timed out"):
        provider.load_provider_caption(candidate, threading.Event())
    cues = b"1\n00:00:00,000 --> 00:00:01,000\nText\n\n" * 20001
    responses(monkeypatch, [Response(cues)])
    with pytest.raises(CaptionError, match="too many cues"):
        provider.load_provider_caption(candidate, threading.Event())






def test_source_video_worker_publishes_provider_catalogue_without_fetching(monkeypatch, tmp_path):
    media = MediaRef(MediaSource.YOUTUBE, "https://youtube.com/watch?v=abcdefghijk", duration=100)
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=4)
    picture = video_sources.VideoTrack("https://provider.example/video", codec="avc1", container="mp4")
    tracks = video_sources.VideoTracks(picture, duration=100, captions=provider.provider_caption_tracks(metadata()))
    monkeypatch.setattr(video_sources, "_connection", lambda _url: pytest.fail("No caption request on open"))
    monkeypatch.setattr(video.VideoByteCache, "bind", lambda cache, track, _cancel: setattr(cache, "track", track))
    monkeypatch.setattr(video, "_probe", lambda *_args, **_kwargs: ("h264", 100))
    monkeypatch.setattr(video, "CachedVideoProxy", lambda *_args: SimpleNamespace(
        url="http://127.0.0.1/private-handle", start=lambda: None, close=lambda: None,
    ))
    service = video.LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _event: None,
                               resolve_video=lambda *_args: tracks)
    try:
        service.request("video")
        deadline = time.monotonic() + 3
        while service.status()["state"] == "preparing":
            assert time.monotonic() < deadline
            time.sleep(0.005)
        state = service.status()
        assert state["state"] == "ready" and state["transport"] == "source"
        assert len(state["captions"]["tracks"]) == 2 and not state["captions"]["available"]
        assert snapshot.position == 4 and snapshot.state == PlaybackState.PLAYING
    finally:
        service.close()
