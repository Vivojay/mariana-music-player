import hashlib
import io
import json
import platform
import subprocess
import zipfile
from pathlib import Path

import pytest

import mariana.tool_setup as tool_setup
import mariana.toolchain as toolchain
from mariana.paths import RuntimePaths
from mariana.tool_setup import MediaToolStatus, ToolSetupError
from mariana.toolchain import ToolchainError, ToolchainManager


def executable_name(name: str) -> str:
    return f"{name}.exe" if platform.system() == "Windows" else name


def make_executables(directory: Path, names: tuple[str, ...]) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in names:
        path = directory / executable_name(name)
        path.write_bytes(b"executable")
        result[name] = str(path.resolve())
    return result


def complete_status(root: Path) -> MediaToolStatus:
    executables = make_executables(root, tool_setup.ALL_TOOLS)
    return MediaToolStatus(executables, {name: f"{name} version" for name in tool_setup.ALL_TOOLS})


def test_executable_location_accepts_file_bin_directory_and_install_root(monkeypatch, tmp_path):
    monkeypatch.setattr(toolchain.platform, "system", lambda: "Windows")
    install = tmp_path / "ffmpeg-release"
    binary = install / "bin" / "ffmpeg.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"exe")

    assert toolchain.executable_from_location("ffmpeg", str(binary)) == str(binary.resolve())
    assert toolchain.executable_from_location("ffmpeg", str(binary.parent)) == str(binary.resolve())
    assert toolchain.executable_from_location("ffmpeg", str(install)) == str(binary.resolve())
    assert toolchain.executable_from_location("ffprobe", str(binary)) is None
    (binary.parent / "ffprobe.exe").write_bytes(b"exe")
    assert toolchain.executable_from_location("ffprobe", str(binary)) == str(
        (binary.parent / "ffprobe.exe").resolve()
    )


def test_discovery_validates_every_candidate(monkeypatch):
    requested = []
    monkeypatch.setattr(
        tool_setup,
        "find_tool_executable",
        lambda name, location: requested.append((name, location)) or f"/{name}",
    )
    monkeypatch.setattr(
        tool_setup,
        "executable_version",
        lambda name, executable: None if name == "fpcalc" else f"{name} 1",
    )
    settings = {"media tools": {"ffmpeg bin": "/suite", "fpcalc bin": "/fingerprint", "rsgain bin": "/gain"}}
    status = tool_setup.discover_media_tools(settings)

    assert status.executables["fpcalc"] is None
    assert status.missing_required == ()
    assert status.missing_optional == ("fpcalc",)
    assert requested == [
        ("ffmpeg", "/suite"),
        ("ffprobe", "/suite"),
        ("ffplay", "/suite"),
        ("fpcalc", "/fingerprint"),
        ("rsgain", "/gain"),
    ]


def test_executable_version_handles_absence_errors_stderr_and_ansi(monkeypatch):
    assert tool_setup.executable_version("ffmpeg", None) is None
    monkeypatch.setattr(
        tool_setup.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("tool", 1)),
    )
    assert tool_setup.executable_version("ffmpeg", "tool") is None
    monkeypatch.setattr(
        tool_setup.subprocess,
        "run",
        lambda *_args, **_kwargs: type("Result", (), {"stdout": "", "stderr": "\x1b[32mtool 1.0\x1b[0m\n"})(),
    )
    assert tool_setup.executable_version("ffmpeg", "tool") == "tool 1.0"
    assert tool_setup.executable_version("unknown", "tool") is None


def test_default_setup_choice_runs_verified_auto_install(monkeypatch, tmp_path):
    missing = MediaToolStatus(dict.fromkeys(tool_setup.ALL_TOOLS), dict.fromkeys(tool_setup.ALL_TOOLS))
    complete = complete_status(tmp_path / "bin")
    statuses = iter((missing, complete))
    saved = []

    class Manager:
        def install_recommended(self, *, progress):
            progress("download")
            return tmp_path / "tools"

    monkeypatch.setattr(tool_setup, "discover_media_tools", lambda _settings: next(statuses))
    monkeypatch.setattr(tool_setup, "persist_media_tools", lambda status, *_args, **_kwargs: saved.append(status))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)

    result = tool_setup.setup_media_tools(
        {"media tools": {}},
        paths=RuntimePaths(tmp_path, tmp_path / "data"),
        manager=Manager(),
    )
    assert result.complete
    assert saved == [complete]


