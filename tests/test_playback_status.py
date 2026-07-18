import math

import pytest

from mariana.database import MarianaDatabase
from mariana.models import (
    MediaCapabilities,
    MediaChapter,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
)
from mariana.playback_status import (
    FavoriteStatusProjection,
    PlaybackChapterProjection,
    project_playback_status,
)
from mariana.queueing import PersistentQueue


def media(
    source=MediaSource.LOCAL,
    *,
    title: str | None = "Track",
    artist="Artist",
    duration=100.0,
    finite=True,
    live=False,
    seekable=True,
):
    return MediaRef(
        source,
        "C:/private/track.flac" if source == MediaSource.LOCAL else "https://signed.example/media?token=secret",
        title=title,
        artist=artist,
        duration=duration,
        capabilities=MediaCapabilities(finite=finite, live=live, seekable=seekable),
    )


@pytest.mark.parametrize(
    ("state", "display"),
    [
        (PlaybackState.RESOLVING, "Resolving"),
        (PlaybackState.BUFFERING, "Buffering"),
        (PlaybackState.PLAYING, "Playing"),
        (PlaybackState.PAUSED, "Paused"),
        (PlaybackState.SEEKING, "Seeking"),
        (PlaybackState.CROSSFADING, "Crossfading"),
        (PlaybackState.FAILED, "Failed"),
        (PlaybackState.STOPPING, "Stopping"),
    ],
)
def test_projection_maps_playback_states(state, display):
    projection = project_playback_status(PlaybackSnapshot(state, media=media()))
    assert projection.state == state.value
    assert projection.display_state == display


@pytest.mark.parametrize(
    ("position", "expected"),
    [(-10, 0.0), (0, 0.0), (25, 25.0), (100, 100.0), (150, 100.0)],
)
def test_projection_clamps_finite_progress(position, expected):
    projection = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=media(), position=position, duration=100)
    )
    assert projection.percent == expected


@pytest.mark.parametrize("duration", [None, 0, -1, math.nan, math.inf, -math.inf])
def test_projection_rejects_unknown_or_nonfinite_duration(duration):
    projection = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=media(), position=20, duration=duration)
    )
    assert projection.duration_seconds is None
    assert projection.percent is None


@pytest.mark.parametrize("position", [math.nan, math.inf, -math.inf])
def test_projection_normalizes_nonfinite_position(position):
    projection = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=media(), position=position, duration=100)
    )
    assert projection.position_seconds == 0
    assert projection.percent == 0


def test_projection_includes_safe_finite_metadata_and_chapter():
    chaptered = media()
    chaptered.chapters = [
        MediaChapter("Intro", 0, 20),
        MediaChapter("Verse\nOne", 20, 40),
        MediaChapter("Outro", 40, 100),
    ]
    projection = project_playback_status(
        PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=chaptered,
            position=25,
            duration=100,
            buffered_seconds=3,
            replaygain_db=-2.5,
            current_chapter=chaptered.chapters[1],
        ),
        queue_position=2,
        queue_count=5,
    )
    assert projection.schema_version == 5
    assert projection.title == "Track" and projection.artist == "Artist"
    assert projection.source == "local" and projection.media_id
    assert projection.finite and projection.seekable and not projection.live
    assert projection.queue_position == 2 and projection.queue_count == 5
    assert projection.buffered_seconds == 3 and projection.replaygain_db == -2.5
    assert projection.chapter == PlaybackChapterProjection("Verse One", 20, 40, 2, 3)
    assert projection.favorite == FavoriteStatusProjection(
        False,
        False,
        False,
        "Favourite state unavailable",
    )
    assert projection.to_dict()["chapter"] == {
        "title": "Verse One",
        "start_time": 20,
        "end_time": 40,
        "index": 2,
        "count": 3,
    }


def test_projection_carries_only_sanitized_favorite_state():
    favorite = FavoriteStatusProjection(True, True, True)
    projection = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=media()),
        favorite=favorite,
    )

    assert projection.favorite is favorite
    assert projection.to_dict()["favorite"] == {
        "available": True,
        "is_favorite": True,
        "toggle_enabled": True,
        "unavailable_reason": None,
    }
    assert set(projection.to_dict()["favorite"]) == {
        "available",
        "is_favorite",
        "toggle_enabled",
        "unavailable_reason",
    }


def test_projection_represents_live_nonseekable_media_without_percentage():
    station = media(MediaSource.RADIO, title="Groove Salad", finite=False, live=True, seekable=False)
    projection = project_playback_status(
        PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=station,
            position=49,
            duration=999,
            stream_title="Current Song",
            live_leveling=True,
        )
    )
    assert projection.title == "Current Song"
    assert projection.source == "radio"
    assert projection.live and not projection.finite and not projection.seekable
    assert projection.duration_seconds is None and projection.percent is None
    assert projection.live_leveling


@pytest.mark.parametrize(
    ("source", "title", "expected"),
    [
        (MediaSource.LOCAL, None, "Local media"),
        (MediaSource.YOUTUBE, None, "YouTube media"),
        (MediaSource.URL, "https://private.example/signed", "Online media"),
        (MediaSource.PODCAST, None, "Podcast episode"),
        (MediaSource.RADIO, None, "Live stream"),
        (MediaSource.RECOMMENDATION, None, "Recommended media"),
    ],
)
def test_projection_uses_safe_source_fallbacks(source, title, expected):
    projected = project_playback_status(
        PlaybackSnapshot(
            PlaybackState.PLAYING,
            media=media(source, title=title, finite=source != MediaSource.RADIO, live=source == MediaSource.RADIO),
        )
    )
    assert projected.title == expected
    assert "private.example" not in (projected.title or "")
    assert "signed.example" not in projected.to_dict().values()


