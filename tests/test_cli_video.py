"""The standalone picture window follows only the current prepared visual resource."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mariana.cli_video import CliVideoError, CliVideoWindow, _picture_sample


class VideoHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cache = Path(self.tmp.name)
        self.handle = "e" * 32
        (self.cache / (self.handle + ".mp4")).touch()
        self.status = dict(state="ready", media_id="abc", handle=self.handle, revision=2,
                           position_seconds=104.15, window_start_seconds=101.0, window_end_seconds=119,
                           playing=False, captions={"enabled": True, "text": "verse"})
        self.allowed = True
        self.closed = threading.Event()
        self.host = CliVideoWindow(video_status=lambda: dict(self.status), cache=self.cache,
                                   ffmpeg=lambda: "ffmpeg", allowed=lambda: self.allowed,
                                   on_close=self.closed.set)
        self.addCleanup(self.host.close)
        self.frames = self.cache / "frames"
        self.launched = []

    def start_child(self, body):
        popen = subprocess.Popen
        def launch(args, **kwargs):
            self.assertIn("--ffmpeg", args)
            child = popen([sys.executable, "-u", "-c", body, os.fspath(self.frames)], **kwargs)
            self.launched.append(child)
            return child
        patched = patch("mariana.cli_video.subprocess.Popen", side_effect=launch)
        patched.start()
        self.addCleanup(patched.stop)

    def helper(self):
        self.start_child("""
import json, sys
from pathlib import Path
print(json.dumps({'event':'ready'}),flush=True)
with Path(sys.argv[1]).open('a', encoding='utf-8') as out:
    for line in sys.stdin:
        print(line.strip(), file=out, flush=True)
        if json.loads(line).get('caption') == 'CLOSE':
            print(json.dumps({'event':'closed'}),flush=True)
            break
""")

    def wait_frame(self, test):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if self.frames.exists():
                lines = self.frames.read_text().splitlines()
                if lines:
                    try:
                        frame = json.loads(lines[-1])
                    except json.JSONDecodeError:
                        continue
                    if test(frame):
                        return frame
            time.sleep(.02)
        self.fail("No matching frame was read by the child")

    def test_worker_reuses_child_stamps_time_and_scrubs_stale_frame(self):
        self.helper()
        self.host.open()
        self.host.open()
        self.assertEqual(len(self.launched), 1)
        frame = self.wait_frame(lambda s: s["state"] == "paused")
        self.assertAlmostEqual(frame["position"], 3.15)
        self.assertEqual(frame["source"], str(self.cache / (self.handle + ".mp4")))
        self.assertEqual(frame["caption"], "verse")
        self.assertLess(abs(frame["sampled_at"] - time.monotonic()), 2)
        self.status.update(position_seconds=120, playing=True)
        hidden = self.wait_frame(lambda s: s["source"] is None)
        self.assertEqual(hidden["caption"], "")
        self.host.close()
        self.assertFalse(self.host.is_open)
        self.assertIsNotNone(self.launched[0].poll())
        self.assertFalse(self.closed.is_set())

    def test_unsafe_sources_never_leave_parent_or_surface_in_diagnostics(self):
        proxy = "http://127.0.0.1:50407/" + "u_"*16 + "/media"
        self.status.update(transport="source", resource=proxy)
        self.assertEqual(_picture_sample(self.status, self.cache, 0)["source"], proxy)
        for url in (proxy + "?token=secret", proxy.replace("127.0.0.1", "elsewhere.com"),
                    proxy.replace("50407", "65536"), "file:///secret",
                    proxy.replace("50407/", "50407@evil.invalid/")):
            sample = _picture_sample({**self.status, "resource": url}, self.cache, 0)
            self.assertIsNone(sample["source"])
            self.assertNotIn(url, json.dumps(sample))
        self.status.pop("transport")
        self.assertIsNone(_picture_sample({**self.status, "handle": "../secret"}, self.cache, 0)["source"])

    def test_policy_revocation_and_window_manager_close_release_audio_independently(self):
        self.helper()
        self.host.open()
        self.allowed = False
        self.assertTrue(self.closed.wait(4))
        self.assertFalse(self.host.is_open)
        self.assertIn("policy", self.host.status()["error"])
        self.allowed = True
        self.closed.clear()
        self.host.open()
        self.status["captions"] = {"enabled": True, "text": "CLOSE"}
        self.assertTrue(self.closed.wait(4))
        self.assertEqual(self.host.status(), {"state":"closed", "error": None})

    def test_headless_startup_error_is_a_cli_message(self):
        self.start_child("""import json; print(json.dumps({'event':'error','code':'display','fatal':True}))""")
        with self.assertRaisesRegex(CliVideoError, "graphical display"):
            self.host.open()
        self.assertTrue(self.closed.wait(4))
