from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playlists import PlaylistError
from mariana.preferences import PreferenceEntry, PreferenceState


@pytest.fixture
def scoped_search(monkeypatch):
    printed = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main.PREFERENCES, "rating", lambda media: 5 if media.stable_id == "favorite-id" else 0)
    monkeypatch.setattr(main.PREFERENCES, "is_favorite", lambda media: media.stable_id == "favorite-id")
    monkeypatch.setattr(main.PREFERENCES, "is_blocked", lambda media: media.stable_id == "blocked-id")
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    return printed


def test_favorite_scope_searches_metadata_and_retains_listing_markers(monkeypatch, scoped_search):
    media = MediaRef(
        MediaSource.PODCAST,
        "https://media.test/temporary.mp3",
        stable_id="favorite-id",
        title="Blue Hour",
        artist="Mina Rao",
        album="Night Sessions",
        provenance="podcast-feed",
    )
    entry = PreferenceEntry(
        media.stable_id,
        PreferenceState.FAVORITE,
        media.title or "",
        media.original_uri,
        1.0,
        media.source,
    )
    monkeypatch.setattr(main.PREFERENCES, "list", lambda state: [entry])
    monkeypatch.setattr(main.PREFERENCES, "media", lambda stable_id: media)

    assert main.advanced_search_command(["find", "--in", "favs", "mina"]) == [(1, "Blue Hour")]

    output = "\n".join(scoped_search)
    assert "in favorites" in output
    assert "Blue Hour" in output
    assert "★★★★★" in output
    assert media.original_uri not in output


def test_favorite_scope_regex_searches_the_complete_trusted_metadata_projection(
    monkeypatch,
    scoped_search,
):
    media = MediaRef(
        MediaSource.PODCAST,
        "https://media.test/temporary.mp3",
        stable_id="favorite-id",
        title="Blue Hour",
        artist="Mina Rao",
        album="Night Sessions",
        provenance="podcast-feed",
    )
    entry = PreferenceEntry(
        media.stable_id,
        PreferenceState.FAVORITE,
        media.title or "",
        media.original_uri,
        1.0,
        media.source,
    )
    monkeypatch.setattr(main.PREFERENCES, "list", lambda state: [entry])
    monkeypatch.setattr(main.PREFERENCES, "media", lambda stable_id: media)

    results = main.advanced_search_command(
        ["find", "--regex", r"^blue hour mina rao night sessions podcast-feed$", "--in", "favs"]
    )

    assert results == [(1, "Blue Hour")]
    assert "Blue Hour" in "\n".join(scoped_search)


def test_named_playlist_scope_preserves_playlist_positions_and_plays_selected_media(
    monkeypatch,
    scoped_search,
):
    media = [
        MediaRef(MediaSource.URL, "https://media.test/one", title="First", artist="A"),
        MediaRef(MediaSource.URL, "https://media.test/two", title="Second", artist="Target Artist"),
    ]
    playlist = SimpleNamespace(name="Night Drive", tree={"items": "opaque"})
    playlists = SimpleNamespace(
        get=lambda name: playlist if name == "Night Drive" else None,
        flattened_media=lambda tree: media if tree is playlist.tree else [],
    )
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(playlists=playlists))
    played = []
    monkeypatch.setattr(main.vas.supervisor, "play", lambda selected, **kwargs: played.append((selected, kwargs)))
    monkeypatch.setattr(main, "stopsong", lambda: None)
    monkeypatch.setattr(main, "_set_current_media_state", lambda selected: None)
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda selected: None)

    results = main.advanced_search_command(
        [".find", "target", "--in", "playlist", "Night Drive"]
    )

    assert results == [(2, "Second")]
    assert played == [(media[1], {"origin": "cli"})]


def test_queue_scope_plays_the_bound_queue_occurrence(monkeypatch, scoped_search):
    media = MediaRef(MediaSource.URL, "https://media.test/mix", title="Late Mix")
    item = SimpleNamespace(queue_id=41, media=media)
    queue = SimpleNamespace(
        items=lambda: [item],
        jump=lambda position: item if position == 0 else None,
    )
    monkeypatch.setattr(main, "QUEUE", queue)
    played = []
    monkeypatch.setattr(main, "_play_queue_item", lambda selected: played.append(selected))

    assert main.advanced_search_command([".f", "--in", "queue", "late"]) == [(1, "Late Mix")]
    assert played == [item]


def test_unknown_playlist_scope_reports_a_search_error(monkeypatch, scoped_search):
    playlists = SimpleNamespace(
        get=lambda _name: (_ for _ in ()).throw(PlaylistError("Unknown playlist: Missing")),
    )
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(playlists=playlists))

    with pytest.raises(ValueError, match="Unknown playlist: Missing"):
        main.advanced_search_command(["find", "track", "--in", "playlist", "Missing"])


def test_blocked_scope_lists_matches_but_refuses_immediate_playback(monkeypatch, scoped_search):
    media = MediaRef(
        MediaSource.URL,
        "https://media.test/blocked",
        stable_id="blocked-id",
        title="Blocked Session",
    )
    entry = PreferenceEntry(
        media.stable_id,
        PreferenceState.BLOCKED,
        media.title or "",
        media.original_uri,
        1.0,
        media.source,
    )
    monkeypatch.setattr(main.PREFERENCES, "list", lambda state: [entry])
    monkeypatch.setattr(main.PREFERENCES, "media", lambda stable_id: media)

    assert main.advanced_search_command(["find", "session", "--in", "blocked"]) == [
        (1, "Blocked Session")
    ]
    with pytest.raises(main.PlaybackBlockedError, match="Playback blocked"):
        main.advanced_search_command([".find", "session", "--in", "blocked"])
