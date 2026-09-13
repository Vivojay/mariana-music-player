import json
import threading

import pytest

from mariana.lyrics_presentation import LyricsPresentationService
from mariana.lyrics_timeline import LyricsTimelineError
from mariana.models import (
    IdentityStatus,
    LyricsResult,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    TrackIdentity,
)


def media(stable_id="track-a", **kwargs):
    return MediaRef(MediaSource.LOCAL, "C:/Private/Music/song.mp3", stable_id=stable_id, duration=20, **kwargs)


def snapshot(track=None, position=0, state=PlaybackState.PLAYING):
    return PlaybackSnapshot(state, position=position, media=track or media())


def timed(text="First"):
    return LyricsResult(
        IdentityStatus.IDENTIFIED,
        synced=f"[00:01]{text}\n[00:03]Second\n[00:05]\n[00:08]Last",
        provider="local-sidecar",
        attribution="C:/Private/Music/song.lrc",
    )


class Resolver:
    def __init__(self, result=None):
        self.result = result or timed()
        self.calls = []

    def lyrics(self, media, identity, refresh=False):
        self.calls.append((media, identity, refresh))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class BlockingResolver(Resolver):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def lyrics(self, media, identity, refresh=False):
        self.calls.append((media, identity, refresh))
        if len(self.calls) == 1:
            self.started.set()
            assert self.release.wait(2), "Test must release the blocked resolver"
            return timed("Stale result")
        return timed(media.stable_id)


@pytest.fixture
def service():
    resolver = Resolver()
    instance = LyricsPresentationService(resolver)
    yield instance, resolver
    instance.close()


def test_playback_observation_and_status_never_request_lyrics(service):
    instance, resolver = service
    for position in (0, 1, 4):
        instance.update_playback(snapshot(position=position), session_id="session-a")
        instance.projection()
    assert resolver.calls == []
    assert instance.projection()["state"] == "idle"
    assert instance.projection()["visible"] is False


def test_explicit_lookup_uses_existing_resolver_and_sanitizes_projection(service):
    instance, resolver = service
    instance.update_playback(snapshot(media(title="Title", artist="Artist"), 3.5))
    initial = instance.request(media_id="track-a")
    assert initial["state"] == "loading"
    assert instance.wait_for_idle()
    result = instance.projection()
    assert result["state"] == "timed"
    assert result["active"] == {"start_ms": 3000, "text": "Second"}
    assert result["previous"] == {"start_ms": 1000, "text": "First"}
    assert result["following"] == {"start_ms": 5000, "text": ""}
    assert result["attribution"] == "Lyrics from the local LRC sidecar"
    assert "Private" not in json.dumps(result)
    assert "original_uri" not in result
    assert resolver.calls[0][1].title == "Title"
    assert resolver.calls[0][1].artist == "Artist"
    assert resolver.calls[0][2] is False
    instance.request(media_id="track-a")
    assert len(resolver.calls) == 1  # Reopening ready lyrics does not repeat I/O.


def test_pause_resume_and_seek_use_source_position_without_refetch(service):
    instance, resolver = service
    instance.update_playback(snapshot(position=2))
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    paused = instance.update_playback(snapshot(position=2, state=PlaybackState.PAUSED))
    assert paused["active"]["text"] == "First"
    assert instance.projection() == paused
    sought = instance.update_playback(snapshot(position=9, state=PlaybackState.SEEKING))
    assert sought["active"]["text"] == "Last"
    rewound = instance.update_playback(snapshot(position=0.5))
    assert rewound["active"] is None
    assert rewound["following"]["text"] == "First"
    blank = instance.update_playback(snapshot(position=6))
    assert blank["active"]["text"] == ""
    ended = instance.update_playback(snapshot(position=21))
    assert ended["active"] is None
    assert ended["previous"]["text"] == "Last"
    assert len(resolver.calls) == 1


def test_source_and_user_offsets_combine_without_moving_audio(service):
    instance, resolver = service
    resolver.result = LyricsResult(IdentityStatus.IDENTIFIED, synced="[offset:500]\n[00:01]First\n[00:02]Second")
    instance.update_playback(snapshot(position=1.25))
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    assert instance.projection()["active"] is None
    shifted = instance.set_offset("track-a", -250)
    assert shifted["active"]["text"] == "First"
    assert shifted["position_ms"] == 1250
    assert shifted["source_offset_ms"] == 500
    assert shifted["offset_ms"] == -250
    instance.set_offset("track-a", -60000)
    instance.set_offset("track-a", 60000)
    assert len(resolver.calls) == 1


