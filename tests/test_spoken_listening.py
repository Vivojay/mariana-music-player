"""Voice dynamics, route selection and persistence with synthetic stereo PCM."""
import unittest

import numpy as np

from mariana.deesser import VoiceDeEsser
from mariana.equalizer import EqualizerProcessor, EqualizerService, command_intent


def sine(hz, amplitude=0.3):
    tone = amplitude * np.sin(np.arange(24000) * 2 * np.pi * hz / 48000)
    return np.column_stack((tone, tone * 0.4)).astype(np.float32)


class SpokenListeningTests(unittest.TestCase):
    def test_selectivity_attenuation_and_stereo_link(self):
        sibilant = sine(7200)
        for mode, reduction in (("gentle", 3), ("balanced", 6), ("strong", 9)):
            with self.subTest(mode=mode):
                dynamics = VoiceDeEsser(mode, 48000)
                result = dynamics.process(sibilant, 1)[3000:]
                expected = sibilant[3000:] * 10 ** (-reduction / 20)
                np.testing.assert_allclose(result, expected, atol=0.0001)
                vowel = sine(400)
                # Settled isolated low-frequency speech should pass at unity.
                np.testing.assert_allclose(dynamics.process(vowel, 2)[3000:], vowel[3000:], atol=1e-5)
                quiet = sine(7200, 0.001)
                np.testing.assert_allclose(dynamics.process(quiet, 3), quiet, atol=1e-5)

    def test_compensates_consistently_across_callback_sizes(self):
        audio = sine(7000)
        whole = VoiceDeEsser("strong", 48000).process(audio, 1)
        processor = VoiceDeEsser("strong", 48000)
        chunks = [processor.process(audio[i:i + 409], 1) for i in range(0, len(audio), 409)]
        np.testing.assert_allclose(np.concatenate(chunks), whole, atol=1e-6)
        self.assertIs(processor.process(audio, None), audio)
        np.testing.assert_allclose(processor.process(audio, 2), whole)

    def test_legacy_settings_independent_of_eq_presets_and_reload(self):
        engine = EqualizerProcessor()
        writes = []
        service = EqualizerService(lambda: engine, {"enabled": False}, writes.append)
        self.assertIsNone(engine.deesser)
        state = service.apply(command_intent(["deesser", "gentle"]))
        self.assertFalse(state["enabled"])
        self.assertEqual(state["deesser"], "gentle")
        service.apply(command_intent(["preset", "apply", "Bass Boost"]))
        self.assertEqual(engine.deesser.mode, "gentle")
        other = EqualizerProcessor()
        loaded = EqualizerService(lambda: other, writes[-1])
        self.assertEqual(other.deesser.mode, "gentle")
        loaded.apply(command_intent(["deesser", "off"]))
        self.assertIsNone(other.deesser)

    def test_failed_write_stale_revision_and_invalid_strength_preserve_audio(self):
        def fail(_):
            raise OSError("disk full")
        engine = EqualizerProcessor()
        service = EqualizerService(lambda: engine, persist=fail)
        with self.assertRaises(OSError):
            service.apply(command_intent(["deesser", "balanced"]))
        with self.assertRaises(ValueError):
            service.apply({"operation": "deesser", "mode": "strong", "revision": 77})
        with self.assertRaises(ValueError):
            command_intent(["deesser", "10"])
        self.assertIsNone(engine.deesser)
        self.assertEqual(service.revision, 0)
