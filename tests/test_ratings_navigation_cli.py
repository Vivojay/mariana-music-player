"""Ratings and collection navigation preserve identity without implicit playback."""

from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.library import LibraryCatalog
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState, podcast_episode_identity
from mariana.navigation import NavigationContext, NavigationEntry, NavigationScope
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue


@pytest.fixture
def collection(monkeypatch, tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    paths = [root / f"Track {number}.mp3" for number in range(1, 4)]
    for number, path in enumerate(paths):
        path.write_bytes(f"local fixture {number}".encode())
    library_file = tmp_path / "library.lib"
    library_file.write_text(str(root), encoding="utf-8")
    database = MarianaDatabase(tmp_path / "preferences.db")
    library = LibraryCatalog(database, library_file=library_file, supported_extensions=[".mp3"])
    assert library.scan().discovered == 3
    preferences = MediaPreferences(database)
    queue = PersistentQueue(database)
    output = []
    snapshot = SimpleNamespace(media=None, state=PlaybackState.PAUSED)
    controller = SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(snapshot.state, media=snapshot.media, position=42),
        play=Mock(), pause=Mock(), seek=Mock(), stop=Mock(),
    )
    supervisor = SimpleNamespace(play=Mock())
    monkeypatch.setattr(main, "vas", SimpleNamespace(controller=controller, supervisor=supervisor))
    monkeypatch.setattr(main, "PREFERENCES", preferences)
    monkeypatch.setattr(main, "LIBRARY", library)
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "_sound_files", [str(path) for path in paths])
    monkeypatch.setattr(main, "_sound_files_names_only", [path.stem for path in paths])
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", None)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", None)
    monkeypatch.setattr(main, "FOCUS_MODE", SimpleNamespace(
        recovery_required=False,
        assert_media_allowed=Mock(), allows_command=lambda _command: True,
    ), raising=False)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "play_local_default_player", Mock())
    monkeypatch.setattr(main, "local_play_commands", Mock())
    monkeypatch.setattr(main, "_play_queue_item", Mock())
    monkeypatch.setattr(main, "stopsong", Mock())
    monkeypatch.setattr(main, "_set_current_media_state", Mock())
    monkeypatch.setattr(main, "_show_local_copy_hint", Mock())
    media = [main._library_media(index) for index in range(1, 4)]
    snapshot.media = media[0]
    try:
        yield SimpleNamespace(
            database=database, library=library, preferences=preferences, queue=queue,
            media=media, paths=paths, output=output, active=snapshot,
            controller=controller, supervisor=supervisor,
        )
    finally:
        database.close()


def _episode(guid="episode-one", enclosure="https://media.example.test/episode.mp3"):
    identity = podcast_episode_identity("https://feeds.example.test/show.xml", guid=guid)
    assert identity is not None
    return MediaRef(
        MediaSource.PODCAST, enclosure, stable_id=identity[0], title="Shared episode title",
        provenance="podcast-feed", resolver_data={"podcast_identity_kind": identity[1]},
    )


def _youtube():
    return MediaRef(
        MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abc12345678", title="Selected recording",
    )


def _rows(database):
    return {
        table: [dict(row) for row in database.fetchall(f"SELECT * FROM {table} ORDER BY stable_id")]
        for table in ("media_items", "media_preferences", "blocked_media")
    }


def _no_playback(collection):
    for operation in ("play", "pause", "seek", "stop"):
        getattr(collection.controller, operation).assert_not_called()
    collection.supervisor.play.assert_not_called()
    main.play_local_default_player.assert_not_called()
    main.local_play_commands.assert_not_called()
    main._play_queue_item.assert_not_called()
    main.stopsong.assert_not_called()


@pytest.mark.parametrize("kind", ["local", "youtube", "podcast", "generic-url"])
def test_rating_and_favourite_inspection_never_persists_media(collection, kind):
    media = {
        "local": collection.media[0], "youtube": _youtube(), "podcast": _episode(),
        "generic-url": MediaRef(MediaSource.URL, "https://cdn.example.test/audio?signature=private-value"),
    }[kind]
    collection.active.media = media
    before = _rows(collection.database)

    assert main.rating_command([]) == 0
    assert main.rating_command(["current"]) == 0
    assert main.favorite_command([]) == PreferenceState.NEUTRAL
    assert main.favorite_command(["current"]) == PreferenceState.NEUTRAL

    assert _rows(collection.database) == before
    assert "signature" not in "\n".join(collection.output)
    _no_playback(collection)


