import json
from dataclasses import asdict
from types import SimpleNamespace

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import PreferenceState


def test_favorite_projection_uses_backend_state_without_exposing_identity(monkeypatch):
    indexed = MediaRef(
        MediaSource.LOCAL,
        "C:/private/library/song.mp3",
        stable_id="private-library-id",
        title="Track",
        provenance="library",
    )
    monkeypatch.setattr(main, "_preference_media", lambda _media: indexed)
    monkeypatch.setattr(
        main,
        "PREFERENCES",
        SimpleNamespace(get=lambda _media: PreferenceState.FAVORITE),
    )

    status = main._favorite_status_projection(indexed)

    assert status.available and status.toggle_enabled and status.is_favorite
    serialized = json.dumps(asdict(status))
    assert "private-library-id" not in serialized
    assert "C:/private" not in serialized


def test_favorite_projection_disables_unbound_and_unsafe_media(monkeypatch):
    direct_local = MediaRef(MediaSource.LOCAL, "C:/private/direct.mp3")
    signed_url = MediaRef(MediaSource.URL, "https://example.test/audio?token=secret")
    monkeypatch.setattr(main, "_preference_media", lambda media: media)

    empty = main._favorite_status_projection(None)
    local = main._favorite_status_projection(direct_local)
    online = main._favorite_status_projection(signed_url)

    assert not empty.available and empty.unavailable_reason == "No active media"
    assert not local.toggle_enabled and "indexed local media" in (local.unavailable_reason or "")
    assert not online.toggle_enabled and "durable favourite identity" in (online.unavailable_reason or "")
    assert "private" not in json.dumps(local.unavailable_reason)
    assert "example.test" not in json.dumps(online.unavailable_reason)


def test_playback_projection_refreshes_favorite_state_for_cli_changes(monkeypatch):
    media = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=public-video",
        stable_id="youtube-item",
        title="Track",
    )
    state = {"value": PreferenceState.NEUTRAL}
    monkeypatch.setattr(
        main,
        "PREFERENCES",
        SimpleNamespace(get=lambda _media: state["value"]),
    )
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media)),
    )
    monkeypatch.setattr(main.QUEUE, "playback_position", lambda _stable_id: (None, 0))

    assert not main._playback_status_projection().favorite.is_favorite
    state["value"] = PreferenceState.FAVORITE
    assert main._playback_status_projection().favorite.is_favorite


def test_desktop_favorite_toggle_binds_expected_current_media_and_emits_projection(monkeypatch):
    media = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=public-video",
        stable_id="youtube-item",
        title="Track",
    )
    state = {"value": PreferenceState.NEUTRAL}
    toggled = []

    def toggle(selected, preference):
        toggled.append((selected.stable_id, preference))
        state["value"] = PreferenceState.FAVORITE
        return state["value"]

    monkeypatch.setattr(
        main,
        "PREFERENCES",
        SimpleNamespace(get=lambda _media: state["value"], toggle=toggle),
    )
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media)),
    )
    monkeypatch.setattr(main.QUEUE, "playback_position", lambda _stable_id: (None, 0))
    emitted = []
    monkeypatch.setattr(
        main,
        "DESKTOP_CONTROL",
        SimpleNamespace(emit=lambda event, payload=None: emitted.append((event, payload)) or True),
    )

    assert main._desktop_control_request("favorite.toggle", {"media_id": "stale-item"}) == {
        "ok": False,
        "error": "Current media changed; try again",
    }
    assert not toggled

    assert main._desktop_control_request("favorite.toggle", {"media_id": "youtube-item"}) == {
        "ok": True,
    }
    assert toggled == [("youtube-item", PreferenceState.FAVORITE)]
    assert emitted[-1][0] == "playback"
    assert emitted[-1][1]["favorite"] == {
        "available": True,
        "is_favorite": True,
        "toggle_enabled": True,
        "unavailable_reason": None,
    }
    serialized = json.dumps(emitted[-1][1])
    assert "youtube.com" not in serialized
    assert "token" not in serialized


def test_desktop_favorite_control_returns_only_safe_failures(monkeypatch):
    media = MediaRef(MediaSource.YOUTUBE, "https://youtu.be/public", stable_id="youtube-item")
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media)),
    )
    monkeypatch.setattr(
        main,
        "PREFERENCES",
        SimpleNamespace(
            get=lambda _media: PreferenceState.NEUTRAL,
            toggle=lambda *_args: (_ for _ in ()).throw(RuntimeError("C:/private?token=secret")),
        ),
    )

    assert main._desktop_control_request("favorite.toggle", {"media_id": "youtube-item"}) == {
        "ok": False,
        "error": "Could not update favourite state",
    }
    assert main._desktop_control_request("other.action", {}) == {
        "ok": False,
        "error": "Unsupported desktop control request",
    }
