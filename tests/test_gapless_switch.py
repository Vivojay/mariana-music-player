"""Gapless manual-switch tests: pre-buffer + overlap fade, no stop-then-start."""

import threading
from typing import ClassVar

import pytest

from mariana import playback
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState

RealThread = threading.Thread


class Stream:
    instances: ClassVar[list] = []

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
    created: ClassVar[list] = []

    def __init__(self, media, **kwargs):
        self.media = media
        self.resolved = kwargs.get("resolved")
        self.start_at = kwargs.get("start_at", 0)
        self.position = self.start_at
        self.buffered_seconds = 1.0
        self.eof = False
        self.started = self.stopped = False
        self.on_metadata = None
        self.created.append(self)

    def start(self):
        self.started = True

    def wait_for_buffer(self, *args, **kwargs):
        return self.wait_result

    def read(self, frames):
        self.position += frames / playback.SAMPLE_RATE
        import numpy as np

        return np.full((frames, 2), 0.25, dtype=np.float32).tobytes()

    def stop(self):
        self.stopped = True

    def reset_fingerprint(self):
        pass


class ImmediateThread:
    def __init__(self, target, args=(), name="", **_kwargs):
        self.target = target
        self.args = args
        self.name = name

    def start(self):
        if getattr(self.target, "__name__", "") == "stop" or self.name in {
            "mariana-playback-complete",
            "mariana-decoder-cleanup",
        }:
            self.target(*self.args)


class Resolvers:
    def resolve(self, media, **_kwargs):
        return playback.ResolvedMedia(media, media.original_uri, media.original_uri, media.capabilities)

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
    control = playback.PlaybackController(output_factory=Stream, crossfade_seconds=2, resolvers=Resolvers())
    control.on_complete = lambda _media: completed.append(_media)
    return control


completed = []


def finite(name="track", duration=30):
    return MediaRef(MediaSource.LOCAL, f"C:/{name}.flac", title=name, duration=duration)


def live(name="station"):
    media = MediaRef(MediaSource.RADIO, f"https://example.invalid/{name}", title=name)
    media.capabilities = MediaCapabilities(finite=False, live=True, seekable=False)
    return media


def vod(name="video"):
    return MediaRef(MediaSource.YOUTUBE, f"https://example.invalid/{name}", title=name, duration=30)


@pytest.fixture(autouse=True)
def _clear_completed():
    completed.clear()
    yield
    completed.clear()


def test_manual_switch_overlaps_without_stopping_outgoing(controller):
    first, second = finite("one"), finite("two")
    controller.play(first, probe=False, origin="cli")
    outgoing = controller._active
    assert controller.snapshot().state == PlaybackState.PLAYING

    controller.play(second, probe=False, origin="cli")

    # Old decoder keeps rendering while the new one is already buffered.
    assert outgoing.stopped is False
    assert controller._active is outgoing
    incoming = controller._next
    assert incoming is not None and incoming.media is second
    assert incoming.started is True
    assert controller._manual_fade is not None
    assert controller.snapshot().state == PlaybackState.CROSSFADING
    # Snapshot follows the outgoing decoder until promotion, matching
    # automatic end-of-track crossfades; the switch is not a completion.
    assert controller.snapshot().media is first
    assert completed == []
    controller.close()


def test_manual_fade_completes_and_promotes(controller):
    import numpy as np

    first, second = finite("one"), finite("two")
    controller.play(first, probe=False, origin="cli")
    controller.play(second, probe=False, origin="cli")
    outgoing = controller._active
    incoming = controller._next

    for _ in range(60):
        out = np.zeros((4800, 2), dtype=np.float32)
        controller._render_ordinary_audio(out, 4800, None, None)
        if controller._active is incoming:
            break

    assert controller._active is incoming
    assert controller._next is None
    assert controller._manual_fade is None
    assert outgoing.stopped is True
    assert controller.snapshot().state == PlaybackState.PLAYING
    assert controller.snapshot().media is second
    assert completed == []
    controller.close()


def test_failed_switch_keeps_outgoing_playing(controller, monkeypatch):
    first, broken = finite("one"), finite("broken")
    controller.play(first, probe=False, origin="cli")
    outgoing = controller._active

    def fail_new(session, *_args, **_kwargs):
        return session.media is not broken

    monkeypatch.setattr(Session, "wait_for_buffer", fail_new)
    with pytest.raises(playback.PlaybackError):
        controller.play(broken, probe=False, origin="cli")

    snapshot = controller.snapshot()
    assert snapshot.media is first
    assert snapshot.state == PlaybackState.PLAYING
    assert outgoing.stopped is False
    controller.close()


def test_live_switch_uses_prebuffered_cut(controller):
    first, second = live("a"), live("b")
    controller.play(first, probe=False, origin="cli")
    outgoing = controller._active

    controller.play(second, probe=False, origin="cli")

    assert controller._manual_fade is None
    assert controller._active is not outgoing
    assert controller._active.media is second
    assert controller.snapshot().media is second
    controller.close()


def test_seek_during_overlap_targets_incoming(controller):
    first, second = finite("one"), finite("two")
    controller.play(first, probe=False, origin="cli")
    controller.play(second, probe=False, origin="cli")
    assert controller._manual_fade is not None

    controller.seek(5, origin="cli")

    assert controller._manual_fade is None
    assert controller.snapshot().media is second
    controller.close()


def test_local_to_online_vod_overlaps(controller):
    first, second = finite("local"), vod("yt")
    controller.play(first, probe=False, origin="cli")
    outgoing = controller._active

    controller.play(second, probe=False, origin="cli")

    assert outgoing.stopped is False
    assert controller._active is outgoing
    assert controller._next is not None and controller._next.media is second
    assert controller._manual_fade is not None
    assert completed == []
    controller.close()


def test_online_vod_to_local_overlaps(controller):
    first, second = vod("yt"), finite("local")
    controller.play(first, probe=False, origin="cli")
    outgoing = controller._active

    controller.play(second, probe=False, origin="cli")

    assert outgoing.stopped is False
    assert controller._active is outgoing
    assert controller._next is not None and controller._next.media is second
    assert controller._manual_fade is not None
    assert completed == []
    controller.close()


def test_online_vod_fade_completes(controller):
    import numpy as np

    first, second = finite("local"), vod("yt")
    controller.play(first, probe=False, origin="cli")
    controller.play(second, probe=False, origin="cli")
    outgoing = controller._active
    incoming = controller._next

    for _ in range(60):
        out = np.zeros((4800, 2), dtype=np.float32)
        controller._render_ordinary_audio(out, 4800, None, None)
        if controller._active is incoming:
            break

    assert controller._active is incoming
    assert outgoing.stopped is True
    assert controller.snapshot().media is second
    assert completed == []
    controller.close()