@pytest.mark.parametrize("offset", [True, 1.2, "100", -60001, 60001])
def test_offset_validation_is_integral_and_bounded(service, offset):
    instance, _ = service
    instance.update_playback(snapshot())
    with pytest.raises(LyricsTimelineError):
        instance.set_offset("track-a", offset)
    assert instance.projection()["offset_ms"] == 0


def test_media_change_rejects_stale_result_and_resets_offset():
    resolver = BlockingResolver()
    emitted = []
    instance = LyricsPresentationService(resolver, on_change=emitted.append)
    try:
        instance.update_playback(snapshot(), session_id="a")
        instance.request(media_id="track-a")
        assert resolver.started.wait(1)
        instance.set_offset("track-a", 500)
        instance.update_playback(snapshot(media("track-b"), 4), session_id="b")
        instance.request(media_id="track-b")
        resolver.release.set()
        assert instance.wait_for_idle()
        result = instance.projection()
        assert result["media_id"] == "track-b"
        assert result["offset_ms"] == 0
        assert result["state"] == "timed"
        assert not any(row["state"] == "timed" and row["media_id"] == "track-a" for row in emitted)
    finally:
        resolver.release.set()
        instance.close()


def test_same_media_new_session_invalidates_pending_result():
    resolver = BlockingResolver()
    instance = LyricsPresentationService(resolver)
    try:
        instance.update_playback(snapshot(), session_id="first-play")
        instance.request(media_id="track-a")
        assert resolver.started.wait(1)
        first_session = instance.projection()["session_revision"]
        instance.update_playback(snapshot(), session_id="second-play")
        resolver.release.set()
        assert instance.wait_for_idle()
        assert instance.projection()["state"] == "idle"
        assert instance.projection()["session_revision"] > first_session
    finally:
        resolver.release.set()
        instance.close()


def test_authoritative_snapshot_session_token_is_used_by_default(service):
    instance, _ = service
    instance.update_playback(PlaybackSnapshot(PlaybackState.PLAYING, media=media(), session_id="first"))
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    instance.update_playback(PlaybackSnapshot(PlaybackState.PLAYING, media=media(), session_id="second"))
    assert instance.projection()["state"] == "idle"


def test_identity_change_drops_ready_lyrics_without_new_io(service):
    instance, resolver = service
    first = TrackIdentity(IdentityStatus.IDENTIFIED, recording_mbid="first")
    second = TrackIdentity(IdentityStatus.IDENTIFIED, recording_mbid="second")
    instance.update_playback(snapshot(), identity=first)
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    instance.update_playback(snapshot(), identity=second)
    assert instance.projection()["state"] == "idle"
    assert instance.projection()["active"] is None
    assert len(resolver.calls) == 1


def test_one_running_and_one_latest_pending_request_bounds_work():
    resolver = BlockingResolver()
    instance = LyricsPresentationService(resolver)
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        assert resolver.started.wait(1)
        for index in range(30):
            stable_id = f"track-{index}"
            instance.update_playback(snapshot(media(stable_id)))
            instance.request(media_id=stable_id)
        resolver.release.set()
        assert instance.wait_for_idle()
        assert [call[0].stable_id for call in resolver.calls] == ["track-a", "track-29"]
        assert instance.projection()["media_id"] == "track-29"
    finally:
        resolver.release.set()
        instance.close()


@pytest.mark.parametrize("synced", [
    "not timed", "[00:99]Bad", ["bad"], "x" * 1_000_001, "[offset:" + "9" * 5000 + "]\n[00:01]Line",
], ids=["untimed", "bad-time", "bad-type", "oversized", "malformed-offset"])
def test_malformed_timing_retains_plain_fallback(service, synced):
    instance, resolver = service
    resolver.result = LyricsResult(IdentityStatus.IDENTIFIED, synced=synced, plain="First\nSecond", provider="embedded")
    instance.update_playback(snapshot())
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    result = instance.projection()
    assert result["state"] == "plain"
    assert result["plain"] == "First\nSecond"
    assert result["active"] is None
    assert result["available"] is True


