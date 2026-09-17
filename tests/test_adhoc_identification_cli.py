from types import SimpleNamespace

import pytest

import main
from mariana.adhoc_identification import AdHocIdentificationError, CapturePhase, CaptureStatus
from mariana.models import MediaRef, MediaSource
from mariana.playback import PlaybackError, UnsupportedAction


def test_media_identify_listen_uses_authoritative_invocation_context(monkeypatch):
    selected = MediaRef(MediaSource.LOCAL, "C:/long-mix.flac", title="Long mix")
    calls = []
    output = []
    expected = CaptureStatus(
        "capture",
        CapturePhase.CAPTURING,
        media_id=selected.stable_id,
        media_title=selected.title,
        playback_session_id="session",
        requested_start_seconds=90,
        target_seconds=15,
    )
    monkeypatch.setattr(
        main.vas.controller,
        "identification_capture_context",
        lambda: (selected, "session", "decoder", 90.0),
    )
    monkeypatch.setattr(
        main,
        "ADHOC_IDENTIFICATION",
        SimpleNamespace(
            status=lambda: CaptureStatus(None, CapturePhase.IDLE),
            start=lambda media, session, decoder, position, duration: calls.append(
                (media, session, decoder, position, duration)
            )
            or expected
        ),
    )
    monkeypatch.setattr(main, "_prepare_fingerprint_tool", lambda: True)
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))

    result = main.media_command(["identify", "listen", "15"])

    assert result is expected
    assert calls == [(selected, "session", "decoder", 90.0, 15.0)]
    assert "newly played audio" in output[0]
    assert "1:30" in output[0]


def test_media_identify_status_reports_exact_captured_interval(monkeypatch):
    status = CaptureStatus(
        "capture",
        CapturePhase.CAPTURING,
        captured_start_seconds=70,
        captured_end_seconds=79.5,
        captured_seconds=9.5,
        target_seconds=20,
    )
    output = []
    monkeypatch.setattr(
        main,
        "ADHOC_IDENTIFICATION",
        SimpleNamespace(status=lambda: status),
    )
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))

    assert main.media_command(["identify", "status"]) is status
    assert "9.5/20 seconds" in output[0]
    assert "1:10 -> 1:19.500" in output[0]


@pytest.fixture
def capture_scene(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/long-mix.flac", title="Long mix")
    state = {
        "context": (media, "session", "decoder", 90.0),
        "phase": CapturePhase.IDLE,
        "tool": None,
    }
    calls, output = [], []

    def start(selected, session, decoder, position, duration):
        calls.append(("capture", selected, session, decoder, position, duration))
        return CaptureStatus("capture", CapturePhase.CAPTURING, target_seconds=duration)

    def find(_configured):
        calls.append(("tool-check",))
        if state["tool"] is None:
            raise PlaybackError("Missing tool")
        return state["tool"]

    def setup(arguments):
        calls.append(("setup", arguments))
        state["tool"] = "verified/fpcalc"
        state["context"] = (media, "session", "decoder", 110.0)

    monkeypatch.setattr(main, "ADHOC_IDENTIFICATION", SimpleNamespace(
        status=lambda: CaptureStatus(None, state["phase"]), start=start,
    ))
    monkeypatch.setattr(main.vas.controller, "identification_capture_context", lambda: state["context"])
    monkeypatch.setattr(main, "IDENTITY", SimpleNamespace())
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace())
    monkeypatch.setattr(main, "find_fpcalc", find)
    monkeypatch.setattr(main, "executable_version", lambda *_args: "fpcalc 1.6.0")
    monkeypatch.setattr(main, "_confirm_action", lambda _message: pytest.fail("Unexpected setup confirmation"))
    monkeypatch.setattr(main, "tools_command", setup)
    monkeypatch.setattr(main, "refresh_runtime_configuration", lambda **_kwargs: pytest.fail("Playback must not restart"))
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))
    return media, state, calls, output


def test_adhoc_missing_tool_declined_does_not_capture_or_install(capture_scene, monkeypatch):
    _media, _state, calls, output = capture_scene
    confirmations = []
    monkeypatch.setattr(main, "_confirm_action", lambda message: confirmations.append(message) or False)
    assert main.media_command(["identify", "listen"]) is None
    assert len(confirmations) == 1
    assert calls == [("tool-check",)]
    assert "no audio was captured" in output[-1]


def test_adhoc_approved_setup_refreshes_tool_and_uses_fresh_position(capture_scene, monkeypatch):
    media, _state, calls, output = capture_scene
    monkeypatch.setattr(main, "_confirm_action", lambda _message: True)
    result = main.media_command(["identify", "listen", "15"])
    assert isinstance(result, CaptureStatus)
    assert result.phase == CapturePhase.CAPTURING
    assert calls == [
        ("tool-check",), ("setup", ["setup"]), ("tool-check",),
        ("capture", media, "session", "decoder", 110.0, 15.0),
    ]
    assert main.IDENTITY.fpcalc_bin == main.LIBRARY.fpcalc_bin == "verified/fpcalc"
    assert "1:50" in output[-1]


