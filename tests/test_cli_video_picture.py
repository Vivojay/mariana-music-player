import functools
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mariana.video_window import Clock, Decoder, PictureBudget, _input_protocols, _size


class VideoClockTests(unittest.TestCase):
    def test_pause_seek_and_delayed_heartbeat(self):
        clock = Clock.read(dict(state="playing", position=6, rate=1.5, sampled_at=100), 100.1)
        self.assertAlmostEqual(clock.at(100.2), 6.3)
        self.assertAlmostEqual(clock.at(103), 6.6)
        pause = Clock.read(dict(state="paused", position=6.3, sampled_at=100.2), 100.2)
        self.assertFalse(pause.jumped(clock))
        self.assertEqual(pause.at(300), 6.3)
        seek = Clock.read(dict(state="paused", position=1.5, sampled_at=300), 300)
        self.assertTrue(seek.jumped(pause))
        with self.assertRaises(ValueError):
            Clock.read(dict(state="paused", position=math.inf), 100)

    def test_persistent_lag_reduces_frame_size_while_transient_lag_recovers(self):
        budget = PictureBudget()
        self.assertFalse(budget.should_downsize(.6, 0))
        self.assertFalse(budget.should_downsize(.03, .7))
        self.assertFalse(budget.should_downsize(.6, 3))
        self.assertTrue(budget.should_downsize(.8, 4.5))
        self.assertEqual(budget.limits(), (640, 360))
        self.assertEqual(_size(10000, 5000, (2560, 1440)), (2560, 1280))

    def test_source_shape_and_working_size(self):
        url = "http://127.0.0.1:8484/" + "a_B-" * 8 + "/media"
        self.assertEqual(_input_protocols(url), "http,tcp")
        for source in (url + "?x", url.replace("127.0.0.1", "example.org"),
                       url.replace("8484", "65536"), "https://example.org/track", "pipe:0"):
            with self.assertRaises(ValueError):
                _input_protocols(source)
        self.assertEqual(_size(1920, 1080), (1280, 720))
        self.assertEqual(_size(801, 453), (800, 452))


@unittest.skipUnless(shutil.which("ffmpeg"), "Needs an FFmpeg executable")
class PictureDecoderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.video = self.directory / "Two scenes ü.mp4"
        self.ffmpeg = shutil.which("ffmpeg")
        subprocess.run([self.ffmpeg, "-nostdin", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=red:s=64x48:r=25:d=1",
                        "-f", "lavfi", "-i", "color=c=blue:s=64x48:r=25:d=1",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-threads", "1",
                        "-c:v", "mpeg4", "-movflags", "+faststart", str(self.video)], check=True)

    def frame(self, decoder, position):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            packet = decoder.advance(position)
            if packet is not None and abs(packet[0] - position) < .03:
                return packet[1]
            self.assertFalse(decoder.error, "FFmpeg rejected the fixture")
            time.sleep(.01)
        self.fail("No synchronized frame")

    def exercise(self, source):
        decoder = Decoder(self.ffmpeg, source, .16, (64, 48))
        try:
            self.assertGreater(self.frame(decoder, .16)[0], 220)
            # A paused position holds indefinitely. Advance the same decoder
            # through the cut, then open a new decoder for a backward seek.
            time.sleep(.08)
            self.assertIsNone(decoder.advance(.16))
            self.assertGreater(self.frame(decoder, 1.32)[2], 220)
        finally:
            decoder.close()
            decoder.thread.join(3)
        self.assertFalse(decoder.thread.is_alive())
        decoder = Decoder(self.ffmpeg, source, .52, (64, 48))
        try:
            self.assertGreater(self.frame(decoder, .52)[0], 220)
        finally:
            decoder.close()
            decoder.thread.join(3)
        self.assertFalse(decoder.thread.is_alive())

    @unittest.skipUnless(os.environ.get("DISPLAY") or os.environ.get("MARIANA_TEST_VIDEO_DISPLAY"),
                         "Needs a graphical desktop")
    def test_failed_picture_then_good_frame_and_eof_close(self):
        bad = self.directory / "broken.mp4"
        bad.write_bytes(b"not a video")
        child = subprocess.Popen([sys.executable, "-m", "mariana.video_window", "--ffmpeg", self.ffmpeg],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        events = queue.Queue()
        def read():
            for line in child.stdout:
                events.put(json.loads(line))
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        def send(path, media):
            child.stdin.write(json.dumps(dict(source=str(path), media_id=media, state="paused", position=.2)) + "\n")
            child.stdin.flush()
        def until(kind):
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                event = events.get(timeout=max(.01, deadline - time.monotonic()))
                if event["event"] == kind:
                    return event
            self.fail(f"Missing event {kind}")
        try:
            until("ready")
            send(bad, "first recording")
            self.assertFalse(until("error")["fatal"])
            send(self.video, "second recording")
            until("showing")
            child.stdin.close()
            until("closed")
            self.assertEqual(child.wait(timeout=3), 0)
        finally:
            child.kill()
            child.wait()
            reader.join(2)
            child.stdout.close()
            child.stdin.close()

    def test_clock_controls_local_frames(self):
        self.exercise(str(self.video))

    def test_clock_controls_loopback_picture(self):
        token = "b" * 32
        directory = self.directory / token
        directory.mkdir()
        self.video.rename(directory / "media")
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Handler, directory=self.directory))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.exercise(f"http://127.0.0.1:{server.server_port}/{token}/media")
        finally:
            server.shutdown()
            thread.join(3)
            server.server_close()