def test_projection_uses_dedicated_indexed_local_display_title_without_exposing_a_path():
    indexed = media(title=None)
    indexed.provenance = "library"
    indexed.resolver_data["library_display_title"] = "maybe you miss me [932698612]"

    projected = project_playback_status(PlaybackSnapshot(PlaybackState.PLAYING, media=indexed))

    assert projected.title == "maybe you miss me [932698612]"
    assert "C:/private" not in str(projected.to_dict())


def test_projection_accepts_library_index_only_for_indexed_local_media():
    indexed = media(title="Indexed Track")
    indexed.provenance = "library"
    online = media(MediaSource.YOUTUBE, title="Online Track")
    unindexed = media(title=None)

    local_status = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=indexed),
        library_index=37,
    )
    online_status = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=online),
        library_index=37,
    )
    unindexed_status = project_playback_status(
        PlaybackSnapshot(PlaybackState.PLAYING, media=unindexed),
        library_index=37,
    )

    assert local_status.library_index == 37
    assert online_status.library_index is None
    assert unindexed_status.library_index is None


def test_projection_rejects_unsafe_indexed_local_display_title():
    indexed = media(title=None)
    indexed.provenance = "library"
    indexed.resolver_data["library_display_title"] = r"C:\\Users\\Vivan\\private-song.mp3"

    projected = project_playback_status(PlaybackSnapshot(PlaybackState.PLAYING, media=indexed))

    assert projected.title == "Local media"


def test_projection_keeps_placeholder_local_title_safe_without_exposing_origin():
    indexed = media(title="Unknown Artist - YouTube audio [dYsg37kwCwM]")
    indexed.provenance = "library"
    indexed.resolver_data.update(
        {
            "library_id": "37",
            "webpage_url": "https://www.youtube.com/watch?v=dYsg37kwCwM&token=secret",
        }
    )

    projected = project_playback_status(PlaybackSnapshot(PlaybackState.PLAYING, media=indexed))

    assert projected.title == "Unknown Artist - YouTube audio [dYsg37kwCwM]"
    serialized = str(projected.to_dict())
    assert "youtube.com" not in serialized
    assert "token=secret" not in serialized
    assert "C:/private" not in serialized


def test_projection_sanitizes_artist_error_and_invalid_numeric_values():
    unsafe = media(MediaSource.URL, title="https://private.example/song", artist="C:\\Users\\Name")
    projection = project_playback_status(
        PlaybackSnapshot(
            PlaybackState.FAILED,
            media=unsafe,
            error="ffmpeg -i https://signed.example/song?token=secret --header cookie=x",
            buffered_seconds=math.nan,
            replaygain_db=math.inf,
        )
    )
    assert projection.title == "Online media" and projection.artist is None
    assert projection.safe_error == "Playback failed; see logs for details"
    assert projection.buffered_seconds == 0 and projection.replaygain_db == 0
    serialized = str(projection.to_dict())
    assert "signed.example" not in serialized and "C:\\Users" not in serialized


def test_projection_keeps_short_safe_errors_and_drops_invalid_chapters():
    projection = project_playback_status(
        PlaybackSnapshot(
            PlaybackState.FAILED,
            media=media(),
            error="  Audio output\nwas disconnected  ",
            current_chapter=MediaChapter("Broken", 20, 10),
        )
    )
    assert projection.safe_error == "Audio output was disconnected"
    assert projection.chapter is None


def test_projection_rejects_command_errors_and_non_numeric_gain():
    projection = project_playback_status(
        PlaybackSnapshot(
            PlaybackState.FAILED,
            media=media(),
            error="ffmpeg -i input.wav",
            replaygain_db="not-a-number",  # type: ignore[arg-type]
        )
    )
    assert projection.safe_error == "Playback failed; see logs for details"
    assert projection.replaygain_db == 0


def test_projection_distinguishes_completed_from_explicitly_stopped_idle():
    completed = project_playback_status(
        PlaybackSnapshot(PlaybackState.IDLE, media=media(), position=100, duration=100)
    )
    stopped = project_playback_status(PlaybackSnapshot(PlaybackState.IDLE, media=media()))
    empty = project_playback_status(PlaybackSnapshot(PlaybackState.IDLE))
    assert completed.display_state == "Finished"
    assert stopped.display_state == empty.display_state == "Stopped"
    assert empty.media_id is None and empty.title is None
    assert not empty.favorite.available and not empty.favorite.toggle_enabled
    assert empty.favorite.unavailable_reason == "No active media"


def test_projection_rejects_invalid_queue_positions():
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media())
    assert project_playback_status(snapshot, queue_position=0, queue_count=2).queue_position is None
    assert project_playback_status(snapshot, queue_position=3, queue_count=2).queue_position is None
    assert project_playback_status(snapshot, queue_position=1, queue_count=-3).queue_position is None


def test_queue_playback_position_is_read_only_and_duplicate_aware(tmp_path):
    with MarianaDatabase(tmp_path / "queue.db") as database:
        queue = PersistentQueue(database)
        track = media()
        queue.add(track, allow_duplicate=True)
        queue.add(track, allow_duplicate=True)
        queue.jump(1)
        before = database.fetchone("SELECT current_id,updated_at FROM queue_state WHERE singleton=1")

        assert queue.playback_position(track.stable_id) == (2, 2)
        assert queue.playback_position("different-media") == (None, 2)
        assert queue.playback_position(None) == (None, 2)

        after = database.fetchone("SELECT current_id,updated_at FROM queue_state WHERE singleton=1")
        assert dict(after) == dict(before)


def test_empty_queue_playback_position():
    class EmptyDatabase:
        @staticmethod
        def fetchone(_query):
            return None

    assert PersistentQueue(EmptyDatabase()).playback_position("track") == (None, 0)
