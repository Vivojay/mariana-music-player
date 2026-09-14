import subprocess
import sys
import threading
from array import array
from types import SimpleNamespace

import pytest

from mariana import playback
from mariana.models import MediaCapabilities, MediaChapter, MediaRef, MediaSource, PlaybackState, PlayRegion

RealDecoderSession = playback.DecoderSession
RealThread = threading.Thread


class Stream:
    instances = []

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.started = self.stopped = self.closed = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class Session:
    wait_result = True
    error = None
    created = []

    def __init__(self, media, **kwargs):
        self.media = media
        self.resolved = kwargs.get("resolved")
        self.start_at = kwargs.get("start_at", 0)
        self.position = self.start_at
        self.buffered_seconds = 1.0
        self.fingerprint_pcm = b"fingerprint"
        self.eof = False
        self.started = self.stopped = self.reset = False
        self.on_metadata = None
        self.created.append(self)

    def start(self):
        self.started = True

    def wait_for_buffer(self, *args, **kwargs):
        return self.wait_result

    def read(self, frames):
        self.position += frames / playback.SAMPLE_RATE
        return array("f", [0.25] * frames * 2).tobytes()

    def stop(self):
        self.stopped = True

    def reset_fingerprint(self):
        self.reset = True


class ImmediateThread:
    def __init__(self, target, args=(), name="", **_kwargs):
        self.target = target
        self.args = args
        self.name = name

    def start(self):
        if getattr(self.target, "__name__", "") == "stop" or self.name == "mariana-playback-complete":
            self.target(*self.args)


class Resolvers:
    def resolve(self, media, **_kwargs):
        return playback.ResolvedMedia(
            media,
            media.original_uri,
            media.original_uri,
            media.capabilities,
        )

    def classify_failure(self, error, media):
        return playback.MediaFailure(playback.FailureCode.UNAVAILABLE, media.source, str(error))


@pytest.fixture
def controller(monkeypatch):
    Session.created.clear()
    Session.wait_result = True
    Session.error = None
    Stream.instances.clear()
    monkeypatch.setattr(playback, "DecoderSession", Session)
    monkeypatch.setattr(playback.threading, "Thread", ImmediateThread)
    return playback.PlaybackController(output_factory=Stream, crossfade_seconds=2, resolvers=Resolvers())


def finite(name="track", duration=10):
    return MediaRef(MediaSource.LOCAL, f"C:/{name}.flac", title=name, duration=duration)


@pytest.mark.parametrize("handoff", ["stop", "selection"])
@pytest.mark.parametrize("buffered", [True, False])
def test_stale_seek_completion_cannot_resume_or_capture_after_replacement(controller, monkeypatch, handoff, buffered):
    original, current = finite("seek-source", duration=30), finite("new-selection", duration=30)
    events = []
    controller._playback_event_sink = lambda **event: events.append(event) or True
    controller.play(original, probe=False, origin="cli")

    def interleaved_buffer(session, *_args, **_kwargs):
        if session.media is original and session.start_at == 8:
            if handoff == "stop":
                controller.stop()
            else:
                controller.play(current, probe=False, start_at=3, start_paused=True, origin="cli")
            return buffered
        return True

    monkeypatch.setattr(Session, "wait_for_buffer", interleaved_buffer)
    with pytest.raises(playback.PlaybackError, match="replaced"):
        controller.seek(8, origin="desktop")

    snapshot = controller.snapshot()
    assert snapshot.state == (PlaybackState.IDLE if handoff == "stop" else PlaybackState.PAUSED)
    assert snapshot.position == (0 if handoff == "stop" else 3)
    assert snapshot.error is None
    assert not any(event["action"] == "seek" for event in events)
    retired = next(session for session in Session.created if session.media is original and session.start_at == 8)
    assert retired.stopped
    if handoff == "selection":
        assert snapshot.media is current
        assert not Session.created[-1].stopped
    controller.close()


def test_stale_resolution_success_cannot_replace_newer_paused_media(controller, monkeypatch):
    old, current = finite("old-resolution"), finite("newer-selection")
    resolve = controller.resolvers.resolve
    probes = []

    def interleaved_resolution(media):
        if media is old:
            controller.play(current, probe=False, start_at=3, start_paused=True)
        return resolve(media)

    monkeypatch.setattr(controller.resolvers, "resolve", interleaved_resolution)
    monkeypatch.setattr(playback, "probe_media", lambda media, **_kwargs: probes.append(media) or media)
    with pytest.raises(playback.PlaybackError, match="replaced"):
        controller.play(old, probe=True)

    snapshot = controller.snapshot()
    assert snapshot.media is current
    assert snapshot.state == PlaybackState.PAUSED
    assert snapshot.position == 3 and snapshot.error is None
    assert len(Session.created) == 1
    assert probes == []
    assert Session.created[0].media is current and not Session.created[0].stopped
    assert controller.resolved_uri == current.original_uri
    controller.close()
    assert Session.created[0].stopped


def test_stale_resolution_failure_cannot_mark_newer_paused_media_failed(controller, monkeypatch):
    old, current = finite("old-resolution"), finite("newer-selection")
    resolve = controller.resolvers.resolve

    def interleaved_resolution(media):
        if media is old:
            controller.play(current, probe=False, start_at=3, start_paused=True)
            raise ValueError("Older resolver failed")
        return resolve(media)

    monkeypatch.setattr(controller.resolvers, "resolve", interleaved_resolution)
    with pytest.raises(ValueError, match="Older resolver failed"):
        controller.play(old, probe=False)

    snapshot = controller.snapshot()
    assert snapshot.media is current
    assert snapshot.state == PlaybackState.PAUSED
    assert snapshot.position == 3 and snapshot.error is None
    assert len(Session.created) == 1 and not Session.created[0].stopped
    assert controller.resolved_uri == current.original_uri
    controller.close()
    assert Session.created[0].stopped


def test_decoder_start_failure_retires_exact_attempt_and_allows_retry(controller, monkeypatch):
    broken, current = finite("startup-failure"), finite("retry")
    start = Session.start

    def acquire_then_fail(session):
        start(session)
        if session.media is broken:
            raise playback.PlaybackError("Decoder startup failed after resource acquisition")

    monkeypatch.setattr(Session, "start", acquire_then_fail)
    with pytest.raises(playback.PlaybackError, match="Decoder startup failed"):
        controller.play(broken, probe=False)

    failed_session = Session.created[0]
    assert failed_session.started and failed_session.stopped
    assert controller._active is None
    assert controller.snapshot().state == PlaybackState.FAILED
    assert controller.snapshot().session_id is None
    controller.play(current, probe=False, start_at=2, start_paused=True)
    assert controller.snapshot().media is current
    assert controller.snapshot().state == PlaybackState.PAUSED
    assert controller.snapshot().position == 2 and controller.snapshot().error is None
    assert len(Session.created) == 2 and not Session.created[1].stopped
    controller.close()
    assert all(session.stopped for session in Session.created)


def test_stop_during_resolution_prevents_late_decoder_start(controller, monkeypatch):
    current, pending = finite("current"), finite("pending-resolution")
    controller.play(current, probe=False, start_paused=True)
    previous = controller._active
    resolve = controller.resolvers.resolve

    def stopped_resolution(media):
        controller.stop()
        return resolve(media)

    monkeypatch.setattr(controller.resolvers, "resolve", stopped_resolution)
    with pytest.raises(playback.PlaybackError, match="replaced"):
        controller.play(pending, probe=False)

    assert previous.stopped
    assert len(Session.created) == 1
    assert controller._active is None and controller.resolved_uri is None
    assert controller.snapshot().state == PlaybackState.IDLE
    assert controller.snapshot().session_id is None
    controller.close()
    assert all(stream.closed for stream in Stream.instances)


@pytest.mark.parametrize("interruption", ["stop", "replacement"])
def test_probe_completion_cannot_revive_stopped_or_replaced_request(controller, monkeypatch, interruption):
    original, pending, current = finite("original"), finite("pending-probe"), finite("newer")
    controller.play(original, probe=False, start_paused=True)
    previous = controller._active
    events, labels, probes, resolutions = [], [], [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.add_metadata_sink(labels.append)
    resolve = controller.resolvers.resolve

    def record_resolution(media):
        resolutions.append(media)
        return resolve(media)

    def finish_obsolete_probe(media, **_kwargs):
        probes.append(media)
        if interruption == "stop":
            controller.stop()
        else:
            controller.play(current, probe=False, start_at=4, start_paused=True, origin="desktop")
        return media

    monkeypatch.setattr(controller.resolvers, "resolve", record_resolution)
    monkeypatch.setattr(playback, "probe_media", finish_obsolete_probe)
    try:
        with pytest.raises(playback.PlaybackError, match="replaced"):
            controller.play(pending, probe=True, origin="cli")

        assert probes == [pending] and previous.stopped
        assert all(session.media is not pending for session in Session.created)
        assert all(event["stable_id"] != pending.stable_id for event in events)
        assert pending.title not in labels
        snapshot = controller.snapshot()
        if interruption == "stop":
            assert resolutions == [pending] and events == [] and labels == []
            assert controller._active is None and controller.resolved_uri is None
            assert snapshot.state == PlaybackState.IDLE and snapshot.session_id is None
        else:
            assert resolutions == [pending, current]
            assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
            assert snapshot.position == 4 and snapshot.error is None
            assert controller.resolved_uri == current.original_uri
            assert labels == [current.title]
            assert [event["action"] for event in events] == ["play", "pause"]
            assert all(event["session_id"] == snapshot.session_id for event in events)
            assert not controller._active.stopped
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)
    assert all(stream.closed for stream in Stream.instances)


