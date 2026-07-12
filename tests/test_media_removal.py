from pathlib import Path

import pytest

from mariana.database import MarianaDatabase
from mariana.library import LibraryCatalog
from mariana.media_removal import MediaRemovalError, MediaRemovalPartialError, MediaRemovalService
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue


class Controller:
    def __init__(self, media=None):
        self.media = media
        self.stopped = False

    def snapshot(self):
        return PlaybackSnapshot(PlaybackState.PLAYING if self.media else PlaybackState.IDLE, media=self.media)

    def stop(self):
        self.stopped = True


def removal_fixture(tmp_path: Path):
    root = tmp_path / "music"
    root.mkdir()
    song = root / "song.mp3"
    song.write_bytes(b"audio")
    library_file = tmp_path / "lib.lib"
    library_file.write_text(str(root), encoding="utf-8")
    database = MarianaDatabase(tmp_path / "state.db")
    catalog = LibraryCatalog(database, library_file=library_file, supported_extensions=[".mp3"])
    catalog.scan()
    info = catalog.info(str(song))
    queue = PersistentQueue(database)
    media = MediaRef(MediaSource.LOCAL, str(song), stable_id=info["library_id"], title="Song")
    queue.add(media)
    return database, catalog, queue, song, media


def test_successful_removal_uses_trash_tombstones_and_retains_preferences(tmp_path: Path):
    database, catalog, queue, song, media = removal_fixture(tmp_path)
    trashed = []

    def trash(path):
        trashed.append(path)
        Path(path).unlink()

    controller = Controller(media)
    preferences = MediaPreferences(database)
    preferences.set(media, PreferenceState.FAVORITE)
    service = MediaRemovalService(database, catalog, queue, controller, trash=trash)
    target = service.resolve("1")
    service.remove(target)
    assert trashed == [str(song.resolve())]
    assert controller.stopped is True
    assert catalog.info(str(song))["state"] == "missing"
    assert queue.items() == []
    assert preferences.get(media) == PreferenceState.FAVORITE
    assert database.fetchall("SELECT key FROM app_state WHERE key LIKE 'media_removal:%'") == []
    database.close()


def test_cancelled_or_failed_trash_does_not_change_database(tmp_path: Path):
    database, catalog, queue, song, media = removal_fixture(tmp_path)
    service = MediaRemovalService(
        database,
        catalog,
        queue,
        Controller(),
        trash=lambda _path: (_ for _ in ()).throw(OSError("denied")),
    )
    with pytest.raises(MediaRemovalError, match="denied"):
        service.remove(service.resolve(str(song)))
    assert catalog.info(str(song))["state"] == "available"
    assert [item.media.stable_id for item in queue.items()] == [media.stable_id]
    assert song.exists()
    assert database.fetchall("SELECT key FROM app_state WHERE key LIKE 'media_removal:%'") == []
    database.close()


def test_post_trash_database_failure_is_recovered_from_journal(monkeypatch, tmp_path: Path):
    database, catalog, queue, song, media = removal_fixture(tmp_path)
    original = catalog.mark_missing
    service = MediaRemovalService(database, catalog, queue, Controller(), trash=lambda path: Path(path).unlink())
    monkeypatch.setattr(catalog, "mark_missing", lambda _stable_id: (_ for _ in ()).throw(RuntimeError("disk")))
    with pytest.raises(MediaRemovalPartialError, match="reconciliation"):
        service.remove(service.resolve(str(song)))
    assert database.fetchall("SELECT key FROM app_state WHERE key LIKE 'media_removal:%'")
    monkeypatch.setattr(catalog, "mark_missing", original)
    assert service.recover() == 1
    assert catalog.info(str(song))["state"] == "missing"
    assert queue.items() == []
    assert database.fetchall("SELECT key FROM app_state WHERE key LIKE 'media_removal:%'") == []
    assert media.stable_id
    database.close()


def test_resolve_rejects_invalid_outside_and_symlink_targets(monkeypatch, tmp_path: Path):
    database, catalog, queue, song, _media = removal_fixture(tmp_path)
    service = MediaRemovalService(database, catalog, queue, Controller(), trash=lambda _path: None)
    with pytest.raises(MediaRemovalError, match="positive"):
        service.resolve("0")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"audio")
    original_info = catalog.info
    monkeypatch.setattr(
        catalog,
        "info",
        lambda _value: {"library_id": "outside", "canonical_path": str(outside), "state": "available"},
    )
    with pytest.raises(MediaRemovalError, match="outside"):
        service.resolve(str(outside))
    monkeypatch.setattr(catalog, "info", original_info)
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == song or original_is_symlink(self))
    with pytest.raises(MediaRemovalError, match="non-symlink"):
        service.resolve(str(song))
    database.close()


def test_recovery_clears_planned_journal_when_file_still_exists(tmp_path: Path):
    database, catalog, queue, song, media = removal_fixture(tmp_path)
    database.set_state(
        "media_removal:planned",
        {"library_id": media.stable_id, "path": str(song), "status": "planned"},
    )
    service = MediaRemovalService(database, catalog, queue, Controller(), trash=lambda _path: None)
    assert service.recover() == 0
    assert database.get_state("media_removal:planned") is None
    assert catalog.info(str(song))["state"] == "available"
    database.close()


def test_resolve_rejects_unindexed_missing_and_unsupported_media(monkeypatch, tmp_path: Path):
    database, catalog, queue, song, _media = removal_fixture(tmp_path)
    service = MediaRemovalService(database, catalog, queue, Controller(), trash=lambda _path: None)
    with pytest.raises(MediaRemovalError, match="available indexed"):
        service.resolve("999")
    monkeypatch.setattr(
        catalog,
        "info",
        lambda _value: {"library_id": "wrong", "canonical_path": str(song), "state": "missing"},
    )
    with pytest.raises(MediaRemovalError, match="available indexed"):
        service.resolve(str(song))
    monkeypatch.setattr(
        catalog,
        "info",
        lambda _value: {"library_id": "wrong", "canonical_path": str(song), "state": "available"},
    )
    monkeypatch.setattr(catalog, "supported_extensions", {".flac"})
    with pytest.raises(MediaRemovalError, match="not supported"):
        service.resolve(str(song))
    database.close()


def test_non_active_or_nonlocal_media_is_not_stopped(tmp_path: Path):
    database, catalog, queue, song, _media = removal_fixture(tmp_path)
    for active in (None, MediaRef(MediaSource.URL, "https://example.test/a"), MediaRef(MediaSource.LOCAL, str(song) + ".other")):
        controller = Controller(active)
        service = MediaRemovalService(database, catalog, queue, controller, trash=lambda _path: None)
        service.trash = lambda _path: None
        target = service.resolve(str(song))
        monkey = catalog.mark_missing
        catalog.mark_missing = lambda _library_id: None
        service.remove(target)
        catalog.mark_missing = monkey
        assert controller.stopped is False
    database.close()


def test_recovery_discards_invalid_journal_and_retains_unknown_tombstone(tmp_path: Path):
    database, catalog, queue, song, _media = removal_fixture(tmp_path)
    service = MediaRemovalService(database, catalog, queue, Controller(), trash=lambda _path: None)
    database.set_state("media_removal:invalid", {})
    unknown_path = song.with_name("unknown.mp3")
    database.set_state(
        "media_removal:unknown",
        {"library_id": "does-not-exist", "path": str(unknown_path), "status": "trashed"},
    )
    assert service.recover() == 0
    assert database.get_state("media_removal:invalid") is None
    assert database.get_state("media_removal:unknown")["library_id"] == "does-not-exist"
    database.close()
