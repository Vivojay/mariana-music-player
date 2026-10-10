from types import SimpleNamespace
from typing import cast

import pytest

import main
from mariana.credentials import CredentialStore
from mariana.focus_mode import FocusActivation, FocusModeError, FocusModeService, FocusStateStore, PairedFocusDevice
from tests.test_focus_mode import Clock, Credentials, Transport


@pytest.fixture
def local_focus(monkeypatch, tmp_path):
    clock = Clock()
    credentials = Credentials()
    transport = Transport(clock)
    store = FocusStateStore(tmp_path / "focus-state.json")
    service = FocusModeService(
        store, credentials=cast(CredentialStore, credentials), transport=transport,
        approved_youtube_ids=["abcdefghijk"], clock=clock,
    )
    messages = []
    monkeypatch.setattr(main, "FOCUS_MODE", service)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: messages.append(str(value)))
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main, "play_vas_media", lambda *_args, **_kwargs: pytest.fail("unexpected playback"))
    return SimpleNamespace(
        service=service, store=store, credentials=credentials, transport=transport,
        clock=clock, messages=messages,
    )


def _status(**updates):
    value = {
        "active": False,
        "passcode_set": True,
        "firebase_configured": True,
        "approved_media_count": 2,
        "paired_devices": [{"device_id": "phone-device-0001", "label": "Phone", "paired_at": 1.0}],
        "unlock_stage": None,
    }
    value.update(updates)
    return value


def test_process_blocks_distracting_commands_while_focus_mode_is_active(monkeypatch):
    printed = []
    monkeypatch.setattr(main, "FOCUS_MODE", SimpleNamespace(recovery_required=False, allows_command=lambda _tokens: False))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "home_command", lambda _arguments: (_ for _ in ()).throw(AssertionError))

    assert main.process("home") is None
    assert "Focus mode is active" in printed[-1]


def test_focus_status_reports_every_activation_prerequisite(monkeypatch):
    printed = []
    monkeypatch.setattr(main, "FOCUS_MODE", SimpleNamespace(recovery_required=False, status=lambda: _status()))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))

    result = main.focus_command([])

    assert isinstance(result, dict)
    assert result["active"] is False
    assert "passcode=ready" in printed[0]
    assert "phone devices=1" in printed[0]
    assert "Firebase=ready" in printed[0]


def test_focus_on_uses_only_the_selected_approved_video_identity(monkeypatch):
    calls = []
    activation = FocusActivation("abcdefghijk")

    class Focus:
        recovery_required = False
        approved_youtube_ids = ("abcdefghijk",)

        def activate(self, *, media_id=None):
            calls.append(("activate", media_id))
            return activation

        def rollback_activation(self, receipt):
            calls.append(("rollback", receipt))

        def confirm_activation(self, receipt):
            assert receipt is activation
            calls.append(("confirm", receipt))
            return True

        def status(self):
            return _status(active=True)

    monkeypatch.setattr(main, "FOCUS_MODE", Focus())
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "play_vas_media", lambda *args, **kwargs: calls.append(("play", args, kwargs)))

    result = main.focus_command(["on", "abcdefghijk"])

    assert isinstance(result, dict)
    assert result["active"] is True
    assert calls[0] == ("activate", "abcdefghijk")
    _, args, kwargs = calls[1]
    assert args == ("https://www.youtube.com/watch?v=abcdefghijk",)
    assert kwargs["media_ref"].resolver_data == {"youtube_id": "abcdefghijk"}
    assert "rollback" not in {value[0] for value in calls}
    assert calls[2] == ("confirm", activation)


def test_focus_verify_keeps_phone_code_hidden_and_emits_desktop_challenge(monkeypatch):
    events = []
    focus = SimpleNamespace(recovery_required=False, submit_phone_code=lambda code: "KLMNPQRS45")
    desktop = SimpleNamespace(enabled=True, emit=lambda event, payload: events.append((event, payload)))
    monkeypatch.setattr(main, "FOCUS_MODE", focus)
    monkeypatch.setattr(main, "DESKTOP_CONTROL", desktop)
    monkeypatch.setattr(main, "getpass", lambda _prompt: "ABCDEFGH23")
    monkeypatch.setattr(main, "_start_focus_unlock_monitor", lambda: None)

    assert main.focus_command(["verify"]) == "KLMNPQRS45"
    assert events == [("desktop-notice", {
        "message": "Enter this code on the paired phone: KLMNPQRS45",
        "focus_code": "KLMNPQRS45",
    })]