def test_newer_selection_after_prepare_return_is_not_consumed_by_old_play(controller, monkeypatch):
    pending, current = finite("prepared-old"), finite("prepared-new")
    events, labels, prepared = [], [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.add_metadata_sink(labels.append)
    prepare = controller._prepare_media

    def replace_after_preparation(media, **kwargs):
        result = prepare(media, **kwargs)
        prepared.append(result)
        if media is pending:
            controller.play(current, probe=False, start_at=3, start_paused=True, origin="desktop")
        return result

    monkeypatch.setattr(controller, "_prepare_media", replace_after_preparation)
    try:
        with pytest.raises(playback.PlaybackError, match="replaced"):
            controller.play(pending, probe=False, origin="cli")

        snapshot = controller.snapshot()
        assert prepared == [pending, current]
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 3 and snapshot.error is None
        assert controller.resolved_uri == current.original_uri
        assert len(Session.created) == 1 and Session.created[0].media is current
        assert not Session.created[0].stopped and labels == [current.title]
        assert [event["action"] for event in events] == ["play", "pause"]
        assert all(event["stable_id"] == current.stable_id for event in events)
        assert all(event["session_id"] == snapshot.session_id for event in events)
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)


def test_newer_selection_during_region_lookup_keeps_its_own_bounds(controller):
    pending, current = finite("old-region"), finite("new-region")
    events, labels, lookups = [], [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.add_metadata_sink(labels.append)

    def preferred_region(media):
        lookups.append(media)
        if media is pending:
            controller.play(current, probe=False, start_at=1, start_paused=True, origin="desktop")
            return PlayRegion(media.stable_id, start_seconds=1, end_seconds=2)
        return PlayRegion(media.stable_id, start_seconds=4, end_seconds=8)

    controller.play_region_provider = preferred_region
    try:
        with pytest.raises(playback.PlaybackError, match="replaced"):
            controller.play(pending, probe=False, origin="cli")

        snapshot = controller.snapshot()
        assert lookups == [pending, current]
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 4 and snapshot.error is None
        assert snapshot.region_start_seconds == 4 and snapshot.region_end_seconds == 8
        assert controller.resolved_uri == current.original_uri
        assert len(Session.created) == 1 and Session.created[0].media is current
        assert not Session.created[0].stopped and labels == [current.title]
        assert [event["action"] for event in events] == ["play", "pause"]
        assert all(event["stable_id"] == current.stable_id for event in events)
        assert all(event["position_seconds"] == 4 for event in events)
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)


def test_newer_selection_after_stop_retirement_prevents_obsolete_decoder_construction(controller, monkeypatch):
    original, pending, current = finite("retiring"), finite("obsolete-construction"), finite("newer")
    controller.play(original, probe=False)
    previous = controller._active
    events, labels = [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.add_metadata_sink(labels.append)
    stop = controller._stop_playback
    replace = True

    def replace_after_retirement(**kwargs):
        nonlocal replace
        stopped = stop(**kwargs)
        if replace:
            replace = False
            assert previous.stopped and controller._active is None
            controller.play(current, probe=False, start_at=5, start_paused=True, origin="desktop")
        return stopped

    monkeypatch.setattr(controller, "_stop_playback", replace_after_retirement)
    try:
        with pytest.raises(playback.PlaybackError, match="replaced"):
            controller.play(pending, probe=False, origin="cli")

        snapshot = controller.snapshot()
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 5 and snapshot.error is None
        assert [session.media for session in Session.created] == [original, current]
        assert previous.stopped and not controller._active.stopped
        assert labels == [current.title]
        assert [event["action"] for event in events] == ["play", "pause"]
        assert all(event["stable_id"] == current.stable_id for event in events)
        assert all(event["session_id"] == snapshot.session_id for event in events)
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)


def test_newer_selection_after_output_open_prevents_stale_play_commit(controller, monkeypatch):
    pending, current = finite("output-ready-old"), finite("output-ready-new")
    events, labels = [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.add_metadata_sink(labels.append)
    ensure = controller._ensure_output
    replace = True

    def replace_after_output(**kwargs):
        nonlocal replace
        ensure(**kwargs)
        if replace:
            replace = False
            controller.play(current, probe=False, start_at=6, start_paused=True, origin="desktop")

    monkeypatch.setattr(controller, "_ensure_output", replace_after_output)
    try:
        with pytest.raises(playback.PlaybackError, match="replaced"):
            controller.play(pending, probe=False, origin="cli")

        snapshot = controller.snapshot()
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 6 and snapshot.error is None
        assert [session.media for session in Session.created] == [pending, current]
        assert Session.created[0].stopped and not Session.created[1].stopped
        assert len(Stream.instances) == 1 and controller._stream is Stream.instances[0]
        assert Stream.instances[0].started and not Stream.instances[0].closed
        assert labels == [current.title]
        assert [event["action"] for event in events] == ["play", "pause"]
        assert all(event["stable_id"] == current.stable_id for event in events)
        assert all(event["session_id"] == snapshot.session_id for event in events)
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)
    assert all(stream.closed for stream in Stream.instances)


def test_replacement_while_old_resources_retire_preserves_new_state_and_publication(controller, monkeypatch):
    original, obsolete, current = finite("original"), finite("obsolete"), finite("newest")
    controller.play(original, probe=False)
    retiring = controller._active
    published = []
    controller.add_active_media_sink(lambda media, _resolved: published.append(media))
    stop = Session.stop

    def replace_while_retiring(session):
        stop(session)
        if session is retiring:
            controller.play(current, probe=False, start_at=4, start_paused=True)

    monkeypatch.setattr(Session, "stop", replace_while_retiring)
    with pytest.raises(playback.PlaybackError, match="replaced"):
        controller.play(obsolete, probe=False)

    snapshot = controller.snapshot()
    assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
    assert snapshot.position == 4 and snapshot.error is None
    assert retiring.stopped and len(Session.created) == 2
    assert not Session.created[1].stopped
    assert published[-1] is current and obsolete not in published
    assert controller.resolved_uri == current.original_uri
    controller.close()
    assert Session.created[1].stopped


def test_close_before_output_open_cannot_reopen_stream(controller, monkeypatch):
    ensure = controller._ensure_output

    def close_before_open(**kwargs):
        controller.close()
        ensure(**kwargs)

    monkeypatch.setattr(controller, "_ensure_output", close_before_open)
    with pytest.raises(playback.PlaybackError, match="replaced"):
        controller.play(finite("closing"), probe=False)

    assert len(Session.created) == 1 and Session.created[0].stopped
    assert Stream.instances == []
    assert controller._stream is None and controller._active is None
    assert controller.snapshot().state == PlaybackState.IDLE
    assert controller.snapshot().session_id is None


def test_newer_play_during_stream_start_retires_only_unpublished_output(controller, monkeypatch):
    old, current = finite("old-output-request"), finite("new-output-request")
    newer_decoder_ready = threading.Event()
    failures, workers = [], []
    start = Stream.start
    wait = Session.wait_for_buffer

    def mark_newer_ready(session, *args, **kwargs):
        if session.media is current:
            newer_decoder_ready.set()
        return wait(session, *args, **kwargs)

    def play_newer():
        try:
            controller.play(current, probe=False, start_at=5, start_paused=True)
        except BaseException as error:
            failures.append(error)

    def replace_during_start(stream):
        start(stream)
        if stream is Stream.instances[0]:
            worker = RealThread(target=play_newer, daemon=True)
            workers.append(worker)
            worker.start()
            assert newer_decoder_ready.wait(2), "Replacement decoder did not reach output acquisition"

    monkeypatch.setattr(Session, "wait_for_buffer", mark_newer_ready)
    monkeypatch.setattr(Stream, "start", replace_during_start)
    try:
        with pytest.raises(playback.PlaybackError, match="replaced"):
            controller.play(old, probe=False)
        for worker in workers:
            worker.join(2)
        assert workers and all(not worker.is_alive() for worker in workers)
        assert failures == []
        snapshot = controller.snapshot()
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 5 and snapshot.error is None
        assert len(Session.created) == 2
        assert Session.created[0].stopped and not Session.created[1].stopped
        assert len(Stream.instances) == 2
        assert Stream.instances[0].stopped and Stream.instances[0].closed
        assert controller._stream is Stream.instances[1]
        assert not Stream.instances[1].closed
    finally:
        controller.close()
        for worker in workers:
            worker.join(2)
    assert all(session.stopped for session in Session.created)
    assert all(stream.closed for stream in Stream.instances)


