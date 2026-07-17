from __future__ import annotations

import pytest

import main
from mariana.models import (
    MediaCapabilities,
    MediaChapter,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
)
from mariana.playback_status import PlaybackStatusProjection, project_playback_status


def _media(
    *,
    source: MediaSource = MediaSource.LOCAL,
    title: str | None = "Track",
    artist: str | None = "Artist",
    live: bool = False,
    seekable: bool = True,
) -> MediaRef:
    uri = "C:/music/track.mp3" if source == MediaSource.LOCAL else "https://private.test/signed?id=secret"
    return MediaRef(
        source,
        uri,
        title=title,
        artist=artist,
        capabilities=MediaCapabilities(finite=not live, live=live, seekable=seekable),
    )


def _status(
    *,
    state: PlaybackState = PlaybackState.PLAYING,
    media: MediaRef | None = None,
    position: float = 30,
    duration: float | None = 120,
    error: str | None = None,
    library_index: int | None = None,
    queue_position: int | None = 2,
    queue_count: int = 5,
    chapter: MediaChapter | None = None,
) -> PlaybackStatusProjection:
    selected_media = media or _media()
    if chapter is not None and not selected_media.chapters:
        selected_media.chapters = [chapter]
    if library_index is not None and selected_media.source == MediaSource.LOCAL:
        selected_media.provenance = "library"
    return project_playback_status(
        PlaybackSnapshot(
            state,
            media=selected_media,
            position=position,
            duration=duration,
            error=error,
            current_chapter=chapter,
        ),
        library_index=library_index,
        queue_position=queue_position,
        queue_count=queue_count,
    )


@pytest.mark.parametrize(
    ("position", "expected_percent", "bar"),
    [(0, "0%", "[--------------------]"), (50, "50%", "[##########----------]"), (100, "100%", "[####################]")],
)
def test_progress_formats_finite_boundaries(position, expected_percent, bar):
    lines = main._playback_status_lines(_status(position=position, duration=100))

    assert len(lines) == 1
    assert "Artist — Track [Local]" in lines[0]
    assert bar in lines[0]
    assert expected_percent in lines[0]
    assert "queue 2/5" in lines[0]


def test_progress_formats_live_and_unknown_duration_without_fake_percent():
    live = _status(media=_media(source=MediaSource.RADIO, title="Station", live=True), duration=None)
    unknown = _status(media=_media(source=MediaSource.URL), duration=None)

    live_line = main._playback_status_lines(live)[0]
    unknown_line = main._playback_status_lines(unknown)[0]

    assert "LIVE" in live_line and "00:30 elapsed" in live_line
    assert "nonseekable" in live_line and "%" not in live_line
    assert "duration unknown" in unknown_line and "%" not in unknown_line


@pytest.mark.parametrize(
    ("state", "label"),
    [
        (PlaybackState.PAUSED, "Paused"),
        (PlaybackState.BUFFERING, "Buffering"),
        (PlaybackState.SEEKING, "Seeking"),
    ],
)
def test_progress_reports_nonplaying_active_states(state, label):
    assert label in main._playback_status_lines(_status(state=state))[0]


def test_failed_and_stopped_output_is_safe_and_does_not_retain_stale_media():
    failed = _status(
        state=PlaybackState.FAILED,
        error="ffmpeg https://private.test/signed?token=secret -headers cookie=x",
    )
    stopped = _status(state=PlaybackState.IDLE, position=0, duration=None)

    failed_output = "\n".join(main._playback_status_lines(failed, detailed=True))
    stopped_output = "\n".join(main._playback_status_lines(stopped, now=True))

    assert "Playback failed; see logs for details" in failed_output
    assert "private.test" not in failed_output and "token=" not in failed_output
    assert stopped_output == "Not playing | Stopped"
    assert "Track" not in stopped_output


def test_finished_media_retains_exact_completed_status():
    finished = _status(state=PlaybackState.IDLE, position=100, duration=100)

    output = main._playback_status_lines(finished, now=True)

    assert "Track" in output[0]
    assert "100%" in output[1]
    assert "Finished" in output[1]


def test_now_and_detailed_progress_include_safe_projection_fields():
    chapter = MediaChapter("Verse", 20, 40)
    status = _status(chapter=chapter)

    now = main._playback_status_lines(status, now=True)
    detailed = main._playback_status_lines(status, detailed=True)

    assert now == [
        "Now: Artist — Track [Local]",
        "Status: [#####---------------] | 00:30 / 02:00 | 25% | Playing | queue 2/5",
        "Chapter 1/1: Verse (00:20-00:40)",
    ]
    assert "Source: Local" in detailed
    assert "Seekable: yes" in detailed
    assert "Queue: 2/5" in detailed
    assert "Chapter 1/1: Verse (00:20-00:40)" in detailed


