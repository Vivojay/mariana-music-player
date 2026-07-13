from contextlib import contextmanager
from pathlib import Path

import pytest

from mariana.database import MarianaDatabase
from mariana.library import LibraryCatalog, LibraryError, path_key
from mariana.media_details import (
    clean_component,
    extract_year,
    extract_youtube_id,
    flattened_details,
    short_filename,
)


def test_short_filename_uses_priority_order_and_optional_fields():
    path = Path("old.mp3")
    assert short_filename(path, {
        "artist": "Artist",
        "releaser": "Label",
        "distributor": "Distributor",
        "title": "Song: One?",
        "date": "2024-08-01",
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    }) == "Artist - Song- One 2024 [dQw4w9WgXcQ].mp3"
    assert short_filename(path, {"releaser": "Label", "title": "Song"}) == "Label - Song.mp3"
    assert short_filename(path, {"distributor": "Dist"}) == "Dist - old.mp3"


def test_filename_helpers_reject_unsafe_characters_and_false_ids():
    assert clean_component('CON') == '_CON'
    assert clean_component(' a/b:*c ') == 'a-b--c'
    assert extract_year('recorded 1998-03') == '1998'
    assert extract_year('unknown') is None
    assert extract_youtube_id({}, 'track [12345678].mp3') is None
    assert extract_youtube_id({"comment": "source youtu.be/aqz-KE-bpKQ"}) == 'aqz-KE-bpKQ'
    assert extract_youtube_id({"webpage_url": "https://youtu.be/dQw4w9WgXcQ?t=4"}) == "dQw4w9WgXcQ"
    assert extract_youtube_id({"webpage_url": "https://youtube.com/watch?v=aqz-KE-bpKQ"}) == "aqz-KE-bpKQ"
    assert extract_youtube_id({"webpage_url": "https://youtube.com/watch?v=short"}) is None
    assert extract_youtube_id({}, "Artist - Track [dQw4w9WgXcQ].flac") == "dQw4w9WgXcQ"


def test_flattened_details_summarizes_fingerprint_without_dumping_it():
    rows = dict(flattened_details({
        "library_id": "id",
        "canonical_path": "track.flac",
        "metadata": {"title": "Track", "empty": None},
        "fingerprint": "abc" * 100,
    }))
    assert rows["Title"] == "Track"
    assert rows["Chromaprint"].startswith("300 characters")
    rows = dict(flattened_details({"metadata": {}, "loudness": {"track_gain_db": -3.0}}))
    assert "track_gain_db" in rows["ReplayGain"]


def test_library_rename_updates_stable_occurrence_and_media_item(tmp_path):
    database = MarianaDatabase(tmp_path / "catalog.sqlite3")
    root = tmp_path / "music"
    root.mkdir()
    source = root / "old.mp3"
    source.write_bytes(b"media")
    library_file = tmp_path / "lib.lib"
    library_file.write_text(str(root), encoding="utf-8")
    catalog = LibraryCatalog(database, library_file=library_file, supported_extensions=(".mp3",))
    catalog.scan("changed")
    before = catalog.info(str(source))
    assert before is not None
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO media_items(stable_id, source, original_uri, capabilities_json, resolver_json, provenance, updated_at) "
            "VALUES(?, 'local', ?, '{}', '{}', 'library', 0)",
            (before["library_id"], str(source)),
        )

    renamed = catalog.rename(before["library_id"], "Artist - Track 2024.mp3")
    assert renamed.is_file() and not source.exists()
    after = catalog.info(str(renamed))
    assert after is not None and after["library_id"] == before["library_id"]
    media = database.fetchone("SELECT original_uri FROM media_items WHERE stable_id=?", (before["library_id"],))
    assert media["original_uri"] == str(renamed.absolute())
    assert after["path_key"] == path_key(renamed)

    collision = root / "collision.mp3"
    collision.write_bytes(b"other")
    with pytest.raises(LibraryError, match="already exists"):
        catalog.rename(before["library_id"], collision.name)
    assert renamed.is_file() and collision.read_bytes() == b"other"
    database.close()


def test_library_rename_rejects_paths_and_extension_changes(tmp_path):
    database = MarianaDatabase(tmp_path / "catalog.sqlite3")
    root = tmp_path / "music"
    root.mkdir()
    source = root / "old.mp3"
    source.write_bytes(b"media")
    library_file = tmp_path / "lib.lib"
    library_file.write_text(str(root), encoding="utf-8")
    catalog = LibraryCatalog(database, library_file=library_file, supported_extensions=(".mp3",))
    catalog.scan("changed")
    item = catalog.info(str(source))
    with pytest.raises(LibraryError, match="filename"):
        catalog.rename(item["library_id"], "nested/new.mp3")
    with pytest.raises(LibraryError, match="extension"):
        catalog.rename(item["library_id"], "new.flac")
    assert catalog.rename(item["library_id"], source.name) == source
    assert catalog.info(item["library_id"])["canonical_path"] == str(source.absolute())
    with pytest.raises(LibraryError, match="not found"):
        catalog.rename("missing", "new.mp3")
    source.unlink()
    with pytest.raises(LibraryError, match="non-symlink"):
        catalog.rename(item["library_id"], "new.mp3")
    database.close()


def test_library_rename_rolls_file_back_when_database_update_fails(monkeypatch, tmp_path):
    database = MarianaDatabase(tmp_path / "catalog.sqlite3")
    root = tmp_path / "music"
    root.mkdir()
    source = root / "old.mp3"
    source.write_bytes(b"media")
    library_file = tmp_path / "lib.lib"
    library_file.write_text(str(root), encoding="utf-8")
    catalog = LibraryCatalog(database, library_file=library_file, supported_extensions=(".mp3",))
    catalog.scan("changed")
    item = catalog.info(str(source))
    real_transaction = database.transaction

    @contextmanager
    def failed_transaction():
        raise RuntimeError("database is read-only")
        yield

    monkeypatch.setattr(database, "transaction", failed_transaction)
    with pytest.raises(LibraryError, match="Could not rename"):
        catalog.rename(item["library_id"], "new.mp3")
    assert source.is_file()
    assert not (root / "new.mp3").exists()
    monkeypatch.setattr(database, "transaction", real_transaction)
    database.close()