def test_metadata_observer_replacement_preserves_commit_order_and_current_label(controller):
    original, current = finite("first-committed"), finite("observer-selection")
    events, observed, labels = [], [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True

    def replace_after_commit(title):
        observed.append(title)
        if title == original.title:
            assert events and events[-1]["stable_id"] == original.stable_id
            controller.play(current, probe=False, start_at=4, start_paused=True, origin="desktop")

    controller.add_metadata_sink(replace_after_commit)
    controller.add_metadata_sink(labels.append)
    try:
        controller.play(original, probe=False, start_at=1, origin="cli")

        snapshot = controller.snapshot()
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 4 and snapshot.error is None
        assert observed == [original.title, current.title]
        assert labels == [current.title]
        assert [event["action"] for event in events] == ["play", "play", "pause"]
        assert [event["stable_id"] for event in events] == [
            original.stable_id, current.stable_id, current.stable_id,
        ]
        assert [event["position_seconds"] for event in events] == [1, 4, 4]
        assert [event["origin"] for event in events] == ["cli", "desktop", "desktop"]
        assert events[0]["session_id"] != snapshot.session_id
        assert events[1]["session_id"] == events[2]["session_id"] == snapshot.session_id
        assert Session.created[0].stopped and not Session.created[1].stopped
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)


def test_active_media_observer_replacement_does_not_publish_obsolete_media_to_later_sinks(controller):
    pending, current = finite("pending-notification"), finite("observer-current")
    events, labels, later_observations = [], [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.add_metadata_sink(labels.append)

    def replace_during_notification(media, _resolved):
        if media is pending:
            controller.play(current, probe=False, start_at=3, start_paused=True, origin="desktop")

    controller.add_active_media_sink(replace_during_notification)
    controller.add_active_media_sink(lambda media, _resolved: later_observations.append(media))
    try:
        with pytest.raises(playback.PlaybackError, match="replaced"):
            controller.play(pending, probe=False, origin="cli")

        snapshot = controller.snapshot()
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 3 and snapshot.error is None
        assert pending not in later_observations
        assert later_observations[later_observations.index(current):] == [current]
        assert labels == [current.title]
        assert [event["action"] for event in events] == ["play", "pause"]
        assert all(event["stable_id"] == current.stable_id for event in events)
        assert all(event["session_id"] == snapshot.session_id for event in events)
        assert all(event["position_seconds"] == 3 for event in events)
        assert len(Session.created) == 2
        assert Session.created[0].stopped and not Session.created[1].stopped
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)
    assert all(stream.closed for stream in Stream.instances)


def test_stop_observer_replacement_does_not_publish_obsolete_empty_state_to_later_sinks(controller):
    original, current = finite("stopped-notification"), finite("observer-current")
    controller.play(original, probe=False)
    previous = controller._active
    events, labels, later_observations = [], [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.add_metadata_sink(labels.append)
    replace = True

    def replace_during_stop(media, _resolved):
        nonlocal replace
        if media is None and replace:
            replace = False
            controller.play(current, probe=False, start_at=5, start_paused=True, origin="desktop")

    controller.add_active_media_sink(replace_during_stop)
    controller.add_active_media_sink(lambda media, _resolved: later_observations.append(media))
    try:
        controller.stop()

        snapshot = controller.snapshot()
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 5 and snapshot.error is None
        assert later_observations[later_observations.index(current):] == [current]
        assert labels == [current.title]
        assert [event["action"] for event in events] == ["play", "pause"]
        assert all(event["stable_id"] == current.stable_id for event in events)
        assert all(event["session_id"] == snapshot.session_id for event in events)
        assert all(event["position_seconds"] == 5 for event in events)
        assert previous.stopped and len(Session.created) == 2
        assert not Session.created[1].stopped
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)
    assert all(stream.closed for stream in Stream.instances)


def test_promoted_media_observer_replacement_keeps_play_events_in_commit_order(controller):
    original, promoted, current = finite("completed"), finite("promoted"), finite("observer-current")
    controller.play(original, probe=False)
    completed = controller._active
    controller.prefetch(promoted, probe=False)
    prepared = controller._next
    events, later_observations = [], []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True

    def replace_promoted_media(media, _resolved):
        if media is promoted:
            controller.play(current, probe=False, start_at=4, start_paused=True, origin="desktop")

    controller.add_active_media_sink(replace_promoted_media)
    controller.add_active_media_sink(lambda media, _resolved: later_observations.append(media))
    try:
        controller._promote_next(completed)

        snapshot = controller.snapshot()
        assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
        assert snapshot.position == 4 and snapshot.error is None
        assert [event["action"] for event in events] == ["play", "play", "pause"]
        assert [event["stable_id"] for event in events] == [
            promoted.stable_id, current.stable_id, current.stable_id,
        ]
        assert [event["origin"] for event in events] == ["automatic", "desktop", "desktop"]
        assert [event["position_seconds"] for event in events] == [0, 4, 4]
        assert events[0]["play_kind"] == "start" and events[0]["session_id"] != snapshot.session_id
        assert events[1]["session_id"] == events[2]["session_id"] == snapshot.session_id
        assert promoted not in later_observations
        assert later_observations[later_observations.index(current):] == [current]
        assert completed.stopped and prepared.stopped
        assert not controller._active.stopped
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)
    assert all(stream.closed for stream in Stream.instances)


@pytest.mark.parametrize("delivery", ["prepared", "live"])
def test_deferred_old_session_metadata_cannot_relabel_current_media(controller, delivery):
    original, current = finite("previous-label"), finite("current-label")
    labels, events = [], []
    controller.add_metadata_sink(labels.append)
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller.play(original, probe=False)
    previous = controller._active
    controller.play(current, probe=False, start_at=3, start_paused=True)
    snapshot = controller.snapshot()
    committed = list(events)
    labels.clear()
    try:
        if delivery == "prepared":
            controller._publish_metadata("Obsolete prepared title", session=previous)
        else:
            controller._handle_stream_metadata(previous, "Obsolete stream title")

        assert labels == [] and events == committed
        refreshed = controller.snapshot()
        assert refreshed.media is current and refreshed.media.title == "current-label"
        assert refreshed.state == PlaybackState.PAUSED and refreshed.position == 3
        assert refreshed.session_id == snapshot.session_id and refreshed.error is None
        assert previous.stopped and not controller._active.stopped
    finally:
        controller.close()
    assert all(session.stopped for session in Session.created)


def test_replaced_decoder_buffer_failure_cannot_mark_new_playback_failed(controller, monkeypatch):
    old, current = finite('old'), finite('current')

    def wait_for_buffer(session, *_args, **_kwargs):
        if session.media is old:
            controller.play(current, probe=False, start_at=3, start_paused=True)
            return False
        return True

    monkeypatch.setattr(Session, 'wait_for_buffer', wait_for_buffer)
    with pytest.raises(playback.PlaybackError, match='no playable audio'):
        controller.play(old, probe=False)
    snapshot = controller.snapshot()
    assert snapshot.media is current
    assert snapshot.state == PlaybackState.PAUSED
    assert snapshot.position == 3
    assert snapshot.error is None
    assert Session.created[0].stopped and not Session.created[1].stopped


@pytest.mark.parametrize('handoff', ['buffer', 'output'])
def test_replaced_successful_preparation_cannot_resume_or_relabel_new_media(controller, monkeypatch, handoff):
    old, current = finite('old'), finite('current')
    labels = []
    controller.add_metadata_sink(labels.append)
    if handoff == 'buffer':
        def wait_for_buffer(session, *_args, **_kwargs):
            if session.media is old:
                controller.play(current, probe=False, start_at=3, start_paused=True)
            return True
        monkeypatch.setattr(Session, 'wait_for_buffer', wait_for_buffer)
    else:
        original = controller._ensure_output

        def ensure_output(**kwargs):
            if controller._active.media is old:
                controller.play(current, probe=False, start_at=3, start_paused=True)
            original(**kwargs)
        monkeypatch.setattr(controller, '_ensure_output', ensure_output)
    with pytest.raises(playback.PlaybackError, match='replaced'):
        controller.play(old, probe=False)
    snapshot = controller.snapshot()
    assert snapshot.media is current and snapshot.state == PlaybackState.PAUSED
    assert snapshot.position == 3 and snapshot.error is None
    assert 'old' not in labels and labels[-1] == 'current'
    assert Session.created[0].stopped and not Session.created[1].stopped


def test_verified_backend_resolution_reaches_decoder_without_second_lookup(controller, monkeypatch):
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", duration=30)
    resolved = playback.ResolvedMedia(media, "https://cdn.example/media?token=SECRET", media.original_uri,
                                      media.capabilities, metadata={"title": "Verified recording"})
    monkeypatch.setattr(controller.resolvers, "resolve", lambda *_args, **_kwargs: pytest.fail("must use verified input"))
    controller.play(media, resolved=resolved, probe=False, start_paused=True)
    assert Session.created[-1].resolved is resolved
    assert controller.snapshot().state == PlaybackState.PAUSED
    assert controller.snapshot().media.title == "Verified recording"


def test_verified_seek_refreshes_exact_transport_and_preserves_pause(controller):
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", duration=30)
    controller.play(media, probe=False, start_paused=True)
    original = Session.created[-1]
    fresh_media = MediaRef(MediaSource.YOUTUBE, media.original_uri, duration=30)
    fresh = playback.ResolvedMedia(fresh_media, "https://cdn.example/renewed", fresh_media.original_uri,
                                  fresh_media.capabilities)
    controller.seek(12, resolved=fresh)
    assert original.stopped
    assert Session.created[-1].resolved is fresh
    assert controller.snapshot().state == PlaybackState.PAUSED and controller.snapshot().position == 12


