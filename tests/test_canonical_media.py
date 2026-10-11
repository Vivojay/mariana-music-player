import pytest

import main
from mariana.canonical_media import (
    find_canonical_media,
    find_duplicate_favorites,
    normalize_media_title,
)
from mariana.database import MarianaDatabase
from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.preferences import MediaPreferences, PreferenceState


@pytest.fixture
def history_database(tmp_path, monkeypatch):
    database = MarianaDatabase(tmp_path / "history.db")
    preferences = MediaPreferences(database)
    monkeypatch.setattr(main, "DATABASE", database)
    monkeypatch.setattr(main, "PREFERENCES", preferences)
    return database, preferences


def remember(preferences, source, uri, title, artist=None):
    media = MediaRef(source, uri, title=title, artist=artist)
    preferences.remember(media)
    return media


def test_normalize_strips_suffixes_accents_and_punctuation():
    assert normalize_media_title("Marwa Loud - Bad Boy (Lyrics)") == "marwa loud bad boy"
    assert normalize_media_title("Marwa Loud - Bad Boy (Clip Officiel)") == "marwa loud bad boy"
    assert normalize_media_title("EARNËD IT [Official Video]") == "earned it"
    assert normalize_media_title("Artist - Title - Lyrics") == "artist title"
    assert normalize_media_title("  Spaced   OUT!! ") == "spaced out"


def test_find_canonical_returns_most_recent_match(history_database):
    _database, preferences = history_database
    old = remember(
        preferences,
        MediaSource.YOUTUBE,
        "https://youtube.test/watch?v=old1",
        "Marwa Loud - Bad Boy (Lyrics)",
        "Marwa Loud",
    )
    remember(
        preferences,
        MediaSource.YOUTUBE,
        "https://youtube.test/watch?v=new1",
        "Marwa Loud - Bad Boy (Clip Officiel)",
        "Marwa Loud",
    )
    row = find_canonical_media(_database, "marwa loud bad boy")
    assert row is not None
    assert row["original_uri"] == "https://youtube.test/watch?v=new1"
    assert old.stable_id != row["stable_id"]


def test_find_canonical_matches_plain_query_forms(history_database):
    database, preferences = history_database
    remember(
        preferences, MediaSource.YOUTUBE, "https://youtube.test/watch?v=x", "Weeknd - Blinding Lights (Official Video)"
    )
    assert find_canonical_media(database, "weeknd blinding lights") is not None
    assert find_canonical_media(database, "something entirely different here") is None
    assert find_canonical_media(database, "ab") is None


def test_canonical_play_reuses_youtube_identity(window_play, monkeypatch):
    played = {}

    def fake_play_vas(*, media_name, media_url, single_video, **_kwargs):
        played.update(name=media_name, url=media_url, single=single_video)

    monkeypatch.setattr(main, "play_vas_media", fake_play_vas)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    row = {
        "source": MediaSource.YOUTUBE.value,
        "original_uri": "https://youtube.test/watch?v=canon1",
        "title": "Marwa Loud - Bad Boy (Clip Officiel)",
        "artist": "Marwa Loud",
    }
    assert main._play_canonical_match(row, "marwa loud bad boy", None) is True
    assert played["url"] == "https://youtube.test/watch?v=canon1"
    assert played["single"] is True


def test_canonical_play_prefers_saved_local_copy(tmp_path, monkeypatch):
    song = tmp_path / "saved song.mp3"
    song.write_bytes(b"data")
    played = {}
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda uri, _songindex, **kwargs: played.update(uri=uri, media=kwargs.get("media")),
    )
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    row = {
        "source": MediaSource.LOCAL.value,
        "original_uri": str(song),
        "title": "Saved Song",
        "artist": "Artist",
        "capabilities_json": MediaCapabilities().to_json(),
    }
    assert main._play_canonical_match(row, "saved song", None) is True
    assert played["uri"] == str(song)
    assert played["media"].provenance == "history"


def test_canonical_play_falls_through_when_saved_copy_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    row = {
        "source": MediaSource.LOCAL.value,
        "original_uri": str(tmp_path / "gone.mp3"),
        "title": "Gone",
        "artist": None,
        "capabilities_json": MediaCapabilities().to_json(),
    }
    assert main._play_canonical_match(row, "gone", None) is False


@pytest.fixture
def window_play(monkeypatch):
    return None


def test_search_replays_canonical_without_provider_search(history_database, monkeypatch):
    _database, preferences = history_database
    remember(
        preferences, MediaSource.YOUTUBE, "https://youtube.test/watch?v=canon9", "Marwa Loud - Bad Boy (Clip Officiel)"
    )
    monkeypatch.setattr(
        main.YT_query,
        "search_youtube",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider search must not run")),
    )
    played = {}
    monkeypatch.setattr(
        main,
        "play_vas_media",
        lambda **kwargs: played.update(kwargs),
    )
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    main.process("/ys marwa loud bad boy")
    assert played.get("media_url") == "https://youtube.test/watch?v=canon9"


def test_search_new_flag_skips_reconciliation(history_database, monkeypatch):
    _database, preferences = history_database
    remember(
        preferences, MediaSource.YOUTUBE, "https://youtube.test/watch?v=canon9", "Marwa Loud - Bad Boy (Clip Officiel)"
    )
    searched = {}

    def fake_search(*, search, **_kwargs):
        searched["query"] = search
        return ("Fresh Upload", "https://youtube.test/watch?v=fresh1")

    monkeypatch.setattr(main.YT_query, "search_youtube", fake_search)
    played = {}
    monkeypatch.setattr(main, "play_vas_media", lambda **kwargs: played.update(kwargs))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    main.process("/ys --new marwa loud bad boy")
    assert searched.get("query") == "marwa loud bad boy"
    assert played.get("media_url") == "https://youtube.test/watch?v=fresh1"


def test_duplicate_favorite_notice_lists_existing_entry(history_database):
    _database, preferences = history_database
    first = remember(
        preferences, MediaSource.YOUTUBE, "https://youtube.test/watch?v=old1", "Marwa Loud - Bad Boy (Lyrics)"
    )
    second = remember(
        preferences, MediaSource.YOUTUBE, "https://youtube.test/watch?v=new1", "Marwa Loud - Bad Boy (Clip Officiel)"
    )
    preferences.set(first, PreferenceState.FAVORITE)
    duplicates = find_duplicate_favorites(preferences, second)
    assert [(position, source) for position, _title, source in duplicates] == [(1, "youtube")]
    assert find_duplicate_favorites(preferences, second, exclude_stable_id=first.stable_id) == []
