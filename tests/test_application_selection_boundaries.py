"""Application selection must preserve identity, ownership and explicit intent."""

import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.navigation import NavigationEntry, NavigationScope
from mariana.session_recipes import RecipeError


@pytest.fixture
def selected_media(monkeypatch, tmp_path):
    path = tmp_path / "selected.mp3"
    path.write_bytes(b"owned selection fixture")
    media = MediaRef(MediaSource.LOCAL, str(path), title="Selected", duration=60)
    monkeypatch.setattr(main, "_ensure_media_playable", Mock())
    monkeypatch.setattr(main, "_is_media_blocked", lambda _media: False)
    monkeypatch.setattr(main, "COMMAND_BUSY", threading.Event())
    monkeypatch.setattr(main, "IPrint", Mock())
    monkeypatch.setattr(main, "_emit_queue_desktop_state", Mock())
    return media


@pytest.mark.parametrize("location", ["active", "preferences", "queue", "remembered", "missing"])
def test_recipe_lookup_retains_exact_media_and_checks_playback_policy(selected_media, monkeypatch, location):
    media = selected_media
    other = MediaRef(MediaSource.LOCAL, "different.mp3", title=media.title)
    preferences = Mock(return_value=media if location == "preferences" else None)
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(
            snapshot=lambda: PlaybackSnapshot(
                PlaybackState.PAUSED,
                media=media if location == "active" else other,
            )
        ),
    )
    monkeypatch.setattr(main, "PREFERENCES", SimpleNamespace(media=preferences))
    monkeypatch.setattr(
        main,
        "QUEUE",
        SimpleNamespace(
            items=lambda: [
                SimpleNamespace(media=other),
                *([SimpleNamespace(media=media)] if location == "queue" else []),
            ]
        ),
    )
    monkeypatch.setattr(main, "_SESSION_MEDIA", {media.stable_id: media} if location == "remembered" else {})
    monkeypatch.setattr(main.PLAY_REGIONS, "get", lambda _media: None)
    result = main._session_media(media.stable_id)
    assert result is (None if location == "missing" else media)
    if location == "missing":
        main._ensure_media_playable.assert_not_called()
    else:
        main._ensure_media_playable.assert_called_once_with(media)
    if location == "active":
        preferences.assert_not_called()


def test_recipe_lookup_refuses_a_preferred_region_without_mutating_it(selected_media, monkeypatch):
    media = selected_media
    region = object()
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(
            snapshot=lambda: PlaybackSnapshot(
                PlaybackState.PAUSED,
                media=media,
            )
        ),
    )
    monkeypatch.setattr(main.PLAY_REGIONS, "get", lambda _media: region)
    with pytest.raises(RecipeError, match="Preferred play regions"):
        main._session_media(media.stable_id)
    main._ensure_media_playable.assert_called_once_with(media)


@pytest.mark.parametrize(
    "condition", ["blocked", "unknown", "missing-state", "wrong-identity", "missing-file", "ready"]
)
def test_discovery_local_choice_requires_available_existing_exact_identity(selected_media, monkeypatch, condition):
    media = selected_media
    info = {"state": "available", "library_id": media.stable_id}
    if condition == "unknown":
        info = None
    elif condition == "missing-state":
        info["state"] = "missing"
    elif condition == "wrong-identity":
        info["library_id"] = "another-edition"
    elif condition == "missing-file":
        from pathlib import Path

        Path(media.original_uri).unlink()
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(info=lambda _path: info))
    monkeypatch.setattr(main, "_is_media_blocked", lambda _media: condition == "blocked")
    expected = (
        None
        if condition == "ready"
        else ("Playback blocked" if condition == "blocked" else "Local media is unavailable")
    )
    assert main._discovery_unavailable(media) == expected


@pytest.mark.parametrize(
    ("source", "entry_kind", "native", "expected"),
    [
        (MediaSource.YOUTUBE, None, False, None),
        (MediaSource.URL, None, False, "Unsupported discovery source"),
        (MediaSource.PODCAST, None, False, "Unverified catalogue source"),
        (MediaSource.PODCAST, "podcast", False, "Unverified catalogue source"),
        (MediaSource.PODCAST, "station", True, "Unverified catalogue source"),
        (MediaSource.PODCAST, "podcast", True, None),
        (MediaSource.RADIO, "podcast", True, "Unverified catalogue source"),
        (MediaSource.RADIO, "station", True, None),
    ],
)
def test_discovery_uses_catalogue_semantics_not_playback_hostname(
    selected_media,
    monkeypatch,
    source,
    entry_kind,
    native,
    expected,
):
    media = MediaRef(source, "https://example.invalid/media", resolver_data={"catalogue_id": "entry"})
    entries = {} if entry_kind is None else {"entry": SimpleNamespace(kind=entry_kind, native=native)}
    monkeypatch.setattr(main, "ENTERTAINMENT_ENTRIES", entries)
    assert main._discovery_unavailable(media) == expected


