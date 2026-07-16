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


def test_local_copy_hint_is_emitted_once_per_media_id(monkeypatch, local_match_cli):
    output, media = local_match_cli
    calls = []
    monkeypatch.setattr(main, "_LOCAL_COPY_HINTED_MEDIA_IDS", set())
    monkeypatch.setattr(
        main,
        "LOCAL_MATCHER",
        SimpleNamespace(match=lambda candidate: calls.append(candidate) or _result(LocalMatchStatus.MATCHED)),
    )

    main._show_local_copy_hint(media)
    main._show_local_copy_hint(media)

    assert len(calls) == 1
    assert output == [
        'Local copy available: library item 7. Run "media local-match current".'
    ]


@pytest.mark.parametrize(
    "status",
    [LocalMatchStatus.NO_MATCH, LocalMatchStatus.AMBIGUOUS, LocalMatchStatus.UNSUPPORTED],
)
def test_local_copy_hint_suppresses_nonselected_results(monkeypatch, local_match_cli, status):
    output, media = local_match_cli
    monkeypatch.setattr(main, "_LOCAL_COPY_HINTED_MEDIA_IDS", set())
    monkeypatch.setattr(main, "LOCAL_MATCHER", SimpleNamespace(match=lambda _media: _result(status)))

    assert main._show_local_copy_hint(media).status == status
    assert output == []


def test_local_copy_hint_suppresses_missing_item_and_matcher_failure(monkeypatch, local_match_cli):
    output, media = local_match_cli
    monkeypatch.setattr(main, "_LOCAL_COPY_HINTED_MEDIA_IDS", set())
    assert main._show_local_copy_hint(None) is None
    monkeypatch.setattr(
        main,
        "LOCAL_MATCHER",
        SimpleNamespace(match=lambda _media: (_ for _ in ()).throw(RuntimeError("database unavailable"))),
    )
    assert main._show_local_copy_hint(media) is None
    assert output == []


@pytest.mark.parametrize(
    "media",
    [
        MediaRef(MediaSource.LOCAL, "C:/music/track.mp3", duration=120),
        MediaRef(
            MediaSource.RADIO,
            "https://radio.example/live",
            duration=120,
            capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
        ),
        MediaRef(
            MediaSource.URL,
            "https://media.example/unknown",
            capabilities=MediaCapabilities(finite=True, live=False),
        ),
    ],
)
def test_local_copy_hint_suppresses_unsupported_media(monkeypatch, local_match_cli, media):
    output, _current = local_match_cli
    monkeypatch.setattr(main, "_LOCAL_COPY_HINTED_MEDIA_IDS", set())
    monkeypatch.setattr(
        main,
        "LOCAL_MATCHER",
        SimpleNamespace(match=lambda _media: pytest.fail("unsupported media reached matcher")),
    )

    assert main._show_local_copy_hint(media).status == LocalMatchStatus.UNSUPPORTED
    assert output == []


def test_queue_online_playback_requests_hint_after_start(monkeypatch, local_match_cli):
    _output, media = local_match_cli
    item = SimpleNamespace(media=media, queue_id="queue-item")
    order = []
    monkeypatch.setattr(main.QUEUE, "items", lambda: [item])
    monkeypatch.setattr(main.LIBRARY.loudness, "get", lambda _media_id: None)
    monkeypatch.setattr(main.vas.supervisor, "play", lambda candidate: order.append(("play", candidate)))
    monkeypatch.setattr(main, "_set_current_media_state", lambda candidate: order.append(("state", candidate)))
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda candidate: order.append(("hint", candidate)))
    monkeypatch.setattr(main.RECOMMENDER, "record_event", lambda candidate, event: order.append((event, candidate)))
    monkeypatch.setattr(main, "_prefetch_after", lambda queued: order.append(("prefetch", queued)))

    main._play_queue_item(item)

    assert [entry[0] for entry in order] == ["play", "state", "hint", "start", "prefetch"]
    assert all(entry[1] is media or entry[1] is item for entry in order)


def test_legacy_online_playback_requests_hint_after_start(monkeypatch, local_match_cli):
    _output, media = local_match_cli
    hinted = []

    def set_media(**_kwargs):
        main.vas.current_media = media
        return media.original_uri

    monkeypatch.setattr(main, "stopsong", lambda: None)
    monkeypatch.setattr(main.vas, "current_media", None)
    monkeypatch.setattr(main.vas, "set_media", set_media)
    monkeypatch.setattr(main.vas, "media_player", lambda **_kwargs: None)
    monkeypatch.setattr(main.vas, "wait_until_playing", lambda _timeout: True)
    monkeypatch.setattr(
        main.vas,
        "player",
        SimpleNamespace(audio_set_volume=lambda _value: None, get_length=lambda: 120_000),
    )
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda candidate: hinted.append(candidate))
    monkeypatch.setattr(main, "recents_queue_save", lambda _value: None)
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "SAY", lambda **_kwargs: None)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main,
        "USER_DATA",
        {"default_user_data": {"stats": {"play_count": {"youtube": 0, "total": 0}}}},
    )
    monkeypatch.setattr(main, "isplaying", False)
    monkeypatch.setattr(main, "currentsong", None)
    monkeypatch.setattr(main, "currentsong_length", None)
    monkeypatch.setattr(main, "current_media_type", None)

    main.play_vas_media(media.original_uri, media_name="Track", media_type="video")

    assert hinted == [media]