def test_complete_setup_persists_without_prompt(monkeypatch, tmp_path):
    complete = complete_status(tmp_path / "bin")
    saved = []
    monkeypatch.setattr(tool_setup, "discover_media_tools", lambda _settings: complete)
    monkeypatch.setattr(tool_setup, "persist_media_tools", lambda status, *_args, **_kwargs: saved.append(status))
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("must not prompt"))
    assert tool_setup.setup_media_tools(
        {"media tools": {}}, paths=RuntimePaths(tmp_path, tmp_path / "data")
    ) == complete
    assert saved == [complete]


def test_manual_setup_accepts_ffmpeg_executable_and_tool_directories(monkeypatch, tmp_path):
    suite = make_executables(tmp_path / "ffmpeg" / "bin", tool_setup.FFMPEG_TOOLS)
    fpcalc = make_executables(tmp_path / "chromaprint", ("fpcalc",))["fpcalc"]
    rsgain = make_executables(tmp_path / "rsgain", ("rsgain",))["rsgain"]
    answers = iter((suite["ffmpeg"], str(Path(fpcalc).parent), str(Path(rsgain).parent)))
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(tool_setup, "executable_version", lambda name, executable: f"{name} ok" if executable else None)

    settings = tool_setup._manual_settings({"media tools": {}})
    assert settings["media tools"] == {
        "ffmpeg bin": str(Path(suite["ffmpeg"]).parent),
        "fpcalc bin": str(Path(fpcalc).parent),
        "rsgain bin": str(Path(rsgain).parent),
    }


def test_manual_setup_reprompts_each_invalid_location(monkeypatch, tmp_path):
    suite = make_executables(tmp_path / "suite", tool_setup.FFMPEG_TOOLS)
    fpcalc = make_executables(tmp_path / "fpcalc", ("fpcalc",))["fpcalc"]
    rsgain = make_executables(tmp_path / "rsgain", ("rsgain",))["rsgain"]
    answers = iter(
        ("missing", suite["ffmpeg"], "missing", fpcalc, "missing", rsgain)
    )
    messages = []
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("builtins.print", lambda message: messages.append(message))
    monkeypatch.setattr(tool_setup, "executable_version", lambda name, executable: name if executable else None)
    result = tool_setup._manual_settings({})
    assert result["media tools"]["rsgain bin"] == str(Path(rsgain).parent)
    assert len(messages) == 3


def test_limited_setup_is_allowed_only_when_ffmpeg_suite_is_ready(monkeypatch, tmp_path):
    suite = make_executables(tmp_path / "bin", tool_setup.FFMPEG_TOOLS)
    executables = {**suite, "fpcalc": None, "rsgain": None}
    status = MediaToolStatus(executables, {name: "ok" if executables[name] else None for name in tool_setup.ALL_TOOLS})
    saved = []
    monkeypatch.setattr(tool_setup, "discover_media_tools", lambda _settings: status)
    monkeypatch.setattr(tool_setup, "persist_media_tools", lambda value, *_args, **_kwargs: saved.append(value))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "3")
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)

    assert tool_setup.setup_media_tools({"media tools": {}}, paths=RuntimePaths(tmp_path, tmp_path / "data")) == status
    assert saved == [status]


def test_invalid_choice_then_manual_validation_failure(monkeypatch, tmp_path):
    missing = MediaToolStatus(dict.fromkeys(tool_setup.ALL_TOOLS), dict.fromkeys(tool_setup.ALL_TOOLS))
    incomplete = MediaToolStatus(
        {**dict.fromkeys(tool_setup.ALL_TOOLS), "ffmpeg": "ffmpeg"},
        {**dict.fromkeys(tool_setup.ALL_TOOLS), "ffmpeg": "version"},
    )
    statuses = iter((missing, incomplete))
    answers = iter(("invalid", "2"))
    monkeypatch.setattr(tool_setup, "discover_media_tools", lambda _settings: next(statuses))
    monkeypatch.setattr(tool_setup, "_manual_settings", lambda settings: settings)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)
    with pytest.raises(ToolSetupError, match="failed validation"):
        tool_setup.setup_media_tools(
            {"media tools": {}}, paths=RuntimePaths(tmp_path, tmp_path / "data")
        )


