from types import SimpleNamespace

import pytest

import main
from mariana.command_parser import split_command
from mariana.commands import normalize_command
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.navigation import (
    NavigationContext,
    NavigationEntry,
    NavigationScope,
    parse_navigation,
)
from mariana.preferences import PreferenceEntry, PreferenceState


@pytest.fixture(autouse=True)
def clear_navigation_memory(monkeypatch):
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", None)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", None)


@pytest.mark.parametrize(
    ("command", "arguments", "offset", "immediate", "scope", "name"),
    [
        ("next", [], 1, False, NavigationScope.AUTO, None),
        (".prev", ["3"], -3, True, NavigationScope.AUTO, None),
        (".next", ["2", "--in", "favs"], 2, True, NavigationScope.FAVORITES, None),
        ("prev", ["--in", "playlist", "Night Drive"], -1, False, NavigationScope.PLAYLIST, "Night Drive"),
        ("next", ["--in", "results"], 1, False, NavigationScope.RESULTS, None),
    ],
)
def test_navigation_parser_supports_counts_modes_and_collections(
    command,
    arguments,
    offset,
    immediate,
    scope,
    name,
):
    request = parse_navigation(command, arguments)

    assert request.offset == offset
    assert request.immediate is immediate
    assert request.scope == scope
    assert request.scope_name == name


@pytest.mark.parametrize(
    "arguments",
    [["0"], ["-1"], ["two"], ["1", "2"], ["--in"], ["--in", "unknown"]],
)
def test_navigation_parser_rejects_ambiguous_or_invalid_requests(arguments):
    with pytest.raises(ValueError):
        parse_navigation("next", arguments)


def test_compact_alias_reaches_the_collection_navigation_handler(monkeypatch):
    delegated = []
    monkeypatch.setattr(
        main,
        "navigation_command",
        lambda command, arguments: delegated.append((command, arguments)),
    )
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )

    main.process(".-2 --in favs")

    assert delegated == [(".prev", ["2", "--in", "favs"])]


def test_online_queue_supports_multi_item_immediate_navigation(monkeypatch):
    media = [
        MediaRef(MediaSource.URL, f"https://media.test/{index}", title=f"Track {index}")
        for index in range(3)
    ]
    items = [SimpleNamespace(queue_id=index, media=value) for index, value in enumerate(media)]
    current = items[0]
    queue = SimpleNamespace(
        current=lambda: current,
        items=lambda: items,
        state=lambda: {"repeat_mode": "off"},
        jump=lambda position: items[position],
    )
    played = []
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media[0]),
    )
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    monkeypatch.setattr(main, "_play_queue_item", played.append)

    main.navigation_command(".next", ["2"])

    assert played == [items[2]]


def test_favorites_navigation_uses_identity_not_duplicate_titles(monkeypatch):
    media = [
        MediaRef(
            MediaSource.YOUTUBE,
            f"https://www.youtube.com/watch?v=track{index:06d}",
            stable_id=f"favorite-{index}",
            title="Shared title",
        )
        for index in range(3)
    ]
    preferences = [
        PreferenceEntry(
            value.stable_id,
            PreferenceState.FAVORITE,
            value.title or "",
            value.original_uri,
            float(index),
            value.source,
        )
        for index, value in enumerate(media)
    ]
    active = {"media": media[0]}
    played = []
    monkeypatch.setattr(main.PREFERENCES, "list", lambda _state: preferences)
    monkeypatch.setattr(main.PREFERENCES, "media", lambda stable_id: media[int(stable_id[-1])])
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=active["media"]),
    )
    monkeypatch.setattr(
        main,
        "_favorite_selection",
        lambda index: (preferences[index - 1], media[index - 1], None),
    )

    def play(index, _entry, selected, _library_index):
        active["media"] = selected
        played.append((index, selected.stable_id))
        return selected

    monkeypatch.setattr(main, "_play_favorite_selection", play)

    main.navigation_command(".next", ["2", "--in", "favorites"])
    main.navigation_command(".prev", [])

    assert played == [(3, "favorite-2"), (2, "favorite-1")]


