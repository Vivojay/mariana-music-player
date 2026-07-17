import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.download_jobs import DownloadManager
from mariana.library import LibraryCatalog, LibraryError, parse_library_file
from mariana.models import MediaChapter, MediaRef, MediaSource


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


def test_probe_prefers_trusted_download_source_tags_over_placeholders(monkeypatch, tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    song = root / "Unknown Artist - YouTube audio [dYsg37kwCwM].mp3"
    song.write_bytes(b"audio")
    database, library = catalog(tmp_path, root)
    payload = {
        "format": {
            "duration": "180",
            "format_name": "mp3",
            "tags": {
                "title": "YouTube audio",
                "artist": "Unknown Artist",
                "youtube_id": "dYsg37kwCwM",
                "purl": "https://www.youtube.com/watch?v=dYsg37kwCwM",
                "mariana_source_title": "Actual Song",
                "mariana_source_artist": "Actual Artist",
                "mariana_metadata_source": "youtube-download",
                "mariana_metadata_confidence": "trusted",
            },
        },
        "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
    }
    monkeypatch.setattr("mariana.library.find_executable", lambda *_args: "ffprobe")
    monkeypatch.setattr(
        "mariana.library.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    monkeypatch.setattr("mariana.library.MutagenFile", lambda *_args, **_kwargs: SimpleNamespace(tags={}))
    try:
        library.scan()
        assert library.process_jobs("probe") == 1
        info = library.info("1")
        media = library.media_refs()[0]
        assert info["metadata"]["title"] == media.title == "Actual Song"
        assert info["metadata"]["artist"] == media.artist == "Actual Artist"
        assert info["metadata"]["metadata_source"] == "youtube-download"
        assert "youtube.com" not in f"{media.title} {media.artist}"
        assert str(song) not in f"{media.title} {media.artist}"
    finally:
        database.close()


@pytest.mark.parametrize(
    ("suffix", "format_name"),
    [
        (".mp3", "mp3"),
        (".m4a", "mov,mp4,m4a,3gp,3g2,mj2"),
        (".mp4", "mov,mp4,m4a,3gp,3g2,mj2"),
        (".webm", "matroska,webm"),
        (".mkv", "matroska,webm"),
    ],
)
def test_probe_persists_embedded_chapters_idempotently(
    monkeypatch, tmp_path: Path, suffix: str, format_name: str
):
    root = tmp_path / "music"
    root.mkdir()
    media_path = root / f"chaptered{suffix}"
    media_path.write_bytes(b"media")
    library_file = tmp_path / "lib.lib"
    write_library(library_file, root)
    database = MarianaDatabase(tmp_path / "chapters.db")
    library = LibraryCatalog(
        database,
        library_file=library_file,
        supported_extensions=[suffix],
        ffmpeg_bin=str(tmp_path),
        fpcalc_bin=str(tmp_path),
    )
    payload = {
        "format": {"duration": "60", "format_name": format_name, "tags": {"title": "Chaptered"}},
        "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        "chapters": [
            {"start_time": "30", "end_time": "80", "tags": {"title": "Second"}},
            {"start_time": "0", "end_time": "40", "tags": {"TITLE": " Intro\nPart "}},
            {"start_time": "bad", "end_time": "50", "tags": {"title": "Invalid"}},
            {"start_time": "60", "end_time": "50", "tags": {"title": "Backwards"}},
        ],
    }
    commands = []

    def ffprobe(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    monkeypatch.setattr("mariana.library.find_executable", lambda *_args: "ffprobe")
    monkeypatch.setattr("mariana.library.subprocess.run", ffprobe)
    monkeypatch.setattr("mariana.library.MutagenFile", lambda *_args, **_kwargs: SimpleNamespace(tags={}))
    try:
        assert library.scan().changed == 1
        assert library.process_jobs("probe") == 1
        expected = [MediaChapter("Intro Part", 0, 30), MediaChapter("Second", 30, 60)]
        assert library.media_refs()[0].chapters == expected
        assert library.info("1")["metadata"]["chapters"] == [
            {"title": "Intro Part", "start_time": 0.0, "end_time": 30.0},
            {"title": "Second", "start_time": 30.0, "end_time": 60.0},
        ]
        stored = json.loads(database.fetchone("SELECT chapters_json FROM media_items")["chapters_json"])
        assert len(stored) == 2
        assert any(
            "chapter=start_time,end_time:chapter_tags=title" in argument
            for argument in commands[0]
        )

        assert library.scan("full").changed == 1
        assert library.process_jobs("probe") == 1
        assert library.media_refs()[0].chapters == expected
        assert len(json.loads(database.fetchone("SELECT chapters_json FROM media_items")["chapters_json"])) == 2
    finally:
        database.close()


def test_trusted_download_metadata_survives_library_reload_and_reprobe(monkeypatch, tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    database, library = catalog(tmp_path, root)
    manager = DownloadManager(database, autostart=False)
    online = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=yWHrYNP6j4k",
        title="The Kid LAROI, Justin Bieber - Stay (Lyrics)",
        artist="7clouds",
    )
    job = manager.create(
        [online],
        destination=root,
        metadata=[
            {
                "source_title": "The Kid LAROI, Justin Bieber - Stay (Lyrics)",
                "source_artist": "7clouds",
            }
        ],
    )
    item = manager.items(job.job_id)[0]
    trusted = {
        **item.metadata,
        "title": "The Kid LAROI, Justin Bieber - Stay (Lyrics)",
        "artist": "7clouds",
        "source_title": "The Kid LAROI, Justin Bieber - Stay (Lyrics)",
        "source_artist": "7clouds",
        "source_uploader": "7clouds",
        "source_channel": "7clouds",
        "duration": 180,
        "chapters": [
            {"title": "Intro", "start_time": 0, "end_time": 30},
            {"title": "Song", "start_time": 30, "end_time": 180},
        ],
        "metadata_source": "youtube-download",
        "metadata_confidence": "trusted",
    }
    output = Path(item.output_path)
    output.write_bytes(b"audio")
    with database.transaction() as connection:
        connection.execute(
            "UPDATE download_items SET state='completed',metadata_json=? WHERE item_id=?",
            (json.dumps(trusted), item.item_id),
        )
        connection.execute(
            "UPDATE download_jobs SET state='completed',completed_items=1 WHERE job_id=?",
            (job.job_id,),
        )
    payload = {
        "format": {"duration": "180", "format_name": "mp3", "tags": {}},
        "streams": [{"codec_type": "audio", "codec_name": "mp3"}],
    }
    monkeypatch.setattr("mariana.library.find_executable", lambda *_args: "ffprobe")
    monkeypatch.setattr(
        "mariana.library.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, json.dumps(payload), ""),
    )
    monkeypatch.setattr("mariana.library.MutagenFile", lambda *_args, **_kwargs: SimpleNamespace(tags={}))
    try:
        library.scan()
        before_probe = library.info("1")["metadata"]
        assert before_probe["source_title"] == "The Kid LAROI, Justin Bieber - Stay (Lyrics)"
        assert before_probe["source_artist"] == "7clouds"
        assert before_probe["source_uploader"] == "7clouds"
        assert before_probe["source_channel"] == "7clouds"

        assert library.process_jobs("probe") == 1
        persisted = json.loads(
            database.fetchone("SELECT metadata_json FROM library_files")["metadata_json"]
        )
        assert persisted["source_title"] == before_probe["source_title"]
        assert persisted["source_artist"] == before_probe["source_artist"]
        assert len(persisted["chapters"]) == 2
        assert library.media_refs()[0].chapter_at(45) == MediaChapter("Song", 30, 180)

        output.write_bytes(b"changed-audio")
        assert library.scan("changed").changed == 1
        assert library.process_jobs("probe") == 1
        reloaded = library.info("1")["metadata"]
        assert reloaded["source_title"] == before_probe["source_title"]
        assert reloaded["source_artist"] == before_probe["source_artist"]
        assert len(reloaded["chapters"]) == 2
        assert "youtube.com" not in json.dumps(reloaded)
    finally:
        manager.close()
        database.close()


def test_download_metadata_bridge_rejects_untrusted_mismatched_and_placeholder_records(tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    database, library = catalog(tmp_path, root)
    manager = DownloadManager(database, autostart=False)
    online = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=yWHrYNP6j4k",
        title="Actual Song",
    )
    job = manager.create([online], destination=root)
    item = manager.items(job.job_id)[0]
    output = Path(item.output_path)
    base = {
        "video_id": "yWHrYNP6j4k",
        "source_title": "Actual Song",
        "metadata_source": "youtube-download",
        "metadata_confidence": "trusted",
    }

    def persist(metadata, *, output_path=output):
        with database.transaction() as connection:
            connection.execute(
                "UPDATE download_items SET state='completed',output_path=?,metadata_json=? WHERE item_id=?",
                (str(output_path), json.dumps(metadata), item.item_id),
            )

    try:
        persist({**base, "metadata_source": "external"})
        assert library._trusted_download_metadata(output, "yWHrYNP6j4k") == {}

        persist({**base, "metadata_confidence": "placeholder"})
        assert library._trusted_download_metadata(output, "yWHrYNP6j4k") == {}

        persist({**base, "video_id": "dYsg37kwCwM"})
        assert library._trusted_download_metadata(output, "yWHrYNP6j4k") == {}

        persist({**base, "source_title": "YouTube audio"})
        assert library._trusted_download_metadata(output, "yWHrYNP6j4k") == {}

        path_only = root / "path-only.mp3"
        persist(
            {
                "source_title": "Path-attributed song",
                "metadata_source": "youtube-download",
                "metadata_confidence": "trusted",
            },
            output_path=path_only,
        )
        assert library._trusted_download_metadata(path_only, None) == {
            "title": "Path-attributed song",
            "source_title": "Path-attributed song",
            "metadata_source": "youtube-download",
            "metadata_confidence": "trusted",
        }
    finally:
        manager.close()
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
        root_columns = {row["name"] for row in database.fetchall("PRAGMA table_info(library_roots)")}
        assert "origin" in root_columns
        assert database.fetchone("SELECT name FROM sqlite_master WHERE name='media_preferences'")
    backup = path.with_suffix(path.suffix + f".pre-schema-{SCHEMA_VERSION}.bak")
    assert backup.is_file()
    check = sqlite3.connect(backup)
    try:
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert check.execute("SELECT value FROM schema_meta").fetchone()[0] == "1"
    finally:
        check.close()


def test_managed_download_root_is_separate_from_library_file(tmp_path: Path):
    library_file = tmp_path / "lib.lib"
    user_root = tmp_path / "user"
    downloads = tmp_path / "downloads"
    user_root.mkdir()
    downloads.mkdir()
    library_file.write_text(str(user_root), encoding="utf-8")
    enabled = [True]
    with MarianaDatabase(tmp_path / "managed.db") as database:
        library = LibraryCatalog(
            database,
            library_file=library_file,
            supported_extensions=[".mp3"],
            managed_roots=lambda: [(downloads, "downloads")] if enabled[0] else [],
        )
        roots = library.sync_roots()
        assert {root["origin"] for root in roots} == {"library-file", "downloads"}
        enabled[0] = False
        roots = library.sync_roots()
        download_row = next(root for root in roots if root["origin"] == "downloads")
        assert download_row["available"] == 0
        assert library_file.read_text(encoding="utf-8") == str(user_root)
