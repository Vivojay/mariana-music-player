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


def dominant_tone_frequency(samples: np.ndarray, sample_rate: int) -> float:
    """Measure the active tone rather than capture framing and keepalive silence."""
    peak = float(np.max(np.abs(samples)))
    active = np.flatnonzero(np.abs(samples) >= max(0.01, peak * 0.1))
    assert active.size >= 2
    tone = samples[active[0] : active[-1] + 1]
    assert tone.size >= sample_rate // 20
    fft_size = max(65_536, 1 << (tone.size - 1).bit_length())
    spectrum = np.abs(np.fft.rfft(tone * np.hanning(tone.size), n=fft_size))
    frequencies = np.fft.rfftfreq(fft_size, 1 / sample_rate)
    return float(frequencies[int(np.argmax(spectrum[1:]) + 1)])


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
    # The broadcaster's own connection timeout is ten seconds. Leave enough
    # headroom for a loaded CI runner to publish the terminal state afterward.
    deadline = time.monotonic() + 15
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
    dominant = dominant_tone_frequency(left, 48_000)
    # Encoder delay, padding, and keepalive silence differ across platform
    # FFmpeg builds. Analyze the windowed active program material while retaining
    # a small extra tolerance for the lossy MP3 path.
    frequency_tolerance = 6 if codec == "mp3" else 5
    assert dominant == pytest.approx(440, abs=frequency_tolerance)


def test_dominant_tone_frequency_ignores_capture_silence_and_short_boundaries():
    sample_rate = 48_000
    frames = np.arange(round(sample_rate * 0.17), dtype=np.float32)
    tone = (0.2 * np.sin(2 * np.pi * 440 * frames / sample_rate)).astype(np.float32)
    capture = np.concatenate((np.zeros(8_137, dtype=np.float32), tone, np.zeros(12_421, dtype=np.float32)))

    assert dominant_tone_frequency(capture, sample_rate) == pytest.approx(440, abs=1)
