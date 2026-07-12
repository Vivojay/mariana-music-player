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
from mariana.database import MarianaDatabase
from mariana.library import LibraryCatalog
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


def run(duration_seconds: float, ffmpeg_bin: str, live_radio: bool, library_files: int = 0) -> dict:
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
        def handler(*args, **kwargs):
            return QuietHandler(*args, directory=str(directory), **kwargs)

        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        controller = PlaybackController(
            ffmpeg_bin=ffmpeg_bin,
            ffprobe_bin=ffmpeg_bin,
            crossfade_seconds=0.1,
            output_factory=NullOutputStream,
        )
        scan_stop = threading.Event()
        scan_errors = []
        scan_thread = None
        database = None
        if library_files:
            library_root = directory / "library"
            library_root.mkdir()
            for index in range(max(0, library_files)):
                (library_root / f"track-{index:06d}.mp3").touch()
            library_file = directory / "lib.lib"
            library_file.write_text(str(library_root), encoding="utf-8")
            database = MarianaDatabase(directory / "soak-library.db")
            catalog = LibraryCatalog(database, library_file=library_file, supported_extensions=[".mp3"])

            def scan_library():
                try:
                    catalog.scan("changed")
                    while not scan_stop.wait(60):
                        catalog.scan("changed")
                except Exception as error:
                    scan_errors.append(error)

            scan_thread = threading.Thread(target=scan_library, name="mariana-soak-library", daemon=True)
            scan_thread.start()
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
            scan_stop.set()
            library_failure = None
            if scan_thread:
                scan_thread.join(timeout=30)
                if scan_thread.is_alive():
                    library_failure = "library scan did not stop within 30 seconds"
            if database:
                integrity = database.fetchone("PRAGMA integrity_check")[0]
                running_jobs = database.fetchone("SELECT COUNT(*) FROM library_jobs WHERE status='running'")[0]
                database.close()
                if integrity != "ok" or running_jobs or scan_errors:
                    library_failure = (
                        f"integrity={integrity}, running_jobs={running_jobs}, errors={scan_errors}"
                    )
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)
            if library_failure:
                raise RuntimeError(f"Library soak failed: {library_failure}")
    children = [child for child in process.children(recursive=True) if child.is_running()]
    growth = peak - baseline
    if children:
        raise RuntimeError(f"Orphan child processes: {[(child.name(), child.pid) for child in children]}")
    if growth > 64 * 1024 * 1024:
        raise RuntimeError(f"Memory grew by {growth / 1024 / 1024:.1f} MiB")
    return {
        "cycles": cycles,
        "library_files": library_files,
        "baseline_rss": baseline,
        "peak_rss": peak,
        "growth": growth,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=8 * 60 * 60)
    parser.add_argument("--ffmpeg-bin", required=True)
    parser.add_argument("--live-radio", action="store_true")
    parser.add_argument("--library-files", type=int, default=10_000)
    arguments = parser.parse_args()
    print(run(arguments.seconds, arguments.ffmpeg_bin, arguments.live_radio, arguments.library_files))


if __name__ == "__main__":
    main()