def test_named_playlist_navigation_plays_the_selected_occurrence(monkeypatch):
    media = [
        MediaRef(MediaSource.URL, f"https://media.test/{index}", title=f"Track {index}")
        for index in range(3)
    ]
    playlist = SimpleNamespace(playlist_id="playlist-id", name="Night Drive", tree=object())
    playlists = SimpleNamespace(
        get=lambda name: playlist if name in {playlist.name, playlist.playlist_id} else None,
        flattened_media=lambda tree: media if tree is playlist.tree else [],
    )
    queue = SimpleNamespace(playlists=playlists, origin=lambda: None)
    played = []
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media[0]),
    )
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    monkeypatch.setattr(main, "stopsong", lambda: None)
    monkeypatch.setattr(main.vas.supervisor, "play", lambda selected, **_kwargs: played.append(selected))
    monkeypatch.setattr(main, "_set_current_media_state", lambda _media: None)
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda _media: None)

    main.navigation_command(".next", ["2", "--in", "playlist", "Night Drive"])

    assert played == [media[2]]
    assert main._NAVIGATION_CONTEXT is not None
    assert main._NAVIGATION_CONTEXT.name == "Night Drive"
    assert main._NAVIGATION_CONTEXT.cursor == 2


def test_explicit_library_navigation_escapes_an_aligned_queue(monkeypatch):
    paths = [f"C:/Music/track-{index}.mp3" for index in range(3)]
    media = [
        MediaRef(MediaSource.LOCAL, path, stable_id=f"library-{index}", title=f"Track {index}")
        for index, path in enumerate(paths)
    ]
    queue_item = SimpleNamespace(queue_id="current", media=media[1])
    monkeypatch.setattr(main, "_sound_files", paths)
    monkeypatch.setattr(main, "_library_media", lambda index: media[index - 1])
    monkeypatch.setattr(
        main,
        "QUEUE",
        SimpleNamespace(current=lambda: queue_item, items=lambda: [queue_item]),
    )
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media[1]),
    )
    played = []
    monkeypatch.setattr(main, "local_play_commands", lambda values: played.append(values))

    main.navigation_command(".next", ["--in", "library"])

    assert played == [[None, "3"]]


def test_filtered_results_become_the_default_navigation_context(monkeypatch):
    media = [
        MediaRef(MediaSource.LOCAL, f"C:/Music/{name}.mp3", stable_id=name, title=name)
        for name in ("Mix One", "Other", "Mix Two")
    ]
    monkeypatch.setattr(main, "_sound_files_names_enumerated", [(1, "Mix One"), (2, "Other"), (3, "Mix Two")])
    monkeypatch.setattr(main, "_sound_files", [item.original_uri for item in media])
    monkeypatch.setattr(main, "_library_media", lambda index: media[index - 1])
    monkeypatch.setattr(main, "_media_listing_fields", lambda _media: ("", "MP3"))
    monkeypatch.setattr(main, "_active_media_marker", lambda _media: "")
    monkeypatch.setattr(main, "_favorite_marker", lambda _media: "")
    monkeypatch.setattr(main, "_is_media_blocked", lambda _media: False)
    active: dict[str, MediaRef | None] = {"media": None}
    played = []

    def play(values):
        selected = int(values[1])
        active["media"] = media[selected - 1]
        played.append(selected)

    monkeypatch.setattr(main, "local_play_commands", play)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            PlaybackState.PLAYING if active["media"] else PlaybackState.IDLE,
            media=active["media"],
        ),
    )

    main.advanced_search_command([".find", "mix"])
    main.navigation_command(".next", [])

    assert played == [1, 3]