def test_projection_and_output_never_fall_back_to_online_url():
    status = _status(media=_media(source=MediaSource.URL, title="https://private.test/token=x", artist=None))

    output = "\n".join(main._playback_status_lines(status, detailed=True, now=True))

    assert "Online media" in output
    assert "private.test" not in output
    assert "token=" not in output


@pytest.mark.parametrize("command", ["prog", "progress", "prog*", "progress*", "now", "now*"])
def test_status_command_aliases_use_projection(monkeypatch, command):
    printed = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "_playback_status_projection", lambda: _status())

    main.process(command)

    assert printed
    assert any("Track" in line for line in printed)


def test_rich_prompt_uses_projection_for_queue_live_unknown_and_stopped(monkeypatch):
    monkeypatch.setattr(main, "songindex", 4)
    monkeypatch.setattr(main, "_playback_status_projection", lambda: _status(library_index=4))
    finite = main.prompt_text()

    monkeypatch.setattr(
        main,
        "_playback_status_projection",
        lambda: _status(media=_media(source=MediaSource.RADIO, title="Station", live=True), duration=None),
    )
    live = main.prompt_text()

    monkeypatch.setattr(
        main,
        "_playback_status_projection",
        lambda: _status(media=_media(source=MediaSource.URL), duration=None),
    )
    unknown = main.prompt_text()

    monkeypatch.setattr(
        main,
        "_playback_status_projection",
        lambda: _status(state=PlaybackState.IDLE, position=0, duration=None),
    )
    stopped = main.prompt_text()

    assert "[4] Artist — Track [local]" in finite and "Q 2/5" in finite
    assert "LIVE" in live and "[radio]" in live
    assert "duration ?" in unknown and "%" not in unknown
    assert "(Not Playing)" in stopped and "Track" not in stopped


def test_source_switch_and_queue_advance_refresh_projected_identity(monkeypatch, tmp_path):
    paths = [tmp_path / f"Track {index}.mp3" for index in range(1, 4)]
    next_path = tmp_path / "Elina - Mirage (Official Video) [audio].mp3"
    paths.append(next_path)
    online = _media(
        source=MediaSource.YOUTUBE,
        title="The Kid LAROI, Justin Bieber - Stay (Lyrics)",
        artist="7clouds",
    )
    local = MediaRef(
        MediaSource.LOCAL,
        str(next_path),
        stable_id="library-four",
        resolver_data={"library_display_title": next_path.stem},
        provenance="library",
        capabilities=MediaCapabilities(finite=True, seekable=True),
    )
    current = {"snapshot": PlaybackSnapshot(PlaybackState.PLAYING, media=online, duration=120)}
    monkeypatch.setattr(main, "_sound_files", [str(path) for path in paths])
    monkeypatch.setattr(main, "songindex", 37)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: current["snapshot"])
    monkeypatch.setattr(
        main.QUEUE,
        "playback_position",
        lambda stable_id: (4, 38) if stable_id == "library-four" else (None, 38),
    )

    status_provider = main._playback_status_projection
    online_status = status_provider()
    monkeypatch.setattr(main, "_playback_status_projection", lambda: online_status)
    online_prompt = main.prompt_text()
    assert online_status.source == "youtube" and online_status.library_index is None
    assert online_status.title == "The Kid LAROI, Justin Bieber - Stay (Lyrics)"
    assert "[37]" not in online_prompt

    current["snapshot"] = PlaybackSnapshot(
        PlaybackState.PLAYING,
        media=local,
        position=10,
        duration=180,
    )
    local_status = status_provider()
    monkeypatch.setattr(main, "_playback_status_projection", lambda: local_status)
    local_prompt = main.prompt_text()
    detailed = "\n".join(main._playback_status_lines(local_status, detailed=True))

    assert local_status.source == "local"
    assert local_status.title == next_path.stem
    assert local_status.library_index == local_status.queue_position == 4
    assert "[4]" in local_prompt and "Q 4/38" in local_prompt
    assert next_path.stem in detailed and "Queue: 4/38" in detailed
    serialized = str(local_status.to_dict()) + str(online_status.to_dict())
    assert str(tmp_path) not in serialized
    assert "private.test" not in serialized