@pytest.mark.parametrize("kind", ["local", "youtube", "podcast"])
def test_current_rating_reloads_and_binary_favourites_preserve_block_policy(collection, monkeypatch, kind):
    media = {"local": collection.media[0], "youtube": _youtube(), "podcast": _episode()}[kind]
    collection.active.media = media
    assert main.rating_command(["current", "4"]) == 4
    assert main._favorite_status_projection(media).rating == 4
    assert main.favorite_command([]) == PreferenceState.NEUTRAL
    before = _rows(collection.database)["media_preferences"]
    assert main.rating_command(["4"]) == 4
    assert _rows(collection.database)["media_preferences"] == before

    with MarianaDatabase(collection.database.path) as reopened:
        restored = MediaPreferences(reopened)
        monkeypatch.setattr(main, "PREFERENCES", restored)
        if kind == "podcast":
            collection.active.media = _episode(enclosure="https://new.example.test/replaced.mp3")
            assert restored.rating(_episode(guid="different-episode")) == 0
        assert main.rating_command([]) == 4
        assert main._favorite_status_projection(collection.active.media).rating == 4
        restored.set_blocked(media)
        assert main.favorite_command(["+"]) == PreferenceState.FAVORITE
        assert restored.rating(media) == 4
        assert main.favorite_command(["!"]) == PreferenceState.NEUTRAL
        assert restored.rating(media) == 4
        assert restored.is_blocked(media)
        assert main.favorite_command(["!"]) == PreferenceState.FAVORITE
        assert main.favorite_command(["-"]) == PreferenceState.NEUTRAL
        assert restored.is_blocked(media)
    _no_playback(collection)


@pytest.mark.parametrize("kind", ["generic-url", "unbound-podcast"])
@pytest.mark.parametrize("operation", ["rating", "favourite-add", "favourite-toggle"])
def test_nondurable_rating_and_favourite_mutations_are_rejected(collection, kind, operation):
    collection.active.media = {
        "generic-url": MediaRef(MediaSource.URL, "https://cdn.example.test/audio?signature=private-value"),
        "unbound-podcast": MediaRef(MediaSource.PODCAST, "https://cdn.example.test/episode.mp3"),
    }[kind]
    before = _rows(collection.database)
    with pytest.raises(ValueError, match="durable"):
        if operation == "rating":
            main.rating_command(["3"])
        else:
            main.favorite_command(["+" if operation == "favourite-add" else "!"])
    assert _rows(collection.database) == before
    _no_playback(collection)


def test_legacy_local_favourite_remains_compatible_but_rating_requires_indexing(collection):
    path = collection.paths[0].parent / "not-indexed.mp3"
    path.write_bytes(b"new local file not scanned yet")
    media = MediaRef(MediaSource.LOCAL, str(path))
    collection.active.media = media
    with pytest.raises(ValueError, match="indexed"):
        main.rating_command(["3"])
    assert main.favorite_command(["+"]) == PreferenceState.FAVORITE
    assert collection.preferences.rating(media) == 0
    assert main.favorite_command(["-"]) == PreferenceState.NEUTRAL
    assert collection.preferences.rating(media) == 0
    _no_playback(collection)


@pytest.mark.parametrize("operation", ["-", "!"])
def test_removing_legacy_nondurable_favourite_does_not_refresh_signed_transport(collection, operation):
    media = MediaRef(MediaSource.URL, "https://cdn.example.test/audio?signature=new-private-value")
    collection.active.media = media
    collection.preferences.set_rating(media.stable_id, 5)
    collection.preferences.set(media.stable_id, PreferenceState.FAVORITE)
    assert collection.database.fetchall("SELECT * FROM media_items") == []
    assert main.favorite_command([operation]) == PreferenceState.NEUTRAL
    assert collection.preferences.rating(media) == 5
    assert collection.database.fetchall("SELECT * FROM media_items") == []
    _no_playback(collection)


