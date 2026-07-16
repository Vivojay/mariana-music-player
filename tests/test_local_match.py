from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from mariana.database import MarianaDatabase
from mariana.local_match import LocalMatchConfidence, LocalMatchStatus, LocalMediaMatcher
from mariana.models import MediaCapabilities, MediaRef, MediaSource


def _online(
    uri: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    *,
    stable_id: str = "online",
    title: str = "Track",
    artist: str = "Artist",
    album: str | None = "Album",
    duration: float | None = 120,
    resolver_data: dict | None = None,
) -> MediaRef:
    return MediaRef(
        MediaSource.YOUTUBE if "youtu" in uri else MediaSource.URL,
        uri,
        stable_id=stable_id,
        title=title,
        artist=artist,
        album=album,
        duration=duration,
        resolver_data=resolver_data or {},
        capabilities=MediaCapabilities(finite=True, live=False),
    )


def _library_row(
    database: MarianaDatabase,
    root: Path,
    library_id: str,
    *,
    metadata: dict | None = None,
    fingerprint: str | None = None,
    fingerprint_duration: float | None = None,
    state: str = "available",
) -> Path:
    path = root / f"{library_id}.mp3"
    path.write_bytes(b"media")
    root_id = "root"
    with database.transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO library_roots(root_id,path,path_key,kind,origin) VALUES(?,?,?,?,?)",
            (root_id, str(root), str(root).casefold(), "local", "library-file"),
        )
        connection.execute(
            "INSERT INTO library_files(library_id,root_id,canonical_path,path_key,size,mtime_ns,extension,state,"
            "metadata_json,fingerprint,fingerprint_duration,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,0)",
            (
                library_id,
                root_id,
                str(path),
                str(path).casefold(),
                path.stat().st_size,
                path.stat().st_mtime_ns,
                ".mp3",
                state,
                json.dumps(metadata or {}),
                fingerprint,
                fingerprint_duration,
            ),
        )
    return path


def _identity(database: MarianaDatabase, stable_id: str, recording: str, *, fingerprint: str = "fp", duration: float = 120):
    payload = {
        "status": "identified",
        "recording_mbid": recording,
        "confidence": 0.95,
        "provenance": ["chromaprint", "acoustid"],
    }
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO track_identities(stable_id,identity_json,fingerprint,fingerprint_duration,updated_at) "
            "VALUES(?,?,?,?,0)",
            (stable_id, json.dumps(payload), fingerprint, duration),
        )


@pytest.fixture
def matcher(tmp_path: Path):
    database = MarianaDatabase(tmp_path / "match.db")
    yield database, LocalMediaMatcher(database), tmp_path
    database.close()


def test_exact_youtube_id_and_safe_canonical_url_matches(matcher):
    database, service, root = matcher
    _library_row(database, root, "youtube", metadata={"youtube_id": "dQw4w9WgXcQ"})
    result = service.match(_online())
    assert result.status == LocalMatchStatus.MATCHED
    assert result.confidence == LocalMatchConfidence.EXACT_SOURCE

    with database.transaction() as connection:
        connection.execute("DELETE FROM library_files")
    _library_row(
        database,
        root,
        "page",
        metadata={"webpage_url": "https://soundcloud.com/artist/track", "duration": 120},
    )
    result = service.match(_online("https://soundcloud.com/artist/track?utm_source=share"))
    assert result.status == LocalMatchStatus.MATCHED


def test_secret_bearing_url_is_not_source_evidence(matcher):
    database, service, root = matcher
    _library_row(
        database,
        root,
        "secret",
        metadata={"webpage_url": "https://media.example/track?token=secret", "duration": 120},
    )
    result = service.match(_online("https://media.example/track?token=secret", title="", artist="", album=None))
    assert result.status == LocalMatchStatus.NO_MATCH


def test_cached_fingerprint_requires_compatible_duration(matcher):
    database, service, root = matcher
    _library_row(database, root, "local", fingerprint="same", fingerprint_duration=120)
    _identity(database, "online", "recording-online", fingerprint="same", duration=120)
    result = service.match(_online())
    assert result.confidence == LocalMatchConfidence.EXACT_ACOUSTIC

    database.execute("UPDATE library_files SET fingerprint_duration=110")
    result = service.match(_online())
    assert result.status == LocalMatchStatus.NO_MATCH