def test_stale_or_unrelated_resolution_cannot_replace_current_decoder(controller):
    media = finite()
    controller.play(media, probe=False)
    active = Session.created[-1]
    other = finite("other")
    wrong = playback.ResolvedMedia(other, other.original_uri, other.original_uri, other.capabilities)
    with pytest.raises(playback.UnsupportedAction, match="does not match"):
        controller.seek(4, resolved=wrong)
    with pytest.raises(playback.UnsupportedAction, match="does not belong"):
        controller.play(media, resolved=wrong, probe=False)
    expired = playback.ResolvedMedia(media, media.original_uri, media.original_uri, media.capabilities, expires_at=1)
    with pytest.raises(playback.UnsupportedAction, match="expired"):
        controller.seek(4, resolved=expired)
    with pytest.raises(playback.UnsupportedAction, match="expired"):
        controller.play(media, resolved=expired, probe=False)
    with pytest.raises(playback.UnsupportedAction, match="requires selected"):
        controller.play(resolved=wrong)
    assert not active.stopped and controller.snapshot().media is media


@pytest.mark.parametrize("paused", [False, True])
def test_output_handoff_preserves_decoder_position_and_pause_intent(controller, paused):
    from mariana.supervisor import PlaybackSupervisor

    controller.play(finite(), probe=False)
    session = controller._active
    controller._audio_callback(bytearray(80), 10, None, None)
    position = session.position
    if paused:
        controller.pause()
    original_factory = controller.output_factory
    attempts = []

    def unavailable(**kwargs):
        attempts.append(kwargs["device"])
        raise OSError("private driver details")

    controller.output_factory = unavailable
    supervisor = PlaybackSupervisor(controller, wait=lambda _: False)
    with pytest.raises(playback.MediaFailure) as failure:
        supervisor.recover_output()
    controller.report_output_error(str(failure.value))
    assert len(attempts) == 3
    assert controller.snapshot().state == (PlaybackState.PAUSED if paused else PlaybackState.BUFFERING)
    assert "private" not in controller.snapshot().error
    assert controller.snapshot().position == position
    assert controller._active is session and not session.stopped
    silent = bytearray(80)
    controller._audio_callback(silent, 10, None, None)
    assert silent == bytes(80) and session.position == position

    controller.output_factory = original_factory
    supervisor.recover_output()
    assert controller.snapshot().error is None
    assert controller.snapshot().state == (PlaybackState.PAUSED if paused else PlaybackState.PLAYING)
    assert controller._active is session and len(Session.created) == 1
    controller._audio_callback(bytearray(80), 10, None, None)
    assert session.position == (position if paused else position + 10 / playback.SAMPLE_RATE)
    supervisor.close()


def test_output_open_failure_retires_decoder_and_allows_replay(controller):
    factory = controller.output_factory
    controller.output_factory = lambda **_: (_ for _ in ()).throw(OSError("private device"))
    with pytest.raises(playback.MediaFailure) as failure:
        controller.play(finite(), probe=False)
    assert failure.value.code == playback.FailureCode.OUTPUT_DEVICE
    assert not failure.value.retryable
    assert controller._active is None and Session.created[-1].stopped
    assert controller.snapshot().state == PlaybackState.FAILED
    assert "private" not in controller.snapshot().error
    controller.output_factory = factory
    controller.play(finite(), probe=False)
    assert controller.snapshot().state == PlaybackState.PLAYING
    assert controller.snapshot().error is None
    controller.close()


