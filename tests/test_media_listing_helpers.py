"""Shared listing facts do not require command routing or navigation state."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.library import LibraryCatalog
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import PreferenceEntry, PreferenceState


def test_display_label_recovers_renamed_catalog_identity_without_mutation(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/old/name.mp3", stable_id="library-id")
    before = media.to_dict()
    lookup = Mock(side_effect=[None, {
        "library_id": "library-id", "canonical_path": "C:/new/Recovered title.mp3",
        "state": "available", "metadata": {},
    }])
    monkeypatch.setattr(main.LIBRARY, "info", lookup)
    assert main._media_display_label(media) == "Recovered title"
    assert [call.args[0] for call in lookup.call_args_list] == [media.original_uri, media.stable_id]
    assert media.to_dict() == before
    assert main._scoped_search_media_label(None, "Saved title") == "Saved title"
    assert main._scoped_search_media_label(None, "https://private.test/token") == "Media"


@pytest.mark.parametrize(("rating", "expected"), [(-2, 0), (3, 3), (8, 5), (None, 0), ("invalid", 0)])
@pytest.mark.parametrize("favorite", [True, False])
def test_favorite_and_rating_markers_are_independent_and_bounded(monkeypatch, rating, expected, favorite):
    media = MediaRef(MediaSource.URL, "https://media.test/song", title="Song")
    monkeypatch.setattr(main, "_preference_media", lambda value: value)
    monkeypatch.setattr(main, "PREFERENCES", SimpleNamespace(
        rating=lambda _media: rating, is_favorite=lambda _media: favorite,
    ))
    assert main._media_rating(media) == expected
    assert main._is_media_favorite(media) is favorite
    assert main._preference_markers(media) == ("♥" if favorite else "", "★" * expected)


def test_preference_markers_support_legacy_services_and_missing_media(monkeypatch):
    media = MediaRef(MediaSource.URL, "https://media.test/song")
    monkeypatch.setattr(main, "_preference_media", lambda value: value)
    monkeypatch.setattr(main, "PREFERENCES", SimpleNamespace(get=lambda _media: PreferenceState.FAVORITE))
    assert main._preference_markers(media) == ("♥", "")
    assert main._preference_markers(None) == ("", "")
    monkeypatch.setattr(main, "PREFERENCES", SimpleNamespace())
    assert main._preference_markers(media) == ("", "")


@pytest.mark.parametrize("state", list(PlaybackState))
def test_active_marker_requires_active_state_and_stable_identity(monkeypatch, state):
    media = MediaRef(MediaSource.URL, "https://media.test/song", stable_id="active", title="Same")
    other = MediaRef(MediaSource.URL, "https://media.test/other", stable_id="other", title="Same")
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(state, media=media))
    expected = "▶" if state in {
        PlaybackState.RESOLVING, PlaybackState.BUFFERING, PlaybackState.PLAYING,
        PlaybackState.PAUSED, PlaybackState.SEEKING, PlaybackState.CROSSFADING,
    } else ""
    assert main._active_media_marker(media) == expected
    assert main._active_media_marker(other) == ""
    assert main._active_media_marker(None) == ""


def test_active_marker_recognizes_station_identity_and_safe_snapshot_failures(monkeypatch):
    active = MediaRef(MediaSource.RADIO, "https://media.test/live", resolver_data={"station_id": "station"})
    listed = MediaRef(MediaSource.RADIO, "radio:station", resolver_data={"station_id": "station"})
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PAUSED, media=active))
    assert main._active_media_marker(listed) == "▶"
    listed.resolver_data["station_id"] = "another"
    assert main._active_media_marker(listed) == ""
    monkeypatch.setattr(main.vas.controller, "snapshot", Mock(side_effect=RuntimeError("unavailable")))
    assert main._active_media_marker(active) == ""


def test_listing_fields_use_catalog_probe_facts_not_filename_suffix(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/private/audio.mp3", stable_id="id")
    lookup = Mock(return_value={"state": "available", "size": 1536, "metadata": {
        "format": "matroska,webm", "codec": "opus",
    }})
    monkeypatch.setattr(main.LIBRARY, "info", lookup)
    assert main._media_listing_fields(media) == ("1.5 KiB", "WebM / Opus")
    lookup.assert_called_once_with("id")
    assert main._media_listing_fields(None) == ("", "")
    assert main._media_listing_fields(MediaRef(MediaSource.URL, "https://media.test/song")) == ("", "")


def test_listing_fields_mark_unavailable_and_use_owned_file_size_when_needed(monkeypatch, tmp_path):
    path = tmp_path / "owned.mp3"
    path.write_bytes(b"data")
    media = MediaRef(MediaSource.LOCAL, str(path), stable_id="id")
    monkeypatch.setattr(main.LIBRARY, "info", lambda _reference: {"state": "missing"})
    assert main._media_listing_fields(media) == ("Unavailable", "Unknown")
    monkeypatch.setattr(main.LIBRARY, "info", lambda _reference: None)
    assert main._media_listing_fields(media) == ("4 B", "Unknown")
    lookup = Mock(side_effect=[OSError("unavailable"), {"size": 1024, "metadata": "invalid"}])
    monkeypatch.setattr(main.LIBRARY, "info", lookup)
    assert main._media_listing_fields(media) == ("1 KiB", "Unknown")
    assert [call.args[0] for call in lookup.call_args_list] == [media.stable_id, media.original_uri]


@pytest.mark.parametrize("exists", [True, False])
def test_listing_fields_degrade_safely_after_real_catalog_database_closes(monkeypatch, tmp_path, exists):
    path = tmp_path / "owned.mp3"
    if exists:
        path.write_bytes(b"data")
    media = MediaRef(MediaSource.LOCAL, str(path), stable_id="a" * 32)
    with MarianaDatabase(tmp_path / "catalog.db") as database:
        catalog = LibraryCatalog(database, library_file=tmp_path / "lib.lib")
    monkeypatch.setattr(main, "LIBRARY", catalog)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=5)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: snapshot)
    play = Mock()
    monkeypatch.setattr(main.vas.supervisor, "play", play)
    before = media.to_dict()
    fields = main._media_listing_fields(media)
    assert fields == ("4 B" if exists else "Unknown", "Unknown")
    assert media.original_uri not in str(fields)
    assert media.to_dict() == before and main.vas.controller.snapshot() is snapshot
    play.assert_not_called()


def test_preference_search_preserves_known_title_when_catalog_tags_are_absent(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/fixture/song.mp3", stable_id="id", title="Known playback title")
    entry = PreferenceEntry("id", PreferenceState.FAVORITE, "Saved", media.original_uri, 1, MediaSource.LOCAL)
    monkeypatch.setattr(main.PREFERENCES, "media", lambda _identity: media)
    monkeypatch.setattr(main.LIBRARY, "info", lambda _reference: {
        "library_id": "id", "canonical_path": media.original_uri, "state": "available", "metadata": {},
    })
    recovered = main._preference_search_media(entry)
    assert recovered is not None and recovered.title == "Known playback title"
    assert recovered.stable_id == media.stable_id and recovered.original_uri == media.original_uri
    assert media.title == "Known playback title"


def test_preference_search_recovers_owned_copy_without_playback_or_mutation(monkeypatch):
    original = MediaRef(MediaSource.LOCAL, "C:/old/song.mp3", stable_id="id", title="Known", duration=42)
    original.resolver_data["library_display_title"] = "Stored"
    before = original.to_dict()
    entry = PreferenceEntry("id", PreferenceState.FAVORITE, "Saved", "C:/new/song.mp3", 1, MediaSource.LOCAL)
    monkeypatch.setattr(main.PREFERENCES, "media", lambda _identity: original)
    bind = Mock(side_effect=lambda media: media)
    monkeypatch.setattr(main, "_preference_media", bind)
    recovered = main._preference_search_media(entry)
    assert recovered is not None
    assert recovered is not original
    assert recovered.stable_id == original.stable_id
    assert recovered.original_uri == entry.uri
    assert recovered.title == "Known" and recovered.duration == 42
    assert recovered.resolver_data == original.resolver_data
    assert recovered.resolver_data is not original.resolver_data
    assert original.to_dict() == before
    bind.assert_called_once_with(recovered)
    monkeypatch.setattr(main, "_preference_media", Mock(side_effect=OSError("catalog unavailable")))
    assert main._preference_search_media(entry) is original


def test_preference_search_restores_saved_online_identity_without_catalog_lookup(monkeypatch):
    entry = PreferenceEntry("id", PreferenceState.FAVORITE, "Saved", "https://media.test/song", 1, MediaSource.URL)
    monkeypatch.setattr(main.PREFERENCES, "media", lambda _identity: None)
    monkeypatch.setattr(main.LIBRARY, "info", Mock(side_effect=AssertionError("Unexpected lookup")))
    recovered = main._preference_search_media(entry)
    assert recovered is not None
    assert recovered.stable_id == entry.stable_id
    assert recovered.title == "Saved"
    assert recovered.source == MediaSource.URL and recovered.provenance == "saved-preference"


def test_listing_selectors_ranges_and_patterns_are_bounded_and_case_insensitive():
    assert main._listing_selector(["DESC", "O", "blue", "moon"]) == ["blue", "moon"]
    assert main._listing_range(["o", "2", "-", "5", "desc"]) == (2, 5)
    assert main._listing_range(["blue-green"]) is None
    assert main._listing_regex(["o", "DESC"]) is None
    for arguments, title in [(["blue", "moon"], "BLUE MOON"), (["ALL"], "Any title"), (["*"], "Any title")]:
        pattern = main._listing_regex(arguments)
        assert pattern is not None and pattern.search(title)
    assert main._listing_regex(["a" * 512])
    with pytest.raises(ValueError, match="512"):
        main._listing_regex(["a" * 513])
    with pytest.raises(ValueError, match="Invalid list regular expression"):
        main._listing_regex(["["])


def test_recent_listing_facts_use_reverse_order_without_changing_entries(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/private/song.mp3", stable_id="id")
    recent = [(0, 0, "online"), (0, -1, (1, media.original_uri))]
    monkeypatch.setattr(main, "RECENTS_QUEUE", recent)
    monkeypatch.setattr(main, "_preference_media", lambda _media: media)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PAUSED, media=media))
    monkeypatch.setattr(main, "PREFERENCES", SimpleNamespace(rating=lambda _media: 2, is_favorite=lambda _media: True))
    monkeypatch.setattr(main.LIBRARY, "info", lambda _reference: {"size": 1024, "metadata": {"format": "mp3"}})
    assert main._recent_listing_fields(0) == ("▶", "♥", "★★", "1 KiB", "MP3")
    assert main._recent_listing_fields(1) == ("", "", "", "", "")
    assert main._recent_listing_fields(2) == ("", "", "", "", "")
    assert recent == [(0, 0, "online"), (0, -1, (1, media.original_uri))]