def test_persisted_paths_are_normalized_and_written_atomically(tmp_path):
    resources = tmp_path / "resources"
    data = tmp_path / "data"
    paths = RuntimePaths(resources, data)
    status = complete_status(tmp_path / "programs")
    settings = {"media tools": {}, "unrelated": {"keep": True}}

    result = tool_setup.persist_media_tools(status, settings, paths=paths)
    loaded = tool_setup.YAML(typ="safe").load(paths.settings.read_text(encoding="utf-8"))
    assert result["unrelated"] == {"keep": True}
    assert loaded["media tools"]["ffmpeg bin"] == str(Path(status.executables["ffmpeg"]).parent)
    assert not list(paths.settings.parent.glob("*.tmp"))


def test_persist_preserves_missing_optional_paths_and_uses_default_services(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "resources", tmp_path / "data")
    settings = {"media tools": {"fpcalc bin": "keep-fpcalc", "rsgain bin": "keep-rsgain"}}
    status = MediaToolStatus(
        {"ffmpeg": "C:/suite/ffmpeg.exe", "fpcalc": None, "rsgain": None},
        {},
    )
    monkeypatch.setattr(tool_setup, "runtime_paths", lambda: paths)
    monkeypatch.setattr(tool_setup, "load_user_settings", lambda: settings)
    result = tool_setup.persist_media_tools(status)
    assert result["media tools"]["fpcalc bin"] == "keep-fpcalc"
    assert result["media tools"]["rsgain bin"] == "keep-rsgain"


class Response:
    def __init__(self, data: bytes):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def raise_for_status(self):
        return None

    def iter_content(self, _size):
        yield self.data


class Session:
    def __init__(self, archives: dict[str, bytes]):
        self.archives = archives

    def get(self, url, **_kwargs):
        return Response(self.archives[url])


def zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


def test_recommended_installer_falls_back_to_pinned_official_archives(monkeypatch, tmp_path):
    monkeypatch.setattr(toolchain.platform, "system", lambda: "Windows")
    resources = tmp_path / "resources"
    (resources / "tools").mkdir(parents=True)
    manifest = resources / "tools" / "manifest.json"
    manifest.write_text('{"schema":1,"toolchain":"test","artifacts":{}}', encoding="utf-8")
    archives = {
        "https://www.gyan.dev/ffmpeg/builds/packages/test.zip": zip_bytes(
            {f"suite/bin/{name}.exe": b"exe" for name in tool_setup.FFMPEG_TOOLS}
        ),
        "https://github.com/acoustid/chromaprint/releases/download/v1/test.zip": zip_bytes(
            {"fpcalc.exe": b"exe"}
        ),
        "https://github.com/complexlogic/rsgain/releases/download/v1/test.zip": zip_bytes(
            {"rsgain.exe": b"exe"}
        ),
    }
    sources = []
    for name, (url, data, names) in {
        "ffmpeg": (next(iter(archives)), archives[next(iter(archives))], list(tool_setup.FFMPEG_TOOLS)),
        "fpcalc": (list(archives)[1], archives[list(archives)[1]], ["fpcalc"]),
        "rsgain": (list(archives)[2], archives[list(archives)[2]], ["rsgain"]),
    }.items():
        sources.append(
            {
                "name": name,
                "url": url,
                "sha256": hashlib.sha256(data).hexdigest(),
                "archive": "zip",
                "executables": names,
            }
        )
    bootstrap = resources / "tools" / "bootstrap-manifest.json"
    bootstrap.write_text(
        json.dumps({"schema": 1, "bundle": "test-bundle", "platforms": {"win32-x64": sources}}),
        encoding="utf-8",
    )
    manager = ToolchainManager(
        RuntimePaths(resources, tmp_path / "data"),
        manifest_path=manifest,
        bootstrap_manifest_path=bootstrap,
        session=Session(archives),
    )

    root = manager.install_recommended("win32-x64")
    assert all(Path(manager.resolve(name)).is_file() for name in tool_setup.ALL_TOOLS)
    assert manager.install_recommended("win32-x64") == root


