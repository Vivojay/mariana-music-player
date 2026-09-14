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


def test_recipe_ownership_suspends_source_recovery_not_explicit_playback(monkeypatch):
    controller = Controller([object()])
    allowed = [False]
    supervisor = PlaybackSupervisor(controller, allow_source_recovery=lambda: allowed[0])
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk")
    supervisor._requested = media
    monkeypatch.setattr("mariana.supervisor.threading.Thread", lambda **_: pytest.fail("must not schedule recovery"))
    supervisor._on_decoder_failure(media, MediaFailure(FailureCode.DECODE, media.source, "failed"))
    with pytest.raises(MediaFailure, match="suspended"):
        supervisor.play(media, origin="recovery")
    assert not controller.calls
    monkeypatch.setattr(supervisor, "_start_output_monitor", lambda: None)
    assert supervisor.play(media, origin="cli") is media


def test_source_recovery_rechecks_ownership_when_scheduled_worker_starts(monkeypatch):
    controller = Controller([])
    allowed = [True]
    pending = []
    supervisor = PlaybackSupervisor(controller, allow_source_recovery=lambda: allowed[0])
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk")
    supervisor._requested = media

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            pending.append(self.target)

    monkeypatch.setattr("mariana.supervisor.threading.Thread", DeferredThread)
    supervisor._on_decoder_failure(media, MediaFailure(FailureCode.DECODE, media.source, "failed"))
    assert len(pending) == 1
    allowed[0] = False
    pending[0]()
    assert not controller.calls and not supervisor._recovering


def test_late_source_resolution_cannot_replace_new_recipe_owner(monkeypatch):
    from mariana.sources import ResolvedMedia

    controller = Controller([])
    allowed = [True]
    supervisor = PlaybackSupervisor(controller, allow_source_recovery=lambda: allowed[0])
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk")

    def resolve(selected, *, force):
        assert force
        allowed[0] = False  # Recipe takes ownership during the provider request.
        return ResolvedMedia(selected, "https://cdn.example/media", selected.original_uri, selected.capabilities)

    monkeypatch.setattr(supervisor.resolvers, "resolve", resolve, raising=False)
    with pytest.raises(MediaFailure, match="suspended"):
        supervisor.play(media, origin="recovery")
    assert not controller.calls


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


