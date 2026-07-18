from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue


def test_blocked_state_persists_independently_from_favorite(tmp_path: Path):
    database_path = tmp_path / "state.db"
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "track.mp3"), title="Track")
    with MarianaDatabase(database_path) as database:
        preferences = MediaPreferences(database)
        assert preferences.set(media, PreferenceState.FAVORITE)
        assert preferences.set_blocked(media)
        assert preferences.is_favorite(media)
        assert preferences.is_blocked(media)
        assert preferences.list(PreferenceState.FAVORITE)[0].stable_id == media.stable_id
        assert preferences.list(PreferenceState.BLOCKED)[0].stable_id == media.stable_id
        assert preferences.set_blocked(media, False)
        assert preferences.is_favorite(media)
        assert not preferences.is_blocked(media)
    with MarianaDatabase(database_path) as database:
        assert MediaPreferences(database).is_favorite(media)
        assert not MediaPreferences(database).is_blocked(media)


def test_schema_migrates_legacy_block_without_leaving_tri_state_row(tmp_path: Path):
    path = tmp_path / "legacy.db"
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "legacy.mp3"), title="Legacy")
    with MarianaDatabase(path) as database:
        preferences = MediaPreferences(database)
        preferences.set(media, PreferenceState.FAVORITE)
        with database.transaction() as connection:
            connection.execute(
                "UPDATE media_preferences SET state='blocked' WHERE stable_id=?", (media.stable_id,)
            )
            connection.execute("UPDATE schema_meta SET value='8' WHERE key='schema_version'")
    with MarianaDatabase(path) as database:
        preferences = MediaPreferences(database)
        assert preferences.is_blocked(media)
        assert not preferences.is_favorite(media)
        assert database.fetchone(
            "SELECT state FROM media_preferences WHERE stable_id=?", (media.stable_id,)
        )["state"] == "neutral"


@pytest.fixture
def blocked_cli(monkeypatch, tmp_path: Path):
    paths = [tmp_path / f"Track {index}.mp3" for index in range(1, 4)]
    for path in paths:
        path.touch()
    database = MarianaDatabase(tmp_path / "policy.db")
    preferences = MediaPreferences(database)
    media = [
        MediaRef(
            MediaSource.LOCAL,
            str(path),
            stable_id=f"library-{index}",
            title=f"Track {index}",
            provenance="library",
        )
        for index, path in enumerate(paths, 1)
    ]
    info = {
        str(path.resolve()).casefold(): {
            "library_id": item.stable_id,
            "canonical_path": str(path.resolve()),
            "state": "available",
            "metadata": {"title": item.title},
        }
        for path, item in zip(paths, media, strict=True)
    }
    printed: list[str] = []
    played: list[MediaRef] = []
    monkeypatch.setattr(main, "PREFERENCES", preferences)
    monkeypatch.setattr(main, "_sound_files", [str(path) for path in paths])
    monkeypatch.setattr(main, "_sound_files_names_only", [path.stem for path in paths])
    monkeypatch.setattr(
        main,
        "_sound_files_names_enumerated",
        [(index, path.stem) for index, path in enumerate(paths, 1)],
    )
    monkeypatch.setattr(
        main.LIBRARY,
        "info",
        lambda value: info.get(str(Path(value).resolve()).casefold())
        or next((row for row in info.values() if row["library_id"] == value), None),
    )
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: printed.append(str(kwargs.get("display_message", ""))))
    monkeypatch.setattr(main, "purge_old_lyrics_if_exist", lambda: None)
    monkeypatch.setattr(main.vas, "set_media", lambda **_kwargs: played.append(media[0]))
    monkeypatch.setattr(main.vas, "media_player", lambda **_kwargs: None)
    monkeypatch.setattr(main.vas.player, "audio_set_volume", lambda _value: None)
    yield SimpleNamespace(
        database=database,
        preferences=preferences,
        media=media,
        paths=paths,
        printed=printed,
        played=played,
    )
    database.close()


