from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def preview_queue(monkeypatch):
    def preview(target, *, offset=1, state=PlaybackState.PLAYING, blocked=False):
        current = SimpleNamespace(
            queue_id=1,
            media=MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=current0001"),
        )
        other = SimpleNamespace(queue_id=2, media=target)
        items = [current, other] if offset > 0 else [other, current]
        snapshot = PlaybackSnapshot(state, media=current.media, position=73)
        jump = Mock()
        play = Mock()
        output = []
        monkeypatch.setattr(
            main,
            "QUEUE",
            SimpleNamespace(
                current=lambda: current,
                items=lambda: items,
                state=lambda: {"repeat_mode": "off"},
                jump=jump,
            ),
        )
        monkeypatch.setattr(main.vas.controller, "snapshot", lambda: snapshot)
        monkeypatch.setattr(main, "_play_queue_item", play)
        monkeypatch.setattr(main, "_library_song_index", lambda _uri: 146)
        monkeypatch.setattr(main, "_is_media_blocked", lambda _media: blocked)
        monkeypatch.setattr(main, "IPrint", lambda text, **_kwargs: output.append(text))
        before = target.to_dict()

        assert main._navigate_active_queue("+" if offset > 0 else "-", offset)

        jump.assert_not_called()
        play.assert_not_called()
        assert main.QUEUE.current() is current
        assert main.vas.controller.snapshot() is snapshot
        assert target.to_dict() == before
        assert len(output) == 1
        return output[0]

    return preview


@pytest.mark.parametrize("offset", [1, -1])
@pytest.mark.parametrize("state", [PlaybackState.PLAYING, PlaybackState.PAUSED])
@pytest.mark.parametrize(
    ("title", "catalog_title", "expected"),
    [
        (None, "Backseat Rider", "Backseat Rider"),
        (None, None, "Sara Kays - Backseat Rider [Official Video]"),
        ("Selected edition", "Backseat Rider", "Selected edition"),
    ],
)
def test_local_queue_preview_uses_trusted_metadata_without_starting_playback(
    monkeypatch, preview_queue, offset, state, title, catalog_title, expected
):
    path = Path("C:/private/Music/Sara Kays - Backseat Rider [Official Video].mp3")
    media = MediaRef(MediaSource.LOCAL, str(path), title=title)
    monkeypatch.setattr(
        main.LIBRARY,
        "info",
        lambda uri: {
            "library_id": "indexed-song",
            "canonical_path": str(path),
            "state": "available",
            "metadata": {"title": catalog_title},
        } if uri == str(path) else None,
    )

    output = preview_queue(media, offset=offset, state=state)

    assert f"| {expected}" in output
    assert "Local media" not in output
    assert str(path.parent) not in output


def test_queue_preview_keeps_stored_library_label_and_blocked_annotation(monkeypatch, preview_queue):
    media = MediaRef(
        MediaSource.LOCAL,
        "C:/private/Music/song.mp3",
        resolver_data={"library_display_title": "Stored library title"},
        provenance="library",
    )
    monkeypatch.setattr(main.LIBRARY, "info", lambda _uri: None)

    output = preview_queue(media, blocked=True)

    assert "| Stored library title [Blocked]" in output
    assert media.original_uri not in output


@pytest.mark.parametrize(
    ("source", "uri", "title", "expected"),
    [
        (MediaSource.LOCAL, "C:/private/Music/unknown.mp3", None, "Local media"),
        (MediaSource.URL, "https://example.test/audio?token=private", None, "Online media"),
        (MediaSource.URL, "https://example.test/audio?token=private", "Known recording", "Known recording"),
        (MediaSource.URL, "https://example.test/audio?token=private", "https://private.test/secret", "Online media"),
    ],
)
def test_queue_preview_preserves_safe_fallbacks(monkeypatch, preview_queue, source, uri, title, expected):
    monkeypatch.setattr(main.LIBRARY, "info", lambda _uri: None)

    output = preview_queue(MediaRef(source, uri, title=title))

    assert f"| {expected}" in output
    assert uri not in output
    assert "https://private.test" not in output
