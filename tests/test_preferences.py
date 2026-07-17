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


def test_preference_persists_unqueued_stream_metadata_and_refreshes_it_idempotently(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        preferences = MediaPreferences(database)
        media = MediaRef(
            MediaSource.YOUTUBE,
            "https://www.youtube.com/watch?v=abc12345678",
            title="Darkest Hour",
            artist="Andrea Russett",
        )
        assert preferences.set(media, PreferenceState.FAVORITE)
        enriched = MediaRef(
            MediaSource.YOUTUBE,
            media.original_uri,
            stable_id=media.stable_id,
            title="Andrea Russett - Darkest Hour (Official Lyric Video)",
            artist="Andrea Russett",
        )
        assert not preferences.set(enriched, PreferenceState.FAVORITE)

        entry = preferences.list(PreferenceState.FAVORITE)[0]
        assert entry.label == "Andrea Russett - Darkest Hour (Official Lyric Video)"
        assert entry.uri == media.original_uri
        assert entry.source == MediaSource.YOUTUBE
        row = database.fetchone("SELECT title, original_uri FROM media_items WHERE stable_id=?", (media.stable_id,))
        assert row and row["title"] == entry.label and row["original_uri"] == media.original_uri


def test_orphaned_legacy_preference_labels_internal_id_explicitly(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        preferences = MediaPreferences(database)
        preferences.set("54a74697918d2c8d3366484d", PreferenceState.FAVORITE)
        entry = preferences.list(PreferenceState.FAVORITE)[0]
        assert entry.label == "Unknown media"
        assert entry.uri is None
        assert entry.source is None


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


def test_preference_listing_limit_and_uri_label_fallbacks(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        preferences = MediaPreferences(database)
        first = MediaRef(MediaSource.URL, "https://example.test/first.mp3", stable_id="first")
        second = MediaRef(MediaSource.URL, "https://example.test/second.mp3", stable_id="second")
        PersistentQueue(database).add(first)
        PersistentQueue(database).add(second)
        preferences.set(first, PreferenceState.FAVORITE)
        preferences.set(second, PreferenceState.FAVORITE)
        listed = preferences.list(PreferenceState.FAVORITE, limit=1)
        assert len(listed) == 1
        assert listed[0].label in {"first", "second"}
        assert preferences.list(PreferenceState.FAVORITE, limit=-1) == []


def test_preference_order_is_stable_and_stored_media_can_be_rebound(tmp_path: Path):
    with MarianaDatabase(tmp_path / "state.db") as database:
        preferences = MediaPreferences(database)
        second = MediaRef(
            MediaSource.YOUTUBE,
            "https://www.youtube.com/watch?v=second",
            stable_id="second",
            title="Second",
        )
        first = MediaRef(
            MediaSource.YOUTUBE,
            "https://www.youtube.com/watch?v=first",
            stable_id="first",
            title="First",
        )
        preferences.set(second, PreferenceState.FAVORITE)
        preferences.set(first, PreferenceState.FAVORITE)
        database.execute("UPDATE media_preferences SET updated_at=100")

        assert [entry.stable_id for entry in preferences.list(PreferenceState.FAVORITE)] == [
            "first",
            "second",
        ]
        rebound = preferences.media("second")
        assert rebound is not None
        assert rebound.stable_id == second.stable_id
        assert rebound.original_uri == second.original_uri
        assert rebound.title == "Second"
        assert preferences.media("missing") is None


def test_legacy_preferences_ignore_malformed_rows_and_reuse_backup(tmp_path: Path):
    legacy = tmp_path / "track-infos.yml"
    neutral = tmp_path / "neutral.mp3"
    legacy.write_text(
        "- not-a-mapping\n",
        encoding="utf-8",
    )

    class Catalog:
        def info(self, _value):
            return None

    with MarianaDatabase(tmp_path / "one.db") as database:
        result = MediaPreferences(database).migrate_legacy(legacy, Catalog())
        assert result == {"imported": 0, "unresolved": 0, "complete": True}

    legacy.write_text(
        f"'{neutral}':\n  isFav: false\nignored: value\nmissing-key:\n  other: true\n",
        encoding="utf-8",
    )
    backup = legacy.with_suffix(".yml.pre-mariana-0.7.bak")
    backup.write_text("retained backup", encoding="utf-8")

    class ResolvedCatalog:
        def info(self, value):
            return {"library_id": "neutral-id"} if value == str(neutral) else None

    with MarianaDatabase(tmp_path / "two.db") as database:
        preferences = MediaPreferences(database)
        result = preferences.migrate_legacy(legacy, ResolvedCatalog())
        assert result == {"imported": 0, "unresolved": 0, "complete": True}
        assert preferences.get("neutral-id") == PreferenceState.NEUTRAL
        assert backup.read_text(encoding="utf-8") == "retained backup"
        assert preferences.migrate_legacy(tmp_path / "missing.yml", ResolvedCatalog()) == {
            "imported": 0,
            "unresolved": 0,
            "complete": False,
        }
