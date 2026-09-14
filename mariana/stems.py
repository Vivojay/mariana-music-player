"""Lazy local music-source separation, cache management, and safe stem export."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

from .models import MediaRef
from .output_targets import BoundOutputTarget, OutputTargetError, bind_output_target
from .playback import CREATE_NO_WINDOW, WindowsJob, find_executable

FOUR_STEMS = ("vocals", "drums", "bass", "other")
SIX_STEMS = (*FOUR_STEMS, "guitar", "piano")
MODELS = {"4": ("htdemucs", FOUR_STEMS), "6": ("htdemucs_6s", SIX_STEMS)}
DEFAULT_RETENTION_SECONDS = 14 * 24 * 60 * 60
DEFAULT_CACHE_BYTES = 16 * 1024**3
MAX_MEDIA_SECONDS = 4 * 60 * 60
MIN_WORKING_BYTES = 2 * 1024**3
COPY_BLOCK_BYTES = 1024 * 1024
MAX_CACHE_ENTRIES = 1024
MAX_RESULT_FILES = 256
MAX_MANIFEST_BYTES = 64 * 1024
CACHE_VERSION = 3
OWNER_MARKER = "mariana-stem-workspace-v3"


class StemError(RuntimeError):
    pass


class _FileLease:
    """Kernel-held local-filesystem lock: released automatically on process exit."""

    def __init__(self, path: Path, *, exclusive: bool):
        self._stream: BinaryIO | None = None
        self._overlapped = None
        self._unlock: Callable[[], None] | None = None
        try:
            _export_directories(path.parent, create=True)
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
                                 | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except OSError as error:
            raise StemError("Stem cache lock storage is unavailable") from error
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if (_export_signature(os.fstat(stream.fileno())) != _export_file_signature(path)):
                raise StemError("Stem cache lock identity changed")
            if os.name == "nt":
                import ctypes
                import msvcrt
                from ctypes import wintypes

                class Overlapped(ctypes.Structure):
                    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                                ("hEvent", wintypes.HANDLE)]

                overlapped = Overlapped()
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.LockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                             wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
                kernel.LockFileEx.restype = wintypes.BOOL
                flags = 1 | (2 if exclusive else 0)  # FAIL_IMMEDIATELY, optional EXCLUSIVE_LOCK
                if not kernel.LockFileEx(msvcrt.get_osfhandle(stream.fileno()), flags, 0, 1, 0,
                                         ctypes.byref(overlapped)):
                    if ctypes.get_last_error() in {32, 33}:
                        raise StemError("Stem cache result is in use; try again after its consumers finish")
                    raise StemError("Stem cache locking is unavailable on this storage")
                self._overlapped = overlapped
                kernel.UnlockFileEx.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                                               wintypes.DWORD, ctypes.c_void_p]
                kernel.UnlockFileEx.restype = wintypes.BOOL

                def unlock() -> None:
                    kernel.UnlockFileEx(msvcrt.get_osfhandle(stream.fileno()), 0, 1, 0, ctypes.byref(overlapped))

                self._unlock = unlock
            else:
                import fcntl

                try:
                    fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise StemError("Stem cache result is in use; try again after its consumers finish") from error
                except OSError as error:
                    raise StemError("Stem cache locking is unavailable on this storage") from error
            self._stream = stream
        except BaseException:
            stream.close()
            raise

    def release(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                if self._unlock is not None:
                    self._unlock()
                elif os.name != "nt":
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.release()


class _LeaseState:
    def __init__(self, lease: _FileLease):
        self.lease = lease
        self.lock = threading.Lock()
        self.references = 1


class StemLease:
    """An independently releasable pin; retain before handing work to a new decoder."""

    def __init__(self, paths: tuple[Path, ...], state: _LeaseState):
        self.paths = paths
        self._state = state
        self._released = False

    def retain(self) -> StemLease:
        with self._state.lock:
            if self._released:
                raise StemError("Prepared stem lease was already released")
            self._state.references += 1
            return StemLease(self.paths, self._state)

    def release(self) -> None:
        with self._state.lock:
            if self._released:
                return
            self._released = True
            self._state.references -= 1
            if self._state.references == 0:
                self._state.lease.release()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.release()


@dataclass(frozen=True, slots=True)
class StemInput:
    uri: str
    headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class StemManifest:
    media_id: str
    title: str
    model: str
    stems: dict[str, Path]
    created_at: float
    source_signature: str = ""
    stem_digests: dict[str, str] = field(default_factory=dict)

    def public(self) -> dict[str, object]:
        return {
            "media_id": self.media_id,
            "title": self.title,
            "model": self.model,
            "stems": tuple(self.stems),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class StemJobStatus:
    state: str = "idle"
    media_id: str | None = None
    title: str | None = None
    model: str | None = None
    progress: float = 0.0
    stage: str | None = None
    error: str | None = None
    available_stems: tuple[str, ...] = ()

    def public(self) -> dict[str, object]:
        return {
            "state": self.state,
            "media_id": self.media_id,
            "title": self.title,
            "model": self.model,
            "progress": self.progress,
            "stage": self.stage,
            "error": self.error,
            "available_stems": self.available_stems,
        }


@dataclass(slots=True)
class _StemJob:
    generation: int
    cancel: threading.Event
    lease: _FileLease | None = None


DemucsRunner = Callable[[Path, Path, str, tuple[str, ...], threading.Event], dict[str, Path]]


def _safe_component(value: str, fallback: str = "media") -> str:
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "-", value).strip(" .-")
    return (cleaned or fallback)[:120]


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def _finite_duration(media: MediaRef) -> float:
    value = media.duration
    if value is None:
        raise StemError("Stem preparation requires a known finite duration")
    try:
        duration = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise StemError("Stem preparation requires a known finite duration") from error
    if not math.isfinite(duration) or duration <= 0 or duration > MAX_MEDIA_SECONDS:
        raise StemError("Stem preparation supports media up to four hours long")
    return duration


def parse_stem_selection(values: Iterable[str], available: Iterable[str]) -> tuple[str, ...]:
    """Resolve model-backed names without pretending unsupported instruments exist."""
    choices = tuple(dict.fromkeys(str(value).casefold() for value in available))
    raw = [
        part.strip()
        for value in values
        for part in re.split(r"[,+]", value.casefold())
        if part.strip()
    ]
    aliases = {
        "vocal": "vocals",
        "voice": "vocals",
        "acapella": "vocals",
        "drum": "drums",
        "kick": "kicks",
        "guitars": "guitar",
        "pianos": "piano",
        "instrument": "karaoke",
        "instrumental": "karaoke",
        "instruments": "karaoke",
        "off": "original",
    }
    tokens = [aliases.get(value, value) for value in raw]
    if not tokens:
        raise StemError("Choose one or more prepared stems")
    if tokens == ["original"]:
        return ()
    if "original" in tokens:
        raise StemError("Original audio cannot be combined with separated stems")
    if "karaoke" in tokens:
        if len(tokens) != 1:
            raise StemError("Karaoke is already the complete non-vocal stem mix")
        return tuple(value for value in choices if value != "vocals")
    unsupported = tuple(value for value in tokens if value not in choices)
    if unsupported:
        detail = "Kicks are part of the drums stem" if "kicks" in unsupported else \
            "Melody is not an independently produced stem" if "melody" in unsupported or "melodies" in unsupported else \
            f"Unsupported stem: {unsupported[0]}"
        raise StemError(f"{detail}; available stems: {', '.join(choices)}")
    return tuple(dict.fromkeys(tokens))


def _export_signature(details: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        details.st_dev, details.st_ino, details.st_mode, details.st_size,
        # Windows path stat and handle fstat expose different ctime semantics.
        details.st_mtime_ns, details.st_nlink,
    )


def _export_link(details: os.stat_result) -> bool:
    return stat.S_ISLNK(details.st_mode) or bool(
        getattr(details, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def _export_file_signature(path: Path) -> tuple[int, int, int, int, int, int]:
    details = path.lstat()
    if _export_link(details) or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise StemError("Stem input/output requires unlinked regular files")
    return _export_signature(details)


def _export_directories(path: Path, *, create: bool = False) -> dict[Path, tuple[int, int, int]]:
    """Bind each existing ancestor without resolving away links or junctions."""
    result = {}
    for directory in (*reversed(path.parents), path):
        if create:
            directory.mkdir(exist_ok=True)
        details = directory.lstat()
        if _export_link(details) or not stat.S_ISDIR(details.st_mode):
            raise StemError("Stem directory must not contain links or reparse points")
        result[directory] = (details.st_dev, details.st_ino, details.st_mode)
    return result


def _revalidate_export_directories(bindings: dict[Path, tuple[int, int, int]]) -> None:
    for path, expected in bindings.items():
        details = path.lstat()
        if _export_link(details) or (details.st_dev, details.st_ino, details.st_mode) != expected:
            raise StemError("Stem directory changed during the filesystem operation")


def _copy_export_stream(source: BinaryIO, destination: BinaryIO) -> str:
    checksum = hashlib.sha256()
    while chunk := source.read(1024 * 1024):
        destination.write(chunk)
        checksum.update(chunk)
    return checksum.hexdigest()


def _export_digest(stream: BinaryIO) -> str:
    stream.seek(0)
    checksum = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        checksum.update(chunk)
    return checksum.hexdigest()


class StemService:
    """Run one bounded separation worker and retain verified local manifests."""

    def __init__(
        self,
        cache_dir: Path | str,
        *,
        ffmpeg_bin: str | None = None,
        runner: DemucsRunner | None = None,
        max_cache_bytes: int = DEFAULT_CACHE_BYTES,
        retention_seconds: float = DEFAULT_RETENTION_SECONDS,
    ):
        self.cache_dir = Path(os.path.abspath(Path(cache_dir).expanduser()))
        self.model_cache = self.cache_dir / "models"
        self.results = self.cache_dir / "results"
        self.work = self.cache_dir / "work"
        self.locks = self.cache_dir / "leases"
        self.ffmpeg_bin = ffmpeg_bin
        self.max_cache_bytes = max(1, int(max_cache_bytes))
        self.retention_seconds = max(0.0, float(retention_seconds))
        self._runner = runner or self._run_demucs
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mariana-stems")
        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._closed = False
        self._clearing = False
        self._generation = 0
        self._job: _StemJob | None = None
        self._future: Future[StemManifest] | None = None
        self._status = StemJobStatus()
        self._manifest: StemManifest | None = None
        self._manifest_lease: _FileLease | None = None

    def _initialize_cache(self) -> None:
        for path in (self.results, self.work, self.locks, self.model_cache):
            _export_directories(path, create=True)

    def _guard(self) -> _FileLease:
        return _FileLease(self.locks / "coordination.lock", exclusive=True)

    def _result_lock(self, key: str, *, exclusive: bool) -> _FileLease:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", key):
            raise StemError("Stem cache identity is invalid")
        path = self.locks / f"{key}.lock"
        if not path.exists():
            # Lock files are never unlinked while another process may hold/open
            # one: recreating the pathname would create two independent locks.
            self._entries(self.locks, maximum=MAX_CACHE_ENTRIES * 8)
        return _FileLease(path, exclusive=exclusive)

    def _directory_for(self, manifest: StemManifest) -> Path:
        if not manifest.stems:
            raise StemError("Prepared stem identities are invalid")
        candidate = next(iter(manifest.stems.values()))
        try:
            relative = candidate.relative_to(self.results)
        except ValueError as error:
            raise StemError("Stem cache identity is invalid") from error
        if len(relative.parts) < 2:
            raise StemError("Stem cache identity is invalid")
        return self.results / relative.parts[0]

    @staticmethod
    def _tree(directory: Path) -> tuple[Path, ...]:
        """Bounded traversal that never follows links, junctions or unexpected hardlinks."""
        _export_directories(directory)
        files: list[Path] = []
        pending = [(directory, 0)]
        entries = 0
        while pending:
            current, depth = pending.pop()
            if depth > 12:
                raise StemError("Stem cache directory nesting exceeds the supported limit")
            for child in current.iterdir():
                entries += 1
                if entries > MAX_RESULT_FILES:
                    raise StemError("Stem cache directory has too many entries")
                details = child.lstat()
                if _export_link(details):
                    raise StemError("Stem cache contains a link or reparse point")
                if stat.S_ISDIR(details.st_mode):
                    pending.append((child, depth + 1))
                elif stat.S_ISREG(details.st_mode) and details.st_nlink == 1:
                    files.append(child)
                else:
                    raise StemError("Stem cache contains an unsupported file")
        return tuple(files)

    @staticmethod
    def _owned(directory: Path) -> bool:
        marker = directory / "ownership.json"
        try:
            _export_directories(directory)
            if _export_file_signature(marker)[3] > 1024:
                return False
            value = json.loads(marker.read_text(encoding="utf-8"))
            return value == {"owner": OWNER_MARKER, "directory": directory.name}
        except (OSError, ValueError, TypeError, StemError):
            return False

    @staticmethod
    def _mark_owned(directory: Path) -> None:
        marker = directory / "ownership.json"
        with marker.open("x", encoding="utf-8") as stream:
            json.dump({"owner": OWNER_MARKER, "directory": directory.name}, stream)

    def _remove_owned(self, directory: Path, parent: Path) -> None:
        # Caller holds this result/workspace's exclusive kernel lock.
        if directory.parent != parent or not self._owned(directory):
            raise StemError("Stem cache cleanup requires a verified owned directory")
        bindings = _export_directories(directory)
        self._tree(directory)
        _revalidate_export_directories(bindings)
        shutil.rmtree(directory)

    def acquire(self, media_id: str, values: Iterable[str]) -> StemLease:
        """Pin a validated result before a monitor/export opens any of its files."""
        with self._lock:
            if self._closed:
                raise StemError("Stem service is closed")
            manifest = self._manifest
        if manifest is None or manifest.media_id != media_id:
            raise StemError("Prepare stems for the current media first")
        names = parse_stem_selection(values, manifest.stems)
        directory = self._directory_for(manifest)
        if any(not path.is_relative_to(directory) for path in manifest.stems.values()):
            raise StemError("Prepared stems must belong to one cache result")
        self._initialize_cache()
        with self._guard():
            lease = self._result_lock(directory.name, exclusive=False)
        try:
            if self.manifest(media_id) is not manifest:
                raise StemError("Prepared stems changed before use")
            _export_directories(directory)
            return StemLease(tuple(manifest.stems[name] for name in names), _LeaseState(lease))
        except BaseException:
            lease.release()
            raise

    @staticmethod
    def separator_available() -> bool:
        try:
            import importlib.util

            return importlib.util.find_spec("demucs") is not None
        except (ImportError, ValueError):
            return False

    def status(self) -> StemJobStatus:
        with self._lock:
            return self._status

    def manifest(self, media_id: str | None = None) -> StemManifest | None:
        with self._lock:
            manifest = self._manifest
        if manifest is None or (media_id is not None and manifest.media_id != media_id):
            return None
        try:
            for path in manifest.stems.values():
                _export_directories(path.parent)
                if _export_file_signature(path)[3] == 0 or not _inside(path, self.results):
                    return None
        except OSError:
            return None
        return manifest

    def prepare(self, media: MediaRef, source: StemInput, *, stem_count: str = "4") -> StemJobStatus:
        if stem_count not in MODELS:
            raise StemError("Stem model must be 4 or 6")
        if media.capabilities.live or not media.capabilities.finite:
            raise StemError("Stem preparation requires finite media; live streams are unsupported")
        _finite_duration(media)
        parsed = urlparse(source.uri)
        local_path = Path(source.uri).expanduser()
        if not local_path.is_absolute() and parsed.scheme not in {"", "file", "http", "https"}:
            raise StemError("This media transport cannot be prepared for stems")
        model, expected = MODELS[stem_count]
        with self._lock:
            if self._closed:
                raise StemError("Stem service is closed")
            if self._clearing:
                raise StemError("Stem cache cleanup is already running")
            if self._future is not None and not self._future.done():
                raise StemError("Stem preparation is already running")
            # Never let later caller metadata/header edits change an accepted job.
            selected = MediaRef.from_dict(media.to_dict())
            selected_source = StemInput(source.uri, dict(source.headers))
            self._generation += 1
            self._cancel = threading.Event()
            job = _StemJob(self._generation, self._cancel)
            self._job = job
            self._status = StemJobStatus(
                state="preparing",
                media_id=selected.stable_id,
                title=selected.title or "Current media",
                model=model,
                stage="queued",
            )
            try:
                self._future = self._executor.submit(
                    self._prepare_job, selected, selected_source, model, expected, job,
                )
            except RuntimeError as error:
                self._job = None
                self._future = None
                self._status = StemJobStatus(
                    state="failed", media_id=selected.stable_id, title=selected.title,
                    model=model, stage="failed", error="Stem worker could not start",
                )
                raise StemError("Stem worker could not start") from error
            self._future.add_done_callback(lambda done: self._complete(done, job))
            return self._status

    def cancel(self) -> bool:
        with self._lock:
            future = self._future
            if self._closed or future is None or self._status.state not in {"preparing", "cancelling"}:
                return False
            self._cancel.set()
            self._generation += 1
            self._status = StemJobStatus(
                **{**self._status.public(), "state": "cancelling", "stage": "cancelling", "error": None}
            )
            if future.done() and self._job is not None:
                self._complete(future, self._job)
            return True

    def wait(self, timeout: float | None = None) -> StemManifest:
        with self._lock:
            future = self._future
            job = self._job
        if future is None or job is None:
            raise StemError("No stem preparation is running")
        try:
            result = future.result(timeout=timeout)
        except CancelledError as error:
            raise StemError("Stem preparation cancelled") from error
        self._require_job(job)
        # Future.result may wake before its done callback obtains the state lock.
        # A successful wait must expose a settled job, not a spurious busy clear.
        self._complete(future, job)
        self._require_job(job)
        return result

    def selection(self, media_id: str, values: Iterable[str]) -> tuple[Path, ...]:
        manifest = self.manifest(media_id)
        if manifest is None:
            raise StemError("Prepare stems for the current media first")
        names = parse_stem_selection(values, manifest.stems)
        return tuple(manifest.stems[name] for name in names)

    def export(self, media_id: str, destination: Path | str, *, overwrite: bool = False) -> tuple[Path, ...]:
        try:
            manifest = self.manifest(media_id)
        except OSError as error:
            raise StemError("Prepared stems are unavailable for export") from error
        if manifest is None:
            raise StemError("Prepare stems for the current media first")
        with self.acquire(media_id, manifest.stems):
            return self._export(manifest, destination, overwrite=overwrite)

    def _export(self, manifest: StemManifest, destination: Path | str, *, overwrite: bool) -> tuple[Path, ...]:
        requested = Path(destination).expanduser()
        if ".." in requested.parts:
            raise StemError("Stem export destination cannot contain parent traversal")
        parent = Path(os.path.abspath(requested))
        target = parent / f"{_safe_component(manifest.title)}-stems"
        expected_names = next((names for model, names in MODELS.values() if model == manifest.model), ())
        if not expected_names or set(manifest.stems) != set(expected_names):
            raise StemError("Prepared stem identities are invalid")
        directories: dict[Path, tuple[int, int, int]] = {}
        output_directories: dict[Path, tuple[int, int, int]] = {}
        sources: dict[str, tuple[int, int, int, int, int, int]] = {}
        destinations: dict[str, BoundOutputTarget] = {}
        staged: dict[str, tuple[Path, tuple[int, int, int, int, int, int], str]] = {}
        exported: list[Path] = []
        try:
            output_directories = _export_directories(target, create=True)
            directories.update(output_directories)
            for name, source in manifest.stems.items():
                source_directories = _export_directories(source.parent)
                if any(path in directories and directories[path] != value for path, value in source_directories.items()):
                    raise StemError("Stem export directory changed during export")
                directories.update(source_directories)
                sources[name] = _export_file_signature(source)
                output = target / f"{name}.wav"
                if output.exists() or output.is_symlink():
                    _export_file_signature(output)
                destinations[name] = bind_output_target(output)
            existing = [item.path.name for item in destinations.values() if item.existed]
            if existing and not overwrite:
                raise StemError(f"Stem export already exists: {', '.join(existing)}")
            for name, source in manifest.stems.items():
                _revalidate_export_directories(directories)
                destinations[name].revalidate()
                with os.fdopen(os.open(source, os.O_RDONLY | getattr(os, "O_BINARY", 0)
                                       | getattr(os, "O_NOFOLLOW", 0)), "rb") as source_stream:
                    if _export_signature(os.fstat(source_stream.fileno())) != sources[name]:
                        raise StemError("Prepared stem changed during export")
                    descriptor, filename = tempfile.mkstemp(prefix=f".{name}.", suffix=".partial", dir=target)
                    temporary = Path(filename)
                    with os.fdopen(descriptor, "w+b") as output_stream:
                        # Register ownership before copying so partial writes are cleaned as well.
                        staged[name] = (temporary, _export_signature(os.fstat(output_stream.fileno())), "")
                        digest = _copy_export_stream(source_stream, output_stream)
                        output_stream.flush()
                        os.fsync(output_stream.fileno())
                        staged[name] = (temporary, _export_signature(os.fstat(output_stream.fileno())), digest)
                        if (_export_digest(output_stream) != digest or _export_digest(source_stream) != digest
                                or _export_signature(os.fstat(source_stream.fileno())) != sources[name]
                                or _export_file_signature(source) != sources[name]):
                            raise StemError("Prepared stem or staged bytes changed during export")
                    closed_signature = _export_file_signature(temporary)
                    if closed_signature[:3] != staged[name][1][:3]:
                        raise StemError("Staged stem changed during export")
                    staged[name] = (temporary, closed_signature, digest)
            # Finish every copy before activating any output; a copy failure exports nothing.
            for name, (temporary, signature, digest) in staged.items():
                _revalidate_export_directories(directories)
                if _export_file_signature(manifest.stems[name]) != sources[name]:
                    raise StemError("Prepared stem changed during export")
                if _export_file_signature(temporary) != signature:
                    raise StemError("Staged stem changed during export")
                with temporary.open("rb") as stream:
                    if _export_signature(os.fstat(stream.fileno())) != signature or _export_digest(stream) != digest:
                        raise StemError("Staged stem bytes changed during export")
                exported.append(destinations[name].activate(temporary))
        except (OSError, OutputTargetError, StemError) as error:
            detail = str(error) if isinstance(error, (StemError, OutputTargetError)) else "Stem export filesystem operation failed"
            if exported:
                detail += f"; {len(exported)} completed output(s) retained"
            raise StemError(detail) from error
        finally:
            for temporary, signature, _digest in staged.values():
                with suppress(OSError, StemError):
                    _revalidate_export_directories(output_directories)
                    # Size/timestamps may differ after a failed write; ownership may not.
                    current = _export_file_signature(temporary)
                    if current[:3] == signature[:3]:
                        temporary.unlink()
        return tuple(exported)

    def clear(self, media_id: str) -> bool:
        with self._lock:
            if self._closed:
                raise StemError("Stem service is closed")
            if self._clearing:
                raise StemError("Stem cache cleanup is already running")
            if self._future is not None and (
                not self._future.done() or self._status.state in {"preparing", "cancelling"}
            ):
                raise StemError("Wait until stem preparation finishes before clearing its cache")
            self._clearing = True
        try:
            manifest = self.manifest(media_id)
            if manifest is None:
                return False
            directory = self._directory_for(manifest)
            with self._guard():
                with self._lock:
                    pin, self._manifest_lease = self._manifest_lease, None
                if pin is not None:
                    pin.release()
                try:
                    removal = self._result_lock(directory.name, exclusive=True)
                except (OSError, StemError):
                    with self._lock:
                        self._manifest_lease = self._result_lock(directory.name, exclusive=False)
                    raise StemError("Prepared stems are in use; finish monitoring or export before clearing") from None
            try:
                self._remove_owned(directory, self.results)
            except BaseException:
                removal.release()
                with self._guard(), self._lock:
                    self._manifest_lease = self._result_lock(directory.name, exclusive=False)
                raise
            finally:
                removal.release()
            with self._lock:
                if self._manifest and self._manifest.media_id == media_id:
                    self._generation += 1
                    self._job = None
                    self._future = None
                    self._manifest = None
                    self._status = StemJobStatus()
            return True
        finally:
            with self._lock:
                self._clearing = False

    def shutdown(self, timeout: float = 2.0) -> None:
        with self._lock:
            self._closed = True
            self._cancel.set()
            self._generation += 1
            future = self._future
            pin, self._manifest_lease = self._manifest_lease, None
            if self._status.state in {"preparing", "cancelling"}:
                self._status = StemJobStatus(**{
                    **self._status.public(), "state": "cancelled", "stage": "cancelled",
                    "error": "Application shutdown cancelled stem preparation",
                })
        if pin is not None:
            pin.release()
        try:
            budget = float(timeout)
        except (TypeError, ValueError, OverflowError):
            budget = 0.0
        budget = min(2.0, max(0.0, budget)) if math.isfinite(budget) else 0.0
        if future is not None and not future.done():
            with suppress(Exception):
                future.result(timeout=budget)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _require_job(self, job: _StemJob) -> None:
        with self._lock:
            if self._closed or self._job is not job or self._generation != job.generation or job.cancel.is_set():
                raise StemError("Stem preparation cancelled")

    def _set_progress(self, job: _StemJob, progress: float, stage: str) -> None:
        with self._lock:
            self._require_job(job)
            current = self._status
            self._status = StemJobStatus(
                state=current.state,
                media_id=current.media_id,
                title=current.title,
                model=current.model,
                progress=min(1.0, max(0.0, progress)),
                stage=stage,
                error=current.error,
                available_stems=current.available_stems,
            )

    def _prepare_job(
        self,
        media: MediaRef,
        source: StemInput,
        model: str,
        expected: tuple[str, ...],
        job: _StemJob,
    ) -> StemManifest:
        self._require_job(job)
        self._initialize_cache()
        self._recover_work(job)
        reservation = self._check_storage(media, source, len(expected)) or 0
        self._require_job(job)
        workspace = self.work / uuid.uuid4().hex
        with self._guard():
            results_size, work_reserved = self._storage_usage()
        if results_size + work_reserved + reservation > self.max_cache_bytes:
            self._prune(exclude=workspace, job=job,
                        target_bytes=max(0, self.max_cache_bytes - work_reserved - reservation))
        with self._guard():
            result_size, work_reserved = self._storage_usage()
            if result_size + work_reserved + reservation > self.max_cache_bytes:
                raise StemError("Stem cache capacity is reserved by active results or preparations; clear unused results first")
            work_lease = self._result_lock(f"work-{workspace.name}", exclusive=True)
            try:
                workspace.mkdir()
                self._mark_owned(workspace)
                (workspace / "reservation.json").write_text(json.dumps({"bytes": reservation}), encoding="utf-8")
            except BaseException:
                with suppress(OSError, StemError):
                    self._remove_owned(workspace, self.work)
                work_lease.release()
                raise
        directory: Path | None = None
        result_lease: _FileLease | None = None
        manifest_written = False
        result_created = False
        try:
            self._set_progress(job, 0.05, "materializing")
            input_path = self._materialize(source, media, workspace, job.cancel)
            signature = self._source_signature(media, input_path, job.cancel, self.max_cache_bytes)
            key = hashlib.sha256(f"v{CACHE_VERSION}\0{media.stable_id}\0{model}\0{signature}".encode()).hexdigest()[:24]
            directory = self.results / key
            with self._guard():
                result_lease = self._result_lock(key, exclusive=False)
            cached = self._read_manifest(directory / "manifest.json", cancel=job.cancel, verify_bytes=True)
            self._require_job(job)
            if (cached is not None and cached.media_id == media.stable_id and cached.model == model
                    and cached.source_signature == signature):
                job.lease, result_lease = result_lease, None
                self._set_progress(job, 1.0, "cached")
                return cached
            with self._guard():
                result_lease.release()
                result_lease = self._result_lock(key, exclusive=True)
            self._require_job(job)
            if directory.exists():
                self._remove_owned(directory, self.results)
            directory.mkdir()
            self._mark_owned(directory)
            result_created = True
            self._set_progress(job, 0.2, "separating")
            stems = self._runner(input_path, directory / "separated", model, expected, job.cancel)
            self._require_job(job)
            if self._source_signature(media, input_path, job.cancel, self.max_cache_bytes) != signature:
                raise StemError("Owned stem input changed during separation")
            verified: dict[str, Path] = {}
            for name in expected:
                self._require_job(job)
                path = Path(os.path.abspath(stems.get(name, "")))
                _export_directories(path.parent)
                if (
                    not _inside(path, directory)
                    or _export_file_signature(path)[3] == 0
                ):
                    raise StemError(f"Separator did not produce a valid {name} stem")
                verified[name] = path
            if sum(_export_file_signature(path)[3] for path in self._tree(directory)) > self.max_cache_bytes:
                raise StemError("Prepared stems exceed the configured stem-cache limit")
            manifest = StemManifest(
                media_id=media.stable_id,
                title=media.title or "Current media",
                model=model,
                stems=verified,
                created_at=time.time(),
                source_signature=signature,
                stem_digests={name: self._digest_file(path, job.cancel, self.max_cache_bytes)
                              for name, path in verified.items()},
            )
            self._require_job(job)
            self._write_manifest(directory / "manifest.json", manifest, directory)
            manifest_written = True
            with self._guard():
                result_lease.release()
                result_lease = None
                job.lease = self._result_lock(key, exclusive=False)
            self._set_progress(job, 1.0, "ready")
            self._prune(exclude=directory, job=job)
            self._require_job(job)
            return manifest
        except BaseException:
            # A completed result that raced cancellation is useful cache, not a
            # published success. Preserve it; remove only incomplete job output.
            if result_created and not manifest_written and directory is not None and result_lease is not None:
                with suppress(OSError, StemError):
                    self._remove_owned(directory, self.results)
            raise
        finally:
            if result_lease is not None:
                result_lease.release()
            with suppress(OSError, StemError):
                self._remove_owned(workspace, self.work)
            work_lease.release()

    @staticmethod
    def _source_signature(media: MediaRef, path: Path, cancel: threading.Event, limit: int) -> str:
        """Bind the exact owned bytes and interpretation, never a temporary URL."""
        digest = StemService._digest_file(path, cancel, limit)
        return hashlib.sha256(f"v{CACHE_VERSION}\0{digest}\0{_finite_duration(media):.3f}".encode()).hexdigest()

    @staticmethod
    def _digest_file(path: Path, cancel: threading.Event, limit: int) -> str:
        signature = _export_file_signature(path)
        if signature[3] <= 0 or signature[3] > limit:
            raise StemError("Stem input or output exceeds the configured byte limit")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            if _export_signature(os.fstat(stream.fileno())) != signature:
                raise StemError("Stem source changed before verification")
            while chunk := stream.read(COPY_BLOCK_BYTES):
                if cancel.is_set():
                    raise StemError("Stem preparation cancelled")
                size += len(chunk)
                if size > limit or size > signature[3]:
                    raise StemError("Stem source grew during verification")
                digest.update(chunk)
            if (size != signature[3] or _export_signature(os.fstat(stream.fileno())) != signature
                    or _export_file_signature(path) != signature):
                raise StemError("Stem source changed during verification")
        return digest.hexdigest()

    def _check_storage(self, media: MediaRef, source: StemInput, stem_count: int) -> int:
        """Reject work that cannot fit its outputs and a conservative workspace."""
        duration = _finite_duration(media)
        stem_bytes = math.ceil(duration * 44_100 * 2 * 3 * stem_count * 1.1) + COPY_BLOCK_BYTES * stem_count
        parsed = urlparse(source.uri)
        local_path = Path(source.uri).expanduser()
        if local_path.is_absolute() or parsed.scheme in {"", "file"}:
            candidate = self._local_path(source)
            _export_directories(candidate.parent)
            input_bytes = _export_file_signature(candidate)[3]
        else:
            # The materialized stereo FLAC may exceed its PCM size slightly.
            input_bytes = math.ceil(duration * 44_100 * 2 * 2 * 1.1) + COPY_BLOCK_BYTES
        result_bytes = stem_bytes + input_bytes
        if result_bytes > self.max_cache_bytes:
            raise StemError("This item and stem model exceed the configured stem-cache limit")
        try:
            free = shutil.disk_usage(self.cache_dir).free
        except OSError as error:
            raise StemError("Stem cache storage is unavailable") from error
        if free < result_bytes + MIN_WORKING_BYTES:
            raise StemError("Not enough free space to prepare these stems safely")
        return result_bytes

    def _storage_usage(self) -> tuple[int, int]:
        result_size = 0
        reserved = 0
        for directory in self._entries(self.results):
            # Unknown/legacy output consumes quota too, but is never auto-deleted.
            result_size += sum(_export_file_signature(path)[3] for path in self._tree(directory))
        for directory in self._entries(self.work):
            if not self._owned(directory):
                raise StemError("Unrecognized stem workspace requires storage inspection")
            path = directory / "reservation.json"
            if _export_file_signature(path)[3] > 512:
                raise StemError("Stem workspace reservation is invalid")
            payload = json.loads(path.read_text(encoding="utf-8"))
            value = payload.get("bytes") if isinstance(payload, dict) else None
            if type(value) is not int or not 0 <= value <= self.max_cache_bytes:
                raise StemError("Stem workspace reservation is invalid")
            reserved += value
        return result_size, reserved

    def _materialize(
        self,
        source: StemInput,
        media: MediaRef,
        directory: Path,
        cancel: threading.Event,
    ) -> Path:
        parsed = urlparse(source.uri)
        local_path = Path(source.uri).expanduser()
        if local_path.is_absolute() or parsed.scheme in {"", "file"}:
            candidate = self._local_path(source)
            bindings = _export_directories(candidate.parent)
            signature = _export_file_signature(candidate)
            if signature[3] <= 0 or signature[3] > self.max_cache_bytes:
                raise StemError("Current local media exceeds the configured stem-cache limit")
            # The separator only sees owned bytes, never the mutable user file.
            suffix = candidate.suffix if re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", candidate.suffix) else ".media"
            destination = directory / f"source{suffix}"
            digest = hashlib.sha256()
            copied = 0
            with candidate.open("rb") as reader, destination.open("xb") as writer:
                if _export_signature(os.fstat(reader.fileno())) != signature:
                    raise StemError("Current local media changed before snapshot")
                while chunk := reader.read(COPY_BLOCK_BYTES):
                    if cancel.is_set():
                        raise StemError("Stem preparation cancelled")
                    copied += len(chunk)
                    if copied > signature[3] or copied > self.max_cache_bytes:
                        raise StemError("Current local media grew during snapshot")
                    writer.write(chunk)
                    digest.update(chunk)
                writer.flush()
                os.fsync(writer.fileno())
                _revalidate_export_directories(bindings)
                if (copied != signature[3] or _export_signature(os.fstat(reader.fileno())) != signature
                        or _export_file_signature(candidate) != signature):
                    raise StemError("Current local media changed during snapshot")
            if (self._digest_file(candidate, cancel, self.max_cache_bytes) != digest.hexdigest()
                    or _export_file_signature(candidate) != signature
                    or self._digest_file(destination, cancel, self.max_cache_bytes) != digest.hexdigest()):
                raise StemError("Current local media changed during snapshot verification")
            return destination
        destination = directory / "source.flac"
        command = [find_executable("ffmpeg", self.ffmpeg_bin), "-hide_banner", "-loglevel", "error", "-nostdin"]
        if source.headers:
            command += ["-headers", "".join(f"{key}: {value}\r\n" for key, value in source.headers.items())]
        command += [
            "-i",
            source.uri,
            "-t",
            f"{_finite_duration(media):.3f}",
            "-vn",
            "-sn",
            "-dn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "flac",
            "-fs",
            str(self.max_cache_bytes),
            "-y",
            str(destination),
        ]
        self._run_process(command, cancel, environment=None)
        if not destination.is_file() or destination.stat().st_size == 0:
            raise StemError("Could not materialize the current online audio")
        if destination.stat().st_size >= self.max_cache_bytes:
            raise StemError("Online stem input reached the configured byte limit")
        return destination

    @staticmethod
    def _local_path(source: StemInput) -> Path:
        if source.uri.startswith("file:"):
            from urllib.request import url2pathname

            parsed = urlparse(source.uri)
            if parsed.netloc not in {"", "localhost"}:
                raise StemError("Stem input must use a local file, not a remote file authority")
            raw = url2pathname(parsed.path)
        else:
            raw = source.uri
        path = Path(raw).expanduser()
        if ".." in path.parts:
            raise StemError("Stem input must not contain parent traversal")
        return Path(os.path.abspath(path))

    def _run_demucs(
        self,
        input_path: Path,
        output: Path,
        model: str,
        expected: tuple[str, ...],
        cancel: threading.Event,
    ) -> dict[str, Path]:
        if not self.separator_available():
            raise StemError("The optional Demucs separator is not installed")
        output.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ)
        environment["TORCH_HOME"] = str(self.model_cache)
        self._run_process(
            [
                sys.executable,
                "-m",
                "demucs",
                "--name",
                model,
                "--int24",
                "--jobs",
                "1",
                "--out",
                str(output),
                str(input_path),
            ],
            cancel,
            environment=environment,
            output_directory=output,
            byte_limit=self.max_cache_bytes,
        )
        found: dict[str, Path] = {}
        produced_files = self._tree(output)
        for name in expected:
            matches = [path for path in produced_files if path.name == f"{name}.wav"]
            if len(matches) != 1:
                raise StemError(f"Separator produced an ambiguous {name} stem")
            found[name] = matches[0]
        return found

    @staticmethod
    def _run_process(
        command: list[str],
        cancel: threading.Event,
        *,
        environment: dict[str, str] | None,
        output_directory: Path | None = None,
        byte_limit: int | None = None,
    ) -> None:
        if cancel.is_set():
            raise StemError("Stem preparation cancelled")
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
                creationflags=CREATE_NO_WINDOW,
                start_new_session=os.name != "nt",
            )
        except OSError as error:
            raise StemError("Stem processing could not start") from error
        job = WindowsJob(process)
        try:
            next_storage_check = 0.0
            while process.poll() is None:
                if cancel.wait(0.1):
                    StemService._terminate_process(process, job)
                    raise StemError("Stem preparation cancelled")
                if output_directory is not None and byte_limit is not None and time.monotonic() >= next_storage_check:
                    try:
                        used = sum(_export_file_signature(path)[3] for path in StemService._tree(output_directory))
                        if used > byte_limit or shutil.disk_usage(output_directory).free < MIN_WORKING_BYTES:
                            raise StemError("Stem processing reached its storage safety limit")
                    except (OSError, StemError):
                        StemService._terminate_process(process, job)
                        raise
                    next_storage_check = time.monotonic() + 0.5
            if process.returncode:
                raise StemError("Stem processing failed")
        finally:
            job.close()

    @staticmethod
    def _terminate_process(process: subprocess.Popen, job: WindowsJob) -> None:
        if os.name == "nt" and job.handle is not None:
            job.close()
        elif os.name != "nt":
            with suppress(OSError, ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        else:
            with suppress(OSError):
                process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                with suppress(OSError, ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            else:
                with suppress(OSError):
                    process.kill()
            with suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=2)

    @staticmethod
    def _write_manifest(path: Path, manifest: StemManifest, parent: Path) -> None:
        payload = {
            "version": CACHE_VERSION,
            "media_id": manifest.media_id,
            "title": manifest.title,
            "model": manifest.model,
            "created_at": manifest.created_at,
            "source_signature": manifest.source_signature,
            "stem_digests": manifest.stem_digests,
            "stems": {name: str(value.relative_to(parent)) for name, value in manifest.stems.items()},
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _read_manifest(
        path: Path, *, cancel: threading.Event | None = None, verify_bytes: bool = False,
    ) -> StemManifest | None:
        try:
            if not StemService._owned(path.parent) or _export_file_signature(path)[3] > MAX_MANIFEST_BYTES:
                return None
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != CACHE_VERSION:
                return None
            parent = path.parent
            model = str(payload["model"])
            expected = next((names for configured, names in MODELS.values() if configured == model), None)
            raw_stems = payload["stems"]
            if expected is None or not isinstance(raw_stems, dict) or set(raw_stems) != set(expected):
                return None
            if any(not isinstance(raw_stems[name], str) or Path(raw_stems[name]).is_absolute()
                   or ".." in Path(raw_stems[name]).parts for name in expected):
                return None
            stems = {name: parent / raw_stems[name] for name in expected}
            hashes = payload["stem_digests"]
            if not isinstance(hashes, dict) or set(hashes) != set(expected):
                return None
            for name, value in stems.items():
                _export_directories(value.parent)
                if (_export_file_signature(value)[3] == 0 or not _inside(value, parent)
                        or not isinstance(hashes[name], str) or not re.fullmatch(r"[a-f0-9]{64}", hashes[name])):
                    return None
                if verify_bytes and StemService._digest_file(
                    value, cancel if cancel is not None else threading.Event(), DEFAULT_CACHE_BYTES,
                ) != hashes[name]:
                    return None
            if (not isinstance(payload["source_signature"], str)
                    or not re.fullmatch(r"[a-f0-9]{64}", payload["source_signature"])
                    or not math.isfinite(float(payload["created_at"]))):
                return None
            manifest = StemManifest(
                media_id=str(payload["media_id"]),
                title=str(payload["title"]),
                model=model,
                stems=stems,
                created_at=float(payload["created_at"]),
                source_signature=str(payload["source_signature"]),
                stem_digests=hashes,
            )
            return manifest
        except (AttributeError, OSError, KeyError, TypeError, ValueError, OverflowError, StemError):
            return None

    def _complete(self, future: Future[StemManifest], job: _StemJob) -> None:
        message: str | None = None
        manifest: StemManifest | None = None
        try:
            manifest = future.result()
        except Exception as error:
            message = str(error) if isinstance(error, StemError) else "Stem preparation failed"
        with self._lock:
            if self._closed or self._job is not job or self._future is not future:
                if job.lease is not None:
                    job.lease.release()
                    job.lease = None
                return
            cancelled = job.cancel.is_set() or self._generation != job.generation
            if cancelled or message:
                if job.lease is not None:
                    job.lease.release()
                    job.lease = None
                current = self._status
                self._status = StemJobStatus(
                    state="cancelled" if cancelled else "failed",
                    media_id=current.media_id,
                    title=current.title,
                    model=current.model,
                    progress=current.progress,
                    stage="cancelled" if cancelled else "failed",
                    error="Stem preparation cancelled" if cancelled else message,
                )
                return
            if manifest is None:
                return
            if job.lease is not None:
                previous, self._manifest_lease = self._manifest_lease, job.lease
                job.lease = None
                if previous is not None:
                    previous.release()
            self._manifest = manifest
            self._status = StemJobStatus(
                state="ready",
                media_id=manifest.media_id,
                title=manifest.title,
                model=manifest.model,
                progress=1.0,
                stage="ready",
                available_stems=tuple(manifest.stems),
            )

    def _prune(self, *, exclude: Path, job: _StemJob, target_bytes: int | None = None) -> None:
        self._require_job(job)
        now = time.time()
        candidates: list[tuple[float, Path, int]] = []
        total = 0
        try:
            directories = self._entries(self.results)
        except OSError:
            return
        for directory in directories:
            self._require_job(job)
            if not self._owned(directory):
                continue
            try:
                files = self._tree(directory)
                size = sum(path.stat().st_size for path in files)
                modified = max((path.stat().st_mtime for path in files), default=directory.stat().st_mtime)
            except (OSError, StemError):
                continue
            total += size
            candidates.append((modified, directory, size))
        for modified, directory, size in sorted(candidates):
            self._require_job(job)
            expired = self.retention_seconds == 0 or now - modified > self.retention_seconds
            if directory != exclude and (expired or total > (self.max_cache_bytes if target_bytes is None else target_bytes)):
                try:
                    with self._guard():
                        lease = self._result_lock(directory.name, exclusive=True)
                    with lease:
                        self._remove_owned(directory, self.results)
                    total -= size
                except (OSError, StemError):
                    continue

    @staticmethod
    def _entries(parent: Path, *, maximum: int = MAX_CACHE_ENTRIES) -> tuple[Path, ...]:
        entries = []
        for path in parent.iterdir():
            entries.append(path)
            if len(entries) > maximum:
                raise StemError("Stem cache contains too many result entries; inspect storage before preparing more")
        return tuple(entries)

    def _recover_work(self, job: _StemJob) -> None:
        for directory in self._entries(self.work):
            self._require_job(job)
            if not self._owned(directory):
                continue
            try:
                with self._guard():
                    lease = self._result_lock(f"work-{directory.name}", exclusive=True)
                with lease:
                    self._remove_owned(directory, self.work)
            except (OSError, StemError):
                # A live process owns this workspace, or ownership cannot be proven.
                continue
        for directory in self._entries(self.results):
            self._require_job(job)
            if not self._owned(directory) or (directory / "manifest.json").exists():
                continue
            try:
                with self._guard():
                    lease = self._result_lock(directory.name, exclusive=True)
                with lease:
                    if not (directory / "manifest.json").exists():
                        self._remove_owned(directory, self.results)
            except (OSError, StemError):
                continue