@pytest.mark.parametrize("result,state", [
    (LyricsResult(IdentityStatus.OFFLINE), "unavailable"),
    (LyricsResult(IdentityStatus.NO_LYRICS), "unavailable"),
    (LyricsResult(IdentityStatus.IDENTIFIED, synced="not timed"), "unavailable"),
    (LyricsResult(IdentityStatus.IDENTIFIED, plain=123), "unavailable"),
    (ValueError("C:/Private/secret https://private.test?token=secret"), "error"),
])
def test_safe_unavailability_and_error_projection(service, result, state):
    instance, resolver = service
    resolver.result = result
    instance.update_playback(snapshot())
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    projected = instance.projection()
    assert projected["state"] == state
    assert projected["available"] is False
    assert "Private" not in json.dumps(projected)
    assert "token" not in json.dumps(projected)


def test_provider_control_characters_and_private_attribution_are_not_projected(service):
    instance, resolver = service
    resolver.result = LyricsResult(
        IdentityStatus.IDENTIFIED, plain="Hello\x00\x1b\u202e\nWorld",
        provider="file:///private/provider", attribution="C:/Private/secret.lrc",
    )
    instance.update_playback(snapshot())
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    result = instance.projection()
    assert result["plain"] == "Hello\nWorld"
    assert result["provider"] is None
    assert result["attribution"] is None


@pytest.mark.parametrize("operation", ["hide", "close"])
def test_hidden_or_shutdown_work_cannot_publish_or_reopen(operation):
    resolver = BlockingResolver()
    emitted = []
    instance = LyricsPresentationService(resolver, on_change=emitted.append)
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        assert resolver.started.wait(1)
        getattr(instance, operation)()
        count = len(emitted)
        resolver.release.set()
        assert instance.wait_for_idle()
        assert len(emitted) == count
        assert instance.projection()["state"] == "idle"
        assert instance.projection()["visible"] is False
        if operation == "close":
            with pytest.raises(RuntimeError, match="closed"):
                instance.request(media_id="track-a")
    finally:
        resolver.release.set()
        instance.close()


def test_wrong_media_controls_are_rejected_and_projection_copies_are_detached(service):
    instance, resolver = service
    instance.update_playback(snapshot())
    with pytest.raises(ValueError, match="Playback changed"):
        instance.request(media_id="track-b")
    with pytest.raises(ValueError, match="Playback changed"):
        instance.set_offset("track-b", 0)
    result = instance.projection()
    result["state"] = "timed"
    assert instance.projection()["state"] == "idle"
    assert resolver.calls == []


def test_idle_playback_clears_existing_lyrics(service):
    instance, _ = service
    instance.update_playback(snapshot())
    instance.request(media_id="track-a")
    assert instance.wait_for_idle()
    instance.update_playback(snapshot(state=PlaybackState.IDLE))
    assert instance.projection()["media_id"] is None
    assert instance.projection()["active"] is None
    assert instance.projection()["available"] is False


def test_existing_identity_resolver_prefers_local_sidecar_without_provider_lookup(tmp_path):
    from mariana.identity import IdentificationService

    class NoNetwork:
        def find(self, _identity):
            raise AssertionError("Local lyrics must not perform a network lookup")

    path = tmp_path / "song.mp3"
    path.with_suffix(".lrc").write_text("[00:01]Local lyric", encoding="utf-8")
    identification = IdentificationService(None, lrclib=NoNetwork())
    instance = LyricsPresentationService(identification)
    try:
        track = MediaRef(MediaSource.LOCAL, str(path), stable_id="local-track")
        instance.update_playback(snapshot(track, 2))
        instance.request(media_id="local-track")
        assert instance.wait_for_idle()
        assert instance.projection()["active"]["text"] == "Local lyric"
        assert instance.projection()["provider"] == "local-sidecar"
    finally:
        instance.close()


