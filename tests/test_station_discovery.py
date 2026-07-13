import json
import time
from pathlib import Path

import pytest

from mariana.database import MarianaDatabase
from mariana.models import IdentityStatus, MediaCapabilities, MediaRef, MediaSource, TrackIdentity
from mariana.queueing import PersistentQueue
from mariana.station_discovery import (
    StationDiscovery,
    StationSeedError,
    _artist_mbid,
    _identity,
    validate_station_seed,
)
from recommendation_engine.engine import Candidate, RecommendationEngine
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

        youtube_by_fields = MediaRef(
            MediaSource.YOUTUBE,
            "https://youtube.com/watch?v=fields",
            resolver_data={"track": "Track", "artist": "Artist"},
        )
        assert validate_station_seed(database, youtube_by_fields) is youtube_by_fields


def test_invalid_identity_unindexed_and_unverified_local_are_rejected(tmp_path: Path):
    with MarianaDatabase(tmp_path / "station.db") as database:
        missing = MediaRef(MediaSource.LOCAL, str(tmp_path / "missing.mp3"), title="Song", artist="Artist")
        with pytest.raises(StationSeedError) as raised:
            validate_station_seed(database, missing)
        assert raised.value.code == "unindexed_local"

        untagged = indexed_track(database, tmp_path / "untagged.mp3", "", "")
        with pytest.raises(StationSeedError) as raised:
            validate_station_seed(database, untagged)
        assert raised.value.code == "unverified_music"

        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO track_identities(stable_id,identity_json,updated_at) VALUES(?,?,?)",
                (youtube("corrupt").stable_id, "not-json", time.time()),
            )
        assert _identity(database, youtube("corrupt")) is None


def youtube(name: str) -> MediaRef:
    return MediaRef(MediaSource.YOUTUBE, f"https://youtube.com/watch?v={name}", title=name, artist="Artist")


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


def test_local_candidate_conformance_filters_every_unsupported_shape(tmp_path: Path):
    existing = tmp_path / "existing.mp3"
    existing.write_bytes(b"audio")
    seed = youtube("seed")
    candidates = [
        Candidate(seed),
        Candidate(MediaRef(MediaSource.YOUTUBE, "https://y/live", title="Live", artist="A", capabilities=MediaCapabilities(False, True, False))),
        Candidate(MediaRef(MediaSource.LOCAL, str(tmp_path / "missing.mp3"), title="Missing", artist="A")),
        Candidate(MediaRef(MediaSource.URL, "https://media.test", title="URL", artist="A")),
        Candidate(MediaRef(MediaSource.YOUTUBE, "https://y/no-title", artist="A")),
        Candidate(MediaRef(MediaSource.LOCAL, str(existing), title="Local", artist="A")),
        Candidate(MediaRef(MediaSource.YOUTUBE, "https://y/good", title="Online", artist="B")),
    ]

    class Engine:
        def candidates_from_history(self):
            return candidates

    with MarianaDatabase(tmp_path / "filters.db") as database:
        discovery = StationDiscovery(database, Engine())
        assert [item.media.title for item in discovery.local_candidates(seed, "hybrid")] == ["Local", "Online"]
        assert [item.media.title for item in discovery.local_candidates(seed, "local")] == ["Local"]
        assert [item.media.title for item in discovery.local_candidates(seed, "online")] == ["Online"]


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


def test_artist_identity_fallback_and_online_candidate_edge_matrix(tmp_path: Path):
    seed = youtube("seed")
    identity = TrackIdentity(
        IdentityStatus.IDENTIFIED,
        metadata={"musicbrainz": {"artist-credit": ["bad", {"artist": {"id": "artist-from-identity"}}]}},
    )
    assert _artist_mbid(seed, identity) == "artist-from-identity"
    assert _artist_mbid(seed, None) is None
    seed.resolver_data["artist_mbid"] = "direct"
    assert _artist_mbid(seed, identity) == "direct"

    known_local_path = tmp_path / "known.mp3"
    known_local_path.write_bytes(b"audio")
    known_local = MediaRef(
        MediaSource.LOCAL,
        str(known_local_path),
        title="Known",
        artist="Artist",
        resolver_data={"recording_mbid": "known"},
    )
    recordings = [
        {},
        {"recording_mbid": "known"},
        {"recording_mbid": "missing-recording"},
        {"recording_mbid": "missing-title"},
        {"recording_mbid": "no-results"},
        {"recording_mbid": "no-url"},
        {"recording_mbid": "not-music"},
        {"recording_mbid": "live"},
        {"recording_msid": "excluded"},
        {"recording_mbid": "good"},
        {"recording_mbid": "extra"},
    ]

    class ListenBrainz:
        def artist_radio(self, *_args, **_kwargs):
            return recordings

    class MusicBrainz:
        def recording(self, mbid):
            if mbid == "missing-recording":
                return None
            if mbid == "missing-title":
                return {"artist-credit": []}
            return {"title": mbid, "artist-credit": [{"name": "Artist"}]}

    def search_edge(query, **_kwargs):
        mbid = query.split()[-1]
        if mbid == "no-results":
            return []
        if mbid == "no-url":
            return [{}]
        return [{"url": f"https://youtube.com/watch?v={mbid}"}]

    def info_edge(url, **_kwargs):
        mbid = url.rsplit("=", 1)[-1]
        if mbid == "not-music":
            return {"categories": ["Education"]}
        if mbid == "live":
            return {"categories": ["Music"], "is_live": True}
        return {"track": mbid, "artist": "Artist", "duration": 100}

    class Engine:
        def candidates_from_history(self):
            return [Candidate(known_local)]

    with MarianaDatabase(tmp_path / "online-edges.db") as database:
        discovery = StationDiscovery(
            database,
            Engine(),
            listenbrainz=ListenBrainz(),
            musicbrainz=MusicBrainz(),
            youtube_search=search_edge,
            youtube_info=info_edge,
        )
        hybrid = discovery.online_candidates(seed, scope="hybrid", limit=2, excluded={youtube("excluded").stable_id})
        assert hybrid[0].media == known_local
        assert hybrid[1].media.resolver_data["recording_mbid"] == "good"
        online = discovery.online_candidates(seed, scope="online", limit=1, excluded=set())
        assert online[0].media.source == MediaSource.YOUTUBE


def test_online_candidates_require_artist_identity(tmp_path: Path):
    with MarianaDatabase(tmp_path / "no-artist.db") as database:
        discovery = StationDiscovery(database, RecommendationEngine(database, exploration=0))
        assert discovery.online_candidates(youtube("seed"), scope="hybrid", limit=2, excluded=set()) == []