@pytest.mark.parametrize("value", ["0", "6", "-1", "2.5", "NaN", "infinity"])
def test_invalid_cli_rating_preserves_existing_rating_and_metadata(collection, value):
    main.rating_command(["3"])
    before = _rows(collection.database)
    with pytest.raises(ValueError, match="whole number"):
        main.rating_command(["current", value])
    assert _rows(collection.database) == before
    assert main.rating_command([]) == 3
    _no_playback(collection)


def test_library_rating_target_is_not_a_rated_list_index_and_show_does_not_play(collection):
    first, second, third = collection.media
    main.rating_command(["2", "5"])
    main.rating_command(["3", "4"])
    assert collection.preferences.rating(first) == 0
    assert collection.preferences.rating(second) == 5
    assert collection.preferences.rating(third) == 4
    selection = main.rating_command(["show", "2"])
    assert selection[1].stable_id == third.stable_id
    assert selection[2] == 3
    assert "Library: #3" in collection.output
    _no_playback(collection)

    main.rating_command(["2"], play=True)
    main.play_local_default_player.assert_called_once()
    args, kwargs = main.play_local_default_player.call_args
    assert args == (third.original_uri,)
    assert kwargs["media"].stable_id == third.stable_id
    assert kwargs["_songindex"] == "3"
    assert collection.active.media is first


def test_favourite_and_rated_selection_use_separate_index_spaces(collection):
    first, _second, third = collection.media
    collection.preferences.set(first, PreferenceState.FAVORITE)
    collection.preferences.set_rating(third, 5)
    assert main.favorite_command(["1"])[1].stable_id == first.stable_id
    assert main.rating_command(["show", "1"])[1].stable_id == third.stable_id
    _no_playback(collection)
    main.favorite_command(["1"], play=True)
    main.rating_command(["1"], play=True)
    assert [call.kwargs["media"].stable_id for call in main.play_local_default_player.call_args_list] == [
        first.stable_id, third.stable_id,
    ]


def test_lists_show_independent_hearts_stars_and_local_facts(collection, monkeypatch):
    heart_only, stars_only, both = collection.media
    collection.preferences.set(heart_only, PreferenceState.FAVORITE)
    collection.preferences.set_rating(stars_only, 5)
    collection.preferences.set(both, PreferenceState.FAVORITE)
    collection.preferences.set_rating(both, 2)
    for media in collection.media:
        collection.preferences.set_blocked(media)
    tables = []
    monkeypatch.setattr(main, "tbl", lambda rows, headers, **_kwargs: tables.append((rows, headers)) or "table")
    entries = main.ratings_command([])
    rows, headers = tables[-1]
    facts = {entry.stable_id: dict(zip(headers, row, strict=True)) for entry, row in zip(entries, rows, strict=True)}
    assert facts[stars_only.stable_id]["Fav"] == ''
    assert facts[stars_only.stable_id]["Rating"] == '★★★★★'
    assert facts[both.stable_id]["Fav"] == '♥'
    assert facts[both.stable_id]["Rating"] == '★★'
    entries = main.list_preferences(PreferenceState.BLOCKED, [])
    rows, headers = tables[-1]
    facts = {entry.stable_id: dict(zip(headers, row, strict=True)) for entry, row in zip(entries, rows, strict=True)}
    assert facts[heart_only.stable_id]["Fav"] == '♥'
    assert facts[heart_only.stable_id]["Rating"] == ''
    assert facts[heart_only.stable_id]["Now"]
    assert facts[heart_only.stable_id]["Size"]
    assert facts[heart_only.stable_id]["Media format"] == 'Unknown'
    main.favorite_command(["list"])
    rows, headers = tables[-1]
    assert 'Fav' not in headers
    assert 'Rating' in headers
    assert all(len(row) == len(headers) for row in rows)
    assert main._preference_markers(heart_only) == ('♥', '')
    assert main._preference_markers(stars_only) == ('', '★★★★★')
    assert main._preference_markers(both) == ('♥', '★★')
    _no_playback(collection)


