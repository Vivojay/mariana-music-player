import numpy as np
import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.output_devices import OutputDeviceInfo
from mariana.playback import BYTES_PER_FRAME, PlaybackController, PlaybackError
from mariana.sources import FailureCode, MediaFailure
from mariana.supervisor import PlaybackSupervisor


class Controller:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []
        self.resolvers = Resolvers()
        self.on_failure = None
        self.recoveries = 0

    def play(self, media, **kwargs):
        self.calls.append((media, kwargs))
        outcome = next(self.outcomes)
        if isinstance(outcome, BaseException):
            raise outcome
        return media

    def stop(self):
        self.calls.append(("stop", {}))

    def close(self):
        self.calls.append(("close", {}))

    def recover_output(self):
        self.recoveries += 1


class Resolvers:
    def classify_failure(self, error, media):
        if isinstance(error, MediaFailure):
            return error
        return MediaFailure(FailureCode.DECODE, media.source, str(error), retryable=True)


def test_network_retries_are_bounded_and_youtube_is_reresolved():
    controller = Controller([PlaybackError("expired"), PlaybackError("expired"), object()])
    waits = []
    supervisor = PlaybackSupervisor(controller, wait=lambda delay: waits.append(delay) or False)
    media = MediaRef(MediaSource.YOUTUBE, "https://youtube.com/watch?v=test")
    assert supervisor.play(media) is media
    assert waits == [1.0, 2.0]
    assert supervisor.metrics["resolver_refreshes"] == 2


def test_radio_cycles_endpoints_before_terminal_failure():
    failure = MediaFailure(FailureCode.UNAVAILABLE, MediaSource.RADIO, "offline", retryable=True)
    controller = Controller([failure] * 5)
    terminal = []
    supervisor = PlaybackSupervisor(controller, wait=lambda _delay: False)
    supervisor.on_terminal_failure = lambda media, error: terminal.append((media, error))
    media = MediaRef(
        MediaSource.RADIO,
        "https://radio.test/a",
        resolver_data={"endpoints": ["https://radio.test/a", "https://radio.test/b"]},
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )
    with pytest.raises(MediaFailure):
        supervisor.play(media)
    assert [call[0].original_uri for call in controller.calls] == [
        "https://radio.test/a",
        "https://radio.test/b",
        "https://radio.test/a",
        "https://radio.test/b",
        "https://radio.test/a",
    ]
    assert terminal and supervisor.metrics["endpoint_changes"] == 4


def test_local_failure_is_not_retried_and_stop_cancels():
    failure = MediaFailure(FailureCode.UNAVAILABLE, MediaSource.LOCAL, "missing")
    controller = Controller([failure])
    supervisor = PlaybackSupervisor(controller, wait=lambda _delay: False)
    with pytest.raises(MediaFailure):
        supervisor.play(MediaRef(MediaSource.LOCAL, "missing.mp3"))
    assert len(controller.calls) == 1
    supervisor.stop()
    assert controller.calls[-1][0] == "stop"


def test_output_recovery_and_numpy_callback(monkeypatch):
    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller)
    supervisor.recover_output()
    assert controller.recoveries == 1

    class Session:
        eof = False
        buffered_seconds = 1
        position = 0
        media = MediaRef(MediaSource.LOCAL, "track")

        def read(self, frames):
            return np.full((frames, 2), 0.25, dtype=np.float32).tobytes()

    pcm = PlaybackController(output_factory=lambda **_kwargs: None)
    pcm._active = Session()
    pcm._state = "playing"
    output = np.zeros((8, 2), dtype=np.float32)
    pcm._audio_callback(output, 8, None, None)
    assert output.nbytes == 8 * BYTES_PER_FRAME
    assert np.allclose(output, 0.25)


def test_retry_wait_can_be_cancelled_and_generic_failures_are_classified():
    controller = Controller([PlaybackError("temporary")])
    supervisor = PlaybackSupervisor(controller, wait=lambda _delay: True)
    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    with pytest.raises(MediaFailure) as captured:
        supervisor.play(media)
    assert captured.value.code == FailureCode.CANCELLED
    assert supervisor.metrics["cancellations"] == 1
    classified = supervisor._failure(ValueError("generic"), media)
    assert classified.code == FailureCode.DECODE and classified.retryable


def test_async_decoder_recovery_is_deduplicated(monkeypatch):
    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller, wait=lambda _delay: False)
    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    failure = MediaFailure(FailureCode.DECODE, media.source, "decode", retryable=True)
    supervisor._on_decoder_failure(media, failure)
    assert controller.calls == []
    supervisor._requested = media

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("mariana.supervisor.threading.Thread", ImmediateThread)
    supervisor._on_decoder_failure(media, failure)
    assert controller.calls and not supervisor._recovering
    supervisor._recovering = True
    before = len(controller.calls)
    supervisor._on_decoder_failure(media, failure)
    assert len(controller.calls) == before