def test_output_retries_resolve_current_device_and_cancel_without_extra_open():
    first = OutputDeviceInfo("first", "First", 1, "First", "test")
    latest = OutputDeviceInfo("latest", "Latest", 2, "Latest", "test")

    class SwitchingController(Controller):
        def recover_output(self, device=None):
            selected = device or latest
            self.calls.append(selected)
            if selected is first:
                raise OSError("route no longer exists")

    controller = SwitchingController([])
    delays = []
    supervisor = PlaybackSupervisor(controller, wait=lambda delay: delays.append(delay) or False)
    supervisor.recover_output(first)
    assert controller.calls == [first, latest]
    assert delays == [0.25]
    controller.calls.clear()
    supervisor = PlaybackSupervisor(controller, wait=lambda _: True)
    with pytest.raises(MediaFailure) as failure:
        supervisor.recover_output(first)
    assert failure.value.code == FailureCode.CANCELLED
    assert controller.calls == [first]


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
            return self.calls > 1

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
            monkeypatch.setattr("mariana.supervisor.threading.Event", OnePoll)
            if error is cancelled:
                def cancelled_query(owner=supervisor):
                    owner._output_monitor_stop.set()
                    raise cancelled
                controller.default_output_device = cancelled_query
            supervisor._start_output_monitor()
            monitor = supervisor._output_monitor
            supervisor._stop_output_monitor()
            assert monitor.joined

    assert reported == [
        "device missing",
        "Audio output is unavailable; retrying automatically",
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


def test_retired_output_lookup_cannot_replace_new_monitor_endpoint():
    import threading

    retired = threading.Event()
    device = OutputDeviceInfo("new", "New", 2, "New", "test")

    class LateController(Controller):
        active_output_device = None
        output_stream_active = False

        def default_output_device(self):
            retired.set()  # Stop/restart wins while native enumeration was pending.
            return device

    controller = LateController([])
    supervisor = PlaybackSupervisor(controller)
    assert not supervisor._sync_output_device(cancelled=retired.is_set)
    assert controller.recoveries == 0


def test_stopping_output_retry_remains_cancelled_after_new_play_clears_global_token():
    import threading

    retired = threading.Event()
    controller = Controller([])

    def unavailable():
        controller.recoveries += 1
        raise OSError("endpoint reconnecting")

    controller.recover_output = unavailable

    def replace_playback(_delay):
        retired.set()
        supervisor._cancel.clear()
        return False

    supervisor = PlaybackSupervisor(controller, wait=replace_playback)
    with pytest.raises(MediaFailure) as error:
        supervisor.recover_output(cancelled=retired.is_set)
    assert error.value.code == FailureCode.CANCELLED
    assert controller.recoveries == 1
    assert supervisor.metrics["output_recoveries"] == 0


def test_recovery_finishing_after_monitor_retirement_is_not_counted_as_success():
    import threading

    retired = threading.Event()
    controller = Controller([])
    controller.recover_output = retired.set
    supervisor = PlaybackSupervisor(controller)
    with pytest.raises(MediaFailure) as error:
        supervisor.recover_output(cancelled=retired.is_set)
    assert error.value.code == FailureCode.CANCELLED
    assert supervisor.metrics["output_recoveries"] == 0


def test_closed_supervisor_does_not_start_an_output_monitor(monkeypatch):
    supervisor = PlaybackSupervisor(Controller([]))
    supervisor.close()
    monkeypatch.setattr(supervisor, "_launch_output_monitor", lambda: pytest.fail("closed owner"))
    supervisor._start_output_monitor()


def test_old_native_query_error_after_bounded_join_is_not_published():
    import threading

    entered, release = threading.Event(), threading.Event()
    messages = []
    device = OutputDeviceInfo("new", "New", 2, "New", "test")

    class LateController(Controller):
        active_output_device = device
        output_stream_active = True

        def default_output_device(self):
            entered.set()
            assert release.wait(5)
            raise OSError("retired native lookup")

        def report_output_error(self, message):
            messages.append(message)

    supervisor = PlaybackSupervisor(LateController([]), output_poll_interval=0.1)
    supervisor._start_output_monitor()
    worker = supervisor._output_monitor
    assert worker is not None
    try:
        assert entered.wait(3)
        supervisor._stop_output_monitor()
    finally:
        release.set()
        worker.join(3)
        supervisor.close()
    assert not worker.is_alive()
    assert messages == []


def test_failed_source_ownership_check_does_not_schedule_recovery(monkeypatch):
    controller = Controller([])

    def ownership():
        raise OSError("owner unavailable")

    supervisor = PlaybackSupervisor(controller, allow_source_recovery=ownership)
    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    supervisor._requested = media
    monkeypatch.setattr("mariana.supervisor.threading.Thread", lambda **_: pytest.fail("no recovery authority"))
    supervisor._on_decoder_failure(media, MediaFailure(FailureCode.DECODE, media.source, "failed"))
    assert not controller.calls


def test_authorized_recovery_passes_fresh_resolution_to_controller(monkeypatch):
    from mariana.sources import ResolvedMedia

    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller, allow_source_recovery=lambda: True)
    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    resolved = ResolvedMedia(media, "https://cdn.example/audio", media.original_uri, media.capabilities)
    monkeypatch.setattr(supervisor.resolvers, "resolve", lambda _media, *, force: resolved if force else None, raising=False)
    assert supervisor.play(media, origin="recovery", start_at=12) is media
    assert controller.calls[0][1] == {"start_at": 12, "probe": True, "origin": "recovery", "resolved": resolved}