def test_typed_desktop_actions_publish_independent_persisted_state(collection, monkeypatch):
    media = collection.active.media
    collection.preferences.set_blocked(media)
    emitted = []
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=lambda event, payload: emitted.append((event, payload))))
    monkeypatch.setattr(main, "_playback_status_projection", lambda: SimpleNamespace(
        to_dict=lambda: {'favorite': asdict(main._favorite_status_projection(collection.active.media))},
    ))
    for action, payload, heart, stars in [
        ('rating.set', {'rating': 4}, False, 4),
        ('favorite.toggle', {}, True, 4),
        ('rating.set', {'rating': 0}, True, 0),
        ('favorite.toggle', {}, False, 0),
    ]:
        assert main._desktop_control_request(action, {'media_id': media.stable_id, **payload}) == {'ok': True}
        assert emitted[-1][0] == 'playback'
        assert emitted[-1][1]['favorite']['is_favorite'] == heart
        assert emitted[-1][1]['favorite']['rating'] == stars
        assert collection.preferences.is_favorite(media) == heart
        assert collection.preferences.rating(media) == stars
        assert collection.preferences.is_blocked(media)
    before = _rows(collection.database)
    assert not main._desktop_control_request('favorite.toggle', {'media_id': 'stale'})['ok']
    assert not main._desktop_control_request('rating.set', {'media_id': media.stable_id, 'rating': True})['ok']
    assert _rows(collection.database) == before
    assert len(emitted) == 4
    _no_playback(collection)


@pytest.mark.parametrize("clear", ["clear", "none", "unrated"])
def test_rating_clear_aliases_preserve_block_and_playback(collection, clear):
    main.rating_command(["5"])
    collection.preferences.set_blocked(collection.active.media)
    assert main.rating_command([clear]) == 0
    assert collection.preferences.is_blocked(collection.active.media)
    assert collection.preferences.list(PreferenceState.FAVORITE) == []
    _no_playback(collection)


def test_relative_queue_targets_use_duplicate_occurrence_and_do_not_advance(collection):
    first, second, third = collection.media
    collection.queue.extend([first, second, first, third], allow_duplicate=True)
    collection.queue.jump(2)
    before = collection.queue.export_snapshot()
    assert main._media_from_argument("-1 --in queue").stable_id == second.stable_id
    assert main._media_from_argument("+1 --in queue").stable_id == third.stable_id
    assert collection.queue.export_snapshot() == before
    _no_playback(collection)


def test_relative_favourites_refresh_after_heart_change_without_changing_scope(collection, monkeypatch):
    first, second, third = collection.media
    for media, rating in reversed(list(zip(collection.media, (5, 4, 3), strict=True))):
        collection.preferences.set_rating(media, rating)
        collection.preferences.set(media, PreferenceState.FAVORITE)
    context = main._favorite_navigation_context(first)
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", context)
    assert main._media_from_argument("+1").stable_id == second.stable_id
    collection.preferences.set(second, PreferenceState.NEUTRAL)
    assert main._media_from_argument("+1").stable_id == third.stable_id
    assert main._media_from_argument("+1 --in favorites").stable_id == third.stable_id
    assert main._NAVIGATION_CONTEXT is context
    assert context.cursor == 0
    _no_playback(collection)


def test_relative_playlist_requires_known_duplicate_occurrence(collection, monkeypatch):
    first, second, third = collection.media
    collection.queue.extend([first, second, first, third], allow_duplicate=True)
    collection.queue.save("Evening")
    before = collection.queue.export_snapshot()
    with pytest.raises(ValueError, match="more than once"):
        main._media_from_argument("+1 --in playlist Evening")
    entries = tuple(
        NavigationEntry(item.media, item.media.stable_id, index + 1, "Track", NavigationScope.PLAYLIST)
        for index, item in enumerate(collection.queue.items())
    )
    context = NavigationContext(NavigationScope.PLAYLIST, entries, 2, "Evening")
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", context)
    assert main._media_from_argument("+1").stable_id == third.stable_id
    assert main._media_from_argument("-1 --in playlist Evening").stable_id == second.stable_id
    assert main._NAVIGATION_CONTEXT is context
    assert collection.queue.export_snapshot() == before
    _no_playback(collection)


