"""Install an explicitly chosen VST3 or Audio Unit archive without loading it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener
from zipfile import BadZipFile, ZipFile


NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SHA256 = re.compile(r"[a-fA-F0-9]{64}")
WINDOWS_RESERVED = re.compile(r"(?:CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|$)", re.I)
PACKAGE_LIMIT = 256 * 1024 * 1024
EXTRACT_LIMIT = 512 * 1024 * 1024
SUFFIXES = {".vst3", ".component"} if sys.platform == "darwin" else {".vst3"}


def _https(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username is not None or parts.password is not None:
        raise ValueError("Use a vendor HTTPS download URL without embedded login details.")
    return url


class _HttpsRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return super().redirect_request(req, fp, code, msg, headers, _https(newurl))


def _copy_package(readable, destination):
    sha = hashlib.sha256()
    total = 0
    deadline = time.monotonic() + 180
    read_chunk = getattr(readable, "read1", readable.read)
    with destination.open("xb") as out:
        while chunk := read_chunk(1024 * 1024):
            total += len(chunk)
            if total > PACKAGE_LIMIT:
                raise ValueError("Plug-in ZIP exceeds the 256 MiB package limit.")
            if time.monotonic() > deadline:
                raise ValueError("Plug-in package copy exceeded three minutes.")
            sha.update(chunk)
            out.write(chunk)
    return sha.hexdigest()


def _fetch(source, destination):
    if "://" in source:
        with build_opener(_HttpsRedirect()).open(_https(source), timeout=15) as response:
            return _copy_package(response, destination)
    package = Path(source).expanduser()
    if not package.is_file():
        raise ValueError("Choose an existing vendor ZIP file or a vendor HTTPS download URL.")
    with package.open("rb") as stream:
        return _copy_package(stream, destination)


def _components(member):
    path = member.orig_filename.rstrip("/")
    parts = path.split("/")
    if len(path) > 400 or len(parts) > 24 or any(
        part in {"", ".", ".."} or part.endswith((".", " "))
        or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
        or WINDOWS_RESERVED.match(part)
        for part in parts
    ):
        raise ValueError("The plug-in ZIP contains an unsafe path.")
    unix_mode = member.external_attr >> 16
    if stat.S_IFMT(unix_mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ValueError("The plug-in ZIP contains a link or special file. Use the vendor's installer instead.")
    return parts


def _unpack(package, destination):
    candidates = set()
    with ZipFile(package) as zipped:
        members = zipped.infolist()
        if len(members) > 8192 or sum(member.file_size for member in members) > EXTRACT_LIMIT:
            raise ValueError("Plug-in ZIP exceeds the unpacked file or size limit.")
        seen = set()
        for member in members:
            parts = _components(member)
            if parts[0] == "__MACOSX":
                continue
            path = destination.joinpath(*parts)
            folded = tuple(part.casefold() for part in parts)
            if folded in seen:
                raise ValueError("The plug-in ZIP contains duplicate paths.")
            seen.add(folded)
            for index, component in enumerate(parts):
                if Path(component).suffix.casefold() in SUFFIXES and not member.is_dir():
                    candidates.add(Path(*parts[:index + 1]))
                    break
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(member) as source, path.open("xb") as target:
                shutil.copyfileobj(source, target)
            # Keep executable bits only for ordinary executables in accepted vendor bundles.
            if member.external_attr >> 16 & 0o111:
                path.chmod(0o755)
    if len(candidates) != 1:
        raise ValueError("Choose a ZIP containing exactly one matching-platform .vst3 or macOS .component effect.")
    return candidates.pop()


def install_package(root, name, source, expected):
    if not NAME.fullmatch(name):
        raise ValueError("Use a plug-in name of 1–40 lowercase letters, digits or hyphens.")
    if not SHA256.fullmatch(expected):
        raise ValueError("Supply the SHA-256 digest of the exact vendor ZIP.")
    folder = root / name
    if folder.exists() or folder.is_symlink():
        raise ValueError("This plug-in name is already installed. Use a new name for a different release.")
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=root) as work:
            stage = Path(work)
            archive, payload = stage / "package.zip", stage / "payload"
            if _fetch(source, archive) != expected.lower():
                raise ValueError("The plug-in package SHA-256 did not match. Nothing was installed.")
            files = payload / "files"
            files.mkdir(parents=True)
            plugin = _unpack(archive, files)
            (payload / "package.json").write_text(json.dumps({
                "path": plugin.as_posix(),
                "sha256": expected.lower(),
            }), encoding="utf-8")
            # Every completed package is a nonempty directory, so a concurrent
            # installation cannot replace it.
            payload.rename(folder)
    except (OSError, URLError, BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError(f"Could not install the plug-in ZIP ({type(exc).__name__}).") from exc


def resolve_package(root, name):
    if not NAME.fullmatch(name):
        return None
    folder = root.resolve() / name
    if folder.is_symlink():
        return None
    try:
        manifest = folder / "package.json"
        if not manifest.is_file() or manifest.is_symlink() or manifest.stat().st_size > 2048:
            return None
        relative = Path(json.loads(manifest.read_text(encoding="utf-8"))["path"])
        if relative.is_absolute() or ".." in relative.parts:
            return None
        files = (folder / "files").resolve()
        path = (files / relative).resolve()
        if files.is_relative_to(folder) and path.is_relative_to(files) and path.suffix.lower() in SUFFIXES and path.exists():
            return path
    except (OSError, ValueError, LookupError, TypeError):
        pass
    return None