def test_monitor_start_failure_does_not_reject_successful_playback_and_can_retry(monkeypatch):
    device = OutputDeviceInfo("new", "New", 2, "New", "test")

    class MonitorController(Controller):
        active_output_device = device
        output_stream_active = True

        def default_output_device(self):
            return device

    created = []

    class Worker:
        def __init__(self, **_kwargs):
            self.started = False
            created.append(self)

        def start(self):
            if len(created) == 1:
                raise RuntimeError("thread unavailable")
            self.started = True

        def is_alive(self):
            return self.started

        def join(self, timeout=None):
            assert self.started and timeout == 1

    monkeypatch.setattr("mariana.supervisor.threading.Thread", Worker)
    controller = MonitorController([object(), object()])
    supervisor = PlaybackSupervisor(controller)
    media = MediaRef(MediaSource.LOCAL, "song.mp3")
    assert supervisor.play(media) is media
    assert supervisor._output_monitor is None
    supervisor.stop()
    assert supervisor.play(media) is media
    assert supervisor._output_monitor is created[1]
    supervisor.close()


def test_monitor_stop_token_is_not_reused_after_bounded_join(monkeypatch):
    device = OutputDeviceInfo("new", "New", 2, "New", "test")

    class MonitorController(Controller):
        active_output_device = device

        def default_output_device(self):
            return device

    class StalledWorker:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return True

        def join(self, timeout=None):
            assert timeout == 1

    monkeypatch.setattr("mariana.supervisor.threading.Thread", StalledWorker)
    supervisor = PlaybackSupervisor(MonitorController([]))
    supervisor._start_output_monitor()
    old_stop = supervisor._output_monitor_stop
    supervisor._stop_output_monitor()
    supervisor._start_output_monitor()
    assert old_stop.is_set()
    assert supervisor._output_monitor_stop is not old_stop
    assert not supervisor._output_monitor_stop.is_set()
    supervisor.close()


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


@pytest.mark.parametrize("stop_first", [False, True])
def test_pending_retry_cannot_replay_old_media_after_new_selection(stop_first):
    old = MediaRef(MediaSource.URL, "https://example.test/old")
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    controller = Controller([PlaybackError("temporary"), object()])

    def replace_during_backoff(_delay):
        if stop_first:
            supervisor.stop()
        assert supervisor.play(selected, probe=False, origin="cli") is selected
        return False

    supervisor = PlaybackSupervisor(controller, wait=replace_during_backoff)
    failures = []
    supervisor.on_terminal_failure = lambda *args: failures.append(args)
    with pytest.raises(MediaFailure) as failure:
        supervisor.play(old, origin="cli")
    assert failure.value.code == FailureCode.CANCELLED
    assert [media for media, _ in controller.calls if isinstance(media, MediaRef)] == [old, selected]
    assert supervisor._requested is selected
    assert failures == []


def test_deferred_source_recovery_does_not_replay_a_newer_selection(monkeypatch):
    old = MediaRef(MediaSource.URL, "https://example.test/old")
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    controller = Controller([object(), object()])
    supervisor = PlaybackSupervisor(controller)
    pending = []

    class DeferredThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            pending.append(self.target)

    monkeypatch.setattr("mariana.supervisor.threading.Thread", DeferredThread)
    supervisor.play(old)
    supervisor._on_decoder_failure(old, MediaFailure(FailureCode.DECODE, old.source, "offline"))
    assert len(pending) == 1
    supervisor.play(selected, origin="cli")
    pending[0]()
    assert [media for media, _ in controller.calls] == [old, selected]
    assert supervisor._requested is selected
    assert not supervisor._recovering


def test_late_recovery_resolution_cannot_replace_new_explicit_selection(monkeypatch):
    from mariana.sources import ResolvedMedia

    old = MediaRef(MediaSource.URL, "https://example.test/old")
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller, allow_source_recovery=lambda: True)

    def resolve(media, *, force):
        assert force and media is old
        supervisor.play(selected, origin="cli")
        return ResolvedMedia(old, old.original_uri, old.original_uri, old.capabilities)

    monkeypatch.setattr(supervisor.resolvers, "resolve", resolve, raising=False)
    with pytest.raises(MediaFailure) as failure:
        supervisor.play(old, origin="recovery")
    assert failure.value.code == FailureCode.CANCELLED
    assert [media for media, _ in controller.calls] == [selected]


