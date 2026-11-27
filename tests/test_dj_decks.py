import math
import shutil
import wave
from pathlib import Path

import numpy as np
import pytest

from mariana.dj import DJSession, SAMPLE_RATE


class Output:
    """Drive the production PortAudio callback without requiring a sound card."""

    def __init__(self, callback):
        self.callback = callback
        self.active = False
        self.closed = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.closed = True

    def read(self, frames):
        assert self.active
        block = np.empty((frames, 2), dtype=np.float32)
        self.callback(block, frames, None, None)
        return block


def write_deck(path, left, right):
    with wave.open(str(path), "wb") as f:
        f.setparams((2, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        f.writeframes(np.column_stack((left, right)).astype("<i2").tobytes())
    return path


@pytest.fixture
def session(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("Integration tests decode local audio with FFmpeg")
    dj = DJSession(tmp_path / "recordings", ffmpeg, Output)
    first = np.full(9600, 8192)
    silent = np.zeros_like(first)
    a = write_deck(tmp_path / "First deck.wav", first, silent)
    b = write_deck(tmp_path / "Second.wav", silent, first)
    dj.command(["load", "A", str(a)])
    dj.command(["load", "b", str(b)])
    try:
        yield dj
    finally:
        dj.close()


def test_stereo_mix_ramp_recording_export_and_share(session, tmp_path, monkeypatch):
    dj = session
    final = tmp_path / "my live mix.wav"
    dj.command(["record", "start", str(final)])
    dj.command(["play", "all"])
    a = dj.output.read(128)
    np.testing.assert_allclose(a, [[0.25, 0.0]] * 128, atol=1e-7)
    dj.command(["crossfade", "50"])
    both = dj.output.read(128)
    np.testing.assert_allclose(both, np.full((128, 2), 0.25 / math.sqrt(2)), atol=1e-7)
    dj.command(["crossfade", "100", "0.01"])
    ramp = np.concatenate([dj.output.read(239), dj.output.read(259)])
    np.testing.assert_allclose(ramp[479:], [[0, 0.25]] * 19, atol=1e-7)
    assert np.all(np.diff(ramp[:480, 0]) <= 0)
    assert np.all(np.diff(ramp[:480, 1]) >= 0)
    assert "Saved" in dj.command(["record", "stop"])
    copy = tmp_path / "export.wav"
    dj.command(["export", str(copy)])
    assert copy.read_bytes() == final.read_bytes()
    with wave.open(str(copy)) as f:
        assert (f.getframerate(), f.getnchannels(), f.getsampwidth()) == (SAMPLE_RATE, 2, 2)
        recorded = np.frombuffer(f.readframes(f.getnframes()), dtype="<i2").reshape(-1, 2)
    np.testing.assert_array_equal(recorded, np.rint(np.concatenate([a, both, ramp]) * 32767).astype("<i2"))
    with pytest.raises(FileExistsError):
        dj.command(["export", str(copy)])
    with pytest.raises(FileExistsError):
        dj.command(["record", "start", str(final)])
    assert dj.command(["export"]) == str(final)
    monkeypatch.setattr("mariana.clip_share.open_share", lambda path, recording: f"share {path}" if recording else "")
    assert dj.command(["share"]) == f"share {final}"


def test_independent_transport_hotcues_loop_interpolation_and_eof(session, tmp_path):
    dj = session
    a = write_deck(tmp_path / "ramp.wav", np.arange(9600), np.zeros(9600))
    dj.command(["load", "A", str(a)])
    dj.command(["play", "all"])
    dj.output.read(120)
    dj.command(["pause", "B"])
    dj.command(["seek", "a", "0.0125"])
    dj.command(["cue", "A", "set", "2"])
    dj.command(["rate", "A", "0.5"])
    np.testing.assert_allclose(dj.output.read(3)[:, 0], np.array([600, 600.5, 601]) / 32768, atol=1e-7)
    assert dj.decks["B"].position == 120
    dj.command(["cue", "A", "go", "2"])
    assert dj.decks["A"].position == 600
    dj.command(["loop", "A", "0.01", "0.011"])
    dj.command(["rate", "A", "2"])
    dj.command(["gain", "A", "50"])
    looped = dj.output.read(52)[:, 0]
    np.testing.assert_allclose(looped, (480 + 2 * (np.arange(52) % 24)) / 65536, atol=1e-7)
    dj.command(["loop", "A", "off"])
    dj.command(["seek", "A", "0.199"])
    assert np.all(dj.output.read(60)[24:] == 0)
    assert not dj.decks["A"].playing
    dj.command(["play", "A"])
    assert dj.decks["A"].position == 0
    dj.command(["stop", "all"])
    assert all(not d.playing and not d.position for d in dj.decks.values())


def test_decode_failure_preserves_state_and_closing_finishes_recording(session, tmp_path):
    dj = session
    old = dj.decks["A"]
    path = tmp_path / "corrupt.wav"
    path.write_bytes(b"broken")
    with pytest.raises(ValueError, match="decode"):
        dj.command(["load", "A", str(path)])
    assert dj.decks["A"] is old
    for invalid in (["gain", "A", "nan"], ["crossfade", "inf"], ["seek", "C", "2"],
                    ["cue", "B", "go", "5"], ["loop", "A", "0.1", "0.01"]):
        with pytest.raises(ValueError):
            dj.command(invalid)
    dj.command(["record", "start"])
    dj.command(["play", "A"])
    dj.output.read(64)
    raw_dir = old.storage.name
    dj.unload_source(old.source)
    assert "A" not in dj.decks
    assert not Path(raw_dir).exists()
    stream = dj.output
    dj.close()
    assert stream.closed
    assert not dj.decks
    with wave.open(str(dj.last_file)) as f:
        assert f.getnframes() == 64


def test_device_failure_keeps_decks_paused_and_creates_no_empty_file(session, tmp_path):
    class Broken(Output):
        def start(self):
            raise RuntimeError("device busy")
    session.output_factory = Broken
    with pytest.raises(ValueError, match="device busy"):
        session.command(["play", "A"])
    assert not session.decks["A"].playing
    dst = tmp_path / "unused.wav"
    with pytest.raises(ValueError, match="device busy"):
        session.command(["record", "start", str(dst)])
    assert not dst.exists()



def test_mixxx_handoff_passes_audio_in_deck_order_and_releases_output(session, tmp_path, monkeypatch):
    executable = tmp_path / "mixxx"
    executable.touch()
    seen = []
    monkeypatch.setattr("mariana.dj.shutil.which", lambda _: str(executable))
    monkeypatch.setattr("mariana.dj.subprocess.Popen", lambda args, **kw: seen.extend(args))
    session.command(["play", "A"])
    stream = session.output
    session.command(["mixxx"])
    assert seen == [str(executable), str(session.decks["A"].source), str(session.decks["B"].source)]
    assert stream.closed and session.output is None
    assert not any(deck.playing for deck in session.decks.values())


def test_cue_outside_loop_releases_loop_and_recorder_keeps_partial_wav(session, tmp_path):
    dj = session
    dj.command(["seek", "A", "0.15"])
    dj.command(["cue", "A", "set", "8"])
    dj.command(["loop", "A", "0", "0.10"])
    dj.command(["cue", "A", "go", "8"])
    assert dj.decks["A"].loop is None
    assert dj.decks["A"].position == 7200
    final = tmp_path / "retained.wav"
    dj.command(["record", "start", str(final)])
    dj.command(["play", "A"])
    dj.output.read(64)
    dj.recording.error = "Storage stalled."
    with pytest.raises(ValueError, match="partial capture"):
        dj.command(["record", "stop"])
    assert dj.last_file is None
    with wave.open(str(final)) as f:
        assert f.getnframes() == 64


def test_share_recorded_wav_over_loopback(session, tmp_path, monkeypatch):
    from urllib.request import build_opener, ProxyHandler
    import mariana.clip_share as share
    addresses = []
    monkeypatch.setattr(share.webbrowser, "open", lambda url, new: addresses.append(url) or True)
    path = tmp_path / "concert.wav"
    session.command(["record", "start", str(path)])
    session.command(["play", "all"])
    session.output.read(128)
    session.command(["record", "stop"])
    assert "Recording saved" in session.command(["share"])
    browser = build_opener(ProxyHandler({}))
    with browser.open(addresses[0], timeout=2) as page:
        assert b"Share your recording" in page.read()
    with browser.open(addresses[0] + "file", timeout=2) as response:
        assert response.read() == path.read_bytes()



def test_overlapping_peaks_report_clipping_and_limit_the_recorded_bus(session):
    dj = session
    hot = write_deck(dj.decks["A"].source.parent / "hot.wav", np.full(200, 30000), np.full(200, -30000))
    for name in ("A", "B"):
        dj.command(["load", name, str(hot)])
    dj.command(["crossfade", "50"])
    dj.command(["play", "all"])
    block = dj.output.read(128)
    np.testing.assert_array_equal(block, [[1, -1]] * 128)
    assert dj.peak > 1
    assert "clipped on 128 sample frames" in dj.status()
