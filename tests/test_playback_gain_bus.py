from array import array
from types import SimpleNamespace

import numpy as np
import pytest

from mariana.loudness import LoudnessProfile
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState
from mariana.playback import PlaybackController


class Repository:
    def __init__(self, profile):
        self.profile = profile

    def get(self, _stable_id):
        return self.profile


class Active:
    def __init__(self, media, gain=1.0, gain_db=0.0):
        self.media = media
        self.program_gain = gain
        self.program_gain_db = gain_db
        self.position = 0.0
        self.buffered_seconds = 1.0
        self.eof = False

    def read(self, frames):
        return array("f", [0.25] * frames * 2).tobytes()


def finite():
    return MediaRef(MediaSource.LOCAL, "C:/track.flac", duration=20)


def live():
    return MediaRef(
        MediaSource.RADIO,
        "https://radio.test/live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )


def test_replaygain_policy_and_live_filter_are_source_specific():
    repository = Repository(LoudnessProfile("song", track_gain_db=-6, track_peak=0.9))
    controller = PlaybackController(
        output_factory=lambda **_kwargs: None,
        loudness_repository=repository,
        replaygain_enabled=True,
        replaygain_mode="track",
        live_leveling=True,
    )
    assert controller._program_gain_db(finite()) == -6
    assert controller._program_gain_db(live()) == 0
    assert controller._live_filter(finite()) is None
    assert controller._live_filter(live()) == "loudnorm=I=-18:TP=-1:LRA=11"


def test_program_bus_precedes_local_volume_mute_and_sleep_gain():
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    controller._active = Active(finite(), gain=2.0, gain_db=6.0206)
    controller._state = PlaybackState.PLAYING
    controller.set_volume(50)
    controller.set_automation_gain(0.5)
    captured = []
    remove = controller.add_program_sink(lambda samples, _frames: captured.append(np.array(samples, copy=True)))
    controller.add_program_sink(lambda *_args: (_ for _ in ()).throw(RuntimeError("consumer failed")))
    output = np.empty((4, 2), dtype=np.float32)
    controller._audio_callback(output, 4, None, None)
    assert captured[0] == pytest.approx(np.full((4, 2), 0.5, dtype=np.float32))
    assert output == pytest.approx(np.full((4, 2), 0.125, dtype=np.float32))
    assert controller.snapshot().replaygain_db == pytest.approx(6.0206)
    remove()


def test_paused_program_publishes_silence_and_configuration_is_live():
    profile = LoudnessProfile("song", track_gain_db=-3, track_peak=0.8)
    controller = PlaybackController(
        output_factory=lambda **_kwargs: None,
        loudness_repository=Repository(profile),
        replaygain_enabled=True,
    )
    active = Active(finite())
    controller._active = active
    controller._state = PlaybackState.PAUSED
    captured = []
    controller.add_program_sink(lambda samples, _frames: captured.append(np.array(samples, copy=True)))
    output = np.ones((2, 2), dtype=np.float32)
    controller._audio_callback(output, 2, None, None)
    assert not output.any()
    assert not captured[0].any()
    controller.configure_replaygain(preamp_db=2)
    assert active.program_gain_db == -1
    with pytest.raises(ValueError, match="between -15 and 15"):
        controller.configure_replaygain(preamp_db=16)


def test_live_level_toggle_restarts_only_active_live_media(monkeypatch):
    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    controller._active = Active(live())
    restarts = []
    monkeypatch.setattr(controller, "restart_live", lambda: restarts.append(True))
    controller.set_live_leveling(True)
    assert restarts == [True]
    controller.set_live_leveling(True)
    assert restarts == [True]
    controller._active = SimpleNamespace(media=finite())
    controller.set_live_leveling(False)
    assert restarts == [True]
