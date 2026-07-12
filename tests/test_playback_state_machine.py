from array import array
import subprocess
from types import SimpleNamespace

import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState
from mariana import playback


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
    with pytest.raises(playback.PlaybackError, match="No media"):
        playback.PlaybackController(output_factory=Stream).play()
    monkeypatch.setattr(controller.resolvers, "resolve", lambda _media: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(ValueError, match="bad"):
        controller.prepare(finite("bad"), probe=False)
    assert controller.snapshot().state == PlaybackState.FAILED


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
    monkeypatch.setattr(controller, "play", lambda media, probe=False: calls.append((media, probe)))
    controller.restart_live()
    assert calls[0][1] is False
    assert controller.notify_metadata_boundary("New title") == 1
    assert controller._active.reset
    controller._active = Session(finite())
    with pytest.raises(playback.UnsupportedAction):
        controller.restart_live()
    with pytest.raises(playback.UnsupportedAction):
        controller.notify_metadata_boundary()


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

    class Pipe:
        def read(self, _size=-1):
            return b""

        def readline(self):
            return b""

    class Process:
        _handle = 1

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
    session.start()
    session.stop()
    assert process.terminated and process.killed

    monkeypatch.setattr(playback.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bad")))
    with pytest.raises(playback.PlaybackError, match="could not start"):
        playback.DecoderSession(media).start()


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


def test_stale_prefetch_metadata_cannot_reset_active_fingerprint(controller):
    active = Session(live())
    stale = Session(live())
    controller._active = active
    controller._handle_stream_metadata(stale, "Wrong")
    assert not active.reset
    controller._handle_stream_metadata(active, "Artist - Current")
    assert active.reset
    assert active.media.title == "Artist - Current"