def test_output_recovery_failure_cancel_and_close():
    controller = Controller([object()])
    attempts = []

    def fail():
        attempts.append(True)
        raise OSError("device gone")

    controller.recover_output = fail
    supervisor = PlaybackSupervisor(controller, wait=lambda _delay: False)
    with pytest.raises(MediaFailure) as captured:
        supervisor.recover_output()
    assert captured.value.code == FailureCode.OUTPUT_DEVICE and len(attempts) == 3
    supervisor.stop()
    with pytest.raises(MediaFailure) as cancelled:
        supervisor.recover_output()
    assert cancelled.value.code == FailureCode.CANCELLED
    supervisor.close()
    assert controller.calls[-1][0] == "close"


def test_output_monitor_reports_typed_and_generic_poll_failures(monkeypatch):
    reported = []

    class MonitorController(Controller):
        active_output_device = OutputDeviceInfo("old", "Old", 1, "Old", "test")
        output_stream_active = True

        def __init__(self, error):
            super().__init__([object()])
            self.error = error

        def default_output_device(self):
            raise self.error

        def report_output_error(self, message):
            reported.append(message)

    class OnePoll:
        def __init__(self):
            self.calls = 0

        def wait(self, _timeout):
            self.calls += 1
            return self.calls > 1

        def clear(self):
            self.calls = 0

        def set(self):
            self.calls = 2

        def is_set(self):
            return self.calls > 0

    class ImmediateMonitor:
        def __init__(self, target, **_kwargs):
            self.target = target
            self.joined = False

        def start(self):
            self.target()

        def is_alive(self):
            return False

        def join(self, timeout=None):
            self.joined = timeout == 1

    monkeypatch.setattr("mariana.supervisor.threading.Thread", ImmediateMonitor)
    typed = MediaFailure(FailureCode.OUTPUT_DEVICE, MediaSource.LOCAL, "device missing")
    cancelled = MediaFailure(FailureCode.CANCELLED, MediaSource.LOCAL, "stopping")
    for error in (typed, ValueError("poll failed"), cancelled):
        for can_report in (True, False):
            controller = MonitorController(error)
            if not can_report:
                controller.report_output_error = None
            supervisor = PlaybackSupervisor(controller)
            supervisor._output_monitor_stop = OnePoll()
            supervisor._start_output_monitor()
            monitor = supervisor._output_monitor
            supervisor._stop_output_monitor()
            assert monitor.joined

    assert reported == [
        "device missing",
        "Audio output monitoring failed: poll failed",
    ]


def test_output_monitor_guard_and_active_none_paths():
    basic = Controller([object()])
    supervisor = PlaybackSupervisor(basic)
    assert not supervisor._sync_output_device()
    supervisor._start_output_monitor()
    assert supervisor._output_monitor is None

    device = OutputDeviceInfo("new", "New", 2, "New", "test")

    class NoActiveController(Controller):
        active_output_device = None
        output_stream_active = True

        def default_output_device(self):
            return device

        def recover_output(self, selected=None):
            self.recoveries += 1
            self.active_output_device = selected

    controller = NoActiveController([object()])
    inactive = PlaybackSupervisor(controller)
    assert inactive._sync_output_device()
    assert controller.recoveries == 1
    assert inactive.metrics["output_device_changes"] == 1

    class AliveMonitor:
        def is_alive(self):
            return True

    inactive._output_monitor = AliveMonitor()
    inactive._start_output_monitor()
    assert isinstance(inactive._output_monitor, AliveMonitor)


def test_radio_without_explicit_endpoints_uses_original_uri():
    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller)
    media = MediaRef(
        MediaSource.RADIO,
        "https://radio.test/live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )
    supervisor.play(media)
    assert controller.calls[0][0].original_uri == media.original_uri


def test_cancellation_before_first_attempt_and_failed_async_recovery(monkeypatch):
    controller = Controller([MediaFailure(FailureCode.DECODE, MediaSource.URL, "bad")])
    supervisor = PlaybackSupervisor(controller)

    class AlreadyCancelled:
        def clear(self):
            pass

        def is_set(self):
            return True

        def set(self):
            pass

        def wait(self, _delay):
            return True

    supervisor._cancel = AlreadyCancelled()
    with pytest.raises(MediaFailure) as captured:
        supervisor.play(MediaRef(MediaSource.URL, "https://example.test/audio"))
    assert captured.value.code == FailureCode.CANCELLED

    class ImmediateThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    supervisor._cancel = __import__("threading").Event()
    supervisor._requested = MediaRef(MediaSource.URL, "https://example.test/audio")
    monkeypatch.setattr("mariana.supervisor.threading.Thread", ImmediateThread)
    supervisor._on_decoder_failure(
        supervisor._requested,
        MediaFailure(FailureCode.DECODE, MediaSource.URL, "bad", retryable=False),
    )
    assert not supervisor._recovering
