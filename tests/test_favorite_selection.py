from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import PreferenceEntry, PreferenceState


def _favorite_fixture(monkeypatch, tmp_path: Path):
    paths = []
    for name in ("Alpha.mp3", "Library Two.mp3", "Gamma.mp3"):
        path = tmp_path / name
        path.write_bytes(b"audio")
        paths.append(path)

    media = {
        "alpha-id": MediaRef(
            MediaSource.LOCAL,
            str(paths[0]),
            stable_id="alpha-id",
            title="Alpha favorite",
            provenance="library",
        ),
        "gamma-id": MediaRef(
            MediaSource.LOCAL,
            str(paths[2]),
            stable_id="gamma-id",
            title="Gamma favorite",
            provenance="library",
        ),
    }
    # Favorite #2 intentionally maps to library #1, not library #2.
    entries = [
        PreferenceEntry(
            "gamma-id",
            PreferenceState.FAVORITE,
            "Gamma favorite",
            str(paths[2]),
            20,
            MediaSource.LOCAL,
            "available",
        ),
        PreferenceEntry(
            "alpha-id",
            PreferenceState.FAVORITE,
            "Alpha favorite",
            str(paths[0]),
            10,
            MediaSource.LOCAL,
            "available",
        ),
    ]
    info = {
        stable_id: {
            "library_id": stable_id,
            "canonical_path": item.original_uri,
            "state": "available",
            "metadata": {"title": item.title},
        }
        for stable_id, item in media.items()
    }
    printed = []
    messages = []
    played = []
    preferences = SimpleNamespace(
        list=lambda state, limit=None: entries[:limit] if limit is not None else list(entries),
        media=lambda stable_id: media.get(stable_id),
        get=lambda _media: PreferenceState.NEUTRAL,
        set=lambda *_args: True,
        toggle=lambda _media, state: state,
    )
    monkeypatch.setattr(main, "PREFERENCES", preferences)
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(info=lambda stable_id: info.get(stable_id)))
    monkeypatch.setattr(main, "_sound_files", [str(path) for path in paths])
    monkeypatch.setattr(main, "_sound_files_names_only", [path.stem for path in paths])
    monkeypatch.setattr(
        main,
        "_sound_files_names_enumerated",
        [(index, path.stem) for index, path in enumerate(paths, start=1)],
    )
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.IDLE)),
    )
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda path, _songindex, **kwargs: played.append((path, _songindex, kwargs["media"])),
    )
    return SimpleNamespace(
        paths=paths,
        media=media,
        entries=entries,
        info=info,
        printed=printed,
        messages=messages,
        played=played,
    )


@pytest.mark.parametrize("command", ["fav list", "favs", "favs list"])
def test_favorite_list_forms_use_local_indices_without_paths(monkeypatch, tmp_path, command):
    state = _favorite_fixture(monkeypatch, tmp_path)

    main.process(command)

    output = "\n".join(state.printed)
    assert "Gamma favorite" in output and "Alpha favorite" in output
    assert "Library #3" in output and "Library #1" in output
    assert str(tmp_path) not in output
    assert "http://" not in output and "https://" not in output


def test_bare_fav_checks_current_media_and_current_alias_remains_compatible(monkeypatch, tmp_path):
    state = _favorite_fixture(monkeypatch, tmp_path)
    active = state.media["alpha-id"]
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=active)),
    )
    monkeypatch.setattr(main.PREFERENCES, "get", lambda _media: PreferenceState.FAVORITE)

    main.process("fav")
    main.process("fav current")

    assert state.printed.count("Current media is favorited") == 2

    state.printed.clear()
    monkeypatch.setattr(main.PREFERENCES, "get", lambda _media: PreferenceState.NEUTRAL)
    main.process("fav")
    assert state.printed == ["Current media is not favorited"]


def test_bare_fav_without_current_media_reports_clear_error(monkeypatch, tmp_path):
    state = _favorite_fixture(monkeypatch, tmp_path)

    main.process("fav")

    assert state.printed == []
    assert state.messages[-1]["display_message"] == "No current media to favorite/check"


def test_fav_numeric_is_independent_from_library_numeric_selection(monkeypatch, tmp_path):
    state = _favorite_fixture(monkeypatch, tmp_path)

    main.process("fav 2")
    favorite_output = "\n".join(state.printed)
    assert "Favorite #2: Alpha favorite" in favorite_output
    assert "Library: #1" in favorite_output
    assert "Library Two" not in favorite_output

    state.printed.clear()
    main.process("2")
    assert any("Library Two" in line for line in state.printed)


