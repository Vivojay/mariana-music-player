"""Negative and routing contracts for optional desktop presentation controls."""

from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback_status import project_playback_status


@pytest.fixture
def controls(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/fixture/movie.mp4", title="Movie", duration=90)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, duration=90, position=12)
    calls, emitted = [], []
    private = "C:/private/library/token?signature=secret"

    def method(name):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return {"state": "ready", "private_transport": private}
        return invoke

    port = SimpleNamespace(**{
        name: method(name) for name in (
            "status", "request", "select_caption", "set_caption_languages", "caption_automatic",
            "load_captions", "configure_captions", "configure_audio_offset",
        )
    })
    port.host_status = lambda: {"state": "ready", "handle": "opaque-picture"}
    monkeypatch.setattr(main, "VIDEO", port)
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(snapshot=lambda: snapshot))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(
        emit=lambda event, payload: emitted.append((event, payload)) or True,
    ))
    monkeypatch.setattr(main, "_ensure_media_playable", lambda selected: None)
    monkeypatch.setattr(main, "process", lambda *_args: pytest.fail("Typed controls must not execute text"))
    return SimpleNamespace(
        media=media, snapshot=snapshot, identity=project_playback_status(snapshot).media_id,
        port=port, calls=calls, emitted=emitted, private=private,
    )


@pytest.mark.parametrize("payload", [
    {}, {"operation": "unknown"},
    {"operation": "on", "extra": True}, {"operation": "load"},
    {"operation": "load", "path": ""}, {"operation": "replace", "path": None},
    {"operation": "shift"}, {"operation": "shift", "value": True},
    {"operation": "set-offset", "value": 0.5},
    {"operation": "set-offset", "value": "250"},
    {"operation": "select", "track_id": "a" * 32},
    {"operation": "select", "track_id": "a" * 32, "revision": True},
    {"operation": "select", "track_id": "a" * 31, "revision": 1},
    {"operation": "select", "track_id": "g" * 32, "revision": 1},
    {"operation": "select", "track_id": 42, "revision": 1},
    {"operation": "languages", "languages": "en"},
    {"operation": "languages", "languages": ["en", None]},
    {"operation": "auto", "path": "C:/unexpected.srt"},
])
def test_malformed_caption_intents_never_reach_the_video_service(controls, payload):
    request = {"media_id": controls.identity, **payload}
    result = main._desktop_control_request("video.captions", request)

    assert result["ok"] is False and result["error"]
    assert controls.calls == [] and controls.emitted == []
    assert controls.snapshot.state == PlaybackState.PAUSED and controls.snapshot.position == 12


@pytest.mark.parametrize(("action", "payload"), [
    ("video.configure", {"mode": "video"}),
    ("video.captions", {"operation": "auto"}),
    ("video.captions", {"operation": "languages", "languages": ["hi", "en"]}),
    ("video.captions", {"operation": "clear"}),
    ("video.audio-offset", {"value": -500, "relative": True}),
])
@pytest.mark.parametrize("target", [None, "", "obsolete-media"])
def test_every_mutating_video_intent_refuses_missing_or_stale_identity(controls, action, payload, target):
    result = main._desktop_control_request(action, {"media_id": target, **payload})
    assert result["ok"] is False
    assert controls.calls == [] and controls.emitted == []
    assert controls.snapshot.media is controls.media and controls.snapshot.position == 12


@pytest.mark.parametrize("payload", [
    {"value": 250}, {"relative": False}, {"value": True, "relative": False},
    {"value": 0.5, "relative": False}, {"value": "250", "relative": False},
    {"value": 250, "relative": 1}, {"value": 250, "relative": "false"},
    {"value": 250, "relative": False, "path": "C:/private.mp4"},
])
def test_audio_offset_requires_whole_milliseconds_and_explicit_relative_mode(controls, payload):
    result = main._desktop_control_request("video.audio-offset", {"media_id": controls.identity, **payload})
    assert result["ok"] is False
    assert controls.calls == [] and controls.emitted == []


@pytest.mark.parametrize(("payload", "method", "args", "extra"), [
    ({"operation": "on"}, "configure_captions", ("on", None), {}),
    ({"operation": "off"}, "configure_captions", ("off", None), {}),
    ({"operation": "clear"}, "configure_captions", ("clear", None), {}),
    ({"operation": "shift", "value": -250}, "configure_captions", ("shift", -250), {}),
    ({"operation": "set-offset", "value": 0}, "configure_captions", ("set-offset", 0), {}),
    ({"operation": "load", "path": "C:/chosen.srt"}, "load_captions", ("C:/chosen.srt",), {"replace": False}),
    ({"operation": "replace", "path": "C:/replacement.vtt"}, "load_captions", ("C:/replacement.vtt",), {"replace": True}),
    ({"operation": "auto"}, "caption_automatic", (), {}),
])
def test_caption_controls_preserve_exact_intent_and_only_emit_host_projection(controls, payload, method, args, extra):
    assert main._desktop_control_request("video.captions", {
        "media_id": controls.identity, **payload,
    }) == {"ok": True}
    assert controls.calls == [(method, args, {"expected_media": controls.media, **extra})]
    assert controls.emitted == [("video", {"state": "ready", "handle": "opaque-picture"})]
    assert controls.private not in repr(controls.emitted)
    assert controls.snapshot.position == 12 and controls.snapshot.state == PlaybackState.PAUSED


@pytest.mark.parametrize(("relative", "value"), [(False, -750), (True, 250), (False, 0)])
def test_audio_offset_routes_exact_sign_and_mode_without_audio_mutation(controls, relative, value):
    assert main._desktop_control_request("video.audio-offset", {
        "media_id": controls.identity, "relative": relative, "value": value,
    }) == {"ok": True}
    assert controls.calls == [("configure_audio_offset", (value,), {
        "relative": relative, "expected_media": controls.media,
    })]
    assert controls.snapshot.position == 12 and controls.snapshot.state == PlaybackState.PAUSED


@pytest.mark.parametrize(("action", "payload", "method"), [
    ("video.status", {}, "status"),
    ("video.configure", {"mode": "video"}, "request"),
    ("video.captions", {"operation": "clear"}, "configure_captions"),
    ("video.audio-offset", {"relative": False, "value": 100}, "configure_audio_offset"),
])
def test_unexpected_video_errors_are_sanitized_and_never_published(controls, monkeypatch, action, payload, method):
    def broken(*_args, **_kwargs):
        raise OSError(controls.private)

    monkeypatch.setattr(controls.port, method, broken)
    request = payload if action == "video.status" else {"media_id": controls.identity, **payload}
    assert main._desktop_control_request(action, request) == {"ok": False, "error": "Local video is unavailable"}
    assert controls.emitted == [] and controls.snapshot.position == 12
