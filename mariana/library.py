"""Incremental, resumable indexing for the user-managed ``lib.lib`` roots."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Iterable
import uuid

from mutagen import File as MutagenFile, MutagenError

from .database import MarianaDatabase
from .identity import IdentificationError, fingerprint_file
from .models import MediaCapabilities, MediaRef, MediaSource
from .playback import CREATE_NO_WINDOW, find_executable


APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY_FILE = APP_DIR / "lib.lib"
PROBE_VERSION = 1


class LibraryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScanResult:
    scan_id: str
    discovered: int
    changed: int
    unavailable_roots: int
    errors: int


@dataclass(frozen=True, slots=True)
class LibraryJob:
    job_id: int
    library_id: str
    stage: str
    path: Path
    attempts: int


def path_key(path: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path))).casefold()


def parse_library_file(path: Path | str = DEFAULT_LIBRARY_FILE) -> list[Path]:
    source = Path(path)
    if not source.is_file():
        return []
    roots: list[Path] = []
    seen: set[str] = set()
    for raw in source.read_text(encoding="utf-8-sig").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        expanded = Path(os.path.expandvars(os.path.expanduser(value))).absolute()
        key = path_key(expanded)
        if key not in seen:
            seen.add(key)
            roots.append(expanded)
    return roots


def root_kind(path: Path) -> str:
    value = str(path)
    if value.startswith(("\\\\", "//")):
        return "network"
    if os.name == "nt":
        try:
            import ctypes

            drive_type = ctypes.windll.kernel32.GetDriveTypeW(path.anchor)
            if drive_type == 2:
                return "removable"
            if drive_type == 4:
                return "network"
        except (AttributeError, OSError):
            pass
    return "local"


def file_key(stat: os.stat_result) -> str | None:
    device = getattr(stat, "st_dev", 0)
    inode = getattr(stat, "st_ino", 0)
    return f"{device}:{inode}" if inode else None


def content_signature(path: Path, size: int, chunk_size: int = 65_536) -> str:
    digest = hashlib.sha256()
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as stream:
        digest.update(stream.read(chunk_size))
        if size > chunk_size:
            stream.seek(max(0, size - chunk_size))
            digest.update(stream.read(chunk_size))
    return digest.hexdigest()


def _safe_text(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        value = "; ".join(str(item) for item in value if item is not None)
    text = str(value).strip()
    return text or None


class LibraryCatalog:
    def __init__(
        self,
        database: MarianaDatabase,
        *,
        library_file: Path | str = DEFAULT_LIBRARY_FILE,
        supported_extensions: Iterable[str] = (),
        ffmpeg_bin: str | None = None,
        fpcalc_bin: str | None = None,
    ) -> None:
        self.database = database
        self.library_file = Path(library_file)
        self.supported_extensions = {
            extension.casefold() if str(extension).startswith(".") else f".{str(extension).casefold()}"
            for extension in supported_extensions
        }
        self.ffmpeg_bin = ffmpeg_bin
        self.fpcalc_bin = fpcalc_bin

    def roots(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.database.fetchall("SELECT * FROM library_roots ORDER BY path_key")]

    def sync_roots(self) -> list[dict[str, Any]]:
        configured = parse_library_file(self.library_file)
        configured_keys = {path_key(root) for root in configured}
        now = time.time()
        with self.database.transaction() as connection:
            for root in configured:
                key = path_key(root)
                root_id = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
                connection.execute(
                    "INSERT INTO library_roots(root_id, path, path_key, kind, available, last_seen) "
                    "VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(path_key) DO UPDATE SET "
                    "path=excluded.path, kind=excluded.kind",
                    (root_id, str(root), key, root_kind(root), int(root.is_dir()), now if root.is_dir() else None),
                )
            if configured_keys:
                placeholders = ",".join("?" for _ in configured_keys)
                connection.execute(
                    f"UPDATE library_roots SET available=0, error='removed from lib.lib' "
                    f"WHERE path_key NOT IN ({placeholders})",
                    tuple(configured_keys),
                )
            else:
                connection.execute("UPDATE library_roots SET available=0, error='removed from lib.lib'")
        return self.roots()

    def _walk(self, root: Path) -> Iterable[tuple[Path, os.stat_result]]:
        pending = [root]
        while pending:
            directory = pending.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError as error:
                raise LibraryError(f"Cannot scan {directory}: {error}") from error
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        path = Path(entry.path)
                        if not self.supported_extensions or path.suffix.casefold() in self.supported_extensions:
                            yield path, entry.stat(follow_symlinks=False)
                except OSError:
                    continue

    def _schedule(self, connection, library_id: str, stage: str, priority: int = 0) -> None:
        now = time.time()
        connection.execute(
            "INSERT INTO library_jobs(library_id, stage, status, priority, created_at, updated_at) "
            "VALUES(?, ?, 'pending', ?, ?, ?) ON CONFLICT(library_id, stage) DO UPDATE SET "
            "status='pending', priority=excluded.priority, attempts=0, lease_owner=NULL, lease_until=NULL, "
            "next_retry=0, error_code=NULL, error_text=NULL, updated_at=excluded.updated_at",
            (library_id, stage, priority, now, now),
        )

    def _discover_file(
        self,
        root_id: str,
        path: Path,
        stat: os.stat_result,
        generation: str,
        full: bool,
    ) -> tuple[bool, str]:
        key = path_key(path)
        existing = self.database.fetchone("SELECT * FROM library_files WHERE path_key=?", (key,))
        changed = full or existing is None or existing["size"] != stat.st_size or existing["mtime_ns"] != stat.st_mtime_ns
        now = time.time()
        if existing and not changed:
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE library_files SET state='available', missing_since=NULL, scan_generation=?, updated_at=? "
                    "WHERE library_id=?",
                    (generation, now, existing["library_id"]),
                )
            return False, existing["library_id"]

        identity = file_key(stat)
        moved = self.database.fetchone(
            "SELECT * FROM library_files WHERE file_key=? ORDER BY updated_at DESC LIMIT 1", (identity,)
        ) if identity else None
        signature = content_signature(path, stat.st_size)
        if moved is None:
            candidates = self.database.fetchall(
                "SELECT * FROM library_files WHERE root_id=? AND content_signature=? AND size=? "
                "AND scan_generation<>? ORDER BY updated_at DESC",
                (root_id, signature, stat.st_size, generation),
            )
            moved = next(
                (candidate for candidate in candidates if not Path(candidate["canonical_path"]).is_file()),
                None,
            )
        library_id = (existing or moved or {}).get("library_id") if isinstance(existing or moved, dict) else None
        if library_id is None:
            row = existing or moved
            library_id = row["library_id"] if row else uuid.uuid4().hex
        with self.database.transaction() as connection:
            if moved and moved["path_key"] != key:
                connection.execute("DELETE FROM library_files WHERE path_key=? AND library_id<>?", (key, library_id))
            connection.execute(
                "INSERT INTO library_files(library_id, root_id, canonical_path, path_key, file_key, "
                "content_signature, size, mtime_ns, extension, state, scan_generation, metadata_json, "
                "features_json, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', ?, '{}', '{}', ?) "
                "ON CONFLICT(library_id) DO UPDATE SET root_id=excluded.root_id, canonical_path=excluded.canonical_path, "
                "path_key=excluded.path_key, file_key=excluded.file_key, content_signature=excluded.content_signature, "
                "size=excluded.size, mtime_ns=excluded.mtime_ns, extension=excluded.extension, state='available', "
                "missing_since=NULL, scan_generation=excluded.scan_generation, fingerprint=NULL, "
                "fingerprint_duration=NULL, updated_at=excluded.updated_at",
                (
                    library_id,
                    root_id,
                    str(path.absolute()),
                    key,
                    identity,
                    signature,
                    stat.st_size,
                    stat.st_mtime_ns,
                    path.suffix.casefold(),
                    generation,
                    now,
                ),
            )
            self._schedule(connection, library_id, "probe", priority=100)
        return True, library_id

    def scan(self, mode: str = "changed") -> ScanResult:
        if mode not in {"changed", "full"}:
            raise LibraryError("Library scan mode must be 'changed' or 'full'")
        scan_id = uuid.uuid4().hex
        now = time.time()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO library_scan_runs(scan_id, mode, status, started_at) VALUES(?, ?, 'running', ?)",
                (scan_id, mode, now),
            )
        discovered = changed = unavailable = errors = 0
        for root in self.sync_roots():
            if root["error"] == "removed from lib.lib":
                continue
            root_path = Path(root["path"])
            if not root_path.is_dir():
                unavailable += 1
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE library_roots SET available=0, error=?, backoff_until=? WHERE root_id=?",
                        ("root unavailable", now + 60, root["root_id"]),
                    )
                continue
            try:
                for media_path, stat in self._walk(root_path):
                    discovered += 1
                    was_changed, _ = self._discover_file(
                        root["root_id"], media_path, stat, scan_id, mode == "full"
                    )
                    changed += int(was_changed)
            except LibraryError as error:
                errors += 1
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE library_roots SET available=0, error=? WHERE root_id=?",
                        (str(error), root["root_id"]),
                    )
                continue
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE library_roots SET available=1, last_seen=?, last_scan=?, backoff_until=NULL, error=NULL "
                    "WHERE root_id=?",
                    (time.time(), time.time(), root["root_id"]),
                )
                connection.execute(
                    "UPDATE library_files SET state='missing', missing_since=COALESCE(missing_since, ?), updated_at=? "
                    "WHERE root_id=? AND state='available' AND scan_generation<>?",
                    (time.time(), time.time(), root["root_id"], scan_id),
                )
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE library_scan_runs SET status='complete', discovered=?, changed=?, unavailable_roots=?, "
                "errors=?, finished_at=? WHERE scan_id=?",
                (discovered, changed, unavailable, errors, time.time(), scan_id),
            )
        return ScanResult(scan_id, discovered, changed, unavailable, errors)

    def paths(self, *, include_missing: bool = False) -> list[str]:
        condition = "" if include_missing else "WHERE state='available'"
        return [
            row["canonical_path"]
            for row in self.database.fetchall(
                f"SELECT canonical_path FROM library_files {condition} ORDER BY path_key"
            )
        ]

    def media_refs(self) -> list[MediaRef]:
        result = []
        for row in self.database.fetchall(
            "SELECT * FROM library_files WHERE state='available' ORDER BY path_key"
        ):
            metadata = json.loads(row["metadata_json"] or "{}")
            result.append(
                MediaRef(
                    MediaSource.LOCAL,
                    row["canonical_path"],
                    stable_id=row["library_id"],
                    title=metadata.get("title"),
                    artist=metadata.get("artist"),
                    album=metadata.get("album"),
                    duration=metadata.get("duration"),
                    resolver_data={
                        "library_id": row["library_id"],
                        "content_id": row["content_signature"],
                        "fingerprint": row["fingerprint"],
                    },
                    provenance="library",
                    capabilities=MediaCapabilities(downloadable=False, metadata_available=bool(metadata)),
                )
            )
        return result

    def lease_jobs(self, stage: str, limit: int, owner: str, lease_seconds: float = 180) -> list[LibraryJob]:
        now = time.time()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE library_jobs SET status='pending', lease_owner=NULL, lease_until=NULL "
                "WHERE status='running' AND lease_until<?",
                (now,),
            )
            rows = connection.execute(
                "SELECT j.job_id, j.library_id, j.stage, j.attempts, f.canonical_path "
                "FROM library_jobs j JOIN library_files f ON f.library_id=j.library_id "
                "WHERE j.stage=? AND j.status IN ('pending', 'failed') AND j.next_retry<=? "
                "AND f.state='available' ORDER BY j.priority DESC, j.job_id LIMIT ?",
                (stage, now, max(0, limit)),
            ).fetchall()
            ids = [row["job_id"] for row in rows]
            for job_id in ids:
                connection.execute(
                    "UPDATE library_jobs SET status='running', lease_owner=?, lease_until=?, updated_at=? WHERE job_id=?",
                    (owner, now + lease_seconds, now, job_id),
                )
        return [
            LibraryJob(row["job_id"], row["library_id"], row["stage"], Path(row["canonical_path"]), row["attempts"])
            for row in rows
        ]

    def _complete(self, job: LibraryJob) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE library_jobs SET status='complete', lease_owner=NULL, lease_until=NULL, "
                "error_code=NULL, error_text=NULL, updated_at=? WHERE job_id=?",
                (time.time(), job.job_id),
            )

    def _fail(self, job: LibraryJob, code: str, error: BaseException) -> None:
        attempts = job.attempts + 1
        delay = min(3600, 2 ** min(attempts, 10))
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE library_jobs SET status='failed', attempts=?, lease_owner=NULL, lease_until=NULL, "
                "next_retry=?, error_code=?, error_text=?, updated_at=? WHERE job_id=?",
                (attempts, time.time() + delay, code, str(error)[:1000], time.time(), job.job_id),
            )

    def _probe(self, job: LibraryJob) -> None:
        ffprobe = find_executable("ffprobe", self.ffmpeg_bin)
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration,format_name,bit_rate,tags:stream=codec_type,codec_name,sample_rate,channels,tags",
                    "-of",
                    "json",
                    str(job.path),
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=True,
                creationflags=CREATE_NO_WINDOW,
            )
            payload = json.loads(result.stdout or "{}")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            raise LibraryError(f"FFprobe failed for {job.path}: {error}") from error
        format_info = payload.get("format") or {}
        streams = payload.get("streams") or []
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        tags = {str(key).casefold(): _safe_text(value) for key, value in (format_info.get("tags") or {}).items()}
        tags.update({str(key).casefold(): _safe_text(value) for key, value in (audio.get("tags") or {}).items()})
        embedded_lyrics = None
        artwork = False
        try:
            mutagen = MutagenFile(job.path, easy=False)
            for key, value in (getattr(mutagen, "tags", {}) or {}).items():
                lowered = str(key).casefold()
                if any(marker in lowered for marker in ("uslt", "sylt", "lyrics")):
                    embedded_lyrics = embedded_lyrics or _safe_text(value)
                if lowered.startswith(("apic", "covr", "metadata_block_picture")):
                    artwork = True
        except (MutagenError, OSError, ValueError):
            pass
        duration = format_info.get("duration") or audio.get("duration")
        try:
            duration = float(duration) if duration not in {None, "N/A"} else None
        except (TypeError, ValueError):
            duration = None
        metadata = {
            "title": tags.get("title"),
            "artist": tags.get("artist"),
            "album": tags.get("album"),
            "genre": tags.get("genre"),
            "date": tags.get("date") or tags.get("year"),
            "track": tags.get("track") or tags.get("tracknumber"),
            "duration": duration,
            "format": format_info.get("format_name"),
            "bit_rate": format_info.get("bit_rate"),
            "codec": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
            "artwork_embedded": artwork,
        }
        features = {
            key: metadata[key]
            for key in ("artist", "album", "genre", "date", "duration", "codec")
            if metadata.get(key) is not None
        }
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE library_files SET metadata_json=?, embedded_lyrics=?, features_json=?, probe_version=?, "
                "updated_at=? WHERE library_id=?",
                (
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    embedded_lyrics,
                    json.dumps(features, ensure_ascii=False, sort_keys=True),
                    PROBE_VERSION,
                    time.time(),
                    job.library_id,
                ),
            )
            self._schedule(connection, job.library_id, "fingerprint", priority=50)

    def _fingerprint(self, job: LibraryJob) -> None:
        duration, fingerprint = fingerprint_file(job.path, self.fpcalc_bin)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE library_files SET fingerprint=?, fingerprint_duration=?, updated_at=? WHERE library_id=?",
                (fingerprint, duration, time.time(), job.library_id),
            )

    def process_jobs(self, stage: str, *, limit: int = 1, owner: str | None = None) -> int:
        if stage not in {"probe", "fingerprint"}:
            raise LibraryError(f"Unknown profiling stage: {stage}")
        owner = owner or f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
        jobs = self.lease_jobs(stage, limit, owner)
        for job in jobs:
            try:
                self._probe(job) if stage == "probe" else self._fingerprint(job)
            except (LibraryError, IdentificationError, OSError) as error:
                self._fail(job, stage, error)
            else:
                self._complete(job)
        return len(jobs)

    def status(self) -> dict[str, Any]:
        files = self.database.fetchone(
            "SELECT COUNT(*) total, SUM(state='available') available, SUM(state='missing') missing FROM library_files"
        )
        jobs = self.database.fetchall("SELECT stage, status, COUNT(*) count FROM library_jobs GROUP BY stage, status")
        latest = self.database.fetchone("SELECT * FROM library_scan_runs ORDER BY started_at DESC LIMIT 1")
        return {
            "files": dict(files) if files else {"total": 0, "available": 0, "missing": 0},
            "jobs": [dict(row) for row in jobs],
            "scan": dict(latest) if latest else None,
        }

    def errors(self) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.database.fetchall(
                "SELECT j.job_id, j.library_id, j.stage, j.attempts, j.error_code, j.error_text, "
                "f.canonical_path FROM library_jobs j JOIN library_files f ON f.library_id=j.library_id "
                "WHERE j.status='failed' ORDER BY j.updated_at DESC"
            )
        ]

    def retry(self, library_id: str | None = None) -> int:
        with self.database.transaction() as connection:
            if library_id:
                cursor = connection.execute(
                    "UPDATE library_jobs SET status='pending', next_retry=0, lease_owner=NULL, lease_until=NULL, "
                    "error_code=NULL, error_text=NULL WHERE library_id=? AND status='failed'",
                    (library_id,),
                )
            else:
                cursor = connection.execute(
                    "UPDATE library_jobs SET status='pending', next_retry=0, lease_owner=NULL, lease_until=NULL, "
                    "error_code=NULL, error_text=NULL WHERE status='failed'"
                )
        return cursor.rowcount

    def clean_missing(self) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM library_files WHERE state='missing'")
        return cursor.rowcount

    def verify(self) -> dict[str, Any]:
        integrity = self.database.fetchone("PRAGMA integrity_check")
        missing = [path for path in self.paths() if not Path(path).is_file()]
        return {"database": integrity[0] if integrity else "unknown", "unavailable_paths": missing}

    def info(self, value: str) -> dict[str, Any] | None:
        if value.isdigit():
            rows = self.database.fetchall("SELECT * FROM library_files ORDER BY path_key LIMIT 1 OFFSET ?", (int(value) - 1,))
            row = rows[0] if rows else None
        else:
            row = self.database.fetchone("SELECT * FROM library_files WHERE path_key=?", (path_key(value),))
        if not row:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        result["features"] = json.loads(result.pop("features_json") or "{}")
        return result
