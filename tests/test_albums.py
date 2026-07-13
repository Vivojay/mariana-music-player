import json
import sqlite3
from pathlib import Path

import pytest

from mariana.albums import AlbumCatalog, AlbumError
from mariana.database import SCHEMA_VERSION, MarianaDatabase
from mariana.models import AlbumRef, AlbumTrack, AlbumTrackStatus, MediaRef, MediaSource
from recommendation_engine import RecommendationEngine


def add_library_track(
    database: MarianaDatabase,
    tmp_path: Path,
    library_id: str,
    *,
    title: str,
    artist: str,
    album: str,
    album_artist: str | None = None,
    disc: str = "1",
    track: str = "1",
    release_mbid: str | None = None,
    recording_mbid: str | None = None,
    duration: float = 180,
) -> Path:
    root = tmp_path / "music"
    root.mkdir(exist_ok=True)
    path = root / f"{library_id}.mp3"
    path.write_bytes(b"audio")
    metadata = {
        "title": title,
        "artist": artist,
        "album": album,
        "album_artist": album_artist,
        "disc": disc,
        "track": track,
        "release_mbid": release_mbid,
        "duration": duration,
    }
    with database.transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO library_roots(root_id,path,path_key,kind,available) VALUES('root',?,?,"
            "'local',1)",
            (str(root), str(root).casefold()),
        )
        connection.execute(
            "INSERT INTO library_files(library_id,root_id,canonical_path,path_key,file_key,content_signature,"
            "size,mtime_ns,extension,state,metadata_json,updated_at) VALUES(?,'root',?,?,?,?,?,?,'.mp3',"
            "'available',?,0)",
            (
                library_id,
                str(path),
                str(path).casefold(),
                library_id,
                f"signature-{library_id}",
                path.stat().st_size,
                path.stat().st_mtime_ns,
                json.dumps(metadata),
            ),
        )
        if recording_mbid:
            connection.execute(
                "INSERT INTO track_identities(stable_id,identity_json,updated_at) VALUES(?,?,0)",
                (
                    library_id,
                    json.dumps(
                        {
                            "status": "identified",
                            "recording_mbid": recording_mbid,
                            "confidence": 0.95,
                        }
                    ),
                ),
            )
    return path


class FakeMusicBrainz:
    def __init__(self, releases=None, details=None):
        self.releases = releases or []
        self.details = details or {}
        self.release_calls = []

    def search_releases(self, query, *, limit=10, **_kwargs):
        return self.releases[:limit]

    def release(self, mbid, refresh=False):
        self.release_calls.append((mbid, refresh))
        return self.details.get(mbid)


def release_payload(mbid="release-1"):
    return {
        "id": mbid,
        "title": "Discovery",
        "artist-credit": [{"name": "Daft Punk"}],
        "date": "2001-03-12",
        "country": "XE",
        "release-group": {"id": "group-1"},
        "media": [
            {
                "position": 1,
                "tracks": [
                    {
                        "position": 1,
                        "length": 180000,
                        "recording": {
                            "id": "recording-1",
                            "title": "One More Time",
                            "artist-credit": [{"name": "Daft Punk"}],
                        },
                    }
                ],
            },
            {
                "position": 2,
                "tracks": [
                    {
                        "position": 1,
                        "length": 240000,
                        "recording": {
                            "id": "recording-2",
                            "title": "Too Long",
                            "artist-credit": [{"name": "Daft Punk"}],
                        },
                    }
                ],
            },
        ],
    }


def test_schema_seven_creates_album_tables_and_verified_backup(tmp_path: Path):
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
        "INSERT INTO schema_meta VALUES('schema_version','6');"
    )
    connection.close()
    with MarianaDatabase(path) as database:
        assert database.fetchone("SELECT name FROM sqlite_master WHERE name='albums'")
        assert database.fetchone("SELECT name FROM sqlite_master WHERE name='album_search_results'")
        assert database.fetchone("SELECT value FROM schema_meta")[0] == str(SCHEMA_VERSION)
    backup = path.with_suffix(f".db.pre-schema-{SCHEMA_VERSION}.bak")
    assert backup.is_file()
    check = sqlite3.connect(backup)
    try:
        assert check.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        check.close()


