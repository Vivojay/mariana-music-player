import threading
from pathlib import Path

import pytest

import tools.soak_test as soak
from mariana.models import PlaybackSnapshot, PlaybackState
from tools.soak_test import NullOutputStream, SoakCredentials, run, wait_for_idle

FFMPEG_BIN = Path(
    r"C:\Users\Vivan.Jaiswal\Documents\ffmpeg-2025-12-18-git-78c75d546a-essentials_build\bin"
)


def test_short_mixed_playback_and_library_soak_has_bounded_resources():
    if not (FFMPEG_BIN / "ffmpeg.exe").is_file():
        pytest.skip("configured FFmpeg build is unavailable")
    result = run(2, str(FFMPEG_BIN), live_radio=False, library_files=100)
    assert result["cycles"] >= 1
    assert result["library_files"] == 100
    assert result["growth"] < 64 * 1024 * 1024


def test_short_broadcast_soak_produces_decodable_program_bytes():
    if not (FFMPEG_BIN / "ffmpeg.exe").is_file():
        pytest.skip("configured FFmpeg build is unavailable")
    result = run(1, str(FFMPEG_BIN), live_radio=False, library_files=10, broadcast=True)
    assert result["cycles"] >= 1
    assert result["broadcast_connections"] >= 1
    assert result["broadcast_bytes"] >= 1024


def test_null_output_stream_pumps_and_closes():
    pumped = threading.Event()

    def callback(output, frames, _time_info, _status):
        assert len(output) == frames * soak.BYTES_PER_FRAME
        pumped.set()

    stream = NullOutputStream(callback=callback, blocksize=48)
    stream.start()
    assert pumped.wait(1)
    stream.stop()
    assert not stream.thread.is_alive()
    stream.close()


def test_wait_for_idle_success_and_timeout(monkeypatch):
    idle = type("Controller", (), {"snapshot": lambda self: PlaybackSnapshot(PlaybackState.IDLE)})()
    wait_for_idle(idle, timeout=0.01)
    playing = type("Controller", (), {"snapshot": lambda self: PlaybackSnapshot(PlaybackState.PLAYING)})()
    monkeypatch.setattr(soak.time, "sleep", lambda _seconds: None)
    with pytest.raises(TimeoutError, match="Playback did not finish"):
        wait_for_idle(playing, timeout=0)


def test_soak_credentials_are_ephemeral():
    assert SoakCredentials().get("unused") == "soak-only-secret"


def test_soak_cli_forwards_arguments(monkeypatch, capsys):
    captured = {}
    monkeypatch.setattr(
        soak,
        "run",
        lambda *args: captured.update(args=args) or {"cycles": 1},
    )
    monkeypatch.setattr(
        "sys.argv",
        ["soak", "--seconds", "2", "--ffmpeg-bin", "tools", "--live-radio", "--library-files", "3", "--broadcast"],
    )
    soak.main()
    assert captured["args"] == (2.0, "tools", True, 3, True)
    assert "cycles" in capsys.readouterr().out
