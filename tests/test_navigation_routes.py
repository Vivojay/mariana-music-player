"""Scoped routing failures and CLI behavior without real playback."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.navigation import NavigationContext, NavigationEntry, NavigationScope
from mariana.queueing import PersistentQueue, QueueError


@pytest.fixture
def navigation_scene(monkeypatch):
    media = tuple(
        MediaRef(MediaSource.LOCAL, f"C:/Music/{index}.mp3", stable_id=f"item-{index}", title=f"Track {index}")
        for index in range(1, 6)
    )
    active = {"media": media[2]}
    items = [SimpleNamespace(queue_id=index, media=value) for index, value in enumerate(reversed(media))]
    played, jumps, output, messages = [], [], [], []
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", None)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", None)
    monkeypatch.setattr(main, "_sound_files", [value.original_uri for value in media])
    monkeypatch.setattr(main, "_library_media", lambda index: media[index - 1])
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    monkeypatch.setattr(main, "_blocked_label", lambda label, _media: label)
    monkeypatch.setattr(main, "IPrint", lambda text, **_kwargs: output.append(text))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs["display_message"]))
    monkeypatch.setattr(main, "local_play_commands", lambda values: played.append(media[int(values[1]) - 1]))
    monkeypatch.setattr(main, "_play_queue_item", lambda item: played.append(item.media))
    monkeypatch.setattr(
        main.vas.controller, "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PAUSED, media=active["media"]),
    )
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(
        current=lambda: items[2], items=lambda: items,
        state=lambda: {"repeat_mode": "off"},
        jump=lambda position: jumps.append(position) or items[position],
    ))
    return SimpleNamespace(
        media=media, active=active, items=items, played=played, jumps=jumps, output=output, messages=messages,
    )


@pytest.mark.parametrize(("command", "expected", "jumps"), [
    (".+2 lib", 4, []), (".-2 library", 0, []),
    (".+2 --in q", 0, [4]), (".-2 queue", 4, [0]),
])
def test_compact_cli_play_uses_the_requested_collection(navigation_scene, command, expected, jumps):
    scene = navigation_scene
    main.process(command)
    assert scene.played == [scene.media[expected]]
    assert scene.jumps == jumps
    assert scene.messages == []


@pytest.mark.parametrize(("command", "expected"), [
    ("+2 lib", "library 5/5"), ("-2 library", "library 1/5"),
    ("+2 --in q", "queue 5/5"), ("-2 queue", "queue 1/5"),
])
def test_compact_cli_preview_has_no_playback_or_queue_mutations(navigation_scene, command, expected):
    scene = navigation_scene
    main.process(command)
    assert expected in scene.output[-1]
    assert scene.played == scene.jumps == scene.messages == []
    assert scene.active["media"] is scene.media[2]


@pytest.mark.parametrize("command", [".+0 q", ".next two library", ".next --in blacklist", ".next queue library"])
def test_invalid_scoped_cli_input_cannot_play(navigation_scene, command):
    scene = navigation_scene
    main.process(command)
    assert len(scene.messages) == 1
    assert scene.played == scene.jumps == []


def test_results_reject_stale_library_identity_without_changing_context(monkeypatch, navigation_scene):
    scene = navigation_scene
    old = MediaRef(MediaSource.LOCAL, "C:/Music/old.mp3", stable_id="removed")
    context = NavigationContext(NavigationScope.RESULTS, (
        NavigationEntry(scene.media[2], scene.media[2].stable_id, 3, "Current", NavigationScope.LIBRARY),
        NavigationEntry(old, old.stable_id, 4, "Old result", NavigationScope.LIBRARY),
    ), 0, "library results")
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", context)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", context)
    with pytest.raises(ValueError, match="Library results changed"):
        main.navigation_command(".next", [])
    assert main._NAVIGATION_CONTEXT is main._LAST_SEARCH_CONTEXT is context
    assert scene.played == scene.jumps == []


def test_blocked_library_result_cannot_advance_navigation_context(monkeypatch, navigation_scene):
    scene = navigation_scene
    context = NavigationContext(NavigationScope.RESULTS, tuple(
        NavigationEntry(value, value.stable_id, index, value.title or "", NavigationScope.LIBRARY)
        for index, value in enumerate(scene.media[2:4], 3)
    ), 0, "library results")
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", context)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", context)

    def refuse(_media):
        raise main.PlaybackBlockedError("blocked")

    monkeypatch.setattr(main, "_ensure_media_playable", refuse)
    with pytest.raises(main.PlaybackBlockedError, match="blocked"):
        main.navigation_command(".next", [])
    assert main._NAVIGATION_CONTEXT is main._LAST_SEARCH_CONTEXT is context
    assert scene.played == scene.jumps == []


def test_failed_online_selection_keeps_both_contexts(monkeypatch):
    media = [MediaRef(MediaSource.URL, f"https://media.test/{index}") for index in range(2)]
    context = NavigationContext(NavigationScope.RESULTS, tuple(
        NavigationEntry(value, value.stable_id, index, "Online", NavigationScope.RESULTS)
        for index, value in enumerate(media, 1)
    ), 0, "results")
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", context)
    monkeypatch.setattr(main, "_LAST_SEARCH_CONTEXT", context)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media[0]))
    monkeypatch.setattr(main, "_ensure_media_playable", lambda _media: None)
    monkeypatch.setattr(main, "stopsong", lambda: None)

    def fail(_media, *, origin):
        assert origin == "cli"
        raise OSError("decoder unavailable")

    monkeypatch.setattr(main.vas.supervisor, "play", fail)
    with pytest.raises(OSError, match="decoder unavailable"):
        main.navigation_command(".next", [])
    assert main._NAVIGATION_CONTEXT is main._LAST_SEARCH_CONTEXT is context


def test_blocked_find_selection_does_not_replace_the_active_context(monkeypatch, navigation_scene):
    scene = navigation_scene
    previous = NavigationContext(NavigationScope.RESULTS, (
        NavigationEntry(scene.media[2], scene.media[2].stable_id, 3, "Current", NavigationScope.LIBRARY),
    ), 0, "previous results")
    monkeypatch.setattr(main, "_NAVIGATION_CONTEXT", previous)
    monkeypatch.setattr(main, "_sound_files_names_enumerated", [(4, "Blocked result")])

    def refuse(_media):
        raise main.PlaybackBlockedError("blocked")

    monkeypatch.setattr(main, "_ensure_media_playable", refuse)
    with pytest.raises(main.PlaybackBlockedError, match="blocked"):
        main.advanced_search_command([".find", "blocked"])
    assert main._NAVIGATION_CONTEXT is previous
    assert main._LAST_SEARCH_CONTEXT.cursor == -1
    assert scene.played == []


def test_unbound_duplicate_occurrences_require_an_explicit_selection():
    media = MediaRef(MediaSource.URL, "https://media.test/repeated")
    entries = tuple(
        NavigationEntry(media, media.stable_id, index, "Repeated", NavigationScope.PLAYLIST, index)
        for index in (1, 2)
    )
    context = NavigationContext(NavigationScope.PLAYLIST, entries, -1, "Duplicates")
    with pytest.raises(ValueError, match="occurs more than once"):
        main._bind_navigation_context(context, media)
    selected = context.at(1)
    assert main._bind_navigation_context(selected, media) is selected


@pytest.mark.parametrize("count", [True, False, 0, -1, 1.5, "2"])
def test_queue_step_rejects_invalid_count_before_any_playback_state_read(monkeypatch, count):
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: pytest.fail("invalid count read playback state"))
    with pytest.raises(QueueError, match="positive integer"):
        main._step_queue_playback("next", count)


@pytest.mark.parametrize("repeat_mode", ["all", "one"])
@pytest.mark.parametrize("count", [101, 10 ** 30])
def test_oversized_queue_count_is_rejected_before_repeating_queue_mutation(monkeypatch, tmp_path, repeat_mode, count):
    database = MarianaDatabase(tmp_path / "repeating.db")
    try:
        queue = PersistentQueue(database)
        for index in range(3):
            queue.add(MediaRef(MediaSource.URL, f"https://media.test/{index}"))
        current = queue.jump(0)
        queue.set_repeat(repeat_mode)
        before = queue.state()
        changes = database._connection.total_changes
        snapshot = Mock(return_value=PlaybackSnapshot(PlaybackState.PLAYING, media=current.media))
        original_advance = main._advance_queue_to_playable
        advances = []

        def bounded_probe(**kwargs):
            advances.append(kwargs)
            if len(advances) > 1:
                pytest.fail("oversized count reached repeated queue advancement")
            return original_advance(**kwargs)

        monkeypatch.setattr(main, "QUEUE", queue)
        monkeypatch.setattr(main.vas.controller, "snapshot", snapshot)
        monkeypatch.setattr(main, "_advance_queue_to_playable", bounded_probe)
        monkeypatch.setattr(main, "_is_media_blocked", lambda _media: False)
        monkeypatch.setattr(main.RECOMMENDER, "record_event", Mock())
        monkeypatch.setattr(main.STATION, "mark_played", Mock())
        monkeypatch.setattr(main, "_play_queue_item", Mock())
        with pytest.raises(QueueError, match="between 1 and 100"):
            main._step_queue_playback("next", count)
        snapshot.assert_not_called()
        main.RECOMMENDER.record_event.assert_not_called()
        main.STATION.mark_played.assert_not_called()
        main._play_queue_item.assert_not_called()
        assert advances == []
        assert queue.state() == before
        assert database._connection.total_changes == changes
    finally:
        database.close()


def test_queue_count_accepts_its_documented_upper_bound(monkeypatch):
    selected = SimpleNamespace(media=MediaRef(MediaSource.URL, "https://media.test/selected"))
    advance, play = Mock(return_value=selected), Mock()
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE))
    monkeypatch.setattr(main, "_advance_queue_to_playable", advance)
    monkeypatch.setattr(main, "_play_queue_item", play)
    assert main._step_queue_playback("next", 100) is selected
    assert advance.call_count == 100
    play.assert_called_once_with(selected)
