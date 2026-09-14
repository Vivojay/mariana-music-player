"""Leased ownership records for disposable picture windows, never source media."""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import stat
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

MAX_RECOVERY_RECORDS = 32
MAX_RECOVERY_SECONDS = 0.1
MAX_RECORD_BYTES = 8192
MAX_OWNED_WINDOWS = 8
_RECORD = re.compile(r"\.mariana-video-[0-9a-f]{32}\.json")
_WINDOW = re.compile(r"[0-9a-f]{32}\.mp4")


def _plain(path: Path, *, directory: bool = False) -> os.stat_result:
    value = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(value.st_mode) or (value.st_nlink != 1 and not directory)
            or getattr(value, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise OSError("Video cache entry is not an ordinary owned file")
    return value


def _identity(value: os.stat_result) -> tuple[int, int, int]:
    if value.st_ino <= 0:
        raise OSError("Video cache needs stable filesystem identities")
    return value.st_dev, value.st_ino, getattr(value, "st_birthtime_ns", 0)


def _lock(fd: int) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def _open_record(path: Path) -> int:
    before = _plain(path)
    fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        if _identity(os.fstat(fd)) != _identity(before) or _identity(_plain(path)) != _identity(before):
            raise OSError("Video cache ownership record changed")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _windows_remove(path: Path, expected: tuple[int, int, int]) -> bool:
    """Delete the verified file handle, not a subsequently replaced path name."""
    if sys.platform != "win32":
        return False
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    # DELETE | FILE_READ_ATTRIBUTES; share reads/writes but deny rename/deletion.
    handle = create(str(path), 0x10000 | 0x80, 0x1 | 0x2, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    try:
        value = os.fstat(fd)
        if (not stat.S_ISREG(value.st_mode) or value.st_nlink != 1
                or getattr(value, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or _identity(value) != expected):
            return False
        remove = kernel.SetFileInformationByHandle
        remove.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        remove.restype = wintypes.BOOL
        disposition = wintypes.BOOL(True)
        if not remove(handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            raise ctypes.WinError(ctypes.get_last_error())
        return True
    finally:
        os.close(fd)


class VideoWindowCache:
    """Lazy, private leases protect other live instances; legacy files are ignored.

    All work belongs on the picture worker. A manifest lists only files created
    exclusively by this instance. File bytes may grow, but inode/birth identity
    must stay unchanged. Malformed records and replaced files are never removed.
    """

    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self._root_identity: tuple[int, int, int] | None = None
        self._fd: int | None = None
        self._record: Path | None = None
        self._record_identity: tuple[int, int, int] | None = None
        self._files: dict[str, tuple[int, int, int]] = {}
        self._recovery_scan: Iterator[os.DirEntry[str]] | None = None
        self._scan_context = contextlib.ExitStack()
        self._recovery_complete = False

    def _check_root(self) -> None:
        for ancestor in (self.root, *self.root.parents):
            _plain(ancestor, directory=True)
        identity = _identity(_plain(self.root, directory=True))
        if self._root_identity is not None and identity != self._root_identity:
            raise OSError("Video cache directory changed")
        self._root_identity = identity

    def _ensure(self) -> None:
        for ancestor in (self.root, *self.root.parents):
            if ancestor.exists() or ancestor.is_symlink():
                _plain(ancestor, directory=True)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._check_root()
        if not self._recovery_complete:
            self._recover()
        if self._fd is None:
            record = self.root / f".mariana-video-{secrets.token_hex(16)}.json"
            fd = os.open(record, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, b" ")
                if not _lock(fd):
                    raise OSError("Could not lease video cache")
                self._fd, self._record = fd, record
                self._record_identity = _identity(os.fstat(fd))
                self._write_record()
            except BaseException:
                self._fd = None
                os.close(fd)
                raise

    def _write_record(self) -> None:
        if self._fd is None:
            return
        self._check_root()
        data = json.dumps({"version": 1, "windows": self._files}, separators=(",", ":")).encode()
        if len(data) > MAX_RECORD_BYTES:
            raise OSError("Video cache ownership record exceeds its limit")
        os.lseek(self._fd, 0, os.SEEK_SET)
        pending = memoryview(data)
        while pending:
            written = os.write(self._fd, pending)
            if written == 0:
                raise OSError("Video cache ownership record could not be written")
            pending = pending[written:]
        os.ftruncate(self._fd, len(data))
        os.fsync(self._fd)

    def allocate(self) -> Path:
        self._ensure()
        if len(self._files) >= MAX_OWNED_WINDOWS:
            raise OSError("Video cache cleanup backlog exceeds its limit")
        path = self.root / f"{secrets.token_hex(16)}.mp4"
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            self._files[path.name] = _identity(os.fstat(fd))
            self._write_record()
        finally:
            os.close(fd)
        return path

    def writer(self, path: Path) -> BinaryIO:
        self._check_root()
        expected = self._files.get(path.name)
        if path.parent != self.root or expected is None or _identity(_plain(path)) != expected:
            raise OSError("Video window is not owned by this worker")
        fd = os.open(path, os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0))
        if _identity(os.fstat(fd)) != expected:
            os.close(fd)
            raise OSError("Video window changed before writing")
        return os.fdopen(fd, "wb", buffering=0)

    def validate(self, path: Path) -> None:
        self._check_root()
        if path.parent != self.root or self._files.get(path.name) != _identity(_plain(path)):
            raise OSError("Video window changed during preparation")

    def _remove_verified(self, name: str, expected: tuple[int, int, int]) -> bool:
        self._check_root()
        path = self.root / name
        try:
            if _identity(_plain(path)) != expected:
                return False
        except FileNotFoundError:
            return True
        if os.name == "nt":
            return _windows_remove(path, expected)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if _identity(os.fstat(directory)) != self._root_identity:
                return False
            current = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if _identity(current) != expected or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
                return False
            os.unlink(name, dir_fd=directory)
            return True
        finally:
            os.close(directory)

    def remove(self, path: Path) -> bool:
        expected = self._files.get(path.name)
        if path.parent != self.root or expected is None:
            return False
        if self._remove_verified(path.name, expected):
            del self._files[path.name]
            self._write_record()
            return True
        return False

    def _recover(self) -> None:
        deadline = time.monotonic() + MAX_RECOVERY_SECONDS
        if self._recovery_scan is None:
            self._recovery_scan = self._scan_context.enter_context(os.scandir(self.root))
        entries = self._recovery_scan
        for _ in range(MAX_RECOVERY_RECORDS):
            if time.monotonic() >= deadline:
                break
            entry = next(entries, None)
            if entry is None:
                self._scan_context.close()
                self._recovery_scan = None
                self._recovery_complete = True
                break
            if _RECORD.fullmatch(entry.name):
                self._recover_record(self.root / entry.name, deadline)

    def _recover_record(self, path: Path, deadline: float) -> None:
        fd = None
        locked = False
        empty = False
        identity = None
        try:
            self._check_root()
            fd = _open_record(path)
            identity = _identity(os.fstat(fd))
            if not _lock(fd):
                return
            locked = True
            raw = os.read(fd, MAX_RECORD_BYTES + 1)
            if len(raw) > MAX_RECORD_BYTES:
                return
            record = json.loads(raw)
            if (not isinstance(record, dict) or set(record) != {"version", "windows"}
                    or type(record["version"]) is not int or record["version"] != 1):
                return
            files = record["windows"]
            if (not isinstance(files, dict) or len(files) > MAX_OWNED_WINDOWS
                    or any(not _WINDOW.fullmatch(name) or not isinstance(value, list) or len(value) != 3
                           or any(type(part) is not int or part < 0 for part in value) for name, value in files.items())):
                return
            remaining = dict(files)
            for name, value in files.items():
                if time.monotonic() >= deadline:
                    break
                with contextlib.suppress(OSError):
                    if self._remove_verified(name, tuple(value)):
                        del remaining[name]
            empty = not remaining
            # Retain incomplete records as-is: already absent windows are harmless.
        except (OSError, ValueError, TypeError):
            return
        finally:
            if fd is not None:
                if locked:
                    with contextlib.suppress(OSError):
                        _unlock(fd)
                os.close(fd)
            if empty and identity is not None:
                with contextlib.suppress(OSError):
                    self._remove_verified(path.name, identity)

    def close(self) -> None:
        if self._recovery_scan is not None:
            self._scan_context.close()
            self._recovery_scan = None
            self._recovery_complete = True
        for name in tuple(self._files):
            with contextlib.suppress(OSError):
                self.remove(self.root / name)
        if self._fd is not None:
            with contextlib.suppress(OSError):
                _unlock(self._fd)
            os.close(self._fd)
            self._fd = None
            if not self._files and self._record is not None and self._record_identity is not None:
                with contextlib.suppress(OSError):
                    self._remove_verified(self._record.name, self._record_identity)