def test_queue_count_and_collection_shorthands_delegate_consistently(monkeypatch):
    first = SimpleNamespace(media=MediaRef(MediaSource.LOCAL, "C:/Music/one.mp3"))
    second = SimpleNamespace(media=MediaRef(MediaSource.LOCAL, "C:/Music/two.mp3"))
    advances = iter([first, second])
    played = []
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    monkeypatch.setattr(main, "_advance_queue_to_playable", lambda **_kwargs: next(advances))
    monkeypatch.setattr(main, "_play_queue_item", played.append)

    main._step_queue_playback("next", 2)

    assert played == [second]

    delegated = []
    monkeypatch.setattr(
        main,
        "navigation_command",
        lambda command, arguments: delegated.append((command, arguments)),
    )
    main.favorite_command(["previous", "3"])
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(playlists=object()))
    main.playlist_command(["next", "2"])

    assert delegated == [
        (".prev", ["3", "--in", "favorites"]),
        (".next", ["2", "--in", "playlist"]),
    ]


def test_navigation_context_does_not_move_until_immediate_selection():
    media = [MediaRef(MediaSource.URL, f"https://media.test/{index}") for index in range(2)]
    context = NavigationContext(
        NavigationScope.RESULTS,
        tuple(
            NavigationEntry(value, value.stable_id, index + 1, f"Track {index}", NavigationScope.RESULTS)
            for index, value in enumerate(media)
        ),
        0,
        "search results",
    )

    target = context.target(1)

    assert target is not None and target[1].stable_id == media[1].stable_id
    assert context.cursor == 0


@pytest.mark.parametrize(("text", "offset", "immediate", "scope", "name"), [
    ("+ library", 1, False, NavigationScope.LIBRARY, None),
    ("- queue", -1, False, NavigationScope.QUEUE, None),
    ("+3 lib", 3, False, NavigationScope.LIBRARY, None),
    (".-2 q", -2, True, NavigationScope.QUEUE, None),
    (".next 2 favorites", 2, True, NavigationScope.FAVORITES, None),
    ('prev playlist "Night Drive"', -1, False, NavigationScope.PLAYLIST, "Night Drive"),
    ("next results", 1, False, NavigationScope.RESULTS, None),
    ("+2 --in library", 2, False, NavigationScope.LIBRARY, None),
])
def test_collection_operand_matches_explicit_scope_flag(text, offset, immediate, scope, name):
    command, *arguments = split_command(normalize_command(text))
    request = parse_navigation(command, arguments)
    assert (request.offset, request.immediate, request.scope, request.scope_name) == (offset, immediate, scope, name)


@pytest.mark.parametrize("arguments", [
    ["queue", "library"], ["2", "unknown"], ["0", "library"],
    ["library", "2"], ["queue", "--in", "library"], ["2", "--in", "library", "--in", "queue"],
])
def test_collection_operand_rejects_conflicting_or_ambiguous_syntax(arguments):
    with pytest.raises(ValueError):
        parse_navigation("next", arguments)


@pytest.fixture
def single_result_in_large_queue(monkeypatch):
    media = [MediaRef(MediaSource.LOCAL, f"C:/Music/item-{i}.flac", stable_id=f"item-{i}", title=f"Track {i}")
             for i in range(1, 162)]
    active = {"media": media[109], "state": PlaybackState.PAUSED}
    items = [SimpleNamespace(queue_id=i, media=value) for i, value in enumerate(media)]
    cursor = [109]
    played, jumps, output = [], [], []
    selected = media[109]
    context = NavigationContext(NavigationScope.RESULTS, (
        NavigationEntry(selected, selected.stable_id, 110, selected.title, NavigationScope.LIBRARY, 110),
    ), 0, "library results")

    def jump(position):
        jumps.append(position)
        cursor[0] = position
        return items[position]

    def play(selected):
        played.append(selected.stable_id)
        active["media"] = selected

    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", context)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", context)
    monkeypatch.setattr(main, "_sound_files", [value.original_uri for value in media])
    monkeypatch.setattr(main, "_library_media", lambda index: media[index - 1])
    monkeypatch.setattr(main, "_blocked_label", lambda label, _media: label)
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "local_play_commands", lambda values: play(media[int(values[1]) - 1]))
    monkeypatch.setattr(main, "_play_queue_item", lambda item: play(item.media))
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(active["state"], media=active["media"]))
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(
        current=lambda: items[cursor[0]], items=lambda: items, jump=jump, state=lambda: {"repeat_mode": "off"},
    ))
    return SimpleNamespace(media=media, active=active, context=context, played=played, jumps=jumps, output=output)