def test_existing_identity_resolver_uses_cached_timing_before_network():
    from mariana.identity import IdentificationService

    class Cache:
        def fetchone(self, _sql, _parameters):
            return {"status": "identified", "plain_lyrics": "Cached", "synced_lyrics": "[00:01]Cached",
                    "provider": "LRCLIB", "provider_id": "123", "retrieved_at": 1, "identity_confidence": 0.9}

    class NoNetwork:
        def find(self, _identity):
            raise AssertionError("Cached lyrics must not perform a network lookup")

    instance = LyricsPresentationService(IdentificationService(Cache(), lrclib=NoNetwork()))
    try:
        track = MediaRef(MediaSource.URL, "https://private.test/track?token=secret", stable_id="cached-track")
        instance.update_playback(snapshot(track, 2))
        instance.request(media_id="cached-track", identity=TrackIdentity(IdentityStatus.IDENTIFIED, recording_mbid="id"))
        assert instance.wait_for_idle()
        assert instance.projection()["active"]["text"] == "Cached"
        assert "secret" not in json.dumps(instance.projection())
    finally:
        instance.close()


def test_superseded_failure_cannot_replace_latest_loading_or_result():
    class FailingFirst(BlockingResolver):
        def lyrics(self, media, identity, refresh=False):
            result = super().lyrics(media, identity, refresh)
            if media.stable_id == "track-a":
                raise OSError("Late failure from an old request")
            return result

    resolver = FailingFirst()
    emitted = []
    instance = LyricsPresentationService(resolver, on_change=emitted.append)
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        assert resolver.started.wait(1)
        instance.update_playback(snapshot(media("track-b")))
        instance.request(media_id="track-b")
        resolver.release.set()
        assert instance.wait_for_idle()
        assert instance.projection()["state"] == "timed"
        assert not any(row["state"] == "error" for row in emitted)
    finally:
        resolver.release.set()
        instance.close()


def observe_worker_waits(instance, monkeypatch):
    """Observe actual condition transitions, without timing-dependent sleeps."""
    indefinite = threading.Event()
    sampling = threading.Event()
    original = instance._condition.wait

    def wait(timeout=None):
        if threading.current_thread() is instance._worker:
            (indefinite if timeout is None else sampling).set()
            assert timeout is None or timeout == 0.1
        return original(timeout)

    monkeypatch.setattr(instance._condition, "wait", wait)
    return indefinite, sampling


def test_visible_timed_lyrics_sample_source_pause_and_seek_without_refetch(monkeypatch):
    resolver = Resolver()
    positions = {2000: threading.Event(), 9000: threading.Event(), 500: threading.Event()}
    current = [snapshot(position=2, state=PlaybackState.PAUSED)]
    reads = []

    def source():
        reads.append(current[0])
        return current[0]

    def changed(value):
        if value["state"] == "timed" and value["position_ms"] in positions:
            positions[value["position_ms"]].set()

    instance = LyricsPresentationService(resolver, snapshot=source, on_change=changed)
    indefinite, _ = observe_worker_waits(instance, monkeypatch)
    try:
        instance.update_playback(snapshot())
        assert instance._worker is None and reads == []
        instance.request(media_id="track-a")
        worker = instance._worker
        assert positions[2000].wait(1)
        assert instance.projection()["active"]["text"] == "First"
        current[0] = snapshot(position=9, state=PlaybackState.SEEKING)
        assert positions[9000].wait(1)
        assert instance.projection()["active"]["text"] == "Last"
        current[0] = snapshot(position=0.5)
        assert positions[500].wait(1)
        assert instance.projection()["active"] is None
        instance.hide()
        assert indefinite.wait(1)
        assert instance._worker is worker
        assert len(resolver.calls) == 1
    finally:
        instance.close()


@pytest.mark.parametrize("result", [
    LyricsResult(IdentityStatus.IDENTIFIED, plain="Plain"),
    LyricsResult(IdentityStatus.NO_LYRICS),
])
def test_plain_and_unavailable_lyrics_do_not_start_timed_source_polling(result, monkeypatch):
    reads = []
    instance = LyricsPresentationService(Resolver(result), snapshot=lambda: reads.append(True))
    indefinite, sampling = observe_worker_waits(instance, monkeypatch)
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        assert indefinite.wait(1)
        assert not sampling.is_set()
        assert reads == []
    finally:
        instance.close()


