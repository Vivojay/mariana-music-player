import ctypes
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import psutil
import pytest

import mariana.library as library_module
from mariana.database import MarianaDatabase
from mariana.library import (
    LibraryCatalog,
    LibraryError,
    LibraryJob,
    _complete_album_group,
    _safe_text,
    content_signature,
    directory_status,
    file_key,
    parse_library_file,
    root_kind,
)
from mariana.models import IdentityStatus, TrackIdentity


class TestPosixPath(PurePosixPath):
    __test__ = False

    def resolve(self):
        return self


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
    monkeypatch.setattr(library_module.sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes,
        "windll",
        SimpleNamespace(kernel32=SimpleNamespace(GetDriveTypeW=lambda _anchor: 2)),
        raising=False,
    )
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
    monkeypatch.setattr(library_module.sys, "platform", "linux")
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=True: [])
    assert root_kind(TestPosixPath("/mnt/music")) == "local"
    available, error = directory_status(SimpleNamespace(is_dir=lambda: (_ for _ in ()).throw(PermissionError("denied"))))
    assert not available
    assert "denied" in error


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


def test_scan_skips_root_removed_from_library_file(monkeypatch, tmp_path):
    database, catalog = make_catalog(tmp_path)
    try:
        monkeypatch.setattr(catalog, "sync_roots", lambda: [{"error": "removed from lib.lib"}])
        result = catalog.scan("changed")
        assert result.discovered == 0
        assert result.changed == 0
    finally:
        database.close()


def test_walk_skips_links_and_descends_directories(monkeypatch, tmp_path):
    database, library = make_catalog(tmp_path)

    class Entry:
        def __init__(self, name, kind):
            self.path = str(tmp_path / name)
            self.kind = kind

        def is_symlink(self): return self.kind == "link"
        def is_dir(self, **_kwargs): return self.kind == "directory"
        def is_file(self, **_kwargs): return self.kind == "file"
        def stat(self, **_kwargs): return SimpleNamespace(st_size=1, st_mtime_ns=1)

    nested = tmp_path / "nested"
    monkeypatch.setattr(
        os,
        "scandir",
        lambda path: [Entry("song.mp3", "file")] if Path(path) == nested else [
            Entry("ignored-link", "link"), Entry("nested", "directory"), Entry("ignored.txt", "file"),
        ],
    )
    try:
        assert [path.name for path, _stat in library._walk(tmp_path)] == ["song.mp3"]
    finally:
        database.close()


@pytest.mark.parametrize(
    ("platform", "partition", "expected"),
    [
        ("linux", SimpleNamespace(mountpoint="/music", fstype="nfs4", opts="rw"), "network"),
        ("linux", SimpleNamespace(mountpoint="/media/disk", fstype="ext4", opts="rw"), "removable"),
        ("darwin", SimpleNamespace(mountpoint="/Volumes/USB", fstype="apfs", opts="rw"), "removable"),
        ("linux", SimpleNamespace(mountpoint="/", fstype="ext4", opts="rw"), "local"),
    ],
)
def test_posix_mount_classification(monkeypatch, platform, partition, expected):
    monkeypatch.setattr(library_module.os, "name", "posix")
    monkeypatch.setattr(library_module.sys, "platform", platform)
    monkeypatch.setattr(library_module, "Path", TestPosixPath)
    monkeypatch.setattr(psutil, "disk_partitions", lambda all=True: [partition])
    assert library_module.root_kind(TestPosixPath(partition.mountpoint) / "music") == expected


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


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ([{"track": "1/2"}], False),
        ([{"track": "1/2"}, {"track": "2/2"}], True),
        ([{"track": "1"}, {"track": "2/2"}], False),
        ([{"track": "1/2"}, {"track": "1/2"}], False),
        ([{"track": "1/2"}, {"track": "2/3"}], False),
        ([{"track": "0/2"}, {"track": "2/2"}], False),
        ([{"track": "1/3"}, {"track": "2/3"}], False),
    ],
)
def test_complete_album_group_requires_consistent_complete_track_numbers(metadata, expected):
    rows = [{"metadata_json": json.dumps(value)} for value in metadata]
    assert _complete_album_group(rows) is expected


def test_library_loudness_album_cache_no_results_and_schedule_modes(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    first, second = root / "one.mp3", root / "two.mp3"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    database, catalog = make_catalog(tmp_path, root, analyze_loudness=True)
    try:
        catalog.scan()
        rows = database.fetchall("SELECT * FROM library_files ORDER BY path_key")
        with database.transaction() as connection:
            for index, row in enumerate(rows, start=1):
                metadata = {"album": "Album", "album_artist": "Artist", "track": f"{index}/2", "disc": "1/1"}
                connection.execute(
                    "UPDATE library_files SET metadata_json=? WHERE library_id=?",
                    (json.dumps(metadata), row["library_id"]),
                )

        class Analyzer:
            def __init__(self):
                self.empty = False

            def analyze(self, paths, *, album=False):
                assert album is True and len(paths) == 2
                if self.empty:
                    return {}
                return {
                    str(path.resolve()): {
                        "track_gain_db": -1.0,
                        "track_peak": 0.8,
                        "album_gain_db": -2.0,
                        "album_peak": 0.9,
                    }
                    for path in paths
                }

        analyzer = Analyzer()
        catalog.rsgain = analyzer
        job = LibraryJob(0, rows[0]["library_id"], "loudness", first, 0)
        catalog._loudness(job)
        assert catalog.loudness.get(rows[1]["library_id"]).complete_album

        cached_job = LibraryJob(0, "copy-id", "loudness", first, 0)
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO library_files(library_id, root_id, canonical_path, path_key, size, mtime_ns, extension, "
                "content_signature, state, scan_generation, metadata_json, updated_at) "
                "SELECT ?, root_id, canonical_path || '.copy', path_key || '.copy', size, mtime_ns, extension, "
                "content_signature, state, scan_generation, metadata_json, updated_at FROM library_files "
                "WHERE library_id=?",
                ("copy-id", rows[0]["library_id"]),
            )
        catalog._loudness(cached_job)
        assert catalog.loudness.get("copy-id").source == "content-cache"

        analyzer.empty = True
        with database.transaction() as connection:
            connection.execute("DELETE FROM loudness_profiles")
            connection.execute("DELETE FROM library_files WHERE library_id='copy-id'")
        with pytest.raises(LibraryError, match="no matching"):
            catalog._loudness(job)

        with pytest.raises(LibraryError, match="scan mode"):
            catalog.schedule_loudness("invalid")
        assert catalog.schedule_loudness("full", rows[0]["library_id"]) == 1
        assert catalog.schedule_loudness("changed") >= 1

        with pytest.raises(LibraryError, match="disappeared"):
            catalog._loudness(LibraryJob(0, "missing", "loudness", first, 0))

        catalog._loudness = lambda _job: None
        assert catalog.process_jobs("loudness", owner="coverage") == 1
    finally:
        database.close()
