import hashlib
import io
import json
import os
import tarfile
import zipfile
from pathlib import Path

import pytest
import requests

from mariana.paths import RuntimePaths
from mariana.toolchain import ToolArtifact, ToolchainError, ToolchainManager, platform_key


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


def test_toolchain_activation_retries_transient_windows_lock(tmp_path, monkeypatch):
    archive = package_bytes({"bin/ffmpeg.exe": b"ffmpeg", "bin/fpcalc.exe": b"fpcalc"})
    tools = manager(tmp_path, archive)
    real_replace = os.replace
    attempts = 0

    def locked_twice(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise PermissionError("scanner temporarily locked the directory")
        return real_replace(source, destination)

    monkeypatch.setattr("mariana.toolchain.os.replace", locked_twice)
    root = tools.install("win32-x64")
    assert attempts >= 3
    assert (root / "bin" / "ffmpeg.exe").is_file()


def test_toolchain_activation_rolls_back_previous_install(tmp_path, monkeypatch):
    target = tmp_path / "tool"
    replacement = tmp_path / ".tool.new"
    target.mkdir()
    replacement.mkdir()
    (target / "version").write_text("old")
    (replacement / "version").write_text("new")
    real_replace = os.replace

    def fail_new_activation(source, destination):
        if Path(source) == replacement:
            raise PermissionError("persistent lock")
        return real_replace(source, destination)

    monkeypatch.setattr("mariana.toolchain.os.replace", fail_new_activation)
    monkeypatch.setattr("mariana.toolchain.time.sleep", lambda _delay: None)
    with pytest.raises(ToolchainError, match="atomically activate"):
        ToolchainManager._replace_install(replacement, target)
    assert (target / "version").read_text() == "old"
    assert not target.with_name(".tool.old").exists()


@pytest.mark.parametrize(
    ("system", "machine", "expected"),
    [
        ("Windows", "AMD64", "win32-x64"),
        ("Darwin", "arm64", "darwin-arm64"),
        ("Linux", "aarch64", "linux-arm64"),
    ],
)
def test_platform_key_supported_hosts(monkeypatch, system, machine, expected):
    monkeypatch.setattr("mariana.toolchain.platform.system", lambda: system)
    monkeypatch.setattr("mariana.toolchain.platform.machine", lambda: machine)
    assert platform_key() == expected


@pytest.mark.parametrize(("system", "machine"), [("Plan9", "x86_64"), ("Linux", "riscv64")])
def test_platform_key_rejects_unsupported_hosts(monkeypatch, system, machine):
    monkeypatch.setattr("mariana.toolchain.platform.system", lambda: system)
    monkeypatch.setattr("mariana.toolchain.platform.machine", lambda: machine)
    with pytest.raises(ToolchainError, match="No managed toolchain"):
        platform_key()


@pytest.mark.parametrize("value", ["not json", '{"schema":2,"artifacts":{}}', '{"schema":1,"artifacts":[]}'])
def test_manifest_validation_is_typed(tmp_path, value):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(value, encoding="utf-8")
    tools = ToolchainManager(RuntimePaths(tmp_path, tmp_path / "data"), manifest_path=manifest)
    with pytest.raises(ToolchainError, match=r"manifest|schema"):
        tools.manifest()


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"url": "x"}, "Incomplete"),
        (
            {
                "url": "https://github.com/Vivojay/mariana-music-player/releases/download/x/tools.zip",
                "sha256": "z" * 64,
                "archive": "zip",
                "executables": {},
            },
            "SHA-256",
        ),
        (
            {"url": "https://example.test/tools.zip", "sha256": "0" * 64, "archive": "zip", "executables": {}},
            "GitHub Releases",
        ),
    ],
)
def test_artifact_entries_are_strict(tmp_path, entry, message):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema": 1, "artifacts": {"win32-x64": entry}}), encoding="utf-8")
    tools = ToolchainManager(RuntimePaths(tmp_path, tmp_path / "data"), manifest_path=manifest)
    with pytest.raises(ToolchainError, match=message):
        tools.artifact("win32-x64")


def test_existing_install_is_reused_and_resolve_is_defensive(tmp_path):
    archive = package_bytes({"bin/ffmpeg.exe": b"ffmpeg", "bin/fpcalc.exe": b"fpcalc"})
    tools = manager(tmp_path, archive)
    root = tools.paths.tools / "test-1" / "win32-x64"
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (root / "bin" / "fpcalc.exe").write_bytes(b"fpcalc")
    assert tools.install("win32-x64") == root
    assert Path(tools.resolve("ffmpeg")).is_file()
    assert tools.resolve("missing") is None
    (tools.paths.tools / "current.json").write_text("bad json", encoding="utf-8")
    assert tools.resolve("ffmpeg") is None
    (tools.paths.tools / "current.json").unlink()
    assert tools.resolve("ffmpeg") is None


def test_replace_path_exhausts_retries(monkeypatch, tmp_path):
    monkeypatch.setattr("mariana.toolchain.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("locked")))
    monkeypatch.setattr("mariana.toolchain.time.sleep", lambda _delay: None)
    with pytest.raises(OSError, match="locked"):
        ToolchainManager._replace_path(tmp_path / "a", tmp_path / "b", attempts=2)


def test_download_wraps_transport_failure(tmp_path):
    class BrokenSession:
        def get(self, *_args, **_kwargs):
            raise requests.Timeout("offline")

    tools = ToolchainManager(RuntimePaths(tmp_path, tmp_path / "data"), session=BrokenSession())
    artifact = ToolArtifact("https://example.test/tool.zip", "0" * 64, "zip", {})
    with pytest.raises(ToolchainError, match="download failed"):
        tools._download(artifact, tmp_path / "tool.zip")


def test_tar_extraction_rejects_links_and_unknown_kinds(tmp_path):
    safe = tmp_path / "safe.tgz"
    payload = tmp_path / "tool"
    payload.write_bytes(b"tool")
    with tarfile.open(safe, "w:gz") as package:
        package.add(payload, arcname="bin/tool")
    destination = tmp_path / "safe"
    destination.mkdir()
    ToolchainManager._extract(safe, destination, "tgz")
    assert (destination / "bin" / "tool").is_file()

    unsafe = tmp_path / "unsafe.tgz"
    with tarfile.open(unsafe, "w:gz") as package:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "../outside"
        package.addfile(info)
    destination = tmp_path / "unsafe"
    destination.mkdir()
    with pytest.raises(ToolchainError, match="Unsafe"):
        ToolchainManager._extract(unsafe, destination, "tar.gz")
    with pytest.raises(ToolchainError, match="Unsupported"):
        ToolchainManager._extract(safe, destination, "rar")
