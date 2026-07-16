from __future__ import annotations

from types import SimpleNamespace

import pytest

import main
from mariana.local_match import LocalMatchConfidence, LocalMatchResult, LocalMatchStatus
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


def _result(status: LocalMatchStatus) -> LocalMatchResult:
    if status != LocalMatchStatus.MATCHED:
        return LocalMatchResult(status)
    return LocalMatchResult(
        status,
        library_id="library-safe-id",
        library_index=7,
        title="Track",
        artist="Artist",
        confidence=LocalMatchConfidence.EXACT_SOURCE,
        evidence="same durable source",
    )


@pytest.fixture
def local_match_cli(monkeypatch):
    output: list[str] = []
    media = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Track",
        artist="Artist",
        duration=120,
        capabilities=MediaCapabilities(finite=True, live=False),
    )
    snapshot = PlaybackSnapshot(PlaybackState.PLAYING, media=media, duration=120)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: snapshot)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    return output, media


def test_media_local_match_prints_safe_selected_result(monkeypatch, local_match_cli):
    output, _media = local_match_cli
    matcher = SimpleNamespace(match=lambda _media: _result(LocalMatchStatus.MATCHED))
    monkeypatch.setattr(main, "LOCAL_MATCHER", matcher)

    result = main.media_command(["local-match", "current"])

    assert isinstance(result, LocalMatchResult)
    assert result.status == LocalMatchStatus.MATCHED
    assert output == [
        "Local copy found: library item 7 - Artist - Track",
        "Confidence: Exact source",
        'Use "path 7" to reveal its local path.',
    ]
    joined = " ".join(output).casefold()
    assert "youtube.com" not in joined
    assert "fingerprint" not in joined
    assert "resolver" not in joined
    assert "credential" not in joined


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (LocalMatchStatus.NO_MATCH, "No strong indexed local match was found."),
        (LocalMatchStatus.AMBIGUOUS, "Multiple strong local candidates exist; no match was selected."),
        (LocalMatchStatus.UNSUPPORTED, "Local matching requires finite online media."),
    ],
)
def test_media_local_match_reports_nonselected_statuses(monkeypatch, local_match_cli, status, expected):
    output, _media = local_match_cli
    monkeypatch.setattr(main, "LOCAL_MATCHER", SimpleNamespace(match=lambda _media: _result(status)))
    result = main.media_command(["local-match", "current"])
    assert isinstance(result, LocalMatchResult)
    assert result.status == status
    assert output == [expected]


def test_media_local_match_uses_snapshot_duration_without_mutating_media(monkeypatch, local_match_cli):
    output, media = local_match_cli
    media.duration = None
    captured = []
    monkeypatch.setattr(
        main,
        "LOCAL_MATCHER",
        SimpleNamespace(match=lambda candidate: captured.append(candidate) or _result(LocalMatchStatus.NO_MATCH)),
    )

    main.media_command(["local-match", "current"])

    assert media.duration is None
    assert captured[0] is not media and captured[0].duration == 120
    assert output == ["No strong indexed local match was found."]


@pytest.mark.parametrize("arguments", [["local-match"], ["local-match", "7"], ["local-match", "current", "extra"]])
def test_media_local_match_requires_explicit_current(arguments):
    with pytest.raises(ValueError, match="Usage: media local-match current"):
        main.media_command(arguments)


def test_media_local_match_has_no_command_side_effects(monkeypatch, local_match_cli):
    _output, _media = local_match_cli
    calls = []
    monkeypatch.setattr(main, "LOCAL_MATCHER", SimpleNamespace(match=lambda _media: _result(LocalMatchStatus.NO_MATCH)))
    monkeypatch.setattr(main.QUEUE, "add", lambda *_args, **_kwargs: calls.append("queue"))
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda *_args, **_kwargs: calls.append("history"))
    monkeypatch.setattr(main.DESKTOP_CONTROL, "emit", lambda *_args, **_kwargs: calls.append("desktop"))
    monkeypatch.setattr(main.BROADCASTER, "metadata", lambda *_args, **_kwargs: calls.append("broadcast"))
    monkeypatch.setattr(main.PRESENCE, "refresh", lambda *_args, **_kwargs: calls.append("presence"))

    main.media_command(["local-match", "current"])

    assert calls == []


def test_local_copy_hint_prints_safe_terminal_message(monkeypatch, local_match_cli):
    output, media = local_match_cli
    monkeypatch.setattr(main, "_LOCAL_COPY_HINTED_MEDIA_IDS", set())
    monkeypatch.setattr(main, "LOCAL_MATCHER", SimpleNamespace(match=lambda _media: _result(LocalMatchStatus.MATCHED)))

    result = main._show_local_copy_hint(media)

    assert result is not None and result.status == LocalMatchStatus.MATCHED
    assert output == [
        'Local copy available: library item 7. Run "media local-match current".'
    ]
    joined = " ".join(output).casefold()
    assert "youtube.com" not in joined
    assert "fingerprint" not in joined
    assert "credential" not in joined