@pytest.mark.parametrize("state", [PlaybackState.PLAYING, PlaybackState.PAUSED])
def test_peeking_outside_single_result_keeps_default_scope_and_playback(single_result_in_large_queue, state):
    scene = single_result_in_large_queue
    scene.active["state"] = state
    for command, position in (("next", 111), ("prev", 109)):
        for collection in ("queue", "library"):
            main.navigation_command(command, [collection])
            assert f"{collection} {position}/161" in scene.output[-1]
            assert f"Track {position}" in scene.output[-1]
            assert main._NAVIGATION_CONTEXT is scene.context
            assert main._LAST_SEARCH_CONTEXT is scene.context
        with pytest.raises(ValueError, match=r"library results \(1/1\)") as error:
            main.navigation_command(command, [])
        assert "preview in another collection" in str(error.value)
        assert 'library"' in str(error.value) and 'queue"' in str(error.value)
    assert scene.played == scene.jumps == []
    assert scene.active["media"] is scene.media[109]
    assert scene.active["state"] is state


@pytest.mark.parametrize(("collection", "command", "expected", "jumps"), [
    ("library", ".next", "item-112", []),
    ("queue", ".prev", "item-108", [107]),
])
def test_explicit_immediate_selection_uses_chosen_collection(single_result_in_large_queue, collection, command, expected, jumps):
    scene = single_result_in_large_queue
    main.navigation_command(command, ["2", collection])
    assert scene.played == [expected]
    assert scene.jumps == jumps
    assert main._LAST_SEARCH_CONTEXT is scene.context


@pytest.mark.parametrize("collection", ["favorites", "playlist", "results"])
def test_preview_other_collection_cannot_replace_default_or_last_search(monkeypatch, single_result_in_large_queue, collection):
    scene = single_result_in_large_queue
    scope = NavigationScope(collection)
    other = NavigationContext(scope, tuple(
        NavigationEntry(value, value.stable_id, i, value.title, NavigationScope.LIBRARY, i)
        for i, value in enumerate(scene.media[109:112], start=110)
    ), 0, "Other collection")
    monkeypatch.setattr(main, "_favorite_navigation_context", lambda _media: other)
    monkeypatch.setattr(main, "_playlist_navigation_context", lambda _name, _media: other)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", other)
    args = ["playlist", "Other collection"] if collection == "playlist" else [collection]
    assert main.navigation_command("next", args) is scene.media[110]
    assert main._NAVIGATION_CONTEXT is scene.context
    assert main._LAST_SEARCH_CONTEXT is other
    assert scene.played == scene.jumps == []


def test_scope_boundary_hint_preserves_direction_count_and_immediate_mode(single_result_in_large_queue):
    with pytest.raises(ValueError) as error:
        main.navigation_command(".prev", ["2"])
    assert '".-2 library"' in str(error.value)
    assert '".-2 queue"' in str(error.value)
    assert "To play" in str(error.value)


def test_shorthand_does_not_invent_library_membership_for_online_media(monkeypatch, single_result_in_large_queue):
    scene = single_result_in_large_queue
    scene.active["media"] = MediaRef(MediaSource.URL, "https://example.test/track", title="Online track")
    with pytest.raises(ValueError, match="indexed library item"):
        main.navigation_command("next", ["library"])
    assert scene.played == scene.jumps == []
