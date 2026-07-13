"""Checksum-verified, atomically activated external toolchain management."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .paths import RuntimePaths, runtime_paths


class ToolchainError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ToolArtifact:
    url: str
    sha256: str
    archive: str
    executables: dict[str, str]


@dataclass(frozen=True, slots=True)
class BootstrapArtifact:
    name: str
    url: str
    sha256: str
    archive: str
    executables: tuple[str, ...]


BOOTSTRAP_HOSTS = (
    "https://www.gyan.dev/ffmpeg/builds/packages/",
    "https://github.com/acoustid/chromaprint/releases/download/",
    "https://github.com/complexlogic/rsgain/releases/download/",
    "https://github.com/denoland/deno/releases/download/",
)


def platform_key() -> str:
    system = {"Windows": "win32", "Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    machine = platform.machine().casefold()
    architecture = "arm64" if machine in {"arm64", "aarch64"} else "x64" if machine in {"amd64", "x86_64"} else machine
    if not system or architecture not in {"x64", "arm64"}:
        raise ToolchainError(f"No managed toolchain is supported for {platform.system()} {platform.machine()}")
    return f"{system}-{architecture}"


class ToolchainManager:
    def __init__(
        self,
        paths: RuntimePaths | None = None,
        *,
        manifest_path: Path | None = None,
        bootstrap_manifest_path: Path | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.paths = paths or runtime_paths()
        self.manifest_path = manifest_path or self.paths.resource("tools", "manifest.json")
        self.bootstrap_manifest_path = bootstrap_manifest_path or self.paths.resource(
            "tools", "bootstrap-manifest.json"
        )
        self.session = session or requests.Session()

    def manifest(self) -> dict[str, Any]:
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ToolchainError(f"Invalid toolchain manifest: {error}") from error
        if value.get("schema") != 1 or not isinstance(value.get("artifacts"), dict):
            raise ToolchainError("Unsupported toolchain manifest schema")
        return value

    def artifact(self, key: str | None = None) -> ToolArtifact:
        value = self.manifest()
        key = key or platform_key()
        raw = value["artifacts"].get(key)
        if not isinstance(raw, dict):
            raise ToolchainError(f"Managed tools have not been published for {key}")
        try:
            artifact = ToolArtifact(raw["url"], raw["sha256"].casefold(), raw["archive"], dict(raw["executables"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ToolchainError(f"Incomplete toolchain manifest entry for {key}") from error
        if len(artifact.sha256) != 64 or any(char not in "0123456789abcdef" for char in artifact.sha256):
            raise ToolchainError(f"Invalid SHA-256 for {key}")
        if not artifact.url.startswith("https://github.com/Vivojay/mariana-music-player/releases/download/"):
            raise ToolchainError("Managed tool downloads must come from Mariana GitHub Releases")
        return artifact

    def install(self, key: str | None = None) -> Path:
        manifest = self.manifest()
        key = key or platform_key()
        artifact = self.artifact(key)
        version = str(manifest["toolchain"])
        target = self.paths.tools / version / key
        if self._validate_install(target, artifact):
            self._activate(target, artifact)
            return target
        self.paths.tools.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="mariana-tools-", dir=self.paths.tools) as workspace_name:
            workspace = Path(workspace_name)
            archive = workspace / f"archive.{artifact.archive}"
            self._download(artifact, archive)
            extracted = workspace / "extracted"
            extracted.mkdir()
            self._extract(archive, extracted, artifact.archive)
            for relative in artifact.executables.values():
                candidate = extracted / relative
                if candidate.is_file() and os.name != "nt":
                    candidate.chmod(0o755)
            if not self._validate_install(extracted, artifact):
                raise ToolchainError("Downloaded tool archive is missing required executables")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_target = target.with_name(f".{target.name}.new")
            shutil.rmtree(temporary_target, ignore_errors=True)
            shutil.copytree(extracted, temporary_target)
            self._replace_install(temporary_target, target)
        self._activate(target, artifact)
        return target

    def bootstrap_manifest(self) -> dict[str, Any]:
        try:
            value = json.loads(self.bootstrap_manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ToolchainError(f"Invalid bootstrap manifest: {error}") from error
        if value.get("schema") != 1 or not isinstance(value.get("platforms"), dict):
            raise ToolchainError("Unsupported bootstrap manifest schema")
        return value

    def bootstrap_artifacts(self, key: str | None = None) -> tuple[BootstrapArtifact, ...]:
        key = key or platform_key()
        raw_artifacts = self.bootstrap_manifest()["platforms"].get(key)
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise ToolchainError(
                f"Automatic tool download is not available for {key}; enter installed tool paths manually"
            )
        artifacts: list[BootstrapArtifact] = []
        for raw in raw_artifacts:
            try:
                artifact = BootstrapArtifact(
                    str(raw["name"]),
                    str(raw["url"]),
                    str(raw["sha256"]).casefold(),
                    str(raw["archive"]),
                    tuple(str(name) for name in raw["executables"]),
                )
            except (KeyError, TypeError, ValueError) as error:
                raise ToolchainError(f"Incomplete bootstrap manifest entry for {key}") from error
            if len(artifact.sha256) != 64 or any(char not in "0123456789abcdef" for char in artifact.sha256):
                raise ToolchainError(f"Invalid bootstrap SHA-256 for {artifact.name}")
            if not artifact.url.startswith(BOOTSTRAP_HOSTS):
                raise ToolchainError(f"Untrusted bootstrap download host for {artifact.name}")
            if not artifact.executables:
                raise ToolchainError(f"No executables declared for {artifact.name}")
            artifacts.append(artifact)
        return tuple(artifacts)

    def install_recommended(
        self,
        key: str | None = None,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        """Install the release bundle, or verified upstream archives when unpublished."""
        key = key or platform_key()
        manifest = self.manifest()
        if manifest["artifacts"].get(key):
            return self.install(key)
        return self.install_bootstrap(key, progress=progress)

    def install_bootstrap(
        self,
        key: str | None = None,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        key = key or platform_key()
        manifest = self.bootstrap_manifest()
        artifacts = self.bootstrap_artifacts(key)
        bundle = str(manifest["bundle"])
        target = self.paths.tools / bundle / key
        expected_names = tuple(name for artifact in artifacts for name in artifact.executables)
        existing = self._locate_executables(target, expected_names)
        if len(existing) == len(expected_names):
            tool_artifact = ToolArtifact("", "0" * 64, "zip", existing)
            self._activate(target, tool_artifact)
            return target

        self.paths.tools.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="mariana-tools-", dir=self.paths.tools) as workspace_name:
            workspace = Path(workspace_name)
            extracted = workspace / "extracted"
            extracted.mkdir()
            for index, source in enumerate(artifacts, start=1):
                if progress:
                    progress(f"Downloading {source.name} ({index}/{len(artifacts)})...")
                archive = workspace / f"source-{index}.{source.archive}"
                self._download(
                    ToolArtifact(source.url, source.sha256, source.archive, {}),
                    archive,
                    progress=progress,
                    label=source.name,
                )
                destination = extracted / f"source-{index}"
                destination.mkdir()
                self._extract(archive, destination, source.archive)
            executable_map = self._locate_executables(extracted, expected_names)
            missing = sorted(set(expected_names) - set(executable_map))
            if missing:
                raise ToolchainError(f"Verified tool archives did not contain: {', '.join(missing)}")
            for relative in executable_map.values():
                candidate = extracted / relative
                if os.name != "nt":
                    candidate.chmod(0o755)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary_target = target.with_name(f".{target.name}.new")
            shutil.rmtree(temporary_target, ignore_errors=True)
            shutil.copytree(extracted, temporary_target)
            self._replace_install(temporary_target, target)
        tool_artifact = ToolArtifact("", "0" * 64, "zip", executable_map)
        self._activate(target, tool_artifact)
        return target

    @staticmethod
    def _locate_executables(root: Path, names: tuple[str, ...]) -> dict[str, str]:
        if not root.is_dir():
            return {}
        result: dict[str, str] = {}
        for name in names:
            filename = f"{name}.exe" if platform.system() == "Windows" else name
            candidate = next(
                (path for path in root.rglob(filename) if path.is_file()),
                None,
            )
            if candidate is not None:
                result[name] = candidate.relative_to(root).as_posix()
        return result

    @staticmethod
    def _replace_path(source: Path, destination: Path, attempts: int = 6) -> None:
        last_error: OSError | None = None
        for attempt in range(attempts):
            try:
                os.replace(source, destination)
                return
            except OSError as error:
                last_error = error
                if attempt + 1 < attempts:
                    time.sleep(0.05 * (2**attempt))
        assert last_error is not None
        raise last_error

    @classmethod
    def _replace_install(cls, temporary_target: Path, target: Path) -> None:
        """Activate a verified directory, restoring the prior version on failure."""
        backup = target.with_name(f".{target.name}.old")
        shutil.rmtree(backup, ignore_errors=True)
        had_target = target.exists()
        try:
            if had_target:
                cls._replace_path(target, backup)
            cls._replace_path(temporary_target, target)
        except OSError as error:
            if had_target and backup.exists() and not target.exists():
                cls._replace_path(backup, target)
            shutil.rmtree(temporary_target, ignore_errors=True)
            raise ToolchainError(f"Could not atomically activate managed tools: {error}") from error
        else:
            shutil.rmtree(backup, ignore_errors=True)

    def resolve(self, name: str) -> str | None:
        state = self.paths.tools / "current.json"
        if not state.is_file():
            return None
        try:
            value = json.loads(state.read_text(encoding="utf-8"))
            relative = value["executables"][name]
            candidate = Path(value["root"]) / relative
            return str(candidate.resolve()) if candidate.is_file() else None
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def _download(
        self,
        artifact: ToolArtifact,
        destination: Path,
        *,
        progress: Callable[[str], None] | None = None,
        label: str = "managed tools",
    ) -> None:
        hasher = hashlib.sha256()
        try:
            with self.session.get(artifact.url, stream=True, timeout=(10, 120)) as response:
                response.raise_for_status()
                total = int(getattr(response, "headers", {}).get("content-length") or 0)
                received = 0
                last_reported = -1
                with destination.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            hasher.update(chunk)
                            output.write(chunk)
                            received += len(chunk)
                            if progress and total:
                                percent = min(100, int(received * 100 / total))
                                bucket = percent // 5
                                if bucket != last_reported:
                                    last_reported = bucket
                                    filled = min(20, percent // 5)
                                    progress(
                                        f"  {label}: [{'#' * filled}{'-' * (20 - filled)}] "
                                        f"{percent:>3}% ({received / 1_048_576:.1f}/"
                                        f"{total / 1_048_576:.1f} MiB)"
                                    )
        except requests.RequestException as error:
            raise ToolchainError(f"Managed tool download failed: {error}") from error
        if hasher.hexdigest() != artifact.sha256:
            destination.unlink(missing_ok=True)
            raise ToolchainError("Managed tool download did not match the expected SHA-256 checksum")

    @staticmethod
    def _extract(archive: Path, destination: Path, kind: str) -> None:
        destination = destination.resolve()
        if kind == "zip":
            with zipfile.ZipFile(archive) as package:
                for member in package.infolist():
                    if stat.S_ISLNK(member.external_attr >> 16) or not (
                        destination / member.filename
                    ).resolve().is_relative_to(destination):
                        raise ToolchainError("Unsafe path in managed tool archive")
                package.extractall(destination)
        elif kind in {"tar.gz", "tgz"}:
            with tarfile.open(archive, "r:gz") as package:
                for member in package.getmembers():
                    if member.issym() or member.islnk() or not (destination / member.name).resolve().is_relative_to(destination):
                        raise ToolchainError("Unsafe path in managed tool archive")
                package.extractall(destination, filter="data")
        else:
            raise ToolchainError(f"Unsupported managed tool archive: {kind}")

    @staticmethod
    def _validate_install(root: Path, artifact: ToolArtifact) -> bool:
        return root.is_dir() and all((root / relative).is_file() for relative in artifact.executables.values())

    def _activate(self, root: Path, artifact: ToolArtifact) -> None:
        state = self.paths.tools / "current.json"
        temporary = state.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"root": str(root.resolve()), "executables": artifact.executables}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, state)


def find_managed_executable(name: str) -> str | None:
    return ToolchainManager().resolve(name)


def executable_from_location(name: str, location: str | os.PathLike[str] | None) -> str | None:
    """Resolve an executable from either the executable itself or a nearby directory."""
    if not location:
        return None
    expanded = os.path.expandvars(os.path.expanduser(os.fspath(location).strip().strip('"')))
    candidate = Path(expanded)
    filename = f"{name}.exe" if platform.system() == "Windows" else name
    candidates: list[Path] = []
    if candidate.is_file():
        if candidate.name.casefold() == filename.casefold():
            candidates.append(candidate)
        candidates.append(candidate.parent / filename)
    elif candidate.is_dir():
        candidates.extend((candidate / filename, candidate / "bin" / filename))
        try:
            for child in candidate.iterdir():
                if child.is_dir():
                    candidates.extend((child / filename, child / "bin" / filename))
        except OSError:
            pass
    return next((str(path.resolve()) for path in candidates if path.is_file()), None)


def common_tool_locations(name: str) -> tuple[Path, ...]:
    filename = f"{name}.exe" if platform.system() == "Windows" else name
    if platform.system() != "Windows":
        return (*tuple(Path(root) / filename for root in ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")),
            Path.home() / ".local" / "bin" / filename,
        )
    home = Path.home()
    roots = (
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "ffmpeg" / "bin",
        Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local")) / "Programs" / "ffmpeg" / "bin",
        Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "chocolatey" / "bin",
        home / "scoop" / "apps" / "ffmpeg" / "current" / "bin",
        Path("C:/ffmpeg/bin"),
    )
    values = [root / filename for root in roots]
    for parent in (home / "Documents", home / "Downloads", home / "apps"):
        if parent.is_dir():
            values.extend(parent.glob(f"ffmpeg*/bin/{filename}"))
    return tuple(values)


def find_tool_executable(name: str, configured: str | None = None) -> str | None:
    if candidate := executable_from_location(name, configured):
        return candidate
    if candidate := find_managed_executable(name):
        return candidate
    if candidate := shutil.which(name):
        return str(Path(candidate).resolve())
    from .paths import runtime_paths

    legacy = executable_from_location(name, runtime_paths().resource(".tools"))
    if legacy:
        return legacy
    return next((str(path.resolve()) for path in common_tool_locations(name) if path.is_file()), None)


def find_javascript_runtime(configured: str | None = None) -> tuple[str, str] | None:
    """Find a yt-dlp JavaScript runtime without assuming one machine layout."""
    runtimes = (("deno", "deno"), ("node", "node"), ("quickjs", "qjs"))
    for runtime, executable in runtimes:
        if candidate := executable_from_location(executable, configured):
            return runtime, candidate
    for runtime, executable in runtimes:
        if candidate := find_managed_executable(executable) or shutil.which(executable):
            return runtime, candidate
    if platform.system() == "Windows":
        node_candidates = [Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "nodejs" / "node.exe"]
        node_candidates.extend(sorted((Path.home() / "apps").glob("node-*-win-x64/node.exe"), reverse=True))
        for candidate in node_candidates:
            if candidate.is_file():
                return "node", str(candidate.resolve())
    environment_location = os.environ.get("MARIANA_JAVASCRIPT_RUNTIME")
    for runtime, executable in runtimes:
        if candidate := executable_from_location(executable, environment_location):
            return runtime, candidate
    return None
