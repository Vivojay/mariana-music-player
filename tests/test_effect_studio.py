"""DSP, monitor routing and offline render regressions using synthetic audio."""

import hashlib
import math
import shutil
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

import numpy as np

from mariana.effect_studio import EffectStudio
from mariana.effects import PRESETS, EffectProcessor, Rack, _voice_pitch
from mariana.models import MediaRef, MediaSource, PlaybackState
from mariana.playback import PlaybackController


def tone(hz, frames, rate=48000):
    mono = 0.25 * np.sin(np.arange(frames) * 2 * np.pi * hz / rate)
    return np.column_stack([mono, mono]).astype(np.float32)


def peak(signal, rate=48000):
    spectrum = abs(np.fft.rfft(signal * np.hanning(len(signal))))
    return np.argmax(spectrum) * rate / len(signal)


class EffectTests(unittest.TestCase):
    def test_pitch_stops_at_expected_octave_without_changing_frame_count(self):
        processor = EffectProcessor(Rack(pitch=12))
        signal = tone(222, 48000)
        out = np.concatenate([processor.process(block) for block in np.array_split(signal, 100)])
        self.assertEqual(out.shape, signal.shape)
        self.assertAlmostEqual(peak(out[5000:, 0]), 444, delta=5)
        self.assertFalse(processor.fault)

    def test_monophonic_correction_and_unvoiced_gate(self):
        self.assertAlmostEqual(_voice_pitch(tone(451, 768, 12000)[:, 0], 12000), 451, delta=1)
        self.assertIsNone(_voice_pitch(np.zeros(768), 12000))
        self.assertIsNone(_voice_pitch(np.random.default_rng(42).normal(0, 0.25, 768), 12000))
        processor = EffectProcessor(Rack(tune=100))
        out = processor.process(tone(451, 96000))
        self.assertAlmostEqual(processor.pitch_adjust, 12 * math.log2(440 / 451), delta=0.035)
        self.assertLess(abs(peak(out[24000:, 0]) - 440), abs(451 - 440))

    def test_delay_reset_deess_and_tape_stop(self):
        proc = EffectProcessor(Rack(delay=100))
        impulse = np.zeros((15000, 2), np.float32)
        impulse[0] = 1
        out = proc.render(impulse, 1)
        self.assertAlmostEqual(out[10800, 0], 0.5)
        self.assertFalse(proc.render(np.zeros_like(impulse), 2).any())
        deess = EffectProcessor(Rack(deess=100))
        s = tone(7200, 4800)
        self.assertLess(np.linalg.norm(deess.process(s)[3000:]), 0.5 * np.linalg.norm(s[3000:]))
        out = EffectProcessor(Rack(tapestop=25)).process(tone(220, 48000))
        self.assertFalse(out[30000:].any())

    def test_bitcrusher_retains_sample_hold_across_callback_boundaries(self):
        signal = tone(331, 200)
        complete = EffectProcessor(Rack(bitcrush=100)).render(signal, 4)
        stream = EffectProcessor(Rack(bitcrush=100))
        split = np.concatenate([stream.render(part, 4) for part in np.array_split(signal, 11)])
        np.testing.assert_array_equal(split, complete)
        np.testing.assert_array_equal(complete[16:32], np.tile(complete[16], (16, 1)))
        np.testing.assert_array_equal(complete * 8, np.floor(complete * 8))
        np.testing.assert_array_equal(stream.render(signal, 5), complete)

    def test_vendor_package_install_checks_digest_and_resolves_before_render(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            studio = EffectStudio(lambda: None, lambda: "ffmpeg", root / "fx" / "presets")
            archive = root / "vendor.zip"
            name = "Test.vst3/Contents/example"
            with ZipFile(archive, "w") as zipped:
                zipped.writestr(name, "fixture effect")
                zipped.writestr("LICENSE", "fixture notice")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "did not match"):
                studio.command(["plugin", "install", "test", str(archive), "0" * 64])
            self.assertEqual(list(studio.plugin_directory.iterdir()), [])
            studio.command(["plugin", "install", "test", str(archive), digest])
            self.assertIn("Installed for this profile: test", studio.command(["plugins"]))
            payload = studio.plugin_directory / "test" / "files"
            self.assertEqual((payload / name).read_text(), "fixture effect")
            self.assertEqual((payload / "LICENSE").read_text(), "fixture notice")

            source, target = root / "in.wav", root / "out.wav"
            source.write_bytes(b"source")

            def run(command, **kwargs):
                self.assertEqual(Path(command[1]), payload / "Test.vst3")
                Path(command[-1]).write_bytes(bytes(100))
                return SimpleNamespace(returncode=0)

            with (
                patch("mariana.effect_studio._plugin_host", return_value=(["fixture"], None)),
                patch("mariana.effect_studio.subprocess.run", side_effect=run),
            ):
                studio.command(["plugin", "test", str(source), str(target)])
            self.assertEqual(target.read_bytes(), bytes(100))
            with self.assertRaisesRegex(ValueError, "already installed"):
                studio.command(["plugin", "install", "test", str(archive), digest])

    def test_vendor_zip_rejects_bad_payload_and_insecure_download(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            studio = EffectStudio(lambda: None, lambda: "ffmpeg", root / "fx" / "presets")
            traversal = "../escape.vst3"
            link = ZipInfo("Link.vst3")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            for member in (traversal, "Fake.vst3/../../escape", "Random/CON.dll", link):
                with self.subTest(member=member):
                    archive = root / "vendor.zip"
                    with ZipFile(archive, "w") as zipped:
                        zipped.writestr(member, "data")
                    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
                    with self.assertRaises(ValueError):
                        studio.command(["plugin", "install", "test", str(archive), digest])
                    self.assertEqual(list(studio.plugin_directory.iterdir()), [])
            with self.assertRaisesRegex(ValueError, "HTTPS"):
                studio.command(["plugin", "install", "test", "http://example.com/x.zip", "0" * 64])

    def test_all_presets_change_input_and_stay_bounded(self):
        signal = tone(451, 24000)
        for key, rack in PRESETS.items():
            with self.subTest(key=key):
                if key == "dry":
                    continue
                p = EffectProcessor(rack)
                out = p.process(signal)
                self.assertFalse(p.fault)
                self.assertTrue(np.isfinite(out).all())
                self.assertLessEqual(np.max(np.abs(out)), 1.0)
                self.assertFalse(np.allclose(out, signal))

    def test_native_callback_wet_output_and_dry_program(self):
        ctrl = PlaybackController(output_factory=lambda **kw: None)
        ctrl._state = PlaybackState.PLAYING
        samples = tone(220, 1024)
        media = MediaRef(MediaSource.LOCAL, "test.wav", duration=2)
        ctrl._active = SimpleNamespace(
            media=media, position=0.1, eof=False, buffered_seconds=2, read=lambda frames: samples[:frames].tobytes()
        )
        recorded = []
        ctrl.add_program_sink(lambda pcm, _: recorded.append(np.asarray(pcm).copy()))
        ctrl.monitor_effect = EffectProcessor(Rack(drive=70))
        out = np.empty_like(samples)
        ctrl._render_ordinary_audio(out, len(out), None, None)
        np.testing.assert_allclose(recorded[0], samples)
        self.assertGreater(np.max(np.abs(out)), np.max(np.abs(samples)) * 2)
        self.assertFalse(ctrl.monitor_effect.fault)

    def test_save_restore_and_invalid_values(self):
        with TemporaryDirectory() as folder:
            engine = SimpleNamespace(monitor_effect=None)
            studio = EffectStudio(lambda: engine, lambda: "ffmpeg", folder)
            studio.command(["preset", "choir"])
            studio.command(["save", "my-choir"])
            studio.command(["off"])
            self.assertIsNone(engine.monitor_effect)
            self.assertIn("Saved: my-choir", studio.command(["presets"]))
            self.assertIn("chorus 62", studio.command(["load", "my-choir"]))
            for cmd in (["set", "pitch", "NaN"], ["set", "room", "101"], ["save", "../out"]):
                with self.assertRaises(ValueError):
                    studio.command(cmd)
            self.assertEqual(engine.monitor_effect.rack, PRESETS["choir"])

    def test_mic_stream_real_callback_and_cleanup(self):
        stream = SimpleNamespace()
        active = []

        def duplex(**spec):
            stream.start = lambda: active.append(1)
            stream.abort = lambda: active.clear()
            stream.close = lambda: None
            stream.callback = spec["callback"]
            return stream

        with TemporaryDirectory() as folder, patch.dict("sys.modules", {"sounddevice": SimpleNamespace(Stream=duplex)}):
            engine = SimpleNamespace(monitor_effect=None)
            studio = EffectStudio(lambda: engine, lambda: "ffmpeg", folder)
            studio.command(["set", "drive", "50"])
            studio.command(["mic", "on"])
            studio.command(["mic", "on"])
            self.assertEqual(active, [1])
            microphone = tone(220, 512)[:, :1]
            out = np.empty((512, 2), np.float32)
            stream.callback(microphone, out, 512, None, None)
            self.assertTrue(np.allclose(out[:, 0], out[:, 1]))
            self.assertGreater(np.max(out), np.max(microphone) * 0.35)
            studio.command(["mic", "off"])
            self.assertFalse(active)

    def test_plugin_helper_flushes_latency_and_preserves_original_length(self):
        from mariana.effect_plugin import main

        original = tone(330, 8192).T
        output = []

        class File:
            def __init__(self, *args):
                self.pos = 0

            samplerate = 48000
            num_channels = 2
            frames = 8192

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def tell(self):
                return self.pos

            def read(self, n):
                chunk = original[..., self.pos : self.pos + n]
                self.pos += n
                return chunk

            def write(self, chunk):
                output.append(chunk.copy())

        class Delayed:
            is_effect = True

            def __init__(self):
                self.held = np.empty((2, 0), np.float32)

            def process(self, chunk, rate, reset):
                joined = np.concatenate((self.held, chunk), axis=1)
                self.held = joined[..., -100:]
                return joined[..., :-100]

        host = SimpleNamespace(load_plugin=lambda path: Delayed())
        with patch.dict("sys.modules", {"pedalboard": host, "pedalboard.io": SimpleNamespace(AudioFile=File)}):
            self.assertEqual(main(["test.vst3", "in.wav", "out.wav"]), 0)
        np.testing.assert_allclose(original, np.concatenate(output, axis=1))

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg needed")
    def test_real_tempo_bounce_preserves_pitch_and_exclusive_target(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "in.wav"
            target = base / "out.wav"
            with wave.open(str(source), "wb") as wav:
                wav.setparams((2, 2, 48000, 0, "NONE", ""))
                wav.writeframes((tone(330, 48000) * 32767).astype("<i2").tobytes())
            studio = EffectStudio(lambda: None, lambda: shutil.which("ffmpeg"), base)
            studio.command(["tempo", "2", str(source), str(target)])
            with wave.open(str(target), "rb") as wav:
                self.assertAlmostEqual(wav.getnframes(), 24000, delta=1700)
                signal = np.frombuffer(wav.readframes(wav.getnframes()), "<i2")[::2]
                self.assertAlmostEqual(peak(signal), 330, delta=3)
            before = target.read_bytes()
            with self.assertRaises(ValueError):
                studio.command(["tempo", ".5", str(source), str(target)])
            self.assertEqual(target.read_bytes(), before)
