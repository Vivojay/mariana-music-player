import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.library import LibraryCatalog, LibraryError, parse_library_file


def write_library(path: Path, *roots: Path) -> None:
    path.write_text("# roots\n\n" + "\n".join(str(root) for root in roots) + "\n", encoding="utf-8")


def catalog(tmp_path: Path, *roots: Path) -> tuple[MarianaDatabase, LibraryCatalog]:
    library_file = tmp_path / "lib.lib"
    write_library(library_file, *roots)
    database = MarianaDatabase(tmp_path / "library.db")
    return database, LibraryCatalog(
        database,
        library_file=library_file,
        supported_extensions=[".mp3", ".FLAC"],
        ffmpeg_bin=str(tmp_path),
        fpcalc_bin=str(tmp_path),
    )


def test_library_parser_expands_deduplicates_and_ignores_comments(monkeypatch, tmp_path: Path):
    root = tmp_path / "Music"
    root.mkdir()
    monkeypatch.setenv("MARIANA_TEST_MUSIC", str(root))
    source = tmp_path / "lib.lib"
    source.write_text(f"# comment\n%MARIANA_TEST_MUSIC%\n{root}\n\n", encoding="utf-8")
    assert parse_library_file(source) == [root.absolute()]


def test_incremental_scan_skips_unchanged_and_preserves_identity_on_move(tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    song = root / "Track.MP3"
    song.write_bytes(b"audio-data")
    database, library = catalog(tmp_path, root)
    try:
        first = library.scan()
        assert (first.discovered, first.changed) == (1, 1)
        original = library.info("1")
        second = library.scan()
        assert (second.discovered, second.changed) == (1, 0)
        moved = root / "Renamed.mp3"
        song.rename(moved)
        third = library.scan()
        assert third.changed == 1
        assert library.info("1")["library_id"] == original["library_id"]
        assert library.paths() == [str(moved.absolute())]
    finally:
        database.close()


def test_missing_files_are_tombstoned_and_only_explicitly_cleaned(tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    song = root / "track.mp3"
    song.touch()
    database, library = catalog(tmp_path, root)
    try:
        library.scan()
        song.unlink()
        library.scan()
        assert library.paths() == []
        assert len(library.paths(include_missing=True)) == 1
        assert library.status()["files"]["missing"] == 1
        assert library.clean_missing() == 1
        assert library.paths(include_missing=True) == []
    finally:
        database.close()


def test_unavailable_root_does_not_tombstone_prior_files(tmp_path: Path):
    root = tmp_path / "removable"
    root.mkdir()
    (root / "track.mp3").touch()
    database, library = catalog(tmp_path, root)
    try:
        library.scan()
        root.rename(tmp_path / "offline")
        result = library.scan()
        assert result.unavailable_roots == 1
        assert len(library.paths()) == 1
        assert library.roots()[0]["available"] == 0
    finally:
        database.close()


def test_probe_and_fingerprint_jobs_are_leased_and_persisted(monkeypatch, tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    song = root / "track.flac"
    song.write_bytes(b"audio")
    database, library = catalog(tmp_path, root)
    payload = {
        "format": {"duration": "12.5", "format_name": "flac", "tags": {"title": "Track", "artist": "Artist"}},
        "streams": [{"codec_type": "audio", "codec_name": "flac", "sample_rate": "48000", "channels": 2}],
    }
    monkeypatch.setattr("mariana.library.find_executable", lambda *_args: "ffprobe")
    monkeypatch.setattr(
        "mariana.library.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    monkeypatch.setattr("mariana.library.MutagenFile", lambda *_args, **_kwargs: SimpleNamespace(tags={}))
    monkeypatch.setattr("mariana.library.fingerprint_file", lambda *_args, **_kwargs: (12.0, "fingerprint"))
    try:
        library.scan()
        assert library.process_jobs("probe", limit=2) == 1
        assert library.process_jobs("fingerprint", limit=2) == 1
        info = library.info("1")
        assert info["metadata"]["title"] == "Track"
        assert info["fingerprint"] == "fingerprint"
        assert library.errors() == []
        assert all(job["status"] == "complete" for job in library.status()["jobs"])
    finally:
        database.close()


def test_failed_jobs_back_off_and_can_be_retried(monkeypatch, tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    (root / "broken.mp3").touch()
    database, library = catalog(tmp_path, root)
    monkeypatch.setattr("mariana.library.find_executable", lambda *_args: "ffprobe")
    monkeypatch.setattr(
        "mariana.library.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("ffprobe", 20)),
    )
    try:
        library.scan()
        library.process_jobs("probe")
        errors = library.errors()
        assert len(errors) == 1 and errors[0]["attempts"] == 1
        assert library.retry(errors[0]["library_id"]) == 1
        assert library.status()["jobs"][0]["status"] == "pending"
        with pytest.raises(LibraryError):
            library.process_jobs("unknown")
    finally:
        database.close()


def test_schema_v1_is_backed_up_and_migrated_atomically(tmp_path: Path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES('schema_version', '1');"
    )
    connection.close()
    with MarianaDatabase(path) as database:
        version = database.fetchone("SELECT value FROM schema_meta WHERE key='schema_version'")[0]
        assert int(version) == SCHEMA_VERSION
        assert database.fetchone("SELECT name FROM sqlite_master WHERE name='library_files'")
    backup = path.with_suffix(path.suffix + f".pre-schema-{SCHEMA_VERSION}.bak")
    assert backup.is_file()
    check = sqlite3.connect(backup)
    try:
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert check.execute("SELECT value FROM schema_meta").fetchone()[0] == "1"
    finally:
        check.close()