@pytest.mark.parametrize("late_error", [None, PlaybackError("old decoder failed")])
def test_retired_controller_result_does_not_publish_success_or_terminal_failure(monkeypatch, late_error):
    old = MediaRef(MediaSource.URL, "https://example.test/old")
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller)
    original_play = controller.play
    monitors, failures = [], []

    def complete_after_replacement(media, **kwargs):
        if media is old:
            supervisor.play(selected, origin="cli")
            if late_error is not None:
                raise late_error
            return old
        return original_play(media, **kwargs)

    monkeypatch.setattr(controller, "play", complete_after_replacement)
    monkeypatch.setattr(supervisor, "_start_output_monitor", lambda: monitors.append(supervisor._requested))
    supervisor.on_terminal_failure = lambda *args: failures.append(args)
    with pytest.raises(MediaFailure) as failure:
        supervisor.play(old)
    assert failure.value.code == FailureCode.CANCELLED
    assert monitors == [selected]
    assert failures == [] and supervisor.metrics["retries"] == 0


def test_supervisor_reservation_rejects_replacement_at_controller_admission(monkeypatch):
    from mariana.sources import ResolvedMedia

    old = MediaRef(MediaSource.URL, "https://example.test/old")
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    resolved = ResolvedMedia(selected, selected.original_uri, selected.original_uri, selected.capabilities)
    controller = PlaybackController(output_factory=lambda **_kwargs: pytest.fail("no output should open"))
    supervisor = PlaybackSupervisor(controller)
    original_play = controller.play

    def admit_after_replacement(media, **kwargs):
        assert media is old and type(kwargs["request_generation"]) is int
        # A direct recipe/controller selection wins after the supervisor's last
        # caller-side check, immediately before the old request is admitted.
        controller.prepare(selected, probe=False, resolved=resolved)
        return original_play(media, **kwargs)

    monkeypatch.setattr(controller, "play", admit_after_replacement)
    with pytest.raises(MediaFailure) as failure:
        supervisor.play(old, probe=False)
    assert failure.value.code == FailureCode.CANCELLED
    assert controller._prepared is selected
    assert controller.resolved_uri == selected.original_uri
    assert supervisor.metrics["retries"] == 0
    controller.close()


def test_source_retries_reuse_one_reserved_controller_generation():
    class ReservedController(Controller):
        generation = 0

        def reserve_media_request(self):
            self.generation += 1
            return self.generation

        def media_request_is_current(self, generation):
            return generation == self.generation

    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    controller = ReservedController([PlaybackError("temporary"), object()])
    supervisor = PlaybackSupervisor(controller, wait=lambda _delay: False)
    assert supervisor.play(media) is media
    assert controller.generation == 1
    assert [kwargs["request_generation"] for _, kwargs in controller.calls] == [1, 1]


def test_source_recovery_worker_start_failure_releases_recovery_slot(monkeypatch):
    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller)
    media = MediaRef(MediaSource.LOCAL, "selected.flac")
    supervisor.play(media)

    class UnavailableThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread unavailable")

    monkeypatch.setattr("mariana.supervisor.threading.Thread", UnavailableThread)
    supervisor._on_decoder_failure(media, MediaFailure(FailureCode.DECODE, media.source, "failed"))
    assert not supervisor._recovering
    assert [selected for selected, _ in controller.calls] == [media]


def test_retired_stop_join_cannot_stop_new_playback_or_its_monitor(monkeypatch):
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    controller = Controller([object()])
    supervisor = PlaybackSupervisor(controller)
    new_monitor = object()

    class OldMonitor:
        def join(self, *, timeout):
            assert timeout == 1
            assert controller.calls == [("stop", {})]
            supervisor.play(selected)
            supervisor._output_monitor = new_monitor

    monkeypatch.setattr(supervisor, "_start_output_monitor", lambda: None)
    supervisor._output_monitor = OldMonitor()
    supervisor.stop()
    assert [media for media, _ in controller.calls] == ["stop", selected]
    assert supervisor._output_monitor is new_monitor
    assert not supervisor._cancel.is_set()