def test_favorite_list_detail_and_play_confirmation_share_safe_catalog_label(monkeypatch, tmp_path):
    state = _favorite_fixture(monkeypatch, tmp_path)
    state.media["alpha-id"].title = None
    state.info["alpha-id"]["metadata"] = {}
    state.entries[1] = PreferenceEntry(
        "alpha-id",
        PreferenceState.FAVORITE,
        state.paths[0].stem,
        str(state.paths[0]),
        10,
        MediaSource.LOCAL,
        "available",
    )

    main.process("fav list")
    listed = "\n".join(state.printed)
    assert state.paths[0].stem in listed

    state.printed.clear()
    main.process("fav 2")
    main.process(".fav 2")
    output = "\n".join(state.printed)
    assert f"Favorite #2: {state.paths[0].stem}" in output
    assert f"Playing favorite #2: {state.paths[0].stem}" in output
    assert "Local media" not in output


def test_favorite_label_uses_generic_fallback_only_without_safe_text(tmp_path):
    entry = PreferenceEntry(
        "local-id",
        PreferenceState.FAVORITE,
        str(tmp_path / "private.mp3"),
        str(tmp_path / "private.mp3"),
        1,
        MediaSource.LOCAL,
    )
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "private.mp3"), stable_id="local-id")

    assert main._favorite_display_label(entry, media) == "Local media"


def test_dot_fav_plays_the_bound_favorite_despite_search_and_queue_state(monkeypatch, tmp_path):
    state = _favorite_fixture(monkeypatch, tmp_path)

    main.process("find Gamma")
    monkeypatch.setattr(
        main,
        "QUEUE",
        SimpleNamespace(items=lambda: (_ for _ in ()).throw(AssertionError("queue consulted"))),
    )
    main.process(".fav 2")

    assert len(state.played) == 1
    path, library_index, media = state.played[0]
    assert Path(path) == state.paths[0]
    assert library_index == "1"
    assert media.stable_id == "alpha-id"
    assert any("Playing favorite #2: Alpha favorite" in line for line in state.printed)


def test_missing_or_tombstoned_favorite_is_refused_without_playback(monkeypatch, tmp_path):
    state = _favorite_fixture(monkeypatch, tmp_path)
    state.info["alpha-id"]["state"] = "missing"

    main.process(".fav 2")

    assert state.played == []
    assert state.messages[-1]["display_message"] == (
        "Favorite #2 is missing or unavailable in the indexed library"
    )


def test_online_favorite_uses_durable_media_without_exposing_its_url(monkeypatch):
    media = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=private-id",
        stable_id="online-id",
        title="Online favorite",
    )
    entry = PreferenceEntry(
        media.stable_id,
        PreferenceState.FAVORITE,
        media.title,
        media.original_uri,
        1,
        MediaSource.YOUTUBE,
    )
    printed = []
    played = []
    monkeypatch.setattr(
        main,
        "PREFERENCES",
        SimpleNamespace(
            list=lambda *_args, **_kwargs: [entry],
            media=lambda stable_id: media if stable_id == media.stable_id else None,
        ),
    )
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "stopsong", lambda: None)
    monkeypatch.setattr(main.vas.supervisor, "play", lambda selected: played.append(selected))
    monkeypatch.setattr(main, "_set_current_media_state", lambda _media: None)
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda _media: None)

    main.favorite_command(["1"])
    main.favorite_command(["1"], play=True)

    assert played == [media]
    assert any("Favorite #1: Online favorite" in line for line in printed)
    output = "\n".join(printed)
    assert "youtube.com" not in output and "private-id" not in output


def test_favorite_edit_tokens_remain_active_media_operations(monkeypatch, tmp_path):
    state = _favorite_fixture(monkeypatch, tmp_path)
    active = state.media["alpha-id"]
    calls = []
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=active)),
    )
    monkeypatch.setattr(main.PREFERENCES, "set", lambda media, value: calls.append((media, value)) or True)

    main.process("fav +")

    assert calls and calls[0][1] == PreferenceState.FAVORITE
    assert any("Preference: favorite" in line for line in state.printed)
