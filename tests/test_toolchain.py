import hashlib
import io
import json
from pathlib import Path
import zipfile

import pytest

from mariana.paths import RuntimePaths
from mariana.toolchain import ToolchainError, ToolchainManager


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self): return self
    def __exit__(self, *_args): return None
    def raise_for_status(self): return None
    def iter_content(self, _size): yield self.data


class Session:
    def __init__(self, data): self.data = data
    def get(self, *_args, **_kwargs): return Response(self.data)


def package_bytes(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as package:
        for name, value in files.items():
            package.writestr(name, value)
    return stream.getvalue()


def manager(tmp_path, archive, sha=None):
    resources, state = tmp_path / "resources", tmp_path / "state"
    (resources / "tools").mkdir(parents=True, exist_ok=True)
    value = {
        "schema": 1,
        "toolchain": "test-1",
        "artifacts": {
            "win32-x64": {
                "url": "https://github.com/Vivojay/mariana-music-player/releases/download/tools/test.zip",
                "sha256": sha or hashlib.sha256(archive).hexdigest(),
                "archive": "zip",
                "executables": {"ffmpeg": "bin/ffmpeg.exe", "fpcalc": "bin/fpcalc.exe"},
            }
        },
    }
    manifest = resources / "tools" / "manifest.json"
    manifest.write_text(json.dumps(value))
    return ToolchainManager(RuntimePaths(resources, state), manifest_path=manifest, session=Session(archive))


def test_verified_toolchain_is_installed_and_atomically_activated(tmp_path):
    archive = package_bytes({"bin/ffmpeg.exe": b"ffmpeg", "bin/fpcalc.exe": b"fpcalc"})
    tools = manager(tmp_path, archive)
    root = tools.install("win32-x64")
    assert (root / "bin" / "ffmpeg.exe").read_bytes() == b"ffmpeg"
    assert Path(tools.resolve("fpcalc")).read_bytes() == b"fpcalc"


def test_toolchain_rejects_checksum_mismatch_and_unsafe_archive(tmp_path):
    archive = package_bytes({"bin/ffmpeg.exe": b"bad", "bin/fpcalc.exe": b"bad"})
    with pytest.raises(ToolchainError, match="checksum"):
        manager(tmp_path, archive, "0" * 64).install("win32-x64")

    unsafe = package_bytes({"../outside": b"bad", "bin/ffmpeg.exe": b"x", "bin/fpcalc.exe": b"x"})
    with pytest.raises(ToolchainError, match="Unsafe"):
        manager(tmp_path, unsafe).install("win32-x64")


def test_unpublished_platform_is_reported(tmp_path):
    resources = tmp_path / "resources"
    (resources / "tools").mkdir(parents=True)
    manifest = resources / "tools" / "manifest.json"
    manifest.write_text('{"schema":1,"toolchain":"x","artifacts":{}}')
    tools = ToolchainManager(RuntimePaths(resources, tmp_path / "data"), manifest_path=manifest)
    with pytest.raises(ToolchainError, match="not been published"):
        tools.artifact("linux-x64")
