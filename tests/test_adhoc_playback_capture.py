from array import array

import numpy as np
import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState
from mariana.playback import BYTES_PER_FRAME, SAMPLE_RATE, PlaybackController, UnsupportedAction


class Active:
    def __init__(self, media: MediaRef, position: float = 42.0):
        self.media = media
        self.program_gain = 1.0
        self.program_gain_db = 0.0
        self.start_at = position
        self.frames_emitted = 0
        self.buffered_seconds = 1.0
        self.eof = False

    @property
    def position(self) -> float:
        return self.start_at + self.frames_emitted / SAMPLE_RATE

    def read(self, frames: int) -> bytes:
        self.frames_emitted += frames
        return array("f", [0.25] * frames * 2).tobytes()


def finite(*, fingerprintable: bool = True) -> MediaRef:
    return MediaRef(
        MediaSource.LOCAL,
        "C:/mix.flac",
        title="Continuous mix",
        duration=600,
        capabilities=MediaCapabilities(fingerprintable=fingerprintable),
    )


def test_identification_sink_receives_only_new_programme_pcm_before_local_gain():
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    media = finite()
    controller._active = Active(media)
    controller._state = PlaybackState.PLAYING
    controller._playback_session_id = "session"
    controller.set_volume(10)
    captures = []
    controller.add_identification_sink(
        lambda samples, *values: captures.append((np.array(samples, copy=True), *values))
    )
    output = np.empty((4, 2), dtype=np.float32)

    controller._audio_callback(output, 4, None, None)

    samples, frames, media_id, session_id, decoder_token, start, mixed = captures[0]
    assert frames == 4
    assert media_id == media.stable_id
    assert session_id == "session"
    assert decoder_token.startswith("decoder-")
    assert start == 42.0
    assert mixed is False
    assert np.asarray(samples)[:frames] == pytest.approx(np.full((4, 2), 0.25))
    assert output == pytest.approx(np.full((4, 2), 0.025))


def test_paused_output_does_not_feed_time_specific_identification():
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    controller._active = Active(finite())
    controller._state = PlaybackState.PAUSED
    controller._playback_session_id = "session"
    captures = []
    controller.add_identification_sink(lambda *values: captures.append(values))

    controller._audio_callback(bytearray(4 * BYTES_PER_FRAME), 4, None, None)

    assert captures == []


def test_capture_context_requires_active_playing_fingerprintable_media():
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    with pytest.raises(UnsupportedAction, match="Nothing"):
        controller.identification_capture_context()
    controller._active = Active(finite(fingerprintable=False))
    controller._playback_session_id = "session"
    controller._state = PlaybackState.PLAYING
    with pytest.raises(UnsupportedAction, match="cannot be fingerprinted"):
        controller.identification_capture_context()
    controller._active = Active(finite())
    media, session_id, decoder_token, position = controller.identification_capture_context()
    assert media.title == "Continuous mix"
    assert session_id == "session"
    assert decoder_token.startswith("decoder-")
    assert position == 42.0
    controller._state = PlaybackState.PAUSED
    with pytest.raises(UnsupportedAction, match='while media is playing'):
        controller.identification_capture_context()


def test_identification_unsubscribe_is_idempotent_and_does_not_silence_other_consumers():
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    controller._active = Active(finite())
    controller._state = PlaybackState.PLAYING
    controller._playback_session_id = 'session'
    first, second = [], []
    remove = controller.add_identification_sink(lambda *values: first.append(values))
    controller.add_identification_sink(lambda *values: second.append(values))
    output = np.empty((4, 2), dtype=np.float32)
    controller._audio_callback(output, 4, None, None)
    remove()
    remove()
    controller._audio_callback(output, 4, None, None)
    assert len(first) == 1 and len(second) == 2
    assert controller.snapshot().state is PlaybackState.PLAYING
    assert np.isfinite(output).all() and output.any()