@pytest.mark.parametrize("reason", ["busy", "unavailable"])
def test_discovery_refusal_does_not_clear_or_append_queue(selected_media, monkeypatch, reason):
    queue = Mock()
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "_discovery_unavailable", lambda _: "Unavailable" if reason == "unavailable" else None)
    if reason == "busy":
        main.COMMAND_BUSY.set()
    with pytest.raises(ValueError, match="temporarily unavailable"):
        main._apply_discovery_selection(selected_media, "queue")
    assert queue.mock_calls == []
    main._ensure_media_playable.assert_not_called()


@pytest.mark.parametrize("intent", ["queue", "play", "invalid"])
@pytest.mark.parametrize("source", [MediaSource.LOCAL, MediaSource.YOUTUBE])
def test_discovery_explicit_choice_preserves_queue_and_uses_existing_playback(
    selected_media,
    monkeypatch,
    intent,
    source,
):
    media = (
        selected_media
        if source == MediaSource.LOCAL
        else MediaRef(
            source,
            "https://youtu.be/abcdefghijk",
            title="Chosen recording",
        )
    )
    queue, local, supervisor, started = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "play_local_default_player", local)
    monkeypatch.setattr(main.vas, "supervisor", supervisor)
    monkeypatch.setattr(main, "_set_current_media_state", Mock())
    monkeypatch.setattr(main, "_record_successful_start", started)
    monkeypatch.setattr(main, "_discovery_unavailable", lambda _: None)
    if intent == "invalid":
        with pytest.raises(ValueError, match="Unsupported discovery action"):
            main._apply_discovery_selection(media, intent)
        assert queue.mock_calls == [] and supervisor.mock_calls == [] and local.mock_calls == []
        return
    main._apply_discovery_selection(media, intent)
    queue.clear.assert_not_called()
    if intent == "queue":
        queue.add.assert_called_once_with(media)
        assert supervisor.mock_calls == [] and local.mock_calls == []
        started.assert_not_called()
    else:
        queue.add.assert_not_called()
        if source == MediaSource.LOCAL:
            supervisor.play.assert_called_once_with(media, origin="desktop")
            local.assert_not_called()
        else:
            supervisor.play.assert_called_once_with(media, origin="desktop")
        started.assert_called_once_with(media)


@pytest.mark.parametrize("surface", ["scoped", "navigation"])
@pytest.mark.parametrize("kind", ["absent", "indexed", "unindexed", "missing", "online"])
def test_result_playback_preserves_selection_identity_and_rejects_missing_media(
    selected_media,
    monkeypatch,
    surface,
    kind,
):
    media = selected_media
    if kind == "absent":
        media = None
    elif kind == "online":
        media = MediaRef(MediaSource.YOUTUBE, "https://youtu.be/abcdefghijk")
    elif kind == "missing":
        from pathlib import Path

        Path(media.original_uri).unlink()
    local, indexed, supervisor, stop = Mock(), Mock(), Mock(), Mock()
    monkeypatch.setattr(main, "_library_song_index", lambda _: 7 if kind == "indexed" else None)
    monkeypatch.setattr(main, "local_play_commands", indexed)
    monkeypatch.setattr(main, "play_local_default_player", local)
    monkeypatch.setattr(main.vas, "supervisor", supervisor)
    monkeypatch.setattr(main, "stopsong", stop)
    monkeypatch.setattr(main, "_set_current_media_state", Mock())
    monkeypatch.setattr(main, "_show_local_copy_hint", Mock())

    def play():
        if surface == "navigation":
            return main._play_navigation_entry(
                NavigationEntry(
                    media,
                    media.stable_id if media else "missing",
                    1,
                    "Selected",
                    NavigationScope.RESULTS,
                )
            )
        return main._play_scoped_search_entry(
            {"media": media, "position": 1},
            SimpleNamespace(scope=main.SearchScope.LIBRARY),
        )

    if kind in {"absent", "missing"}:
        with pytest.raises(ValueError, match="unavailable"):
            play()
        assert local.mock_calls == [] and supervisor.mock_calls == [] and indexed.mock_calls == []
        stop.assert_not_called()
        return
    play()
    if kind == "indexed":
        indexed.assert_called_once_with([None, "7"])
    elif kind == "unindexed":
        local.assert_called_once_with(media.original_uri, _songindex=None, media=media)
    else:
        stop.assert_called_once_with()
        supervisor.play.assert_called_once_with(media, origin="cli")


@pytest.mark.parametrize("surface", ["scoped", "navigation"])
def test_removed_queue_occurrence_never_plays_a_reused_ordinal(selected_media, monkeypatch, surface):
    other_occurrence = SimpleNamespace(queue_id="new-occurrence", media=selected_media)
    queue = SimpleNamespace(items=lambda: [other_occurrence], jump=Mock())
    monkeypatch.setattr(main, "QUEUE", queue)

    def invoke():
        if surface == "scoped":
            return main._play_scoped_search_entry(
                {"media": selected_media, "position": 1, "queue_id": "removed"},
                SimpleNamespace(scope=main.SearchScope.QUEUE),
            )
        return main._play_navigation_entry(
            NavigationEntry(
                selected_media,
                selected_media.stable_id,
                1,
                "Selected",
                NavigationScope.QUEUE,
                "removed",
            )
        )

    with pytest.raises(ValueError, match=r"no longer available|changed"):
        invoke()
    queue.jump.assert_not_called()
