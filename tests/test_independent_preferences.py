"""Hearts save media; stars assess it; blocking remains a separate policy."""

import sqlite3

import pytest

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.preferences import MediaPreferences, PreferenceState


@pytest.mark.parametrize("rating", range(6))
@pytest.mark.parametrize("blocked", [False, True])
def test_hearts_and_stars_survive_reload_and_clear_independently(tmp_path, rating, blocked):
    path = tmp_path / "preferences.db"
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abc12345678", title="Recording")
    with MarianaDatabase(path) as database:
        preferences = MediaPreferences(database)
        preferences.set_rating(media, rating)
        preferences.set_blocked(media, blocked)
        assert not preferences.is_favorite(media)
        assert preferences.set(media, PreferenceState.FAVORITE)
        assert preferences.rating(media) == rating
        assert not preferences.set(media, PreferenceState.FAVORITE)

    with MarianaDatabase(path) as database:
        preferences = MediaPreferences(database)
        assert preferences.is_favorite(media)
        assert preferences.rating(media) == rating
        assert preferences.is_blocked(media) == blocked
        assert preferences.list(PreferenceState.FAVORITE)[0].rating == rating
        assert bool(preferences.list_rated()) == (rating > 0)
        preferences.toggle(media, PreferenceState.FAVORITE)
        assert not preferences.is_favorite(media)
        assert preferences.rating(media) == rating
        preferences.set(media, PreferenceState.FAVORITE)
        preferences.set_rating(media, 0)
        assert preferences.is_favorite(media)
        assert preferences.rating(media) == 0
        assert preferences.list_rated() == []
        assert preferences.is_blocked(media) == blocked


def test_existing_rating_and_heart_values_are_not_reinterpreted_during_upgrade(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO schema_meta VALUES ('schema_version', '14');
            CREATE TABLE media_preferences (
                stable_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                rating INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL
            );
            INSERT INTO media_preferences VALUES
                ('heart-only', 'favorite', 0, 1), ('both', 'favorite', 3, 2),
                ('stars-only', 'neutral', 5, 3), ('legacy-block', 'blocked', 4, 4);
        """)
    for _ in range(2):
        with MarianaDatabase(path) as database:
            preferences = MediaPreferences(database)
            assert {entry.stable_id for entry in preferences.list(PreferenceState.FAVORITE)} == {'heart-only', 'both'}
            assert [(entry.stable_id, entry.rating) for entry in preferences.list_rated()] == [
                ('stars-only', 5), ('legacy-block', 4), ('both', 3),
            ]
            assert preferences.rating('heart-only') == 0
            assert preferences.is_blocked('legacy-block')
            assert preferences.list(PreferenceState.BLOCKED)[0].rating == 4
