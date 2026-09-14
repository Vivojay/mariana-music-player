"""Real decoding with deterministic PCM verification, not audible-device acceptance."""

import shutil
import subprocess

import numpy as np
import pytest

from mariana.equalizer import EqualizerProcessor, EqualizerSettings
from mariana.models import MediaRef, MediaSource
from mariana.playback import DecoderSession


def test_equalizer_updates_leave_real_decoder_and_position_untouched(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is required for real decoder acceptance")
    path = tmp_path / "tone.flac"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=1000:sample_rate=44100:duration=1", str(path)], check=True, timeout=20)
    session = DecoderSession(MediaRef(MediaSource.LOCAL, str(path), duration=1), ffmpeg_bin=ffmpeg)
    engine = EqualizerProcessor(48000)
    session.start()
    try:
        assert session.wait_for_buffer(.5, timeout=10)
        process, position = session.process, session.position
        engine.submit(engine.prepare(EqualizerSettings(True, (0, 0, 0, 0, 0, 6, 0, 0, 0, 0), -3)))
        assert session.process is process and session.position == position
        original, filtered = [], []
        for _ in range(40):
            block = np.frombuffer(session.read(512), np.float32).reshape(-1, 2)
            assert len(block) == 512
            original.append(block)
            filtered.append(engine.process(block))
        dry, wet = np.concatenate(original)[9600:], np.concatenate(filtered)[9600:]
        measured = 20 * np.log10(np.sqrt(np.mean(wet ** 2)) / np.sqrt(np.mean(dry ** 2)))
        assert measured == pytest.approx(3, abs=.03)
        assert session.process is process
        assert session.position == pytest.approx(40 * 512 / 48000)
    finally:
        session.stop()
    assert session.process is None
