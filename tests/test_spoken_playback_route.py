"""Exercise the ordinary PCM callback with a synthetic source and output."""
import unittest

import numpy as np

from mariana.equalizer import EqualizerService, command_intent
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState
from mariana.playback import PlaybackController


class VoiceSession:
    def __init__(self, source):
        self.media = MediaRef(source, "/sample.wav", duration=30, capabilities=MediaCapabilities())
        self.position = 0
        self.eof = False
        self.buffered_seconds = 30
        self.program_gain = 1
        self.block = np.repeat((.3 * np.sin(np.arange(4800) * 2 * np.pi * 7200 / 48000))[:, None], 2, axis=1).astype(np.float32)

    def read(self, frames):
        self.position += frames / 48000
        return self.block[:frames].tobytes()


class SpokenPlaybackRoute(unittest.TestCase):
    def test_program_tap_dry_and_only_spoken_playback_attenuated(self):
        ctrl = PlaybackController(output_factory=lambda **kw: None)
        service = EqualizerService(lambda: ctrl.equalizer)
        service.apply(command_intent(["deesser", "strong"]))
        broadcast = []
        ctrl.add_program_sink(lambda pcm, _: broadcast.append(np.asarray(pcm).copy()))
        ctrl._state = PlaybackState.PLAYING
        for kind in (MediaSource.PODCAST, MediaSource.LOCAL):
            with self.subTest(kind=kind):
                ctrl._active = source = VoiceSession(kind)
                output = np.empty_like(source.block)
                ctrl._render_ordinary_audio(output, len(output), None, None)
                np.testing.assert_allclose(broadcast[-1], source.block)
                gain = 10 ** (-9 / 20) if kind == MediaSource.PODCAST else 1
                np.testing.assert_allclose(output[3000:], source.block[3000:] * gain, atol=0.0001)
        speech = VoiceSession(MediaSource.PODCAST)
        self.assertIs(ctrl._spoken_samples(speech.block, speech, VoiceSession(MediaSource.LOCAL)), speech.block)
