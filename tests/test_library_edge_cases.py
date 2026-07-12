import ctypes
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from mariana.database import MarianaDatabase
from mariana.library import (
    LibraryCatalog,
    LibraryError,
    LibraryJob,
    _safe_text,
    content_signature,
    file_key,
    parse_library_file,
    root_kind,
)
from mariana.models import IdentityStatus, TrackIdentity


def make_catalog(tmp_path, root=None, **kwargs):
    library_file = tmp_path / "lib.lib"
    library_file.write_text(f"{root}\n" if root else "# empty\n", encoding="utf-8")
    database = MarianaDatabase(tmp_path / "library.db")
    return database, LibraryCatalog(
        database,
        library_file=library_file,
        supported_extensions=["mp3"],
        **kwargs,
    )


def test_helpers_cover_missing_large_and_platform_variants(monkeypatch, tmp_path):
    assert parse_library_file(tmp_path / "missing.lib") == []
    large = tmp_path / "large.mp3"
    large.write_bytes(b"a" * 70_000 + b"b" * 70_000)
    assert len(content_signature(large, large.stat().st_size)) == 64
    assert _safe_text(None) is None
    assert _safe_text(["a", None, "b"]) == "a; b"
    assert _safe_text(SimpleNamespace(text=" lyric ")) == "lyric"
    assert _safe_text("  ") is None
    assert file_key(SimpleNamespace(st_dev=1, st_ino=0)) is None
    assert root_kind(Path("//server/share")) == "network"
    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", lambda _anchor: 2)
    assert root_kind(tmp_path) == "removable"
    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", lambda _anchor: 4)
    assert root_kind(tmp_path) == "network"
    monkeypatch.setattr(
        ctypes.windll.kernel32,
        "GetDriveTypeW",
        lambda _anchor: (_ for _ in ()).throw(OSError("unavailable")),
    )
    assert root_kind(tmp_path) == "local"


def test_sync_empty_roots_and_walk_entry_errors(monkeypatch, tmp_path):
    database, library = make_catalog(tmp_path)
    try:
        assert library.sync_roots() == []

        class Entry:
            path = str(tmp_path / "x.mp3")

            def is_symlink(self):
                return False

            def is_dir(self, **_kwargs):
                return False

            def is_file(self, **_kwargs):
                raise OSError("denied")

        monkeypatch.setattr(os, "scandir", lambda _path: [Entry()])
        assert list(library._walk(tmp_path)) == []
        monkeypatch.setattr(os, "scandir", lambda _path: (_ for _ in ()).throw(OSError("denied")))
        with pytest.raises(LibraryError):
            list(library._walk(tmp_path))
    finally:
        database.close()