def test_recommended_installer_prefers_published_bundle(monkeypatch, tmp_path):
    resources = tmp_path / "resources"
    (resources / "tools").mkdir(parents=True)
    manifest = resources / "tools" / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "toolchain": "published",
                "artifacts": {
                    "win32-x64": {
                        "url": "https://github.com/Vivojay/mariana-music-player/releases/download/t/tools.zip",
                        "sha256": "0" * 64,
                        "archive": "zip",
                        "executables": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    manager = ToolchainManager(RuntimePaths(resources, tmp_path / "data"), manifest_path=manifest)
    monkeypatch.setattr(manager, "install", lambda key: tmp_path / key)
    assert manager.install_recommended("win32-x64") == tmp_path / "win32-x64"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"schema": 2, "platforms": {}}, "schema"),
        ({"schema": 1, "platforms": {"win32-x64": []}}, "not available"),
        (
            {
                "schema": 1,
                "platforms": {
                    "win32-x64": [
                        {
                            "name": "bad",
                            "url": "https://example.test/tool.zip",
                            "sha256": "0" * 64,
                            "archive": "zip",
                            "executables": ["tool"],
                        }
                    ]
                },
            },
            "Untrusted",
        ),
    ],
)
def test_bootstrap_manifest_fails_closed(tmp_path, payload, message):
    manifest = tmp_path / "bootstrap.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manager = ToolchainManager(
        RuntimePaths(tmp_path, tmp_path / "data"),
        bootstrap_manifest_path=manifest,
    )
    with pytest.raises(ToolchainError, match=message):
        manager.bootstrap_artifacts("win32-x64")


def test_noninteractive_setup_never_downloads_or_prompts(monkeypatch, tmp_path):
    missing = MediaToolStatus(dict.fromkeys(tool_setup.ALL_TOOLS), dict.fromkeys(tool_setup.ALL_TOOLS))
    monkeypatch.setattr(tool_setup, "discover_media_tools", lambda _settings: missing)
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("must not prompt"))
    assert tool_setup.setup_media_tools(
        {"media tools": {}}, paths=RuntimePaths(tmp_path, tmp_path / "data"), interactive=False
    ) == missing


def test_post_install_validation_failure_and_default_manager(monkeypatch, tmp_path):
    missing = MediaToolStatus(dict.fromkeys(tool_setup.ALL_TOOLS), dict.fromkeys(tool_setup.ALL_TOOLS))
    monkeypatch.setattr(tool_setup, "discover_media_tools", lambda _settings: missing)
    installed = []

    class Manager:
        def __init__(self, paths):
            assert paths.data == tmp_path / "data"

        def install_recommended(self, **_kwargs):
            installed.append(True)

    monkeypatch.setattr(tool_setup, "ToolchainManager", Manager)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)
    with pytest.raises(ToolSetupError, match="failed validation"):
        tool_setup.setup_media_tools(
            {"media tools": {}}, paths=RuntimePaths(tmp_path, tmp_path / "data")
        )
    assert installed == [True]


def test_failed_auto_install_has_actionable_recovery(monkeypatch, tmp_path):
    missing = MediaToolStatus(dict.fromkeys(tool_setup.ALL_TOOLS), dict.fromkeys(tool_setup.ALL_TOOLS))

    class Manager:
        def install_recommended(self, **_kwargs):
            raise ToolchainError("offline")

    monkeypatch.setattr(tool_setup, "discover_media_tools", lambda _settings: missing)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")
    monkeypatch.setattr("builtins.print", lambda *_args, **_kwargs: None)
    with pytest.raises(ToolSetupError, match=r"Resume setup.*manual paths"):
        tool_setup.setup_media_tools(
            {"media tools": {}},
            paths=RuntimePaths(tmp_path, tmp_path / "data"),
            manager=Manager(),
        )


def test_tool_setup_main_reports_success_limited_mode_and_failure(monkeypatch, capsys):
    complete = MediaToolStatus(
        {name: f"/{name}" for name in tool_setup.ALL_TOOLS},
        {name: name for name in tool_setup.ALL_TOOLS},
    )
    monkeypatch.setattr(tool_setup, "setup_media_tools", lambda: complete)
    assert tool_setup.main() == 0
    assert "Media tool check" in capsys.readouterr().out

    limited = MediaToolStatus(
        {**dict.fromkeys(tool_setup.ALL_TOOLS), "fpcalc": "/fpcalc"},
        dict.fromkeys(tool_setup.ALL_TOOLS),
    )
    monkeypatch.setattr(tool_setup, "setup_media_tools", lambda: limited)
    assert tool_setup.main() == 1

    monkeypatch.setattr(
        tool_setup,
        "setup_media_tools",
        lambda: (_ for _ in ()).throw(ToolSetupError("broken")),
    )
    assert tool_setup.main() == 1
    assert "setup failed" in capsys.readouterr().out