def test_local_album_grouping_multidisc_order_and_serialization(tmp_path: Path):
    with MarianaDatabase(tmp_path / "albums.db") as database:
        add_library_track(
            database,
            tmp_path,
            "second",
            title="Disc Two",
            artist="Artist",
            album="Album",
            album_artist="Album Artist",
            disc="2/2",
            track="1/1",
            release_mbid="release-local",
            recording_mbid="recording-2",
        )
        add_library_track(
            database,
            tmp_path,
            "first",
            title="Disc One",
            artist="Artist",
            album="Album",
            album_artist="Album Artist",
            disc="1/2",
            track="1/1",
            release_mbid="release-local",
            recording_mbid="recording-1",
        )
        catalog = AlbumCatalog(database)
        album = catalog.local_albums()[0]
        assert album.release_mbid == "release-local"
        assert [track.title for track in album.tracks] == ["Disc One", "Disc Two"]
        assert [track.disc_number for track in album.tracks] == [1, 2]
        assert all(track.resolution_status == AlbumTrackStatus.LOCAL for track in album.tracks)
        assert AlbumRef.from_dict(album.to_dict()) == album
        assert catalog.get(album.album_id).tracks[0].media.source == MediaSource.LOCAL


def test_hybrid_search_keeps_distinct_editions_and_numeric_references(tmp_path: Path):
    releases = [
        {
            "id": "standard",
            "title": "Album",
            "artist-credit": [{"name": "Artist"}],
            "date": "2001",
            "country": "US",
            "disambiguation": "standard",
        },
        {
            "id": "deluxe",
            "title": "Album",
            "artist-credit": [{"name": "Artist"}],
            "date": "2002",
            "country": "JP",
            "disambiguation": "deluxe",
        },
    ]
    with MarianaDatabase(tmp_path / "albums.db") as database:
        catalog = AlbumCatalog(database, musicbrainz=FakeMusicBrainz(releases))
        results = catalog.search("Artist Album", scope="online", limit=10)
        assert [album.release_mbid for album in results] == ["standard", "deluxe"]
        assert catalog.resolve_reference("1").release_mbid == "standard"
        assert catalog.resolve_reference("2").disambiguation == "deluxe"
        with pytest.raises(AlbumError, match="Unknown album search result"):
            catalog.resolve_reference("3")


def test_remote_release_prefers_recording_mbid_local_then_verified_youtube(tmp_path: Path):
    payload = release_payload()
    searches = []

    def youtube_search(query, **_kwargs):
        searches.append(query)
        return [{"id": "youtube-2", "url": "https://www.youtube.com/watch?v=youtube-2"}]

    with MarianaDatabase(tmp_path / "albums.db") as database:
        add_library_track(
            database,
            tmp_path,
            "local-one",
            title="Different Tag Title",
            artist="Daft Punk",
            album="Local Album",
            recording_mbid="recording-1",
        )
        catalog = AlbumCatalog(
            database,
            musicbrainz=FakeMusicBrainz(
                [{"id": "release-1", "title": "Discovery", "artist-credit": [{"name": "Daft Punk"}]}],
                {"release-1": payload},
            ),
            youtube_search=youtube_search,
            youtube_info=lambda *_args, **_kwargs: {
                "categories": ["Music"],
                "duration": 240,
                "is_live": False,
            },
        )
        catalog.search("Discovery", scope="online")
        album = catalog.fetch("1", scope="hybrid")
        assert album.tracks[0].resolution_status == AlbumTrackStatus.LOCAL
        assert album.tracks[0].media.stable_id == "local-one"
        assert album.tracks[1].resolution_status == AlbumTrackStatus.ONLINE
        assert album.tracks[1].media.original_uri == "https://www.youtube.com/watch?v=youtube-2"
        assert "bestaudurl" not in json.dumps(album.to_dict())
        assert searches == ["Daft Punk Too Long"]


