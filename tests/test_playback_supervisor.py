import numpy as np
import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.playback import BYTES_PER_FRAME, PlaybackController, PlaybackError, PlaybackSupervisor
from mariana.sources import FailureCode, MediaFailure


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
