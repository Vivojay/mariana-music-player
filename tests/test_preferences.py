from pathlib import Path

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue
from recommendation_engine import Candidate, RecommendationEngine


def test_preferences_are_persistent_idempotent_and_listed(tmp_path: Path):
    path = tmp_path / "state.db"
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "song.mp3"), title="Song")
    with MarianaDatabase(path) as database:
        PersistentQueue(database).add(media)
        preferences = MediaPreferences(database)
        assert preferences.get(media) == PreferenceState.NEUTRAL
        assert preferences.set(media, PreferenceState.FAVORITE) is True
        assert preferences.set(media, PreferenceState.FAVORITE) is False
        assert preferences.list(PreferenceState.FAVORITE)[0].label == "Song"
        assert preferences.toggle(media, PreferenceState.FAVORITE) == PreferenceState.NEUTRAL
        assert preferences.toggle(media, PreferenceState.BLOCKED) == PreferenceState.BLOCKED
    with MarianaDatabase(path) as database:
        assert MediaPreferences(database).get(media) == PreferenceState.BLOCKED


def test_blocked_preferences_are_excluded_from_recommendations(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        blocked = MediaRef(MediaSource.LOCAL, "C:/music/blocked.mp3", title="Blocked")
        allowed = MediaRef(MediaSource.LOCAL, "C:/music/allowed.mp3", title="Allowed")
        preferences = MediaPreferences(database)
        preferences.set(blocked, PreferenceState.BLOCKED)
        engine = RecommendationEngine(
            database,
            seed=1,
            exploration=0,
            blocked=lambda stable_id: preferences.get(stable_id) == PreferenceState.BLOCKED,
        )
        results = engine.recommend([Candidate(blocked), Candidate(allowed)])
        assert [result.media.title for result in results] == ["Allowed"]


def test_legacy_preferences_are_backed_up_and_retry_unresolved_paths(tmp_path: Path):
    legacy = tmp_path / "track-infos.yml"
    favorite = tmp_path / "favorite.mp3"
    missing = tmp_path / "missing.mp3"
    legacy.write_text(
        f"'{favorite}':\n  isFav: true\n'{missing}':\n  isFav: null\n",
        encoding="utf-8",
    )

    class Catalog:
        def __init__(self):
            self.resolved = {str(favorite): {"library_id": "favorite-id"}}

        def info(self, value):
            return self.resolved.get(value)

    with MarianaDatabase(tmp_path / "state.db") as database:
        catalog = Catalog()
        preferences = MediaPreferences(database)
        first = preferences.migrate_legacy(legacy, catalog)
        assert first == {"imported": 1, "unresolved": 1, "complete": False}
        assert legacy.with_suffix(".yml.pre-mariana-0.7.bak").is_file()
        catalog.resolved[str(missing)] = {"library_id": "missing-id"}
        second = preferences.migrate_legacy(legacy, catalog)
        assert second == {"imported": 1, "unresolved": 0, "complete": True}
        assert preferences.get("favorite-id") == PreferenceState.FAVORITE
        assert preferences.get("missing-id") == PreferenceState.BLOCKED
        assert preferences.migrate_legacy(legacy, catalog) == second


def test_invalid_legacy_preferences_are_non_destructive(tmp_path: Path):
    legacy = tmp_path / "track-infos.yml"
    legacy.write_text("[broken", encoding="utf-8")
    with MarianaDatabase(tmp_path / "state.db") as database:
        result = MediaPreferences(database).migrate_legacy(legacy, object())
        assert result["complete"] is False
        assert result["error"] == "invalid legacy YAML"
        assert not legacy.with_suffix(".yml.pre-mariana-0.7.bak").exists()
