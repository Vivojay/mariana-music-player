import os
import shutil
import threading
from pathlib import Path

import pytest

import tools.soak_test as soak
from mariana.models import PlaybackSnapshot, PlaybackState
from tools.soak_test import NullOutputStream, SoakCredentials, run, wait_for_idle


def ffmpeg_bin() -> Path | None:
    if configured := os.environ.get("MARIANA_TEST_FFMPEG_BIN"):
        directory = Path(configured).expanduser()
        executable = directory / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        if executable.is_file():
            return directory
    executable = shutil.which("ffmpeg")
    return Path(executable).parent if executable else None


def test_short_mixed_playback_and_library_soak_has_bounded_resources():
    binary_directory = ffmpeg_bin()
    if binary_directory is None:
        pytest.skip("configured FFmpeg build is unavailable")
    result = run(2, str(binary_directory), live_radio=False, library_files=100)
    assert result["cycles"] >= 1
    assert result["library_files"] == 100
    assert result["growth"] < 64 * 1024 * 1024


def test_short_broadcast_soak_produces_decodable_program_bytes():
    binary_directory = ffmpeg_bin()
    if binary_directory is None:
        pytest.skip("configured FFmpeg build is unavailable")
    result = run(1, str(binary_directory), live_radio=False, library_files=10, broadcast=True)
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


def test_soak_orchestration_covers_library_broadcast_and_live_radio(monkeypatch):
    events = []

    class Clock:
        value = 0.0

        def monotonic(self):
            self.value += 0.01
            return self.value

    class Process:
        def children(self, recursive=True):
            assert recursive
            return []

        def memory_info(self):
            return type("Memory", (), {"rss": 10_000_000})()

    class Server:
        server_port = 49152

        def __init__(self, *_args, **_kwargs):
            pass

        def serve_forever(self):
            events.append("server-start")

        def shutdown(self):
            events.append("server-stop")

        def server_close(self):
            events.append("server-close")

    class Controller:
        def __init__(self, **_kwargs):
            self.media = None

        def add_program_sink(self, _sink):
            events.append("program-sink")

        def play(self, media, probe=True):
            self.media = media
            events.append(("play", media.source.value, probe))

        def snapshot(self):
            return PlaybackSnapshot(PlaybackState.IDLE, media=self.media)

        def pause(self):
            events.append("pause")

        def resume(self):
            events.append("resume")

        def seek(self, position):
            events.append(("seek", position))

        def restart_live(self):
            events.append("restart-live")

        def stop(self):
            events.append("stop")

        def close(self):
            events.append("controller-close")

    class Sink:
        def __init__(self):
            self.port = 49153
            self.connections = 1
            self.bytes_received = 4096

        def start(self):
            events.append("sink-start")

        def close(self):
            events.append("sink-close")

    class Broadcaster:
        def __init__(self, *_args, **_kwargs):
            self.state = soak.BroadcastState.LIVE

        def offer(self, *_args):
            pass

        def start(self, name):
            events.append(("broadcast", name))

        def snapshot(self):
            return type("Snapshot", (), {"state": self.state})()

        def close(self):
            events.append("broadcast-close")

    class Database:
        def __init__(self, _path):
            pass

        def fetchone(self, statement):
            return ("ok",) if "integrity" in statement else (0,)

        def close(self):
            events.append("database-close")

    class Catalog:
        def __init__(self, *_args, **_kwargs):
            pass

        def scan(self, mode):
            events.append(("scan", mode))

    def generate_tone(command, **_kwargs):
        Path(command[-1]).touch()
        return type("Result", (), {"returncode": 0})()

    clock = Clock()
    monkeypatch.setattr(soak.psutil, "Process", Process)
    monkeypatch.setattr(soak.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(soak.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(soak.subprocess, "run", generate_tone)
    monkeypatch.setattr(soak, "ThreadingHTTPServer", Server)
    monkeypatch.setattr(soak, "PlaybackController", Controller)
    monkeypatch.setattr(soak, "BroadcastSink", Sink)
    monkeypatch.setattr(soak, "IcecastBroadcaster", Broadcaster)
    monkeypatch.setattr(soak, "MarianaDatabase", Database)
    monkeypatch.setattr(soak, "LibraryCatalog", Catalog)

    result = run(0.06, "tools", live_radio=True, library_files=3, broadcast=True)
    assert result == {
        "cycles": 2,
        "library_files": 3,
        "baseline_rss": 10_000_000,
        "peak_rss": 10_000_000,
        "growth": 0,
        "broadcast_bytes": 4096,
        "broadcast_connections": 1,
    }
    assert {"pause", "resume", "restart-live", "controller-close", "database-close"} <= set(events)
    assert ("seek", 0.2) in events
    assert ("play", "radio", False) in events
