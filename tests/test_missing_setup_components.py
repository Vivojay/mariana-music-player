import hashlib
import io
import json
import tempfile
import unittest
import zipfile

import requests
from pathlib import Path
from unittest.mock import Mock, patch

import first_boot_setup
from mariana.paths import RuntimePaths
from mariana.setup import SetupStateStore
from mariana.tool_setup import ALL_TOOLS, MediaToolStatus, setup_media_tools
from mariana.toolchain import ToolchainError, ToolchainManager


class MissingComponentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = RuntimePaths(self.root, self.root / "data")
        self.url = "https://github.com/complexlogic/rsgain/releases/download/test/rsgain.zip"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("bin/rsgain", "example")
            archive.writestr("bin/rsgain.exe", "example")
            archive.writestr("bin/library.dll", "dependency")
        self.payload = buffer.getvalue()
        pin = hashlib.sha256(self.payload).hexdigest()
        specs = [{"name": tool, "url": self.url if tool == "rsgain" else
                  "https://www.gyan.dev/ffmpeg/builds/packages/unavailable.zip",
                  "archive": "zip", "executables": [tool], "sha256": pin} for tool in ("ffmpeg", "rsgain")]
        manifest = self.root / "bootstrap.json"
        manifest.write_text(json.dumps({"schema": 1, "platforms": {"win32-x64": specs}}))
        self.session = Mock()
        self.manager = ToolchainManager(self.paths, bootstrap_manifest_path=manifest, session=self.session)
        platform = patch("mariana.toolchain.platform_key", return_value="win32-x64")
        platform.start()
        self.addCleanup(platform.stop)

    def response(self, payload):
        from unittest.mock import MagicMock
        context = MagicMock()
        response = context.__enter__.return_value
        response.headers = {}
        response.iter_content.return_value = [payload]
        self.session.get.return_value = context

    def test_first_run_requests_only_rsgain_and_reuses_verified_cache(self):
        self.response(self.payload)
        initial = {name: None if name == "rsgain" else str(self.root / name) for name in ALL_TOOLS}
        settings = {"media tools": {"ffmpeg bin": "existing-ffmpeg", "javascript bin": "existing-deno"}}
        def discover(config):
            paths = initial.copy()
            if folder := config["media tools"].get("rsgain bin"):
                paths["rsgain"] = str(Path(folder) / "rsgain")
                self.assertTrue((Path(folder) / "library.dll").is_file())
            return MediaToolStatus(paths, {})
        with patch("mariana.tool_setup.discover_media_tools", side_effect=discover), \
             patch("mariana.tool_setup.find_javascript_runtime", return_value=("deno", "existing-deno")), \
             patch("mariana.tool_setup.persist_media_tools") as save, patch("builtins.input", return_value="1"):
            status = setup_media_tools(settings, paths=self.paths, manager=self.manager)
        self.assertTrue(status.complete)
        self.assertEqual(save.call_args.args[1]["media tools"]["ffmpeg bin"], "existing-ffmpeg")
        self.manager.install_missing({"rsgain"})
        self.session.get.assert_called_once_with(self.url, stream=True, timeout=(10, 120))

    def test_partial_download_rejects_checksum_mismatch_before_publishing(self):
        self.response(b"bad archive")
        with self.assertRaisesRegex(ToolchainError, "SHA-256"):
            self.manager.install_missing({"rsgain"})
        self.assertFalse(any((self.paths.tools / "components" / "win32-x64").iterdir()))

    def test_failed_download_reopens_menu_and_allows_optional_skip(self):
        self.response(b"")
        self.session.get.return_value.__enter__.return_value.raise_for_status.side_effect = requests.HTTPError("404 Not Found")
        entries = {name: None if name == "rsgain" else name for name in ALL_TOOLS}
        status = MediaToolStatus(entries, {})
        store = SetupStateStore(self.paths)
        store.reset()
        workflow = iter(["1", "yes", "3", "no", "no", "yes"])
        def media_tools(*, paths):
            return setup_media_tools({"media tools": {}}, paths=paths, manager=self.manager)
        with patch.object(first_boot_setup, "runtime_paths", return_value=self.paths), \
             patch.object(first_boot_setup, "setup_media_tools", side_effect=media_tools), \
             patch("mariana.tool_setup.discover_media_tools", return_value=status), \
             patch("mariana.tool_setup.find_javascript_runtime", return_value=("deno", "deno")), \
             patch("mariana.tool_setup.persist_media_tools") as save, \
             patch("builtins.input", side_effect=lambda _: next(workflow)):
            self.assertFalse(first_boot_setup.fbs({"ver": {"maj": 0, "min": 7, "rel": 0}}, store))
        save.assert_called_once()
        self.assertEqual(store.load().status, "complete")
