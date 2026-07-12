from pathlib import Path

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.queueing import PersistentQueue
from recommendation_engine.engine import DEFAULT_REWARDS, Candidate, RecommendationEngine, cosine, features
from recommendation_engine.listenbrainz import ListenBrainzClient
from recommendation_engine.research import Metrics, should_promote


def candidate(index: int, artist: str = "Artist", tags=None) -> Candidate:
    return Candidate(
        MediaRef(MediaSource.LOCAL, f"C:/music/{index}.mp3", title=f"Song {index}", artist=artist),
        tags=tags or ["rock"],
    )


def test_feature_hash_is_stable_and_normalized():
    enriched = candidate(1)
    enriched.media.album = "Album"
    enriched.collaborative_score = 0.5
    enriched.embedding = [0.1, -0.2]
    first = features(enriched)
    second = features(enriched)
    assert first == second
    assert abs(sum(value * value for value in first) - 1) < 1e-9
    assert cosine([0.0], [0.0]) == 0


def test_rewards_ranking_explanations_diversity_and_artist_cap(tmp_path: Path):
    with MarianaDatabase(tmp_path / "recommend.db") as database:
        engine = RecommendationEngine(database, seed=10, exploration=0)
        liked = candidate(0, "Loved", ["ambient"])
        engine.record_event(liked.media, "like", candidate=liked)
        assert DEFAULT_REWARDS["like"] == 5
        pool = [liked] + [candidate(index, "Same", ["rock"]) for index in range(1, 6)] + [candidate(8, "Other")]
        recommendations = engine.recommend(pool, limit=7)
        assert recommendations[0].media.stable_id == liked.media.stable_id
        assert all(result.reasons for result in recommendations)
        artists = [result.media.artist for result in recommendations]
        assert artists.count("Same") <= 2
        assert database.fetchone("SELECT COUNT(*) FROM interaction_events WHERE event_type='impression'")[0] == len(
            recommendations
        )


def test_training_is_thresholded_atomic_persistent_and_rollback_capable(tmp_path: Path):
    path = tmp_path / "recommend.db"
    with MarianaDatabase(path) as database:
        engine = RecommendationEngine(database, seed=1)
        item = candidate(1)
        engine.record_event(item.media, "like", candidate=item)
        assert engine.retrain_if_due(threshold=2) is None
        first = engine.retrain_if_due(force=True)
        assert (tmp_path / "models" / f"{first}.json").is_file()
        engine.record_event(item.media, "dislike", candidate=item)
        second = engine.retrain_if_due(force=True)
        assert second != first
        rows = database.fetchall("SELECT model_id, champion FROM recommendation_models ORDER BY created_at")
        assert sum(row["champion"] for row in rows) == 1
        assert {row["model_id"] for row in rows} == {first, second}
    with MarianaDatabase(path) as database:
        restored = RecommendationEngine(database)
        assert restored.ranker.to_dict() == engine.ranker.to_dict()


def test_history_candidate_generation_uses_queue_media(tmp_path: Path):
    with MarianaDatabase(tmp_path / "recommend.db") as database:
        queue = PersistentQueue(database)
        queue.add(candidate(1, tags=["jazz"]).media)
        engine = RecommendationEngine(database)
        history = engine.candidates_from_history()
        assert [item.media.title for item in history] == ["Song 1"]


def test_research_promotion_gate():
    champion = Metrics(0.50, 0.80)
    assert should_promote(champion, Metrics(0.51, 0.76))
    assert not should_promote(champion, Metrics(0.509, 0.80))
    assert not should_promote(champion, Metrics(0.52, 0.70))
    assert should_promote(Metrics(0, 0), Metrics(0.1, 0.1))


def test_exploration_recent_collaboration_exclusion_and_empty(tmp_path: Path):
    with MarianaDatabase(tmp_path / "recommend.db") as database:
        engine = RecommendationEngine(database, seed=2, exploration=1)
        collaborative = candidate(1, artist="", tags=[])
        collaborative.collaborative_score = 0.8
        recent = candidate(2, tags=["rock"])
        results = engine.recommend([collaborative, recent], recent=[recent], exclude_ids={recent.media.stable_id})
        assert len(results) == 1
        assert any("collaborative" in reason for reason in results[0].reasons)
        assert engine.recommend([], limit=0) == []
        assert engine.record_event(None, "unknown") == 0


def test_recent_context_boosts_related_candidates(tmp_path: Path):
    with MarianaDatabase(tmp_path / "related.db") as database:
        engine = RecommendationEngine(database, seed=3, exploration=0)
        recent = candidate(1, artist="Context", tags=["ambient", "calm"])
        related = candidate(2, artist="Other", tags=["ambient", "calm"])
        unrelated = candidate(3, artist="Other", tags=["metal", "loud"])
        results = engine.recommend([unrelated, related], recent=[recent])
        assert results[0].media.stable_id == related.media.stable_id


def test_listenbrainz_is_opt_in_and_normalizes_payload():
    assert ListenBrainzClient().recommendations("user") == []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"payload": {"mbids": [{"recording_mbid": "one"}]}}

    class Session:
        def get(self, url, **kwargs):
            assert "/user/user/" in url
            assert kwargs["headers"]["Authorization"] == "Token token"
            return Response()

    client = ListenBrainzClient("token", session=Session())
    assert client.enabled
    assert client.recommendations("user", 1000) == [{"recording_mbid": "one"}]