def live():
    return MediaRef(
        MediaSource.RADIO,
        "https://example.test/live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )


def test_prepare_success_failure_and_play_without_media(controller, monkeypatch):
    media = finite()
    assert controller.prepare(media, probe=False) is media
    assert controller.resolved_uri.endswith("track.flac")
    probed = finite("probed")
    monkeypatch.setattr(
        playback,
        "probe_media",
        lambda value, **_kwargs: value,
    )
    assert controller.prepare(probed, probe=True) is probed
    with pytest.raises(playback.PlaybackError, match="No media"):
        playback.PlaybackController(output_factory=Stream).play()
    monkeypatch.setattr(controller.resolvers, "resolve", lambda _media: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(ValueError, match="bad"):
        controller.prepare(finite("bad"), probe=False)
    assert controller.snapshot().state == PlaybackState.FAILED


def test_prepare_preserves_catalog_chapters_and_projects_position(controller):
    catalog_chapters = [
        MediaChapter("Local intro", 0, 10),
        MediaChapter("Local verse", 10, 20),
    ]
    media = MediaRef(
        MediaSource.LOCAL,
        "C:/chaptered.flac",
        title="Chaptered",
        duration=20,
        chapters=catalog_chapters,
    )

    class ResolverWithDifferentChapters(Resolvers):
        def resolve(self, source, **_kwargs):
            resolved = super().resolve(source)
            resolved.metadata["chapters"] = [
                {"title": "Resolver fallback", "start_time": 0, "end_time": 20}
            ]
            return resolved

    controller.resolvers = ResolverWithDifferentChapters()
    assert controller.prepare(media, probe=False).chapters == catalog_chapters
    active = Session(media)
    active.position = 12
    controller._active = active
    assert controller.snapshot().current_chapter == catalog_chapters[1]


def test_play_prefetch_replace_and_failure(controller):
    media = controller.play(finite(), probe=False)
    assert media.title == "track"
    assert controller.snapshot().state == PlaybackState.PLAYING
    assert Stream.instances[0].started
    controller.prefetch(finite("next"), probe=False)
    first_next = controller._next
    controller.prefetch(finite("later"), probe=False)
    assert first_next.stopped
    Session.wait_result = False
    Session.error = "decode failed"
    with pytest.raises(playback.PlaybackError, match="decode failed"):
        controller.prefetch(finite("broken"), probe=False)
    assert Session.created[-1].stopped


def test_active_media_sinks_follow_play_prefetch_promotion_and_stop(controller):
    events = []
    remove = controller.add_active_media_sink(lambda media, resolved: events.append((media, resolved)))
    controller.add_active_media_sink(lambda *_args: (_ for _ in ()).throw(RuntimeError("sink")))

    current = finite()
    upcoming = finite("next")
    controller.play(current, probe=False)
    assert events[-1][0] is current
    assert events[-1][1].media is current

    controller.prefetch(upcoming, probe=False)
    completed = controller._active
    controller._promote_next(completed)
    assert events[-1][0] is upcoming
    assert events[-1][1].media is upcoming

    controller.stop()
    assert events[-1] == (None, None)
    remove()
    controller.play(current, probe=False)
    assert events[-1] == (None, None)


@pytest.mark.parametrize("replaced", [False, True])
def test_promotion_defers_presentation_observers_and_rejects_stale_delivery(controller, monkeypatch, replaced):
    current, upcoming = finite("finishing"), finite("queued")
    controller.play(current, probe=False)
    controller.prefetch(upcoming, probe=False)
    completed = controller._active
    observations, pending = [], []
    controller.add_active_media_sink(lambda media, _resolved: observations.append(media))

    class DeferredThread:
        def __init__(self, target, args=(), **_kwargs):
            self.target, self.args = target, args

        def start(self):
            pending.append((self.target, self.args))

    monkeypatch.setattr(playback.threading, "Thread", DeferredThread)
    controller._promote_next(completed)
    assert controller.snapshot().media is upcoming
    assert observations == []  # Presentation code cannot run on the rendering caller.
    if replaced:
        controller.stop()
        assert observations == [None]
        observations.clear()
    for target, arguments in pending:
        target(*arguments)
    assert observations == ([] if replaced else [upcoming])
    assert completed.stopped
    controller.close()


def test_active_media_sink_observes_resolved_media_when_buffering_fails(controller):
    events = []
    controller.add_active_media_sink(lambda media, resolved: events.append((media, resolved)))
    media = finite("unbuffered")
    Session.wait_result = False
    Session.error = "decode failed"

    with pytest.raises(playback.PlaybackError, match="decode failed"):
        controller.play(media, probe=False)

    assert events[-1][0] is media
    assert events[-1][1].media is media
    assert controller.snapshot().state == PlaybackState.FAILED


def test_active_media_observer_order_cannot_reactivate_a_stopped_session(controller):
    entered = threading.Event()
    release = threading.Event()
    events = []
    media = finite("racing")
    session = Session(media)
    controller._active = session

    def observe(active_media, _resolved):
        events.append(active_media)
        if active_media is media:
            entered.set()
            assert release.wait(1)

    controller.add_active_media_sink(observe)
    publish = RealThread(
        target=controller._publish_active_media_for_session,
        args=(session, media, None),
    )
    publish.start()
    assert entered.wait(1)
    with controller._lock:
        controller._active = None
    clear = RealThread(target=controller._publish_active_media, args=(None, None))
    clear.start()
    release.set()
    publish.join(1)
    clear.join(1)

    assert not publish.is_alive()
    assert not clear.is_alive()
    assert events == [media, None]
    controller._publish_active_media_for_session(session, media, None)
    assert events == [media, None]


def test_preferred_region_applies_to_play_prefetch_completion_and_snapshot(controller):
    regions = {
        "track": PlayRegion("track", 2.5, 8.0),
        "next": PlayRegion("next", 3.0, None),
    }
    controller.play_region_provider = lambda media: regions.get(media.stable_id)
    current = finite(duration=10)
    current.stable_id = "track"
    upcoming = finite("next", duration=12)
    upcoming.stable_id = "next"

    controller.play(current, probe=False)
    assert controller._active.start_at == 2.5
    snapshot = controller.snapshot()
    assert snapshot.region_start_seconds == 2.5
    assert snapshot.region_end_seconds == 8.0

    controller.prefetch(upcoming, probe=False)
    assert controller._next.start_at == 3.0
    controller._active.position = 7.999
    controller._audio_callback(bytearray(1024 * playback.BYTES_PER_FRAME), 1024, None, None)

    assert controller._active is controller._next or controller.snapshot().media is upcoming
    promoted = controller.snapshot()
    assert promoted.media is upcoming
    assert promoted.region_start_seconds == 3.0
    assert promoted.region_end_seconds is None


def test_preferred_region_clamps_seek_and_completes_at_end(controller):
    media = finite(duration=10)
    media.stable_id = "bounded"
    controller.play_region_provider = lambda _media: PlayRegion("bounded", 2.0, 8.0)
    controller.play(media, probe=False)

    controller.seek(0)
    assert controller._active.start_at == 2.0
    controller.seek(99)

    snapshot = controller.snapshot()
    assert snapshot.state == PlaybackState.IDLE
    assert snapshot.position == 8.0
    assert snapshot.duration == 10
    assert snapshot.region_start_seconds == 2.0
    assert snapshot.region_end_seconds == 8.0


def test_start_only_region_and_absent_region_provider_paths(controller):
    media = finite(duration=10)
    media.stable_id = "start-only"
    controller.play_region_provider = lambda source: (
        PlayRegion(source.stable_id, 2.0, None) if source.stable_id == "start-only" else None
    )

    controller.play(media, probe=False)
    assert controller._active.start_at == 2.0
    assert controller.snapshot().region_end_seconds is None
    assert controller._play_region(finite("unbounded")) is None


@pytest.mark.parametrize(
    ("media", "region", "message"),
    [
        (live(), PlayRegion("live", 1, None), "finite media"),
        (finite(duration="invalid"), PlayRegion("invalid", 1, None), "valid media duration"),
        (finite(duration=float("nan")), PlayRegion("nan", 1, None), "valid media duration"),
    ],
)
def test_preferred_region_rejects_inapplicable_media(controller, media, region, message):
    controller.play_region_provider = lambda _media: region
    with pytest.raises(playback.UnsupportedAction, match=message):
        controller._play_region(media)


@pytest.mark.parametrize("numpy_output", [False, True])
def test_callback_completes_immediately_when_region_end_is_reached(controller, numpy_output):
    media = finite(duration=10)
    active = Session(media)
    active.position = 4.0
    controller._active = active
    controller._active_region = PlayRegion(media.stable_id, None, 4.0)
    controller._state = PlaybackState.PLAYING
    output = (
        playback.np.ones((8, playback.CHANNELS), dtype=playback.np.float32)
        if numpy_output
        else bytearray(8 * playback.BYTES_PER_FRAME)
    )

    controller._audio_callback(output, 8, None, None)

    assert controller.snapshot().state == PlaybackState.IDLE
    assert not output.any() if numpy_output else output == bytes(len(output))


@pytest.mark.parametrize(
    "region",
    [
        PlayRegion("bad", 1, 1),
        PlayRegion("bad", -1, 2),
        PlayRegion("bad", 0, 11),
    ],
)
def test_invalid_saved_region_is_refused_before_playback_replacement(controller, region):
    prior = finite("prior")
    controller.play(prior, probe=False)
    active = controller._active
    media = finite("bad", duration=10)
    media.stable_id = "bad"
    controller.play_region_provider = lambda _media: region

    with pytest.raises(playback.UnsupportedAction, match=r"preferred playback|Preferred playback|Saved preferred"):
        controller.play(media, probe=False)

    assert controller._active is active


def test_play_buffer_failure_is_typed(controller):
    Session.wait_result = False
    controller._prepared = finite()
    with pytest.raises(playback.PlaybackError, match="produced no playable"):
        controller.play()
    assert controller.snapshot().state == PlaybackState.FAILED
    assert Session.created[-1].stopped


def test_audio_callback_pause_normal_crossfade_and_promotion(controller):
    out = bytearray(8 * 4)
    controller._audio_callback(out, 4, None, "underflow")
    assert out == bytes(len(out))
    assert "underflow" in controller.snapshot().error

    active = Session(finite(duration=10))
    controller._active = active
    controller._state = PlaybackState.PAUSED
    controller._audio_callback(out, 4, None, None)
    assert out == bytes(len(out))

    controller._state = PlaybackState.PLAYING
    controller.set_volume(50)
    controller._audio_callback(out, 4, None, None)
    assert any(out)

    upcoming = Session(finite("next"))
    controller._next = upcoming
    active.position = 9
    controller._audio_callback(out, 4, None, None)
    assert controller.snapshot().state == PlaybackState.CROSSFADING
    assert upcoming.position > 0

    completed = controller._active
    completed.eof = True
    completed.buffered_seconds = 0
    seen = []
    controller.on_complete = lambda media: seen.append(media.title)
    controller._audio_callback(out, 4, None, None)
    assert controller._active is upcoming
    assert completed.stopped
    assert seen == ["track"]
    controller._promote_next(completed)
    assert controller._active is upcoming


def test_crossfade_excludes_live_upcoming_media_and_disabling_restores_playing_state(controller):
    active = Session(finite(duration=10))
    active.position = 9
    live_upcoming = Session(live())
    controller._active = active
    controller._next = live_upcoming
    controller._state = PlaybackState.PLAYING

    controller._audio_callback(bytearray(4 * playback.BYTES_PER_FRAME), 4, None, None)

    assert live_upcoming.position == 0
    assert controller.snapshot().state == PlaybackState.PLAYING
    controller._state = PlaybackState.CROSSFADING
    controller.set_crossfade_seconds(0)
    assert controller.snapshot().state == PlaybackState.PLAYING


def test_audio_callback_uses_equal_power_gains_at_crossfade_midpoint(controller):
    active = Session(finite(duration=10))
    active.position = 9
    controller._active = active
    controller._next = Session(finite("next"))
    controller._state = PlaybackState.PLAYING
    output = playback.np.zeros((4, playback.CHANNELS), dtype=playback.np.float32)

    controller._audio_callback(output, 4, None, None)

    assert output == pytest.approx(playback.np.full_like(output, 0.25 * 2 ** 0.5), abs=1e-6)


def test_pause_resume_toggle_seek_restart_and_boundaries(controller, monkeypatch):
    with pytest.raises(playback.UnsupportedAction):
        controller.pause()
    with pytest.raises(playback.UnsupportedAction):
        controller.resume()
    controller._state = PlaybackState.PLAYING
    controller.toggle_pause()
    assert controller.snapshot().state == PlaybackState.PAUSED
    controller.toggle_pause()

    active = Session(finite(duration=5))
    controller._active = active
    controller._state = PlaybackState.PAUSED
    controller.seek(99)
    assert Session.created[-1].start_at == 5
    assert controller.snapshot().state == PlaybackState.PAUSED

    controller._active = None
    with pytest.raises(playback.UnsupportedAction, match="Nothing is loaded"):
        controller.seek(1)
    controller._active = Session(live())
    with pytest.raises(playback.UnsupportedAction, match="cannot be seeked"):
        controller.seek(1)

    calls = []
    monkeypatch.setattr(
        controller,
        "play",
        lambda media, probe=False, origin="system": calls.append((media, probe, origin)),
    )
    controller.restart_live()
    assert calls[0][1] is False
    assert calls[0][2] == "recovery"
    assert controller.notify_metadata_boundary("New title") == 1
    assert controller._active.reset
    controller._active = Session(finite())
    with pytest.raises(playback.UnsupportedAction):
        controller.restart_live()
    with pytest.raises(playback.UnsupportedAction):
        controller.notify_metadata_boundary()


def test_completed_finite_media_can_rewind_as_paused_and_then_resume(controller):
    events = []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    media = controller.play(finite(duration=20), probe=False, origin="cli")
    completed_session_id = events[-1]["session_id"]
    completed = controller._active
    completed.position = 20
    completed.eof = True
    completed.buffered_seconds = 0
    controller._finish_active(completed)

    finished = controller.snapshot()
    assert finished.state == PlaybackState.IDLE
    assert finished.media is media
    assert finished.position == 20

    controller.seek(0, origin="cli")
    reset = controller.snapshot()
    assert reset.state == PlaybackState.PAUSED
    assert reset.media is media
    assert reset.position == 0
    assert controller._active.start_at == 0
    assert events[-1]["action"] == "seek"
    assert events[-1]["seek_from_seconds"] == 20
    assert events[-1]["seek_to_seconds"] == 0
    assert events[-1]["session_id"] != completed_session_id

    controller.resume(origin="cli")
    assert controller.snapshot().state == PlaybackState.PLAYING


def test_successful_play_pause_resume_and_seek_capture_once_with_one_session(controller):
    events = []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True

    media = controller.play(finite(duration=20), probe=False, origin="cli")
    session_id = events[0]["session_id"]
    controller._audio_callback(bytearray(80), 10, None, None)
    assert len(events) == 1
    controller._active.position = 3
    controller.pause(origin="desktop")
    controller.resume(origin="mini-player")
    controller._active.position = 5
    controller.seek(12, origin="desktop")

    assert [item["action"] for item in events] == ["play", "pause", "play", "seek"]
    assert [item["origin"] for item in events] == ["cli", "desktop", "mini-player", "desktop"]
    assert all(item["stable_id"] == media.stable_id for item in events)
    assert all(item["session_id"] == session_id for item in events)
    assert events[0]["play_kind"] == "start"
    assert events[2]["play_kind"] == "resume"
    assert events[-1]["seek_from_seconds"] == 5
    assert events[-1]["seek_to_seconds"] == 12
    assert events[-1]["position_seconds"] == 12


def test_capture_failure_never_interrupts_playback_and_failed_seek_is_not_captured(
    controller, monkeypatch
):
    def broken_capture(**_payload):
        raise OSError("capture unavailable")

    controller._playback_event_sink = broken_capture
    controller.play(finite(duration=20), probe=False, origin="cli")
    controller.pause(origin="cli")
    controller.resume(origin="cli")
    replacement = Session(controller._active.media)
    replacement.wait_for_buffer = lambda *_args, **_kwargs: False
    replacement.error = "seek failed"
    monkeypatch.setattr(controller, "_new_session", lambda *_args, **_kwargs: replacement)
    with pytest.raises(playback.PlaybackError, match="seek failed"):
        controller.seek(8, origin="cli")
    assert controller.snapshot().media is not None


def test_seek_clean_eof_at_safe_end_completes_without_false_failure(controller, monkeypatch):
    media = finite(duration=100)
    events = []
    controller._playback_event_sink = lambda **payload: events.append(payload) or True
    controller._playback_session_id = "session"
    controller._active = Session(media)
    controller._state = PlaybackState.PLAYING
    replacement = Session(media)
    replacement.eof = True
    replacement.buffered_seconds = 0
    replacement.wait_for_buffer = lambda *_args, **_kwargs: False
    monkeypatch.setattr(controller, "_new_session", lambda *_args, **_kwargs: replacement)

    controller.seek(99.75, origin="cli")

    snapshot = controller.snapshot()
    assert snapshot.state == PlaybackState.IDLE
    assert snapshot.media is media
    assert snapshot.position == 100
    assert replacement.stopped
    assert len(events) == 1
    assert {
        key: events[0][key]
        for key in ("action", "origin", "session_id", "seek_from_seconds", "seek_to_seconds")
    } == {
        "action": "seek",
        "origin": "cli",
        "session_id": "session",
        "seek_from_seconds": 0,
        "seek_to_seconds": 99.75,
    }


def test_seek_unbuffered_before_end_still_reports_decoder_failure(controller, monkeypatch):
    media = finite(duration=100)
    controller._active = Session(media)
    controller._state = PlaybackState.PLAYING
    replacement = Session(media)
    replacement.eof = True
    replacement.buffered_seconds = 0
    replacement.error = "seek failed"
    replacement.wait_for_buffer = lambda *_args, **_kwargs: False
    monkeypatch.setattr(controller, "_new_session", lambda *_args, **_kwargs: replacement)

    with pytest.raises(playback.PlaybackError, match="seek failed"):
        controller.seek(99.74)


def test_stop_close_recover_fingerprint_and_snapshot(controller):
    active, upcoming = Session(finite()), Session(finite("next"))
    controller._active, controller._next = active, upcoming
    assert controller.fingerprint_pcm() == b"fingerprint"
    controller._ensure_output()
    old_stream = controller._stream
    controller.recover_output()
    assert old_stream.stopped and old_stream.closed
    assert controller._stream is not old_stream
    controller.stop()
    assert active.stopped and upcoming.stopped
    assert controller.snapshot().state == PlaybackState.IDLE
    stream = controller._stream
    controller.close()
    assert stream.stopped and stream.closed
    assert controller.fingerprint_pcm() == b""


def test_natural_completion_retains_end_position_until_next_action(controller):
    completed = Session(finite("finished", duration=42))
    completed.position = 41.75
    controller._active = completed
    controller._state = PlaybackState.PLAYING

    controller._promote_next(completed)

    snapshot = controller.snapshot()
    assert snapshot.state == PlaybackState.IDLE
    assert snapshot.media.title == "finished"
    assert snapshot.position == snapshot.duration == 42

    controller.stop()
    snapshot = controller.snapshot()
    assert snapshot.position == 0
    assert snapshot.duration is None


def test_prefetched_promotion_does_not_retain_previous_end_position(controller):
    completed = Session(finite("finished", duration=42))
    upcoming = Session(finite("upcoming", duration=30))
    upcoming.position = 0.25
    controller._active = completed
    controller._next = upcoming
    controller._state = PlaybackState.PLAYING

    controller._promote_next(completed)

    snapshot = controller.snapshot()
    assert snapshot.media.title == "upcoming"
    assert snapshot.position == 0.25
    assert snapshot.duration == 30


def test_clear_prefetch_stops_only_the_upcoming_decoder(controller):
    active, upcoming = Session(finite()), Session(finite("next"))
    controller._active, controller._next = active, upcoming
    controller.clear_prefetch()
    assert controller._active is active
    assert controller._next is None
    assert upcoming.stopped and not active.stopped


def test_launch_ffplay_success_and_failure(monkeypatch):
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffplay")
    process = object()
    captured = {}
    monkeypatch.setattr(
        playback.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(command=command, kwargs=kwargs) or process,
    )
    assert playback.launch_ffplay(finite()) is process
    assert "-autoexit" in captured["command"]
    monkeypatch.setattr(playback.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(playback.PlaybackError, match="could not start"):
        playback.launch_ffplay(finite())


def test_decoder_start_http_command_errors_and_forced_kill(monkeypatch):
    commands = []
    monkeypatch.setattr(
        playback,
        "_ffmpeg_http_options",
        lambda _executable: {"reconnect_max_retries", "reconnect_delay_total_max", "respect_retry_after"},
    )

    class Pipe:
        def read(self, _size=-1):
            return b""

        def readline(self):
            return b""

    class Process:
        _handle = 1
        pid = 42

        def __init__(self):
            self.stdout = Pipe()
            self.stderr = Pipe()
            self.killed = self.terminated = False
            self.waits = 0

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr(playback, "WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(playback.threading, "Thread", lambda **_kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: False))
    monkeypatch.setattr(
        playback.subprocess,
        "Popen",
        lambda command, **_kwargs: commands.append(command) or process,
    )
    media = MediaRef(MediaSource.URL, "https://example.test/audio", duration=10)
    session = playback.DecoderSession(media, start_at=2)
    session.start()
    assert "-reconnect" in commands[0] and "-ss" in commands[0]
    assert "-reconnect_max_retries" in commands[0] and "-respect_retry_after" in commands[0]
    session.start()
    session.stop()
    assert process.terminated and process.killed

    monkeypatch.setattr(playback.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bad")))
    with pytest.raises(playback.PlaybackError, match="could not start"):
        playback.DecoderSession(media).start()

    process = Process()
    monkeypatch.setattr(playback.subprocess, "Popen", lambda command, **_kwargs: commands.append(command) or process)
    playback.DecoderSession(live()).start()
    assert "-icy" in commands[-1]


def test_decoder_parses_unique_icy_title_updates(monkeypatch):
    class Lines:
        def __init__(self):
            self.values = iter([b"StreamTitle: Artist - Song\n", b"icy-title='Artist - Song'\n", b""])

        def readline(self):
            return next(self.values)

    session = object.__new__(playback.DecoderSession)
    session.process = SimpleNamespace(stderr=Lines())
    session._stderr = []
    session._last_stream_title = None
    titles = []
    session.on_metadata = titles.append
    session._stderr_loop()
    assert titles == ["Artist - Song"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("StreamTitle='Artist - Song';StreamUrl='';", "Artist - Song"),
        (b"icy-title: Caf\xe9 del Mar", "Caf\u00e9 del Mar"),
        ("unrelated metadata", None),
        ("StreamTitle='';", None),
    ],
)
def test_icy_title_parser_tolerates_encodings_and_malformed_fields(value, expected):
    assert playback.parse_icy_title(value) == expected


def test_stale_prefetch_metadata_cannot_reset_active_fingerprint(controller):
    active = Session(live())
    stale = Session(live())
    controller._active = active
    controller._handle_stream_metadata(stale, "Wrong")
    assert not active.reset
    controller._handle_stream_metadata(active, "Artist - Current")
    assert active.reset
    assert active.media.title == "Artist - Current"


def test_executable_resolution_youtube_input_and_invalid_probe_metadata(monkeypatch):
    monkeypatch.setattr("mariana.toolchain.find_managed_executable", lambda name: f"managed/{name}")
    assert playback.find_executable("ffmpeg") == "managed/ffmpeg"
    monkeypatch.setattr("beta.youtube_media.stream_url", lambda url, **_kwargs: f"resolved:{url}")
    youtube = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch?v=x")
    assert playback.resolve_input(youtube).startswith("resolved:")

    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffprobe")
    captured = {}

    def run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(stdout='{"format":{"duration":"bad"},"streams":[]}')

    monkeypatch.setattr(playback.subprocess, "run", run)
    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    playback.probe_media(media, source="https://cdn.test/audio", headers={"Referer": "safe"})
    assert media.duration is None and "-headers" in captured["command"]


def test_decoder_properties_timeout_filter_and_private_tunnel(monkeypatch):
    media = MediaRef(
        MediaSource.URL,
        "https://example.test/private",
        capabilities=MediaCapabilities(finite=True, seekable=True),
    )
    resolved = playback.ResolvedMedia(
        media,
        media.original_uri,
        media.original_uri,
        media.capabilities,
        headers={"Referer": "safe"},
        metadata={"credential_ref": "radio", "credential_username": "listener"},
    )
    commands = []

    class Tunnel:
        def __init__(self, *args):
            commands.append(("tunnel", args))

        def start(self):
            return "http://127.0.0.1:1234/stream"

        def close(self):
            commands.append(("closed",))

    class Pipe:
        def read(self, _size=-1):
            return b""

        def readline(self):
            return b""

    class Process:
        stdout = Pipe()
        stderr = Pipe()
        pid = 1

        def poll(self):
            return 0

    monkeypatch.setattr("mariana.credentials.ListenerAuthTunnel", Tunnel)
    monkeypatch.setattr(playback.subprocess, "Popen", lambda command, **_kwargs: commands.append(command) or Process())
    monkeypatch.setattr(playback, "_ffmpeg_http_options", lambda _executable: frozenset())
    monkeypatch.setattr(playback, "WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))

    class NoThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return False

    monkeypatch.setattr(playback.threading, "Thread", NoThread)
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    session = playback.DecoderSession(
        media,
        ffmpeg_bin="ffmpeg",
        resolved=resolved,
        start_at=1,
        audio_filter="volume=1",
    )
    assert session.fingerprint_pcm == b"" and session.error is None and not session.failed
    session.start()
    command = next(item for item in commands if isinstance(item, list))
    assert "-headers" in command and "-af" in command and "-ss" in command
    assert not session.wait_for_buffer(minimum_seconds=1, timeout=0)
    session.reset_fingerprint()
    session.stop()
    assert ("closed",) in commands


def test_decoder_buffer_reads_complete_frames_and_reports_position(monkeypatch):
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    session = playback.DecoderSession(finite("buffer"), start_at=2)
    session._buffer.extend(b"\x00" * (playback.BYTES_PER_FRAME * 3 + 1))

    assert session.wait_for_buffer(
        minimum_seconds=1 / playback.SAMPLE_RATE,
        timeout=0,
    )
    payload = session.read(2)
    assert len(payload) == playback.BYTES_PER_FRAME * 2
    assert session.frames_emitted == 2
    assert session.position == pytest.approx(2 + 2 / playback.SAMPLE_RATE)
    assert len(session._buffer) == playback.BYTES_PER_FRAME + 1


def test_windows_job_close_tolerates_host_api_failure(monkeypatch):
    job = object.__new__(playback.WindowsJob)
    job.handle = 123
    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(CloseHandle=lambda _handle: (_ for _ in ()).throw(OSError("closed"))),
    )
    job.close()
    assert job.handle is None


def test_failed_completion_sink_isolation_and_replaygain_branches(controller, monkeypatch):
    media = finite("failed")
    failed = Session(media)
    failed.failed = True
    failed.error = "decoder broke"
    controller._active = failed
    controller._state = PlaybackState.PLAYING
    failures = []
    controller.on_failure = lambda source, error: failures.append((source, error))
    monkeypatch.setattr(playback.threading, "Thread", ImmediateThread)
    controller._finish_active(failed)
    assert controller.snapshot().state == PlaybackState.FAILED

    good = Session(finite("gain"))
    controller._active = good
    controller._next = Session(finite("next"))
    controller.configure_replaygain(enabled=True, mode="track", preamp_db=2, prevent_clipping=False)
    assert controller.replaygain_enabled and controller.replaygain_preamp_db == 2
    with pytest.raises(ValueError, match="preamp"):
        controller.configure_replaygain(preamp_db=16)

    calls = []
    remove_program = controller.add_program_sink(lambda *_args: (_ for _ in ()).throw(RuntimeError("sink")))
    remove_metadata = controller.add_metadata_sink(lambda title: calls.append(title))
    controller.add_metadata_sink(lambda _title: (_ for _ in ()).throw(RuntimeError("sink")))
    controller._publish_program(b"", 0)
    controller._publish_metadata("Title")
    remove_program()
    remove_program()
    remove_metadata()
    remove_metadata()
    assert calls == ["Title"]


def test_numpy_crossfade_empty_next_and_output_recovery(controller):
    active = Session(finite("active", duration=1))
    active.position = 0.9
    next_session = Session(finite("next"))
    next_session.read = lambda _frames: b""
    controller._active = active
    controller._next = next_session
    controller._state = PlaybackState.PLAYING
    output = __import__("numpy").zeros((8, 2), dtype="float32")
    controller._audio_callback(output, 8, None, "underflow")
    assert controller.snapshot().error.startswith("Audio output")

    stream = Stream(callback=lambda *_args: None)
    controller._stream = stream
    controller.recover_output()
    assert stream.stopped and stream.closed and controller._stream is not stream


def test_remaining_playback_branches(controller, monkeypatch, tmp_path):
    monkeypatch.setattr("mariana.toolchain.find_tool_executable", lambda name, _configured=None: f"PATH/{name}")
    assert playback.find_executable("ffmpeg", str(tmp_path / "missing")) == "PATH/ffmpeg"

    with monkeypatch.context() as scoped:
        scoped.setattr(playback.os, "name", "posix")
        job = playback.WindowsJob(SimpleNamespace())
        assert job.handle is None
        job.close()

    media = finite("metadata")

    class MetadataResolvers(Resolvers):
        def resolve(self, source, **_kwargs):
            return playback.ResolvedMedia(
                source,
                source.original_uri,
                source.original_uri,
                source.capabilities,
                metadata={"title": "Resolved title"},
            )

    controller.resolvers = MetadataResolvers()
    assert controller.prepare(media, probe=False).title == "metadata"
    untitled = MediaRef(MediaSource.LOCAL, "C:/untitled.flac", duration=1)
    assert controller.prepare(untitled, probe=False).title == "Resolved title"

    class ChapterResolvers(Resolvers):
        def resolve(self, source, **_kwargs):
            return playback.ResolvedMedia(
                source,
                source.original_uri,
                source.original_uri,
                source.capabilities,
                metadata={
                    "title": "Chaptered",
                    "artist": "Artist",
                    "categories": ["Music"],
                    "track": "Chaptered",
                    "provider_metadata": {
                        "provider": "Youtube",
                        "provider_media_id": "chaptered",
                        "publisher": "Channel",
                        "views": 25,
                        "playback_url": "https://signed.test/private",
                    },
                    "chapters": [
                        {"title": "Intro", "start_time": 0, "end_time": 10},
                        {"title": "Verse", "start_time": 10, "end_time": 20},
                    ],
                },
            )

    controller.resolvers = ChapterResolvers()
    chaptered = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch?v=chaptered", duration=20)
    controller.prepare(chaptered, probe=False)
    active = Session(chaptered)
    controller._active = active
    active.position = 10
    snapshot = controller.snapshot()
    assert snapshot.current_chapter == MediaChapter("Verse", 10, 20)
    assert chaptered.resolver_data["is_music"] is True
    assert chaptered.resolver_data["provider_metadata"] == {
        "provider": "Youtube",
        "provider_media_id": "chaptered",
        "publisher": "Channel",
        "views": 25,
    }

    controller._ensure_output()
    existing = controller._stream
    controller._ensure_output()
    assert controller._stream is existing

    empty = Session(finite("empty", duration=1))
    empty.read = lambda _frames: b""
    empty.position = 0.9
    controller._active = empty
    controller._next = Session(finite("next"))
    controller._state = PlaybackState.PLAYING
    output = __import__("numpy").zeros((4, 2), dtype="float32")
    controller._audio_callback(output, 4, None, None)

    stale = Session(finite("stale"))
    stale.failed = True
    controller._active = Session(finite("current"))
    controller._finish_active(stale)
    assert controller._active.media.title == "current"

    failed = Session(finite("failed-again"))
    failed.failed = True
    failed.error = None
    controller._active = failed
    controller.on_failure = None
    controller._finish_active(failed)
    assert controller.snapshot().state == PlaybackState.FAILED

    controller._active = None
    controller._watch_stop.clear()
    controller._watch_completion()
    controller.set_volume(0.5)
    controller.configure_replaygain(enabled=False)

    live_session = Session(live())
    controller._active = live_session
    controller._state = PlaybackState.PLAYING
    generation = controller.notify_metadata_boundary(None)
    assert generation > 0 and live_session.media.title is None

    controller._stream = None
    controller.recover_output()
    assert controller._stream is not None


def test_decoder_posix_shutdown_and_seek_failure(controller, monkeypatch):
    class Reader:
        def __init__(self):
            self.joined = False

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.joined = timeout == 2

    class Process:
        pid = 42

        def __init__(self):
            self.waits = 0
            self.terminated = self.killed = False

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    session = RealDecoderSession(finite(), ffmpeg_bin="ffmpeg")
    replacement = Session(finite("replacement", duration=None))
    active = Session(finite("seek-source", duration=None))
    signals = []
    session.process = Process()
    session._reader = Reader()
    session.job = SimpleNamespace(close=lambda: signals.append(("job", "closed")))
    with monkeypatch.context() as scoped:
        scoped.setattr(playback.os, "name", "posix")
        scoped.setattr(playback.os, "killpg", lambda pid, sig: signals.append((pid, sig)), raising=False)
        scoped.setattr(playback.signal, "SIGKILL", 9, raising=False)
        session.stop()
    assert len(signals) >= 3 and session.process is None

    replacement.wait_for_buffer = lambda *_args, **_kwargs: False
    replacement.error = "seek failed"
    controller._active = active
    controller._state = PlaybackState.PLAYING
    monkeypatch.setattr(controller, "_new_session", lambda *_args, **_kwargs: replacement)
    with pytest.raises(playback.PlaybackError, match="seek failed"):
        controller.seek(20)


def test_windows_job_none_handle_and_legacy_tool_lookup(monkeypatch, tmp_path):
    legacy = tmp_path / ".tools"
    legacy.mkdir()
    executable = legacy / ("ffmpeg.exe" if playback.os.name == "nt" else "ffmpeg")
    executable.write_bytes(b"tool")
    monkeypatch.setattr("mariana.toolchain.find_managed_executable", lambda _name: None)
    monkeypatch.setattr("mariana.paths.runtime_paths", lambda: SimpleNamespace(resource=lambda _name: legacy))
    monkeypatch.setattr("mariana.toolchain.shutil.which", lambda _name: None)
    monkeypatch.setattr("mariana.toolchain.common_tool_locations", lambda _name: ())
    assert playback.find_executable("ffmpeg") == str(executable.resolve())

    fake_job = SimpleNamespace(
        CreateJobObject=lambda *_args: None,
        JobObjectExtendedLimitInformation=1,
    )
    monkeypatch.setattr(playback, "_is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32job", fake_job)
    job = playback.WindowsJob(SimpleNamespace(_handle=1))
    assert job.handle is None


def test_windows_job_assigns_and_closes_handle_on_every_test_platform(monkeypatch):
    calls = []
    information = {"BasicLimitInformation": {"LimitFlags": 0}}
    fake_job = SimpleNamespace(
        CreateJobObject=lambda *_args: "job-handle",
        QueryInformationJobObject=lambda *_args: information,
        SetInformationJobObject=lambda *args: calls.append(("set", args)),
        AssignProcessToJobObject=lambda *args: calls.append(("assign", args)),
        JobObjectExtendedLimitInformation=1,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=2,
    )
    fake_api = SimpleNamespace(CloseHandle=lambda handle: calls.append(("close", handle)))
    monkeypatch.setattr(playback, "_is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32job", fake_job)
    monkeypatch.setitem(sys.modules, "win32api", fake_api)

    job = playback.WindowsJob(SimpleNamespace(_handle=7))
    assert job.handle == "job-handle"
    assert information["BasicLimitInformation"]["LimitFlags"] == 2
    assert calls[:2] == [
        ("set", ("job-handle", 1, information)),
        ("assign", ("job-handle", 7)),
    ]

    job.close()
    assert calls[-1] == ("close", "job-handle")
    assert job.handle is None


def test_decoder_read_loop_backpressure_fingerprint_and_metadata_without_callback(monkeypatch):
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    media = finite("reader")

    class Stdout:
        def __init__(self, values):
            self.values = iter(values)

        def read(self, _size):
            return next(self.values, b"")

    session = RealDecoderSession(media, ffmpeg_bin="ffmpeg")
    session.process = SimpleNamespace(stdout=Stdout([b"\0" * playback.BYTES_PER_FRAME, b""]))
    session._read_loop()
    assert session.eof and session.buffered_seconds > 0 and session.fingerprint_pcm

    stopped = RealDecoderSession(media, ffmpeg_bin="ffmpeg", max_buffer_seconds=0)
    stopped.process = SimpleNamespace(stdout=Stdout([b"data"]))

    class Condition:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def wait(self, _timeout):
            stopped._stop.set()

        def notify_all(self):
            pass

    stopped._condition = Condition()
    stopped._read_loop()
    assert stopped.eof

    stopped._last_stream_title = None
    stopped.on_metadata = None
    stopped.process = SimpleNamespace(
        stderr=SimpleNamespace(readline=iter([b"StreamTitle='No callback';", b""]).__next__)
    )
    stopped._stderr_loop()
    assert stopped._last_stream_title == "No callback"


def test_controller_gain_filter_pause_promotion_and_leveling_branches(controller, monkeypatch):
    profile = SimpleNamespace(
        track_gain_db=-3.0,
        album_gain_db=None,
        track_peak=0.8,
        album_peak=None,
        complete_album=False,
    )
    controller.loudness_repository = SimpleNamespace(get=lambda _stable_id: profile)
    controller.replaygain_enabled = True
    assert controller._program_gain_db(finite("gain-enabled")) == pytest.approx(-3)
    controller.live_leveling = True
    assert controller._live_filter(live()).startswith("loudnorm=")

    paused = Session(finite("paused"))
    controller._active = paused
    controller._state = PlaybackState.PAUSED
    output = __import__("numpy").ones((4, 2), dtype="float32")
    controller._audio_callback(output, 4, None, None)
    assert not output.any()

    controller._active = paused
    controller._next = None
    controller.on_complete = None
    controller._promote_next(paused)
    assert controller.snapshot().state == PlaybackState.IDLE

    with pytest.raises(ValueError, match="Automation"):
        controller.set_automation_gain(-0.1)
    controller.set_automation_gain(0.5)
    assert controller.snapshot().volume == 1.0

    restarts = []
    controller._active = Session(live())
    monkeypatch.setattr(controller, "restart_live", lambda: restarts.append(True))
    controller.live_leveling = False
    controller.set_live_leveling(False)
    controller.set_live_leveling(True)
    assert restarts == [True]


@pytest.mark.parametrize("numpy_output", [True, False])
def test_equalizer_is_after_broadcast_before_local_gains_without_decoder_changes(controller, numpy_output):
    import numpy as np

    from mariana.equalizer import EqualizerSettings

    controller.play(finite(duration=100), probe=False)
    active = controller._active
    active.program_gain = .5
    controller.set_volume(.5)
    controller.set_automation_gain(.5)
    before = controller.snapshot()
    created = len(Session.created)
    engine = controller.equalizer
    engine.submit(engine.prepare(EqualizerSettings(True, preamp=-6)))
    for _ in range(12):
        engine.process(np.zeros((512, 2)))
    assert len(Session.created) == created
    assert controller.snapshot() == before
    broadcasts = []
    controller.add_program_sink(lambda pcm, frames: broadcasts.append(
        pcm.copy() if isinstance(pcm, np.ndarray) else np.frombuffer(pcm, np.float32).reshape(-1, 2).copy()))
    output = np.zeros((512, 2), np.float32) if numpy_output else bytearray(512 * 8)
    controller._audio_callback(output, 512, None, None)
    actual = output if numpy_output else np.frombuffer(output, np.float32).reshape(-1, 2)
    np.testing.assert_allclose(broadcasts[-1], .125)
    np.testing.assert_allclose(actual, .125 * .25 * 10 ** (-6 / 20), atol=1e-7)
    assert controller._active is active and len(Session.created) == created
    controller.set_muted(True)
    controller._audio_callback(output, 512, None, None)
    np.testing.assert_array_equal(actual, 0)
    np.testing.assert_allclose(broadcasts[-1], .125)
    serial = engine.reset_serial
    controller.seek(5)
    assert engine.reset_serial > serial
    serial = engine.reset_serial
    controller.stop()
    assert engine.reset_serial > serial


@pytest.mark.parametrize("existing_output", [False, True])
def test_recipe_paused_start_is_silent_before_and_after_output_open(controller, monkeypatch, existing_output):
    if existing_output:
        controller.play(finite("previous"), probe=False)
    original_wait = Session.wait_for_buffer
    observations = []

    def inspect_buffering(session, *args, **kwargs):
        output = bytearray(b"x" * 80)
        controller._audio_callback(output, 10, None, None)
        observations.append((bytes(output), session.position, controller.snapshot().state))
        return original_wait(session, *args, **kwargs)

    monkeypatch.setattr(Session, "wait_for_buffer", inspect_buffering)
    controller.play(finite("paused"), start_at=3, probe=False, start_paused=True)
    output = bytearray(b"x" * 80)
    controller._audio_callback(output, 10, None, None)
    assert observations == [(bytes(80), 3, PlaybackState.PAUSED)]
    assert output == bytes(80)
    assert controller.snapshot().position == 3
    assert controller.snapshot().state == PlaybackState.PAUSED
    controller.resume()
    controller._audio_callback(output, 10, None, None)
    assert output != bytes(80)