def test_library_block_target_is_not_poisoned_by_search_or_queue(monkeypatch, blocked_cli):
    state = blocked_cli
    monkeypatch.setattr(main.QUEUE, "current", lambda: SimpleNamespace(media=state.media[2]))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=state.media[1]),
    )

    assert main.block_command(["1"])
    assert state.preferences.is_blocked(state.media[0])
    assert not state.preferences.is_blocked(state.media[1])
    assert not state.preferences.is_blocked(state.media[2])
    assert main.block_command(["1"], unblock=True) is False
    assert not state.preferences.is_blocked(state.media[0])


def test_block_current_preserves_favorite_and_projection_is_sanitized(monkeypatch, blocked_cli):
    state = blocked_cli
    state.preferences.set(state.media[1], PreferenceState.FAVORITE)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=state.media[1]),
    )
    monkeypatch.setattr(main.QUEUE, "playback_position", lambda _stable_id: (2, 3))

    assert main.block_command(["current"])
    projected = main._playback_status_projection()
    assert projected.policy.blocked and not projected.policy.playable
    assert projected.policy.unavailable_reason == "Playback blocked for this media"
    assert projected.favorite.is_favorite
    assert "Users" not in str(projected.to_dict())


def test_direct_local_play_refuses_blocked_without_preparing_audio(blocked_cli):
    state = blocked_cli
    state.preferences.set_blocked(state.media[0])

    main.local_play_commands(["play", "1"])

    assert state.played == []
    assert any("Playback blocked" in line for line in state.printed)


def test_blocked_favorite_can_be_inspected_but_not_played(monkeypatch, blocked_cli):
    state = blocked_cli
    state.preferences.set(state.media[0], PreferenceState.FAVORITE)
    state.preferences.set_blocked(state.media[0])
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("blocked favorite played")),
    )

    main.favorite_command(["1"])
    with pytest.raises(main.PlaybackBlockedError, match="Playback blocked"):
        main.favorite_command(["1"], play=True)
    assert any("[Blocked]" in line for line in state.printed)


def test_random_and_queue_advance_skip_blocked(monkeypatch, blocked_cli):
    state = blocked_cli
    state.preferences.set_blocked(state.media[0])
    state.preferences.set_blocked(state.media[1])
    assert main.rand_song_index_generate() == 2

    queue = PersistentQueue(state.database)
    queue.clear()
    items = [queue.add(item, allow_duplicate=True) for item in state.media]
    queue.jump(0)
    monkeypatch.setattr(main, "QUEUE", queue)
    assert main._advance_queue_to_playable().queue_id == items[2].queue_id


def test_queue_jump_refuses_blocked_item_without_moving_cursor(monkeypatch, blocked_cli):
    state = blocked_cli
    queue = PersistentQueue(state.database)
    queue.clear()
    items = [queue.add(item, allow_duplicate=True) for item in state.media]
    queue.jump(0)
    state.preferences.set_blocked(state.media[1])
    monkeypatch.setattr(main, "QUEUE", queue)

    with pytest.raises(main.PlaybackBlockedError, match="Playback blocked"):
        main.queue_command(["jump", "2"])

    assert queue.current().queue_id == items[0].queue_id


def test_blocked_list_and_search_mark_items_without_hiding_them(blocked_cli):
    state = blocked_cli
    state.preferences.set(state.media[0], PreferenceState.FAVORITE)
    state.preferences.set_blocked(state.media[0])

    main.blocked_command([])
    main.advanced_search_command(["find", "Track"])

    output = "\n".join(state.printed)
    assert "Track 1 [Blocked]" in output
    assert "Track 2" in output and "Track 3" in output


