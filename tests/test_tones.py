import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np

from mariana.tones import RATE, WAVES, parse_tone, render_tone


class ToneTests(unittest.TestCase):
    def setUp(self):
        session = tempfile.TemporaryDirectory()
        self.addCleanup(session.cleanup)
        self.folder = Path(session.name)

    def samples(self, command):
        path = render_tone(parse_tone(command.split()), self.folder)
        with wave.open(str(path), "rb") as src:
            self.assertEqual((src.getnchannels(), src.getsampwidth(), src.getframerate()), (1, 2, RATE))
            return np.frombuffer(src.readframes(src.getnframes()), dtype="<i2")

    def test_waveform_peaks_pitch_and_duration(self):
        results = []
        for waveform in WAVES:
            with self.subTest(waveform=waveform):
                pcm = self.samples(f"{waveform} 400 --seconds .3 --level 20")
                self.assertEqual(pcm.size, round(.3 * RATE))
                self.assertEqual((pcm[0], pcm[-1]), (0, 0))
                self.assertLessEqual(max(abs(pcm)), 6554)
                # Ten complete cycles from the steady part, beyond a block boundary.
                clip = pcm[8300:9500]
                spectrum = np.abs(np.fft.rfft(clip))
                self.assertEqual(np.argmax(spectrum), 10)
                results.append(clip)
        for i, left in enumerate(results):
            for right in results[i + 1:]:
                self.assertFalse(np.array_equal(left, right))

    def test_harmony_contains_each_note_with_equal_amplitude(self):
        pcm = self.samples("harmony 250 400 600 --seconds 1")
        window = pcm[RATE // 10:RATE * 9 // 10]
        magnitudes = np.abs(np.fft.rfft(window))
        strongest = sorted(np.argpartition(magnitudes, -3)[-3:])
        self.assertEqual(strongest, [200, 320, 480])
        self.assertLess(max(magnitudes[strongest]) / min(magnitudes[strongest]), 1.01)

    def test_chord_presets_expand_to_equal_temperament_from_the_root(self):
        self.assertEqual(parse_tone(["harmony", "220", "--chord", "octave"]).frequencies, (220, 440))
        tone = parse_tone(["harmony", "440", "--chord", "minor7"])
        np.testing.assert_allclose(tone.frequencies, (440, 523.2511, 659.2551, 783.9909), rtol=1e-5)

    def test_sweeps_cross_expected_frequencies_in_both_directions(self):
        for start, end in [(200, 800), (800, 200)]:
            for curve in ("linear", "log"):
                with self.subTest(start=start, end=end, curve=curve):
                    pcm = self.samples(f"sweep {start} {end} --seconds 2 --curve {curve}")
                    for fraction in (.25, .75):
                        middle = round(2 * RATE * fraction)
                        clip = pcm[middle - 2400:middle + 2400]
                        measured = np.count_nonzero((clip[:-1] <= 0) & (clip[1:] > 0)) * RATE / len(clip)
                        expected = (start + (end - start) * fraction if curve == "linear"
                                    else start * (end / start) ** fraction)
                        self.assertAlmostEqual(measured, expected, delta=12)

    def test_constant_log_sweep_default_pitch_and_silent_level(self):
        np.testing.assert_array_equal(self.samples("sweep 440 440 --curve log"), self.samples("sine"))
        self.assertFalse(np.any(self.samples("sawtooth 440 --seconds .05 --level 0")))

    def test_invalid_arguments_do_not_terminate_the_repl(self):
        for command in ("sine nan", "sine inf", "sine 0", "sine 21000", "sine 440 880", "sine --wave square",
                        "tone", "sweep 120", "sweep 220 110 --curve quadratic", "sweep 10 12 --seconds inf",
                        "harmony 440", "harmony 1 2 3 4 5 6 7 8 9", "triangle 1 --seconds 61",
                        "square 120 --seconds .01", "sine --level -1", "sine --level 101",
                        "sine --curve log", "sine --unknown", "sine 440 --chord major",
                        "harmony 220 440 --chord octave", "harmony 16000 --chord major"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_tone(command.split())

    def test_render_cache_and_interrupted_write(self):
        request = parse_tone(["sine"])
        with patch("mariana.tones._write_wav", side_effect=OSError("disk full")), self.assertRaises(OSError):
            render_tone(request, self.folder)
        self.assertEqual(list(self.folder.iterdir()), [])
        result = render_tone(request, self.folder)
        with patch("mariana.tones._write_wav", side_effect=AssertionError("re-render")):
            self.assertEqual(result, render_tone(parse_tone(["sine", "440", "--seconds", "2"]), self.folder))
