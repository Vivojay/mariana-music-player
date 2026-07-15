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
    queue_position: int | None = 2,
    queue_count: int = 5,
    chapter: MediaChapter | None = None,
) -> PlaybackStatusProjection:
    return project_playback_status(
        PlaybackSnapshot(
            state,
            media=media or _media(),
            position=position,
            duration=duration,
            error=error,
            current_chapter=chapter,
        ),
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
        "Chapter: Verse (00:20-00:40)",
    ]
    assert "Source: Local" in detailed
    assert "Seekable: yes" in detailed
    assert "Queue: 2/5" in detailed
    assert "Chapter: Verse (00:20-00:40)" in detailed


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
    monkeypatch.setattr(main, "_playback_status_projection", lambda: _status())
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
