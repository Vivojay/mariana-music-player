from sqlite3 import OperationalError
from unittest.mock import Mock

import pytest

import main
from mariana.models import MediaRef, MediaSource
from mariana.preferences import PreferenceEntry, PreferenceState


def test_saved_preference_label_is_kept_when_catalog_entry_is_unavailable(monkeypatch):
    monkeypatch.setattr(main.LIBRARY, "info", lambda _value: None)
    entry = PreferenceEntry(
        "saved", PreferenceState.FAVORITE, "Previously known title", "C:/missing/song.mp3",
        1, MediaSource.LOCAL, "missing", 5,
    )

    assert main._favorite_display_label(entry) == "Previously known title"


@pytest.mark.parametrize("error", [OSError("unavailable"), OperationalError("closed"), ValueError("invalid")])
def test_catalog_failure_keeps_safe_saved_label_without_exposing_paths(monkeypatch, error):
    lookup = Mock(side_effect=error)
    monkeypatch.setattr(main.LIBRARY, "info", lookup)
    media = MediaRef(
        MediaSource.LOCAL, "C:/private/song.mp3",
        resolver_data={"library_display_title": "Saved title"}, provenance="library",
    )

    assert main._media_display_label(media) == "Saved title"
    assert media.title is None


def test_known_title_needs_no_catalog_access_and_sources_never_expose_locations(monkeypatch):
    lookup = Mock(side_effect=AssertionError("Unexpected catalog access"))
    monkeypatch.setattr(main.LIBRARY, "info", lookup)
    local = MediaRef(MediaSource.LOCAL, "C:/private/song.mp3", title="Known title")
    assert main._media_display_label(local) == "Known title"
    for source, expected in [
        (MediaSource.YOUTUBE, "YouTube media"), (MediaSource.PODCAST, "Podcast"),
        (MediaSource.URL, "Online media"), (MediaSource.RADIO, "Internet radio"),
    ]:
        media = MediaRef(source, "https://private.test/media?token=secret", title="https://private.test/secret")
        assert main._media_display_label(media) == expected
    lookup.assert_not_called()