def test_focus_setup_uses_hidden_input_and_keeps_passcode_out_of_state_and_output(local_focus, monkeypatch):
    passcode = "example-study-passcode"
    inputs = iter([passcode, passcode])
    monkeypatch.setattr(main, "getpass", lambda _prompt: next(inputs))
    status = main.focus_command(["setup"])
    assert isinstance(status, dict) and status["passcode_set"]
    assert passcode not in " ".join(local_focus.messages)
    local_focus.store.save(local_focus.service.state)
    assert passcode not in local_focus.store.path.read_text(encoding="utf-8")
    assert passcode not in str(local_focus.credentials.values)


def test_focus_pairing_requires_approval_and_revoke_is_persistent(local_focus):
    invitation = main.focus_command(["pair"])
    assert isinstance(invitation, dict) and invitation["code"] == "ABCDEFGH23"
    assert main.focus_command(["pair", "status"]) is None
    assert main.focus_command(["devices"]) == []
    local_focus.transport.paired = True
    device = main.focus_command(["pair", "status"])
    assert isinstance(device, PairedFocusDevice)
    assert main.focus_command(["devices"]) == [
        {"device_id": device.device_id, "label": device.label, "paired_at": device.paired_at},
    ]
    assert main.focus_command(["revoke", device.device_id]) is True
    assert main.focus_command(["revoke", device.device_id]) is False
    reloaded = local_focus.store.load()
    assert reloaded.paired_devices == []


def test_declined_focus_activation_does_not_persist_lock_or_start_media(local_focus, monkeypatch):
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: False)
    assert main.focus_command(["on"]) is None
    assert local_focus.service.status()["active"] is False
    assert local_focus.transport.calls == []


def test_failed_focus_playback_rolls_back_only_the_attempted_activation(local_focus, monkeypatch):
    service = local_focus.service
    service.setup_passcode("example-passcode", "example-passcode")
    service.state.paired_devices.append(PairedFocusDevice("phone-device-0001", "Phone", local_focus.clock()))

    def failed_play(_url, **kwargs):
        assert service.status()["active"] is True
        assert kwargs["media_ref"].resolver_data["youtube_id"] == "abcdefghijk"
        raise RuntimeError("Synthetic playback refusal")

    monkeypatch.setattr(main, "play_vas_media", failed_play)
    with pytest.raises(RuntimeError, match="Synthetic playback refusal"):
        main.focus_command(["on", "--yes"])
    assert service.status()["active"] is False
    assert local_focus.store.load().active is False


def test_focus_unlock_and_cancel_keep_passcode_hidden_and_do_not_unlock_early(local_focus, monkeypatch):
    service = local_focus.service
    passcode = "example-passcode"
    service.setup_passcode(passcode, passcode)
    service.state.paired_devices.append(PairedFocusDevice("phone-device-0001", "Phone", local_focus.clock()))
    service.activate(media_id="abcdefghijk")
    monkeypatch.setattr(main, "getpass", lambda _prompt: passcode)
    assert main.focus_command(["off"]) == "unlock-request-1"
    assert service.status()["active"] is True
    status = main.focus_command(["status"])
    assert isinstance(status, dict) and status["unlock_stage"]
    assert any("Unlock stage:" in value for value in local_focus.messages)
    cancelled = main.focus_command(["cancel"])
    assert isinstance(cancelled, dict) and cancelled["active"] is True
    assert cancelled["unlock_stage"] is None
    assert passcode not in " ".join(local_focus.messages)


def test_direct_cli_verification_shows_return_challenge_without_desktop_window(monkeypatch):
    messages = []
    monitors = []
    codes = []
    monkeypatch.setattr(main, "FOCUS_MODE", SimpleNamespace(
        recovery_required=False,
        submit_phone_code=lambda value: codes.append(value) or "KLMNPQRS45",
    ))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(enabled=False))
    monkeypatch.setattr(main, "getpass", lambda _prompt: "ABCDEFGH23")
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: messages.append(value))
    monkeypatch.setattr(main, "_start_focus_unlock_monitor", lambda: monitors.append(True))
    assert main.focus_command(["verify"]) == "KLMNPQRS45"
    assert codes == ["ABCDEFGH23"]
    assert monitors == [True]
    assert messages == ["Enter this code on the paired phone: KLMNPQRS45"]


@pytest.mark.parametrize("arguments", [
    ["setup", "unexpected"], ["pair", "invalid"], ["pair", "status", "extra"],
    ["revoke"], ["media", "extra"], ["on", "one", "two"], ["off", "extra"],
    ["verify", "extra"], ["cancel", "extra"], ["unknown"],
])
def test_invalid_focus_commands_do_not_mutate_lock_or_contact_transport(local_focus, arguments):
    before = local_focus.service.status()
    with pytest.raises(FocusModeError, match="Usage:"):
        main.focus_command(arguments)
    assert local_focus.service.status() == before
    assert local_focus.transport.calls == []