def test_scan_invalid_removed_root_and_walk_failure(monkeypatch, tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    database, library = make_catalog(tmp_path, root)
    try:
        with pytest.raises(LibraryError):
            library.scan("invalid")
        library.sync_roots()
        library.library_file.write_text("# removed\n", encoding="utf-8")
        assert library.scan().discovered == 0
        library.library_file.write_text(f"{root}\n", encoding="utf-8")
        monkeypatch.setattr(library, "_walk", lambda _root: (_ for _ in ()).throw(LibraryError("denied")))
        result = library.scan()
        assert result.errors == 1
        assert library.roots()[0]["error"] == "denied"
    finally:
        database.close()


def test_duplicate_content_stays_distinct_and_media_refs_are_normalized(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    (root / "one.mp3").write_bytes(b"same")
    (root / "two.mp3").write_bytes(b"same")
    database, library = make_catalog(tmp_path, root)
    try:
        library.scan()
        rows = database.fetchall("SELECT library_id FROM library_files")
        assert len({row["library_id"] for row in rows}) == 2
        with database.transaction() as connection:
            connection.execute(
                "UPDATE library_files SET metadata_json=?, fingerprint='fp' WHERE library_id=?",
                (json.dumps({"title": "Title", "duration": 2}), rows[0]["library_id"]),
            )
        refs = library.media_refs()
        assert len(refs) == 2
        assert any(ref.title == "Title" and ref.stable_id == rows[0]["library_id"] for ref in refs)
        assert all(ref.provenance == "library" and not ref.capabilities.downloadable for ref in refs)
    finally:
        database.close()


def test_expired_job_leases_are_reclaimed(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    (root / "track.mp3").touch()
    database, library = make_catalog(tmp_path, root)
    try:
        library.scan()
        first = library.lease_jobs("probe", 1, "first", lease_seconds=-1)
        second = library.lease_jobs("probe", 1, "second")
        assert first[0].job_id == second[0].job_id
        row = database.fetchone("SELECT lease_owner FROM library_jobs WHERE job_id=?", (first[0].job_id,))
        assert row["lease_owner"] == "second"
    finally:
        database.close()


def test_probe_extracts_embedded_data_and_handles_bad_duration(monkeypatch, tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    (root / "track.mp3").touch()
    database, library = make_catalog(tmp_path, root)
    payload = {
        "format": {"duration": "bad", "format_name": "mp3", "tags": {"genre": ["Rock", "Alt"]}},
        "streams": [{"codec_type": "audio", "tags": {"year": "2020"}}],
    }
    monkeypatch.setattr("mariana.library.find_executable", lambda *_args: "ffprobe")
    monkeypatch.setattr(
        "mariana.library.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    monkeypatch.setattr(
        "mariana.library.MutagenFile",
        lambda *_args, **_kwargs: SimpleNamespace(
            tags={"USLT::eng": SimpleNamespace(text="words"), "APIC:cover": object()}
        ),
    )
    try:
        library.scan()
        library.process_jobs("probe")
        info = library.info("1")
        assert info["embedded_lyrics"] == "words"
        assert info["metadata"]["artwork_embedded"] is True
        assert info["metadata"]["duration"] is None
        assert info["metadata"]["genre"] == "Rock; Alt"
    finally:
        database.close()


def test_online_enrichment_reuses_fingerprint(monkeypatch, tmp_path):
    class Identity:
        def __init__(self):
            self.calls = []

        def identify_fingerprint(self, media, duration, fingerprint):
            self.calls.append((media, duration, fingerprint))
            return TrackIdentity(IdentityStatus.NO_MATCH)

        def lyrics(self, media, identity):
            self.calls.append((media, identity))

    identity = Identity()
    root = tmp_path / "music"
    root.mkdir()
    (root / "track.mp3").touch()
    database, library = make_catalog(
        tmp_path,
        root,
        identity_service=identity,
        online_enrichment=True,
    )
    monkeypatch.setattr("mariana.library.fingerprint_file", lambda *_args, **_kwargs: (10, "fp"))
    try:
        library.scan()
        job = library.lease_jobs("probe", 1, "test")[0]
        with database.transaction() as connection:
            connection.execute(
                "UPDATE library_files SET metadata_json=? WHERE library_id=?",
                (json.dumps({"title": "Track", "duration": 10}), job.library_id),
            )
            library._schedule(connection, job.library_id, "fingerprint")
        library.process_jobs("fingerprint")
        assert library.process_jobs("enrich") == 1
        assert identity.calls[0][1:] == (10.0, "fp")
        disabled = LibraryCatalog(database, online_enrichment=False)
        disabled._enrich(LibraryJob(0, job.library_id, "enrich", root / "track.mp3", 0))
    finally:
        database.close()


def test_enrich_missing_fingerprint_retry_all_verify_and_path_info(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    song = root / "track.mp3"
    song.touch()
    database, library = make_catalog(tmp_path, root, identity_service=object(), online_enrichment=True)
    try:
        library.scan()
        info = library.info(str(song))
        job = LibraryJob(0, info["library_id"], "enrich", song, 0)
        with pytest.raises(LibraryError):
            library._enrich(job)
        leased = library.lease_jobs("probe", 1, "owner")[0]
        library._fail(leased, "probe", OSError("bad"))
        assert library.retry() == 1
        song.unlink()
        assert library.verify()["unavailable_paths"] == [str(song.absolute())]
        assert library.info("999") is None
        assert library.info("missing.mp3") is None
    finally:
        database.close()