def test_confirmed_cached_recording_matches_but_inferred_mbid_does_not(matcher):
    database, service, root = matcher
    _library_row(database, root, "local")
    _identity(database, "local", "recording", fingerprint="local-fp")
    _identity(database, "online", "recording", fingerprint="online-fp")
    result = service.match(_online(resolver_data={"recording_mbid": "different-inferred"}))
    assert result.confidence == LocalMatchConfidence.VERIFIED_RECORDING

    database.execute("DELETE FROM track_identities WHERE stable_id='online'")
    result = service.match(_online(resolver_data={"recording_mbid": "recording"}))
    assert result.status == LocalMatchStatus.NO_MATCH


def test_strong_metadata_requires_duration_and_corroboration(matcher):
    database, service, root = matcher
    _library_row(
        database,
        root,
        "local",
        metadata={"title": " Track ", "artist": "ARTIST", "album": "Album", "duration": 121.5},
    )
    result = service.match(_online("https://media.example/item"))
    assert result.confidence == LocalMatchConfidence.STRONG_METADATA

    database.execute("UPDATE library_files SET metadata_json=?", (json.dumps({"title": "Track", "duration": 120}),))
    assert service.match(_online("https://media.example/item")).status == LocalMatchStatus.NO_MATCH
    database.execute(
        "UPDATE library_files SET metadata_json=?",
        (json.dumps({"title": "Track", "artist": "Artist", "album": "Album", "duration": 125}),),
    )
    assert service.match(_online("https://media.example/item")).status == LocalMatchStatus.NO_MATCH


def test_duplicate_and_conflicting_strong_candidates_are_ambiguous(matcher):
    database, service, root = matcher
    _library_row(database, root, "first", metadata={"youtube_id": "dQw4w9WgXcQ"})
    _library_row(database, root, "second", metadata={"youtube_id": "dQw4w9WgXcQ"})
    assert service.match(_online()).status == LocalMatchStatus.AMBIGUOUS

    with database.transaction() as connection:
        connection.execute("DELETE FROM library_files")
    _library_row(database, root, "source", metadata={"youtube_id": "dQw4w9WgXcQ"})
    _library_row(
        database,
        root,
        "metadata",
        metadata={"title": "Track", "artist": "Artist", "album": "Album", "duration": 120},
    )
    assert service.match(_online()).status == LocalMatchStatus.AMBIGUOUS


def test_missing_rows_are_excluded_and_result_model_is_safe(matcher):
    database, service, root = matcher
    _library_row(
        database,
        root,
        "missing",
        metadata={"youtube_id": "dQw4w9WgXcQ"},
        state="missing",
    )
    assert service.match(_online()).status == LocalMatchStatus.NO_MATCH

    _library_row(
        database,
        root,
        "available",
        metadata={"youtube_id": "dQw4w9WgXcQ", "title": "C:/private/song.mp3", "artist": "https://secret"},
    )
    before = database._connection.total_changes
    result = service.match(_online())
    assert database._connection.total_changes == before
    payload = asdict(result)
    assert result.status == LocalMatchStatus.MATCHED
    assert result.title == "Local media" and result.artist is None
    assert not {"path", "url", "uri", "fingerprint", "credential"}.intersection(payload)


@pytest.mark.parametrize(
    "media",
    [
        None,
        MediaRef(MediaSource.LOCAL, "C:/music/song.mp3", duration=120),
        MediaRef(
            MediaSource.RADIO,
            "https://radio.example/live",
            duration=120,
            capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
        ),
        _online(duration=None),
    ],
)
def test_unsupported_media_is_rejected_without_queries(matcher, monkeypatch, media):
    database, service, _root = matcher
    monkeypatch.setattr(database, "fetchall", lambda *_args, **_kwargs: pytest.fail("library queried"))
    assert service.match(media).status == LocalMatchStatus.UNSUPPORTED