def test_hidden_ready_lyrics_stop_polling_and_reopen_same_worker_without_lookup(monkeypatch):
    resolver = Resolver()
    sampled = threading.Event()
    reads = []

    def source():
        reads.append(True)
        sampled.set()
        return snapshot(position=2)

    instance = LyricsPresentationService(resolver, snapshot=source)
    indefinite, sampling = observe_worker_waits(instance, monkeypatch)
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        worker = instance._worker
        assert sampled.wait(1)
        instance.hide()
        assert indefinite.wait(1)
        count = len(reads)
        sampled.clear()
        sampling.clear()
        instance.request(media_id="track-a")
        assert sampling.wait(1)
        assert sampled.wait(1)
        assert len(reads) > count
        assert instance._worker is worker
        assert len(resolver.calls) == 1
    finally:
        instance.close()


@pytest.mark.parametrize("operation", ["hide", "close"])
def test_source_read_is_outside_lock_and_late_sample_cannot_publish_after_hide_or_close(operation):
    started = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    events = []

    def source():
        started.set()
        assert release.wait(2)
        return snapshot(position=9)

    instance = LyricsPresentationService(Resolver(), snapshot=source, on_change=events.append)
    controller = None
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        assert started.wait(1)

        def stop():
            getattr(instance, operation)()
            stopped.set()

        controller = threading.Thread(target=stop)
        controller.start()
        assert stopped.wait(1), "Source callback must not hold the lyrics condition"
        count = len(events)
        release.set()
        assert instance.wait_for_idle()
        assert len(events) == count
        assert instance.projection()["visible"] is False
        assert instance.projection()["position_ms"] == 0
        if operation == "close":
            instance._worker.join(1)
            assert not instance._worker.is_alive()
    finally:
        release.set()
        instance.close()
        if controller:
            controller.join(1)


@pytest.mark.parametrize("stable_id,session_id", [("track-b", "first"), ("track-a", "second")])
def test_sampled_media_or_same_media_session_change_invalidates_lyrics_and_stops_sampling(stable_id, session_id, monkeypatch):
    reads = []
    resolver = Resolver()
    next_snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media(stable_id), session_id=session_id)

    def source():
        reads.append(True)
        return next_snapshot

    instance = LyricsPresentationService(resolver, snapshot=source)
    indefinite, _ = observe_worker_waits(instance, monkeypatch)
    try:
        instance.update_playback(PlaybackSnapshot(PlaybackState.PLAYING, media=media(), session_id="first"))
        instance.request(media_id="track-a")
        assert indefinite.wait(1)
        assert instance.projection()["state"] == "idle"
        assert instance.projection()["active"] is None
        assert instance.projection()["media_id"] == stable_id
        assert len(reads) == len(resolver.calls) == 1
    finally:
        instance.close()


def test_delayed_source_sample_cannot_undo_explicit_seek():
    started = threading.Event()
    release = threading.Event()
    events = []
    reads = []

    def source():
        reads.append(True)
        if len(reads) == 1:
            started.set()
            assert release.wait(2)
            return snapshot(position=2)  # Captured before the explicit seek.
        return snapshot(position=9)

    instance = LyricsPresentationService(Resolver(), snapshot=source, on_change=events.append)
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        assert started.wait(1)
        instance.update_playback(snapshot(position=9, state=PlaybackState.SEEKING))
        count = len(events)
        release.set()
        assert instance.wait_for_idle()
        assert instance.projection()["position_ms"] == 9000
        assert not any(value["position_ms"] == 2000 for value in events[count:])
    finally:
        release.set()
        instance.close()


@pytest.mark.parametrize("invalid", [None, {"position": 9}, RuntimeError("Private source error")])
def test_source_observation_errors_are_nonfatal_and_do_not_trigger_lyrics_lookup(invalid):
    selected = threading.Event()
    reads = []
    resolver = Resolver()

    def source():
        reads.append(True)
        if len(reads) == 1:
            if isinstance(invalid, Exception):
                raise invalid
            return invalid
        return snapshot(position=9)

    def changed(value):
        if value["position_ms"] == 9000:
            selected.set()

    instance = LyricsPresentationService(resolver, snapshot=source, on_change=changed)
    try:
        instance.update_playback(snapshot())
        instance.request(media_id="track-a")
        assert selected.wait(1)
        assert instance.projection()["active"]["text"] == "Last"
        assert len(resolver.calls) == 1
    finally:
        instance.close()
