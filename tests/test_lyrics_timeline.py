import math
from types import SimpleNamespace

import pytest

from mariana.lyrics_timeline import (
    MAX_SYNCED_LYRICS_CHARACTERS,
    LyricsTimelineError,
    parse_lrc,
    timeline_from_result,
    validate_user_offset,
)
from mariana.models import IdentityStatus, LyricsResult, MediaRef, MediaSource


def test_lrc_timeline_tracks_authoritative_position_and_seeks():
    timeline = parse_lrc(
        "[ar:Artist]\n[00:01.00]First\n[00:03.250]Second\n[00:09.00]Last",
        stable_id="track-1",
        duration_seconds=12,
        provider="local-sidecar",
    )

    before = timeline.cursor(0.999)
    assert before.active is None
    assert before.following and before.following.text == "First"

    first = timeline.cursor(1)
    assert first.active and first.active.text == "First"
    assert first.effective_start_ms == 1_000
    assert first.effective_end_ms == 3_250

    sought = timeline.cursor(8.75)
    assert sought.active and sought.active.text == "Second"
    assert sought.previous and sought.previous.text == "First"
    assert sought.following and sought.following.text == "Last"

    assert timeline.cursor(9).active and timeline.cursor(9).active.text == "Last"
    assert timeline.cursor(12.001).active is None


def test_lrc_offsets_shift_selection_without_mutating_source_cues():
    timeline = parse_lrc(
        "[offset:+500]\n[00:01.00]Delayed\n[00:02.00]Next",
        stable_id="track-1",
    )

    assert timeline.lines[0].start_ms == 1_000
    assert timeline.cursor(1.499).active is None
    assert timeline.cursor(1.5).active and timeline.cursor(1.5).active.text == "Delayed"

    corrected = timeline.cursor(1.25, user_offset_ms=-250)
    assert corrected.active and corrected.active.text == "Delayed"
    assert corrected.effective_start_ms == 1_250
    assert timeline.lines[0].start_ms == 1_000


def test_multiple_timestamps_translations_and_blank_cues_are_preserved():
    timeline = parse_lrc(
        "[00:01][00:03]Repeat\n[00:03]Translation\n[00:05]\n[00:61]Invalid",
        stable_id="track-1",
    )

    assert [(line.start_ms, line.text) for line in timeline.lines] == [
        (1_000, "Repeat"),
        (3_000, "Repeat\nTranslation"),
        (5_000, ""),
    ]
    assert timeline.cursor(3).active and timeline.cursor(3).active.text == "Repeat\nTranslation"
    assert timeline.cursor(5).active and timeline.cursor(5).active.text == ""


def test_provider_result_is_identity_bound_and_malformed_sync_is_nonfatal():
    result = LyricsResult(
        IdentityStatus.IDENTIFIED,
        plain="First\nSecond",
        synced="[00:01]First\n[00:02]Second",
        provider="LRCLIB",
        attribution="Lyrics provided by LRCLIB",
    )

    timeline = timeline_from_result("stable-media", result, duration_seconds=10)
    assert timeline is not None
    assert timeline.stable_id == "stable-media"
    assert timeline.provider == "LRCLIB"
    assert timeline.attribution == "Lyrics provided by LRCLIB"
    assert timeline_from_result(
        "stable-media",
        LyricsResult(IdentityStatus.IDENTIFIED, plain="Plain only"),
    ) is None
    assert timeline_from_result(
        "stable-media",
        LyricsResult(IdentityStatus.IDENTIFIED, synced="not timed"),
    ) is None


def test_embedded_sylt_is_available_as_synced_and_plain_lyrics(monkeypatch):
    from mariana.identity import local_lyrics

    embedded = SimpleNamespace(
        tags={
            "SYLT::eng": SimpleNamespace(
                format=2,
                text=[("First", 1_250), ("Second", 2_500)],
            )
        }
    )
    monkeypatch.setattr("mariana.identity.MutagenFile", lambda _path: embedded)

    result = local_lyrics(MediaRef(MediaSource.LOCAL, "C:/Music/song.mp3"))
    assert result is not None
    assert result.provider == "embedded"
    assert result.synced == "[00:01.250]First\n[00:02.500]Second"
    assert result.plain == "First\nSecond"


def test_embedded_syncedlyrics_field_takes_priority_over_plain_text(monkeypatch):
    from mariana.identity import local_lyrics

    embedded = SimpleNamespace(
        tags={
            "SYNCEDLYRICS": ["[00:01.00]Timed"],
            "LYRICS": ["Plain fallback"],
        }
    )
    monkeypatch.setattr("mariana.identity.MutagenFile", lambda _path: embedded)

    result = local_lyrics(MediaRef(MediaSource.LOCAL, "C:/Music/song.flac"))
    assert result is not None
    assert result.synced == "[00:01.00]Timed"
    assert result.plain == "Plain fallback"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "1"])
def test_position_validation_rejects_nonfinite_or_non_numeric_values(value):
    timeline = parse_lrc("[00:01]Line", stable_id="track-1")
    with pytest.raises(LyricsTimelineError, match="position"):
        timeline.cursor(value)


@pytest.mark.parametrize("value", [-60_001, 60_001, True, 1.5])
def test_user_offset_is_bounded_and_integral(value):
    with pytest.raises(LyricsTimelineError, match="offset"):
        validate_user_offset(value)


def test_oversized_or_untimed_lyrics_are_rejected_without_partial_results():
    with pytest.raises(LyricsTimelineError, match="size"):
        parse_lrc("x" * (MAX_SYNCED_LYRICS_CHARACTERS + 1), stable_id="track-1")
    with pytest.raises(LyricsTimelineError, match="timestamps"):
        parse_lrc("plain lyrics only", stable_id="track-1")
    with pytest.raises(LyricsTimelineError, match="stable media identity"):
        parse_lrc("[00:01]Line", stable_id=" ")


def test_excessively_long_offset_is_nonfatal_for_provider_timeline():
    synced = "[offset:" + "9" * 5000 + "]\n[00:01]Line"
    with pytest.raises(LyricsTimelineError, match="offset"):
        parse_lrc(synced, stable_id="track-1")
    result = LyricsResult(IdentityStatus.IDENTIFIED, synced=synced, plain="Line")
    assert timeline_from_result("track-1", result) is None
