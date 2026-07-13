import json
import time
from pathlib import Path

import pytest

from mariana.database import MarianaDatabase
from mariana.models import IdentityStatus, MediaCapabilities, MediaRef, MediaSource, TrackIdentity
from mariana.queueing import PersistentQueue
from mariana.station_discovery import StationDiscovery, StationSeedError, validate_station_seed
from recommendation_engine.engine import RecommendationEngine
from recommendation_engine.listenbrainz import ListenBrainzClient


def indexed_track(database: MarianaDatabase, path: Path, title: str, artist: str) -> MediaRef:
    path.write_bytes(b"music")
    media = MediaRef(MediaSource.LOCAL, str(path), title=title, artist=artist)
    now = time.time()
    with database.transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO library_roots(root_id,path,path_key,kind,available) VALUES(?,?,?,?,1)",
            ("root", str(path.parent), str(path.parent).casefold(), "local"),
        )
        connection.execute(
            "INSERT INTO library_files(library_id,root_id,canonical_path,path_key,size,mtime_ns,extension,"
            "metadata_json,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                media.stable_id,
                "root",
                str(path),
                str(path.resolve()).casefold(),
                path.stat().st_size,
                path.stat().st_mtime_ns,
                path.suffix,
                "{}",
                now,
            ),
        )
    PersistentQueue(database).add(media)
    return media


@pytest.mark.parametrize(
    ("media", "code"),
    [
        (MediaRef(MediaSource.RADIO, "https://radio.test", capabilities=MediaCapabilities(False, True, False)), "live_media"),
        (MediaRef(MediaSource.PODCAST, "https://feed.test/episode"), "unsupported_source"),
        (MediaRef(MediaSource.URL, "https://media.test/file"), "unsupported_source"),
        (MediaRef(MediaSource.RECOMMENDATION, "rec:1"), "unsupported_source"),
        (MediaRef(MediaSource.YOUTUBE, "https://youtube.com/watch?v=generic"), "unverified_video"),
    ],
)
def test_seed_rejections_are_typed(tmp_path: Path, media: MediaRef, code: str):
    with MarianaDatabase(tmp_path / "station.db") as database, pytest.raises(StationSeedError) as raised:
        validate_station_seed(database, media)
    assert raised.value.code == code


def test_local_and_youtube_seed_eligibility(tmp_path: Path):
    with MarianaDatabase(tmp_path / "station.db") as database:
        seed = indexed_track(database, tmp_path / "seed.mp3", "Seed", "Artist")
        assert validate_station_seed(database, seed) is seed

        youtube = MediaRef(
            MediaSource.YOUTUBE,
            "https://youtube.com/watch?v=music",
            resolver_data={"categories": ["Music"]},
        )
        assert validate_station_seed(database, youtube) is youtube

        untagged = indexed_track(database, tmp_path / "unknown.mp3", "", "")
        identity = TrackIdentity(
            IdentityStatus.IDENTIFIED,
            title="Known",
            artist="Known Artist",
            confidence=0.91,
        )
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO track_identities(stable_id,identity_json,updated_at) VALUES(?,?,?)",
                (untagged.stable_id, json.dumps(identity.to_dict()), time.time()),
            )
        assert validate_station_seed(database, untagged) is untagged


def test_local_discovery_filters_unplayable_blocked_and_scopes(tmp_path: Path):
    with MarianaDatabase(tmp_path / "station.db") as database:
        seed = indexed_track(database, tmp_path / "seed.mp3", "Seed", "Artist")
        good = indexed_track(database, tmp_path / "good.mp3", "Good", "Other")
        blocked = indexed_track(database, tmp_path / "blocked.mp3", "Blocked", "Third")
        engine = RecommendationEngine(database, exploration=0, seed=1, blocked=lambda value: value == blocked.stable_id)
        discovery = StationDiscovery(database, engine)

        results = discovery.discover(seed, scope="local", limit=10)
        assert [item.media.stable_id for item in results] == [good.stable_id]
        assert results[0].provider == "local-history"
        assert discovery.discover(seed, scope="online", limit=10) == []
        with pytest.raises(ValueError, match="scope"):
            discovery.discover(seed, scope="invalid")


def test_hybrid_online_discovery_prefers_known_then_youtube(tmp_path: Path):
    class ListenBrainz:
        def artist_radio(self, _artist_mbid, *, count, mode="medium"):
            assert count >= 10 and mode == "medium"
            return [
                {"recording_mbid": "known", "score": 0.9},
                {"recording_mbid": "new", "score": 0.8},
            ]

    class MusicBrainz:
        def recording(self, mbid):
            if mbid != "new":
                return None
            return {"title": "New Song", "artist-credit": [{"name": "New Artist"}]}

    def youtube_search(_query, *, limit, browser_profile):
        assert limit == 1 and browser_profile == "firefox"
        return [{"url": "https://www.youtube.com/watch?v=new", "title": "New Song"}]

    def youtube_info(_url, *, detailed, browser_profile):
        assert detailed and browser_profile == "firefox"
        return {"categories": ["Music"], "duration": 180, "is_live": False}

    with MarianaDatabase(tmp_path / "station.db") as database:
        seed = MediaRef(
            MediaSource.YOUTUBE,
            "https://www.youtube.com/watch?v=seed",
            title="Seed",
            artist="Seed Artist",
            resolver_data={"is_music": True, "artist_mbid": "artist"},
        )
        known = MediaRef(
            MediaSource.YOUTUBE,
            "https://www.youtube.com/watch?v=known",
            title="Known",
            artist="Known Artist",
            resolver_data={"is_music": True, "recording_mbid": "known"},
        )
        queue = PersistentQueue(database)
        queue.add(seed)
        queue.add(known)
        engine = RecommendationEngine(database, exploration=0, seed=1)
        discovery = StationDiscovery(
            database,
            engine,
            listenbrainz=ListenBrainz(),
            musicbrainz=MusicBrainz(),
            youtube_search=youtube_search,
            youtube_info=youtube_info,
            browser_profile="firefox",
        )

        results = discovery.discover(seed, scope="online", limit=2)
        assert {item.media.resolver_data.get("recording_mbid") for item in results} == {"known", "new"}
        generated = next(item for item in results if item.media.resolver_data.get("recording_mbid") == "new")
        assert generated.media.original_uri == "https://www.youtube.com/watch?v=new"
        assert generated.provider == "listenbrainz"


def test_public_artist_radio_normalizes_payload():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"payload": {"recordings": ["one", {"recording_mbid": "two"}]}}

    class Session:
        def get(self, url, **kwargs):
            assert url.endswith("/artist/artist")
            assert "Authorization" not in kwargs["headers"]
            return Response()

    client = ListenBrainzClient(session=Session())
    assert client.artist_radio("artist", count=1) == [{"recording_mbid": "one"}]
    assert client.artist_radio("", mode="wrong") == []