def test_relative_results_and_global_library_inspection_do_not_replace_context(collection, monkeypatch):
    first, second, third = collection.media
    context = NavigationContext(NavigationScope.RESULTS, (
        NavigationEntry(second, second.stable_id, 2, "Second", NavigationScope.LIBRARY),
        NavigationEntry(first, first.stable_id, 1, "First", NavigationScope.LIBRARY),
    ), 0, "Search results")
    collection.active.media = second
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", context)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", context)
    assert main._media_from_argument("+1").stable_id == first.stable_id
    assert main._media_from_argument("+1 --in results").stable_id == first.stable_id
    assert main._media_from_argument("+1 --in library").stable_id == third.stable_id
    collection.active.media = third
    with pytest.raises(ValueError, match="not in Search results"):
        main._media_from_argument("-1 --in results")
    assert main._NAVIGATION_CONTEXT is context
    assert main._LAST_SEARCH_CONTEXT is context
    _no_playback(collection)


def test_missing_search_reference_and_misaligned_queue_fail_without_library_substitution(collection, monkeypatch):
    first, second, third = collection.media
    context = NavigationContext(NavigationScope.RESULTS, (
        NavigationEntry(first, first.stable_id, 1, "First", NavigationScope.LIBRARY),
        NavigationEntry(None, "missing-id", 2, "Missing item", NavigationScope.LIBRARY),
    ), 0)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", context)
    with pytest.raises(ValueError, match="missing or unavailable"):
        main._media_from_argument("+1 --in results")
    collection.queue.extend([second, third])
    collection.queue.jump(0)
    before = collection.queue.export_snapshot()
    with pytest.raises(ValueError, match="not the active queue"):
        main._media_from_argument("+1 --in queue")
    assert collection.queue.export_snapshot() == before
    _no_playback(collection)


@pytest.mark.parametrize("scope", [NavigationScope.FAVORITES, NavigationScope.LIBRARY, NavigationScope.QUEUE])
def test_stale_collection_selection_rejects_replacement_before_playback(collection, monkeypatch, scope):
    first, second, _third = collection.media
    if scope == NavigationScope.FAVORITES:
        collection.preferences.set(second, PreferenceState.FAVORITE)
        collection.preferences.set(first, PreferenceState.FAVORITE)
        entry = main._favorite_navigation_context(first).entries[1]
        collection.preferences.set(second, PreferenceState.NEUTRAL)
    elif scope == NavigationScope.LIBRARY:
        entry = NavigationEntry(second, second.stable_id, 2, "Second", scope)
        monkeypatch.setattr(main, "_sound_files", [second.original_uri, first.original_uri])
    else:
        collection.queue.extend([first, second])
        item = collection.queue.items()[1]
        entry = NavigationEntry(second, second.stable_id, 2, "Second", scope, item.queue_id)
        collection.queue.remove(1)
        collection.queue.add(second)
        assert collection.queue.items()[1].queue_id != entry.occurrence_id
    before = collection.queue.export_snapshot()
    with pytest.raises(ValueError, match="changed"):
        main._play_navigation_entry(entry)
    assert collection.queue.export_snapshot() == before
    _no_playback(collection)


def test_missing_rated_local_media_keeps_rating_but_cannot_be_selected(collection):
    media = collection.media[1]
    main.rating_command(["2", "5"])
    original = collection.paths[1]
    original.unlink()
    collection.library.scan()
    assert main.favorite_command([]) == PreferenceState.NEUTRAL
    with pytest.raises(ValueError, match="missing or unavailable"):
        main.rating_command(["show", "1"])
    assert collection.preferences.rating(media) == 5
    _no_playback(collection)


def test_command_dispatch_keeps_rate_alias_list_and_detail_consistent(collection, monkeypatch):
    monkeypatch.setattr(main, "_capture_session_queue", Mock())
    main.process("rate 3")
    main.process("rating current")
    main.process("ratings")
    main.process("rating show 1")
    assert collection.preferences.rating(collection.active.media) == 3
    output = "\n".join(collection.output)
    assert "Rating: 3/5" in output
    assert "Rated #1" in output
    assert "Library: #1" in output
    assert str(collection.paths[0]) not in output
    main.process("fav -")
    assert collection.preferences.rating(collection.active.media) == 3
    assert not collection.preferences.is_favorite(collection.active.media)
    _no_playback(collection)