def test_reserved_stop_cannot_clear_selection_that_won_at_controller_admission(monkeypatch):
    from mariana.sources import ResolvedMedia

    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    resolved = ResolvedMedia(selected, selected.original_uri, selected.original_uri, selected.capabilities)
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    supervisor = PlaybackSupervisor(controller)
    original_stop = controller.stop_reserved_media_request

    def stop_after_replacement(generation):
        controller.prepare(selected, probe=False, resolved=resolved)
        return original_stop(generation)

    monkeypatch.setattr(controller, "stop_reserved_media_request", stop_after_replacement)
    supervisor.stop()
    assert controller._prepared is selected
    assert controller.resolved_uri == selected.original_uri
    controller.close()


def test_reserved_stop_clears_current_owner_without_native_output():
    from mariana.sources import ResolvedMedia

    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    supervisor = PlaybackSupervisor(controller)
    controller.prepare(
        selected, probe=False,
        resolved=ResolvedMedia(selected, selected.original_uri, selected.original_uri, selected.capabilities),
    )
    supervisor.stop()
    assert controller.resolved_uri is None
    assert controller.snapshot().state.value == "idle"
    controller.close()


def test_close_remains_terminal_while_retired_monitor_is_joining():
    controller = Controller([])
    supervisor = PlaybackSupervisor(controller)

    class OldMonitor:
        def join(self, *, timeout):
            assert timeout == 1 and controller.calls == [("close", {})]
            with pytest.raises(MediaFailure) as failure:
                supervisor.play(MediaRef(MediaSource.LOCAL, "selected.flac"))
            assert failure.value.code == FailureCode.CANCELLED

    supervisor._output_monitor = OldMonitor()
    supervisor.close()
    assert controller.calls == [("close", {})]


def test_same_media_failure_from_old_decoder_cannot_claim_new_controller_request(monkeypatch):
    from mariana.sources import ResolvedMedia

    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    resolved = ResolvedMedia(selected, selected.original_uri, selected.original_uri, selected.capabilities)
    controller = PlaybackController(output_factory=lambda **_kwargs: pytest.fail("must not open output"))
    supervisor = PlaybackSupervisor(controller)
    supervisor._requested = selected
    old_generation = controller.reserve_media_request()
    old_failure = MediaFailure(
        FailureCode.DECODE, selected.source, "old decoder failed", request_generation=old_generation,
    )
    controller.prepare(selected, probe=False, resolved=resolved)

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr("mariana.supervisor.threading.Thread", ImmediateThread)
    supervisor._on_decoder_failure(selected, old_failure)
    assert controller._prepared is selected
    assert controller.resolved_uri == selected.original_uri
    assert supervisor._request_epoch == 0 and not supervisor._recovering
    assert supervisor.metrics["retries"] == 0
    controller.close()


def test_current_decoder_failure_atomically_reserves_its_replacement(monkeypatch):
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")

    class ReservedController(Controller):
        generation = 4

        def reserve_media_request_if_current(self, expected):
            if expected != self.generation:
                return None
            self.generation += 1
            return self.generation

        def media_request_is_current(self, generation):
            return generation == self.generation

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    controller = ReservedController([object()])
    supervisor = PlaybackSupervisor(controller)
    supervisor._requested = selected
    monkeypatch.setattr("mariana.supervisor.threading.Thread", ImmediateThread)
    supervisor._on_decoder_failure(
        selected, MediaFailure(FailureCode.DECODE, selected.source, "failed", request_generation=4),
    )
    assert controller.calls == [(selected, {
        "start_at": 0, "probe": True, "origin": "recovery", "request_generation": 5,
    })]
    assert controller.generation == 5 and not supervisor._recovering


def test_generation_bound_failure_is_rejected_by_controller_without_admission_support(monkeypatch):
    selected = MediaRef(MediaSource.LOCAL, "selected.flac")
    controller = Controller([])
    supervisor = PlaybackSupervisor(controller)
    supervisor._requested = selected
    with pytest.raises(MediaFailure) as failure:
        supervisor.play(selected, origin="recovery", _expected_controller_generation=2)
    assert failure.value.code == FailureCode.CANCELLED
    assert controller.calls == [] and supervisor._request_epoch == 0