@pytest.mark.parametrize("failure", ["setup-error", "still-missing", "invalid-version"])
def test_unsuccessful_setup_never_captures(capture_scene, monkeypatch, failure):
    _media, state, calls, output = capture_scene
    monkeypatch.setattr(main, "_confirm_action", lambda _message: True)

    def unsuccessful(_arguments):
        if failure == "setup-error":
            raise OSError("Unavailable installation folder")
        if failure == "invalid-version":
            state["tool"] = "broken/fpcalc"

    monkeypatch.setattr(main, "tools_command", unsuccessful)
    monkeypatch.setattr(main, "executable_version", lambda *_args: None)
    assert main.media_command(["identify", "listen"]) is None
    assert not any(call[0] == "capture" for call in calls)
    assert "no audio was captured" in output[-1]


def test_installed_tool_starts_without_confirmation_or_setup(capture_scene):
    media, state, calls, _output = capture_scene
    state["tool"] = "existing/fpcalc"
    main.media_command(["identify", "start", "8"])
    assert calls == [("tool-check",), ("capture", media, "session", "decoder", 90.0, 8.0)]


@pytest.mark.parametrize("value", ["NaN", "inf", "-inf", "7.9", "120.1", "unknown"])
def test_invalid_duration_is_rejected_before_tool_confirmation(capture_scene, value):
    _media, _state, calls, _output = capture_scene
    with pytest.raises(AdHocIdentificationError, match="duration"):
        main.media_command(["identify", "listen", value])
    assert calls == []


@pytest.mark.parametrize("phase", [CapturePhase.CAPTURING, CapturePhase.IDENTIFYING])
def test_active_capture_is_not_disturbed_by_another_setup_request(capture_scene, phase):
    _media, state, calls, _output = capture_scene
    state["phase"] = phase
    with pytest.raises(AdHocIdentificationError, match="already active"):
        main.media_command(["identify", "listen"])
    assert calls == []


def test_unsupported_playback_does_not_offer_tool_install(capture_scene, monkeypatch):
    _media, _state, calls, _output = capture_scene

    def unavailable():
        raise UnsupportedAction("Nothing is currently playing")

    monkeypatch.setattr(main.vas.controller, "identification_capture_context", unavailable)
    with pytest.raises(UnsupportedAction, match="Nothing"):
        main.media_command(["identify", "listen"])
    assert calls == []


@pytest.mark.parametrize("changed", ["media", "session", "decoder"])
def test_changed_playback_during_setup_requires_explicit_retry(capture_scene, monkeypatch, changed):
    media, state, calls, _output = capture_scene
    monkeypatch.setattr(main, "_confirm_action", lambda _message: True)

    def setup(_arguments):
        state["tool"] = "verified/fpcalc"
        state["context"] = (
            MediaRef(MediaSource.LOCAL, "C:/other.flac") if changed == "media" else media,
            "new-session" if changed == "session" else "session",
            "new-decoder" if changed == "decoder" else "decoder",
            0.0,
        )

    monkeypatch.setattr(main, "tools_command", setup)
    with pytest.raises(AdHocIdentificationError, match="Playback changed"):
        main.media_command(["identify", "listen"])
    assert not any(call[0] == "capture" for call in calls)


def test_pause_during_setup_does_not_start_capture(capture_scene, monkeypatch):
    _media, state, calls, _output = capture_scene
    monkeypatch.setattr(main, "_confirm_action", lambda _message: True)

    def paused():
        raise UnsupportedAction("Start time-specific identification while media is playing")

    def setup(_arguments):
        state["tool"] = "verified/fpcalc"
        monkeypatch.setattr(main.vas.controller, "identification_capture_context", paused)

    monkeypatch.setattr(main, "tools_command", setup)
    with pytest.raises(UnsupportedAction, match="while media is playing"):
        main.media_command(["identify", "listen"])
    assert not any(call[0] == "capture" for call in calls)


@pytest.mark.parametrize("action", ["status", "stop", "cancel"])
def test_capture_management_never_requires_tool_setup(capture_scene, monkeypatch, action):
    _media, _state, calls, _output = capture_scene
    expected = CaptureStatus("capture", CapturePhase.FAILED, reason="Provider is unavailable")
    monkeypatch.setattr(main, "ADHOC_IDENTIFICATION", SimpleNamespace(**{action: lambda: expected}))
    assert main.media_command(["identify", action]) is expected
    assert calls == []


def test_provider_failure_display_does_not_offer_tool_setup(capture_scene):
    _media, _state, calls, output = capture_scene
    main._adhoc_identification_update(CaptureStatus(
        "capture", CapturePhase.FAILED, reason="Recognition provider returned HTTP 403",
    ))
    assert "HTTP 403" in output[-1]
    assert calls == []
