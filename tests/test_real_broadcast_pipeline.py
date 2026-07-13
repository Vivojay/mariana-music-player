"""Real FFmpeg encoder acceptance through Mariana's authenticated loopback tunnel."""

import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from mariana.broadcast import BroadcastProfile, BroadcastState, IcecastBroadcaster


def tool(name: str) -> str | None:
    if configured := os.environ.get("MARIANA_TEST_FFMPEG_BIN"):
        candidate = Path(configured).expanduser() / (f"{name}.exe" if os.name == "nt" else name)
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


class Credentials:
    def get(self, _reference):
        return "test-password"


def dechunk(payload: bytes) -> bytes:
    output = bytearray()
    while payload:
        line, separator, payload = payload.partition(b"\r\n")
        if not separator:
            break
        try:
            size = int(line.split(b";", 1)[0], 16)
        except ValueError:
            return bytes(output) if output else line + separator + payload
        if not size or len(payload) < size:
            break
        output.extend(payload[:size])
        payload = payload[size + 2 :]
    return bytes(output)


@pytest.mark.parametrize(("codec", "suffix"), [("opus", ".ogg"), ("mp3", ".mp3")])
def test_real_broadcast_encodes_decodable_normalized_program_mix(tmp_path, codec, suffix):
    ffmpeg, ffprobe = tool("ffmpeg"), tool("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and FFprobe are required")
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    captured = {}

    def receive_source():
        connection, _address = server.accept()
        payload = bytearray()
        while b"\r\n\r\n" not in payload:
            payload.extend(connection.recv(65_536))
        head, body = bytes(payload).split(b"\r\n\r\n", 1)
        captured["headers"] = head
        connection.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n")
        chunks = [body]
        while data := connection.recv(65_536):
            chunks.append(data)
        captured["body"] = b"".join(chunks)
        connection.close()
        server.close()

    thread = threading.Thread(target=receive_source, daemon=True)
    thread.start()
    profile = BroadcastProfile(
        "local", f"http://127.0.0.1:{port}", f"/test{suffix}", codec=codec, bitrate_kbps=128
    )
    broadcaster = IcecastBroadcaster({"local": profile}, ffmpeg_bin=ffmpeg, credentials=Credentials())
    broadcaster.start("local")
    deadline = time.monotonic() + 10
    while broadcaster.snapshot().state != BroadcastState.LIVE and time.monotonic() < deadline:
        time.sleep(0.01)
    assert broadcaster.snapshot().state == BroadcastState.LIVE, broadcaster.snapshot().error

    frames = np.arange(48_000, dtype=np.float32)
    tone = (0.2 * np.sin(2 * np.pi * 440 * frames / 48_000)).astype(np.float32)
    stereo = np.column_stack((tone, tone))
    for offset in range(0, len(stereo), 1024):
        block = stereo[offset : offset + 1024]
        broadcaster.offer(block, len(block))
        time.sleep(len(block) / 48_000)
    time.sleep(0.5)
    broadcaster.stop()
    thread.join(10)
    assert not thread.is_alive()
    assert b"test-password" not in captured["headers"]
    body = dechunk(captured["body"]) if b"transfer-encoding: chunked" in captured["headers"].lower() else captured["body"]
    output = tmp_path / f"captured{suffix}"
    output.write_bytes(body)
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(output)],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    duration = float(result.stdout.strip())
    # Startup silence is intentional: a manually active broadcast stays connected
    # before playback and while the queue is empty.
    assert 1.0 <= duration <= 7.0
    decoded = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(output), "-f", "f32le", "-ac", "2", "-ar", "48000", "pipe:1"],
        capture_output=True,
        check=True,
        timeout=15,
    ).stdout
    left = np.frombuffer(decoded, dtype=np.float32)[::2]
    assert np.max(np.abs(left)) > 0.1
    spectrum = np.abs(np.fft.rfft(left))
    frequencies = np.fft.rfftfreq(len(left), 1 / 48_000)
    dominant = frequencies[int(np.argmax(spectrum[1:]) + 1)]
    assert dominant == pytest.approx(440, abs=3)
