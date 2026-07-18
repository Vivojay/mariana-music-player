from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.play_regions import (
    PlayRegionError,
    PlayRegionStore,
    format_region_time,
    parse_region_time,
)
from mariana.preferences import MediaPreferences


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("5.180", 5.18),
        ("5.180s", 5.18),
        ("00:05.180", 5.18),
        ("1:05:03.180", 3903.18),
        ("1h5m3.180s", 3903.18),
        ("1h 5m 3s 180ms", 3903.18),
    ],
)
def test_parse_region_time_forms(value, seconds):
    assert parse_region_time(value) == seconds


@pytest.mark.parametrize(
    "value",
    ["", "-1", "+2s", "1m2h", "1s 2s", "1:bad", "1:2:3:4:5", "nan", "9" * 400],
)
def test_parse_region_time_rejects_invalid_or_ambiguous_values(value):
    with pytest.raises(PlayRegionError):
        parse_region_time(value)


def test_region_store_persists_normalized_bounds_and_clears_independently(tmp_path: Path):
    path = tmp_path / "regions.db"
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "song.mp3"), duration=100, stable_id="library-1")
    with MarianaDatabase(path) as database:
        store = PlayRegionStore(database)
        region = store.set(media, start_seconds=5.1804, end_seconds=65.1804, duration=100)
        assert region.start_seconds == 5.18
        assert region.end_seconds == 65.18
        assert store.clear_bound(media, "start").start_seconds is None
        assert store.get(media).end_seconds == 65.18
    with MarianaDatabase(path) as database:
        store = PlayRegionStore(database)
        assert store.get(media).end_seconds == 65.18
        assert store.clear_bound(media, "end") is None
        assert store.get(media) is None


@pytest.mark.parametrize(
    ("start", "end", "duration", "message"),
    [
        (-1, None, 100, "Start bound"),
        (5, 5, 100, "after"),
        (None, 0, 100, "positive"),
        (100, None, 100, "before"),
        (None, 101, 100, "exceeds"),
        (None, 5, None, "finite known"),
        (None, 5, "invalid", "finite known"),
    ],
)
def test_region_store_rejects_invalid_bounds(tmp_path, start, end, duration, message):
    with (
        MarianaDatabase(tmp_path / "invalid.db") as database,
        pytest.raises(PlayRegionError, match=message),
    ):
        PlayRegionStore(database).set(
            "media",
            start_seconds=start,
            end_seconds=end,
            duration=duration,
        )


@pytest.fixture
def region_cli(monkeypatch, tmp_path):
    paths = []
    metadata = {}
    for index, duration in enumerate((100.0, 5000.0), 1):
        path = tmp_path / f"Track {index}.mp3"
        path.write_bytes(b"source audio")
        paths.append(path)
        metadata[str(path.resolve()).casefold()] = {
            "library_id": f"library-{index}",
            "canonical_path": str(path.resolve()),
            "state": "available",
            "metadata": {"title": f"Track {index}", "duration": duration},
        }
        metadata[f"library-{index}"] = metadata[str(path.resolve()).casefold()]
        metadata[str(index)] = metadata[str(path.resolve()).casefold()]
    database = MarianaDatabase(tmp_path / "cli.db")
    regions = PlayRegionStore(database)
    preferences = MediaPreferences(database)
    printed = []
    monkeypatch.setattr(main, "_sound_files", [str(path) for path in paths])
    monkeypatch.setattr(main, "_sound_files_names_only", [path.stem for path in paths])
    monkeypatch.setattr(main.LIBRARY, "info", lambda value: metadata.get(str(value).casefold()))
    monkeypatch.setattr(main, "PLAY_REGIONS", regions)
    monkeypatch.setattr(main, "PREFERENCES", preferences)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=MediaRef(
                MediaSource.LOCAL,
                str(paths[1]),
                duration=5000,
                stable_id="library-2",
                title="Track 2",
                provenance="library",
            ),
            duration=5000,
        ),
    )
    yield SimpleNamespace(database=database, regions=regions, preferences=preferences, paths=paths, printed=printed)
    database.close()


def test_region_commands_bind_library_index_without_current_or_list_poisoning(region_cli, monkeypatch):
    state = region_cli
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(current=lambda: SimpleNamespace(media=MediaRef(MediaSource.LOCAL, str(state.paths[1])))))
    main._sound_files_names_enumerated = [(99, "stale search")]

    region = main.region_command(["1", "5.180", "1:05.180"])
    assert region.stable_id == "library-1"
    assert state.regions.get("library-2") is None
    main.region_command(["clear-start", "1"])
    assert state.regions.get("library-1").start_seconds is None
    main.region_command(["clear", "1"])
    assert state.regions.get("library-1") is None


def test_region_current_partial_bounds_listing_and_blocked_independence(region_cli):
    state = region_cli
    state.preferences.set_blocked("library-2")

    start = main.region_command(["current", "start", "1h", "5m", "3s", "180ms"])
    assert start.start_seconds == 3903.18
    assert state.preferences.is_blocked("library-2")
    end = main.region_command(["current", "end", "1:06:03.180"])
    assert end.end_seconds == 3963.18


def test_region_current_and_listing_are_path_free(region_cli):
    state = region_cli
    main.region_command(["current", "start", "5s"])
    main.region_command(["show", "current"])
    rows = main.regions_command([])

    assert rows
    output = "\n".join(state.printed)
    assert str(state.paths[1]) not in output
    assert "library-2" not in output
    assert "Track 2" in output


def test_region_is_shown_in_media_info_and_playback_status(region_cli, monkeypatch):
    state = region_cli
    main.region_command(["1", "5.180", "1:05.180"])
    main.media_command(["info", "1"])
    media = main._library_media(1)
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=media,
            position=6,
            duration=100,
            region_start_seconds=5.18,
            region_end_seconds=65.18,
        ),
    )
    monkeypatch.setattr(main.QUEUE, "playback_position", lambda _stable_id: (None, 0))

    status = main._playback_status_projection()
    lines = main._playback_status_lines(status, detailed=True)

    assert "Preferred play region" in "\n".join(state.printed)
    status_output = "\n".join(lines)
    assert "0:05.180 -> 1:05.180" in status_output
    assert str(state.paths[0]) not in status_output


def test_region_refuses_unknown_duration_and_live_current(monkeypatch, region_cli):
    state = region_cli
    live = MediaRef(
        MediaSource.RADIO,
        "https://radio.example/live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=live),
    )
    with pytest.raises(PlayRegionError, match="Live or non-finite"):
        main.region_command(["current", "start", "5"])

    unknown = MediaRef(MediaSource.YOUTUBE, "https://youtube.example/watch", title="Online")
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=unknown),
    )
    with pytest.raises(PlayRegionError, match="finite known"):
        main.region_command(["current", "start", "5"])
    assert not state.regions.list()


def test_setting_region_does_not_modify_source_file(region_cli):
    state = region_cli
    before = state.paths[0].read_bytes(), state.paths[0].stat().st_mtime_ns
    main.region_command(["1", "start", "5.180"])
    after = state.paths[0].read_bytes(), state.paths[0].stat().st_mtime_ns
    assert after == before


def test_region_format_uses_natural_endpoint_labels():
    assert format_region_time(None) == "natural"
    assert format_region_time(5.18) == "0:05.180"


def test_clear_missing_region_is_a_safe_noop(tmp_path):
    with MarianaDatabase(tmp_path / "missing.db") as database:
        assert PlayRegionStore(database).clear_bound("missing", "start") is None