def test_queue_list_marks_blocked_item_and_unblock_restores_playability(monkeypatch, blocked_cli):
    state = blocked_cli
    queue = PersistentQueue(state.database)
    queue.clear()
    queue.add(state.media[0], allow_duplicate=True)
    monkeypatch.setattr(main, "QUEUE", queue)
    state.preferences.set(state.media[0], PreferenceState.FAVORITE)
    state.preferences.set_blocked(state.media[0])

    main.queue_command(["list"])
    assert any("Track 1 [Blocked]" in line for line in state.printed)

    assert main.block_command(["1"], unblock=True) is False
    assert state.preferences.is_favorite(state.media[0])
    assert not state.preferences.is_blocked(state.media[0])
    assert main._ensure_media_playable(state.media[0]) == state.media[0]


def test_blocked_online_media_is_refused_before_current_playback_stops(monkeypatch, blocked_cli):
    state = blocked_cli
    media_url = "https://www.youtube.com/watch?v=abcdefghijk"
    media = MediaRef(MediaSource.YOUTUBE, media_url, title="Online track")
    state.preferences.set_blocked(media)
    stopped: list[bool] = []
    monkeypatch.setattr(main, "stopsong", lambda: stopped.append(True))

    with pytest.raises(main.PlaybackBlockedError, match="Playback blocked"):
        main.play_vas_media(media_url, media_type="video")

    assert stopped == []


def test_policy_helpers_handle_unbound_and_legacy_preference_adapters(monkeypatch, blocked_cli):
    state = blocked_cli
    assert not main._is_media_blocked(None)
    monkeypatch.setattr(
        main,
        "PREFERENCES",
        SimpleNamespace(get=lambda media: PreferenceState.BLOCKED if media else PreferenceState.NEUTRAL),
    )
    assert main._is_media_blocked(state.media[0])
    with pytest.raises(main.PlaybackBlockedError, match="Playback blocked"):
        main._ensure_media_playable(state.media[0])

    with pytest.raises(ValueError, match="Library number"):
        main._library_media(0)
    monkeypatch.setattr(main, "_preference_media", lambda _media: None)
    with pytest.raises(ValueError, match="unavailable"):
        main._library_media(1)

    monkeypatch.setattr(
        main.LIBRARY,
        "info",
        lambda _value: {"state": "available", "canonical_path": 1, "library_id": "library-1"},
    )
    local = MediaRef(MediaSource.LOCAL, str(state.paths[0]))
    assert main._indexed_local_playback_media(local) == local


def test_block_commands_validate_targets_and_legacy_operations(monkeypatch, blocked_cli):
    state = blocked_cli
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=state.media[0]),
    )

    assert main.preference_command([], PreferenceState.BLOCKED) == PreferenceState.NEUTRAL
    assert main.preference_command(["!"], PreferenceState.BLOCKED) == PreferenceState.BLOCKED
    assert main.preference_command([], PreferenceState.BLOCKED) == PreferenceState.BLOCKED
    assert main.preference_command(["-"], PreferenceState.BLOCKED) == PreferenceState.NEUTRAL
    assert main.preference_command(["+"], PreferenceState.BLOCKED) == PreferenceState.BLOCKED
    with pytest.raises(ValueError, match="Usage: bl"):
        main.preference_command(["invalid"], PreferenceState.BLOCKED)
    with pytest.raises(ValueError, match="Usage: block"):
        main.block_command([])
    with pytest.raises(ValueError, match="Usage: unblock"):
        main.block_command(["search", "1"], unblock=True)
    with pytest.raises(ValueError, match="Usage: block"):
        main.block_command(["0"])
    with pytest.raises(ValueError, match="Usage: blocked"):
        main.blocked_command(["bad"])

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    with pytest.raises(ValueError, match="No current media"):
        main.block_command(["current"])