def test_remote_release_rejects_unverified_video_and_partial_policy_is_visible(tmp_path: Path):
    with MarianaDatabase(tmp_path / "albums.db") as database:
        catalog = AlbumCatalog(
            database,
            musicbrainz=FakeMusicBrainz(
                [{"id": "release-1", "title": "Discovery"}],
                {"release-1": release_payload()},
            ),
            youtube_search=lambda *_args, **_kwargs: [
                {"id": "video", "url": "https://www.youtube.com/watch?v=video"}
            ],
            youtube_info=lambda *_args, **_kwargs: {
                "categories": ["Education"],
                "is_live": False,
            },
        )
        catalog.search("Discovery", scope="online")
        album = catalog.fetch("1", scope="online")
        assert len(album.unresolved_tracks) == 2
        assert all(track.resolution_status == AlbumTrackStatus.UNRESOLVED for track in album.tracks)


def test_tag_only_local_ambiguity_is_reported_without_guessing(tmp_path: Path):
    payload = release_payload()
    payload["media"] = [payload["media"][0]]
    payload["media"][0]["tracks"][0]["recording"].pop("id")
    with MarianaDatabase(tmp_path / "albums.db") as database:
        for library_id in ("copy-a", "copy-b"):
            add_library_track(
                database,
                tmp_path,
                library_id,
                title="One More Time",
                artist="Daft Punk",
                album="Unknown Edition",
                duration=180,
            )
        catalog = AlbumCatalog(
            database,
            musicbrainz=FakeMusicBrainz(
                [{"id": "release-1", "title": "Discovery"}],
                {"release-1": payload},
            ),
        )
        catalog.search("Discovery", scope="online")
        album = catalog.fetch("1", scope="local")
        assert album.tracks[0].media is None
        assert album.tracks[0].resolution_status == AlbumTrackStatus.AMBIGUOUS


def test_youtube_playlist_album_requires_explicit_catalog_entry_and_is_canonical(tmp_path: Path):
    with MarianaDatabase(tmp_path / "albums.db") as database:
        catalog = AlbumCatalog(
            database,
            youtube_playlist=lambda *_args, **_kwargs: {
                "id": "PL1",
                "title": "User Album",
                "url": "https://www.youtube.com/playlist?list=PL1",
                "entries": [
                    {
                        "id": "one",
                        "title": "One",
                        "artist": "Artist",
                        "url": "https://www.youtube.com/watch?v=one",
                        "duration": 10,
                        "playlist_index": 1,
                    }
                ],
            },
        )
        album = catalog.fetch("https://www.youtube.com/playlist?list=PL1")
        assert album.provenance == ["youtube-playlist"]
        assert album.tracks[0].media.resolver_data["playlist_id"] == "PL1"
        assert catalog.get(album.album_id).tracks[0].media.original_uri.endswith("watch?v=one")


def test_track_selectors_custom_permutations_and_deterministic_orders(tmp_path: Path):
    tracks = [
        AlbumTrack(
            title=f"Track {position}",
            disc_number=1 if position < 3 else 2,
            track_number=position if position < 3 else position - 2,
            position=position,
            media=MediaRef(MediaSource.LOCAL, f"C:/music/{position}.mp3", title=f"Track {position}"),
            resolution_status=AlbumTrackStatus.LOCAL,
        )
        for position in range(1, 5)
    ]
    album = AlbumRef("album", "Album", tracks=tracks)
    assert [item.position for item in AlbumCatalog.select_tracks(album, "1,3,2,4")] == [1, 3, 2, 4]
    assert [item.position for item in AlbumCatalog.select_tracks(album, "2.1-2.2")] == [3, 4]
    assert [item.position for item in AlbumCatalog.select_tracks(album, "1-3")] == [1, 2, 3]
    with pytest.raises(AlbumError, match="duplicates"):
        AlbumCatalog.select_tracks(album, "1,1")
    with pytest.raises(AlbumError, match="reversed"):
        AlbumCatalog.select_tracks(album, "4-2")
    with pytest.raises(AlbumError, match="does not exist"):
        AlbumCatalog.select_tracks(album, "9")
    shuffled, seed = AlbumCatalog.order_tracks(tracks, "shuffle", seed=42)
    repeated, _ = AlbumCatalog.order_tracks(tracks, "shuffle", seed=42)
    assert [item.position for item in shuffled] == [item.position for item in repeated]
    assert seed == 42
    with MarianaDatabase(tmp_path / "rank.db") as database:
        smart, _ = AlbumCatalog.order_tracks(
            tracks,
            "smart",
            recommender=RecommendationEngine(database, exploration=0),
        )
        assert sorted(item.position for item in smart) == [1, 2, 3, 4]
