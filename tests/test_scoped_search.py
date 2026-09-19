from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.navigation import NavigationRequest, NavigationScope
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


def _relative_media(media_id="relative-media", source=MediaSource.LOCAL):
    return MediaRef(source, "C:/relative.mp3", stable_id=media_id, title="Relative")


def test_relative_reference_requires_active_media(monkeypatch):
    monkeypatch.setattr(
        main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE, media=None),
    )
    request = NavigationRequest(offset=1, immediate=False)
    with pytest.raises(ValueError, match="currently active media"):
        main._relative_media_reference(request)


def test_relative_results_scope_uses_bound_search_context(monkeypatch):
    media = _relative_media()
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    )
    bound = SimpleNamespace(target=lambda offset: (0, SimpleNamespace(media=media)))
    monkeypatch.setattr(main, "_bind_navigation_context", lambda _context, _media: bound)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", SimpleNamespace())
    request = NavigationRequest(offset=2, immediate=False, scope=NavigationScope.RESULTS)
    assert main._relative_media_reference(request) is media
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", None)
    with pytest.raises(ValueError, match="No search results"):
        main._relative_media_reference(request)


def test_relative_reference_rejects_stale_and_missing_targets(monkeypatch):
    media = _relative_media()
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    )
    monkeypatch.setattr(
        main, "_bind_navigation_context", lambda _context, _media: SimpleNamespace(target=lambda _offset: None),
    )
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", SimpleNamespace())
    request = NavigationRequest(offset=1, immediate=False, scope=NavigationScope.RESULTS)
    with pytest.raises(ValueError, match="outside the collection"):
        main._relative_media_reference(request)
    monkeypatch.setattr(
        main, "_bind_navigation_context",
        lambda _context, _media: SimpleNamespace(target=lambda _offset: (0, SimpleNamespace(media=None))),
    )
    with pytest.raises(ValueError, match="missing or unavailable"):
        main._relative_media_reference(request)


def test_relative_queue_scope_respects_repeat_modes(monkeypatch):
    media = _relative_media()
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    )
    current = SimpleNamespace(media=media, queue_id="current")
    other = SimpleNamespace(media=_relative_media("other-media"), queue_id="other")
    monkeypatch.setattr(main.QUEUE, "current", lambda: current)
    monkeypatch.setattr(main.QUEUE, "items", lambda: [current, other])
    monkeypatch.setattr(main.QUEUE, "state", lambda: {"repeat_mode": "one"})
    request = NavigationRequest(offset=5, immediate=False, scope=NavigationScope.QUEUE)
    assert main._relative_media_reference(request) is media
    monkeypatch.setattr(main.QUEUE, "state", lambda: {"repeat_mode": "all"})
    assert main._relative_media_reference(request) is other.media
    monkeypatch.setattr(main.QUEUE, "state", lambda: {"repeat_mode": "off"})
    with pytest.raises(ValueError, match="outside the queue"):
        main._relative_media_reference(request)
    monkeypatch.setattr(
        main.QUEUE, "current", lambda: SimpleNamespace(media=_relative_media("elsewhere"), queue_id="missing"),
    )
    with pytest.raises(ValueError, match="not the active queue item"):
        main._relative_media_reference(request)


def test_relative_library_fallback_validates_bounds(monkeypatch):
    media = _relative_media()
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    )
    monkeypatch.setattr(main, "_library_song_index", lambda _uri: 3)
    monkeypatch.setattr(main, "_sound_files", ["a", "b", "c", "d"])
    resolved = _relative_media("resolved")
    monkeypatch.setattr(main, "_library_media", lambda _index: resolved)
    request = NavigationRequest(offset=1, immediate=False, scope=NavigationScope.LIBRARY)
    assert main._relative_media_reference(request) is resolved
    monkeypatch.setattr(main, "_library_song_index", lambda _uri: None)
    with pytest.raises(ValueError, match="outside the indexed library"):
        main._relative_media_reference(request)
    online = _relative_media("online", MediaSource.YOUTUBE)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=online),
    )
    with pytest.raises(ValueError, match="No ordered collection"):
        main._relative_media_reference(request)


def test_expand_relative_target_passes_through_plain_tokens():
    assert main._expand_relative_library_target([]) == []
    assert main._expand_relative_library_target(["seek", "5"]) == ["seek", "5"]
    assert main._expand_relative_library_target(["play", "3"]) == ["play", "3"]


def test_expand_relative_target_rejects_nonlocal_and_unknown_index(monkeypatch):
    online = _relative_media("online", MediaSource.YOUTUBE)
    monkeypatch.setattr(main, "_relative_media_reference", lambda _request: online)
    with pytest.raises(ValueError, match="local library item"):
        main._expand_relative_library_target(["play", "+1"])
    local = _relative_media()
    monkeypatch.setattr(main, "_relative_media_reference", lambda _request: local)
    monkeypatch.setattr(main, "_library_song_index", lambda _uri: None)
    with pytest.raises(ValueError, match="outside the indexed library"):
        main._expand_relative_library_target(["play", "+1"])


def test_expand_relative_target_resolves_library_index(monkeypatch):
    monkeypatch.setattr(main, "_relative_media_reference", lambda _request: _relative_media())
    monkeypatch.setattr(main, "_library_song_index", lambda _uri: 7)
    assert main._expand_relative_library_target(["play", "+1"]) == ["play", "7"]


def test_scoped_entries_reject_unknown_scopes_and_playlists(monkeypatch):
    request = SimpleNamespace(scope=main.SearchScope.CATALOGUE, scope_name=None, action="list", query=("x",))
    with pytest.raises(ValueError, match="Unsupported search scope"):
        main._scoped_search_entries(request)
    monkeypatch.setattr(
        main.QUEUE, "playlists", SimpleNamespace(get=Mock(side_effect=main.PlaylistError("Unknown playlist: Missing"))),
    )
    scoped = SimpleNamespace(scope="playlist", scope_name="Missing", action="list", query=("x",))
    with pytest.raises(ValueError, match="Unknown playlist: Missing"):
        main._scoped_search_entries(scoped)


def test_scoped_play_rejects_unavailable_queue_results(monkeypatch):
    missing = {"position": 1, "media": None}
    request = SimpleNamespace(scope="queue")
    with pytest.raises(ValueError, match="unavailable"):
        main._play_scoped_search_entry(missing, request)
    gone = {"position": 2, "media": _relative_media(), "queue_id": "gone"}
    monkeypatch.setattr(main.QUEUE, "items", list)
    with pytest.raises(ValueError, match="no longer available"):
        main._play_scoped_search_entry(gone, request)


def test_advanced_scoped_search_reports_empty_and_short_results(monkeypatch):
    monkeypatch.setattr(main.QUEUE, "items", list)
    empty = SimpleNamespace(
        scope=main.SearchScope.QUEUE, scope_name=None, action="list",
        query=("zzz-no-match",), mode="all", limit=None, result_index=None,
    )
    assert main._advanced_scoped_search(empty) == []
    monkeypatch.setattr(main, "_scoped_search_entries", lambda _request: [
        {"position": 1, "media": _relative_media(), "stable_id": "relative-media",
         "label": "Relative", "search": "Relative"},
    ])
    short = SimpleNamespace(
        scope=main.SearchScope.QUEUE, scope_name=None, action="first",
        query=("Relative",), mode="all", limit=None, result_index=5,
    )
    with pytest.raises(ValueError, match="only 1 match"):
        main._advanced_scoped_search(short)