def test_queue_policy_helpers_cover_empty_repeat_wrap_and_previous(monkeypatch, blocked_cli):
    state = blocked_cli
    queue = PersistentQueue(state.database)
    queue.clear()
    monkeypatch.setattr(main, "QUEUE", queue)
    assert main._queue_candidate_after(SimpleNamespace(queue_id="missing")) is None
    assert main._advance_queue_to_playable() is None

    items = [queue.add(item, allow_duplicate=True) for item in state.media]
    assert main._queue_candidate_after(SimpleNamespace(queue_id="missing")) is None
    queue.jump(0)
    queue.set_repeat("one")
    assert main._queue_candidate_after(items[0]).queue_id == items[0].queue_id
    state.preferences.set_blocked(state.media[0])
    assert main._queue_candidate_after(items[0]) is None

    queue.set_repeat("all")
    state.preferences.set_blocked(state.media[0], False)
    state.preferences.set_blocked(state.media[1])
    assert main._queue_candidate_after(items[2]).queue_id == items[0].queue_id
    queue.jump(2)
    assert main._advance_queue_to_playable(previous=True).queue_id == items[0].queue_id

    for media in state.media:
        state.preferences.set_blocked(media)
    queue.jump(0)
    assert main._advance_queue_to_playable() is None

    blocked_item = SimpleNamespace(queue_id="blocked", media=state.media[0])
    monkeypatch.setattr(
        main,
        "QUEUE",
        SimpleNamespace(
            items=lambda: [blocked_item],
            current=lambda: None,
            next=lambda: blocked_item,
            previous=lambda: blocked_item,
        ),
    )
    assert main._advance_queue_to_playable() is None


def test_prefetch_and_all_blocked_random_obey_policy(monkeypatch, blocked_cli):
    state = blocked_cli
    queue = PersistentQueue(state.database)
    queue.clear()
    items = [queue.add(item, allow_duplicate=True) for item in state.media]
    queue.jump(0)
    state.preferences.set_blocked(state.media[1])
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "AUTOPLAY_ENABLED", True)
    prefetched: list[MediaRef] = []
    monkeypatch.setattr(main.vas.controller, "prefetch", prefetched.append)

    main._prefetch_after(items[0])
    assert prefetched and prefetched[0].stable_id == state.media[2].stable_id

    state.preferences.set_blocked(state.media[0])
    state.preferences.set_blocked(state.media[2])
    assert main.rand_song_index_generate() is None
    assert any("No playable library media" in line for line in state.printed)


def test_status_summary_and_current_fallback_report_blocked_safely(monkeypatch, blocked_cli):
    state = blocked_cli
    media = MediaRef(MediaSource.YOUTUBE, "https://example.test/watch", title=None)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=5, duration=10),
    )
    assert main.block_command(["current"])
    projection = main._playback_status_projection()
    assert projection.policy.blocked
    assert "playback blocked" in main._status_summary(projection)
    assert any("YouTube media" in line for line in state.printed)


def test_blocked_list_labels_durable_sources_without_exposing_locations(blocked_cli):
    state = blocked_cli
    sources = (
        MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch", title="Video"),
        MediaRef(MediaSource.URL, "https://media.test/audio", title="Stream"),
        MediaRef(MediaSource.PODCAST, "https://podcast.test/episode", title="Episode"),
        MediaRef(MediaSource.RADIO, "https://radio.test/live", title="Station"),
    )
    for media in sources:
        state.preferences.set_blocked(media)
    state.preferences.set_blocked("orphaned-policy-id")

    main.blocked_command(["list"])
    main.blocked_command(["2"])
    output = "\n".join(state.printed)
    assert "YouTube" in output
    assert "Online media" in output
    assert "Podcast" in output
    assert "Radio" in output
    assert "https://" not in output
    assert "orphaned-policy-id" not in output


def test_favorite_selection_validation_remains_safe_with_block_policy(blocked_cli):
    state = blocked_cli
    with pytest.raises(ValueError, match="No favorites"):
        main._favorite_selection(1)

    state.preferences.set(state.media[0], PreferenceState.FAVORITE)
    with pytest.raises(ValueError, match="Favorite number"):
        main._favorite_selection(2)
    with pytest.raises(ValueError, match=r"Usage: \.fav"):
        main.favorite_command([], play=True)
    with pytest.raises(ValueError, match="Usage: fav"):
        main.favorite_command(["0"])

    state.paths[0].unlink()
    with pytest.raises(ValueError, match="missing or unavailable"):
        main._favorite_selection(1)
