"""Long-running FFmpeg lifecycle soak for Mariana.

The release gate is eight hours (the default). A shorter duration is useful as
an implementation stress probe but does not satisfy the release gate.
"""

from __future__ import annotations

import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import tempfile
import threading
import time

import psutil

from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState
from mariana.playback import BYTES_PER_FRAME, PlaybackController, SAMPLE_RATE


class NullOutputStream:
    def __init__(self, *, callback, blocksize, **_kwargs):
        self.callback = callback
        self.blocksize = blocksize
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        def pump():
            interval = self.blocksize / SAMPLE_RATE
            while not self.stop_event.wait(interval):
                self.callback(bytearray(self.blocksize * BYTES_PER_FRAME), self.blocksize, None, None)

        self.thread = threading.Thread(target=pump, name="mariana-null-output", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def close(self):
        self.stop()


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def wait_for_idle(controller: PlaybackController, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if controller.snapshot().state == PlaybackState.IDLE:
            return
        time.sleep(0.02)
    raise TimeoutError(f"Playback did not finish: {controller.snapshot()}")


def run(duration_seconds: float, ffmpeg_bin: str, live_radio: bool) -> dict:
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = baseline
    cycles = 0
    with tempfile.TemporaryDirectory(prefix="mariana-soak-") as directory:
        directory = Path(directory)
        ffmpeg = Path(ffmpeg_bin) / "ffmpeg.exe"
        tone = directory / "tone.flac"
        subprocess.run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=1",
                "-y",
                str(tone),
            ],
            check=True,
            timeout=30,
        )
        handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(directory), **kwargs)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        controller = PlaybackController(
            ffmpeg_bin=ffmpeg_bin,
            ffprobe_bin=ffmpeg_bin,
            crossfade_seconds=0.1,
            output_factory=NullOutputStream,
        )
        deadline = time.monotonic() + duration_seconds
        try:
            while time.monotonic() < deadline:
                source = (
                    MediaRef(MediaSource.LOCAL, str(tone))
                    if cycles % 2 == 0
                    else MediaRef(MediaSource.URL, f"http://127.0.0.1:{server.server_port}/tone.flac")
                )
                controller.play(source)
                if cycles % 3 == 0:
                    controller.pause()
                    time.sleep(0.03)
                    controller.resume()
                if cycles % 4 == 0:
                    controller.seek(0.2)
                wait_for_idle(controller)
                cycles += 1
                peak = max(peak, process.memory_info().rss)
            if live_radio:
                radio = MediaRef(
                    MediaSource.RADIO,
                    "https://ice6.somafm.com/groovesalad-128-mp3",
                    title="SomaFM Groove Salad",
                    capabilities=MediaCapabilities(finite=False, live=True, seekable=False, downloadable=False),
                )
                controller.play(radio, probe=False)
                time.sleep(5)
                controller.restart_live()
                time.sleep(5)
                controller.stop()
        finally:
            controller.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
    children = [child for child in process.children(recursive=True) if child.is_running()]
    growth = peak - baseline
    if children:
        raise RuntimeError(f"Orphan child processes: {[(child.name(), child.pid) for child in children]}")
    if growth > 64 * 1024 * 1024:
        raise RuntimeError(f"Memory grew by {growth / 1024 / 1024:.1f} MiB")
    return {"cycles": cycles, "baseline_rss": baseline, "peak_rss": peak, "growth": growth}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=8 * 60 * 60)
    parser.add_argument("--ffmpeg-bin", required=True)
    parser.add_argument("--live-radio", action="store_true")
    arguments = parser.parse_args()
    print(run(arguments.seconds, arguments.ffmpeg_bin, arguments.live_radio))


if __name__ == "__main__":
    main()
