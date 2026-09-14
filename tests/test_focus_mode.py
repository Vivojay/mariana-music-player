from __future__ import annotations

from dataclasses import dataclass

import pytest

from mariana.focus_mode import (
    FirebaseFocusTransport,
    FocusModeError,
    FocusModeService,
    FocusStateStore,
    PairedFocusDevice,
    focus_environment,
    verify_passcode,
)
from mariana.models import MediaRef, MediaSource


class Credentials:
    def __init__(self):
        self.values = {}

    def get(self, reference):
        return self.values.get(reference)

    def set(self, reference, value):
        self.values[reference] = value


@dataclass
class Clock:
    value: float = 1_000.0

    def __call__(self):
        return self.value


class Transport:
    def __init__(self, clock):
        self.clock = clock
        self.ready = True
        self.paired = False
        self.approved = False
        self.calls = []

    def configured(self):
        return self.ready

    def begin_pairing(self, desktop_instance_id):
        self.calls.append(("pair", desktop_instance_id))
        return {"request_id": "pairing-request-1", "code": "ABCDEFGH23", "expires_at": self.clock() + 300}

    def pairing_status(self, request_id):
        self.calls.append(("pair-status", request_id))
        return {"paired": True, "device_id": "phone-device-0001", "label": "Study phone"} if self.paired else None

    def begin_unlock(self, desktop_instance_id, device_id):
        self.calls.append(("unlock", desktop_instance_id, device_id))
        return {"request_id": "unlock-request-1", "expires_at": self.clock() + 300}

    def verify_phone_code(self, request_id, code):
        self.calls.append(("phone-code", request_id, code))
        return {"desktop_code": "KLMNPQRS45"}

    def unlock_status(self, request_id):
        self.calls.append(("unlock-status", request_id))
        return {"approved": True} if self.approved else None


@pytest.fixture
def service(tmp_path):
    clock = Clock()
    credentials = Credentials()
    transport = Transport(clock)
    result = FocusModeService(
        FocusStateStore(tmp_path / "focus-state.json"),
        credentials=credentials,
        transport=transport,
        approved_youtube_ids=["abcdefghijk", "12345678901", "bad"],
        clock=clock,
    )
    return result, credentials, transport, clock


def test_firebase_placeholders_are_rejected():
    environment = {
        "MARIANA_FIREBASE_PROJECT_ID": "replace-with-project-id",
        "MARIANA_FIREBASE_API_KEY": "replace-with-web-api-key",
        "MARIANA_FIREBASE_APP_ID": "replace-with-web-app-id",
        "MARIANA_FIREBASE_FOCUS_FUNCTION_URL": "https://example.invalid/focus",
        "MARIANA_FIREBASE_RECAPTCHA_ENTERPRISE_SITE_KEY": "replace-with-site-key",
    }
    assert FirebaseFocusTransport(environment=environment).configured() is False


def test_paired_device_requires_a_finite_numeric_timestamp():
    payload = {"device_id": "phone-device-0001", "label": "Phone"}
    assert PairedFocusDevice.from_dict({**payload, "paired_at": 1_000}) == PairedFocusDevice(
        "phone-device-0001", "Phone", 1_000.0
    )
    assert PairedFocusDevice.from_dict({**payload, "paired_at": None}) is None
    assert PairedFocusDevice.from_dict({**payload, "paired_at": True}) is None
    assert PairedFocusDevice.from_dict({**payload, "paired_at": "1000"}) is None
    assert PairedFocusDevice.from_dict({**payload, "paired_at": float("inf")}) is None


def test_focus_environment_keeps_placeholders_local_and_never_overrides_real_values(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "MARIANA_FIREBASE_PROJECT_ID=replace-with-project-id\n"
        "MARIANA_FIREBASE_FOCUS_FUNCTION_URL=https://example.invalid/focus\n"
        "MARIANA_FOCUS_YOUTUBE_IDS=abcdefghijk,12345678901\n"
        "UNRELATED_SECRET=must-not-be-loaded\n",
        encoding="utf-8",
    )

    environment = focus_environment(
        path,
        base={"MARIANA_FIREBASE_PROJECT_ID": "configured-project"},
    )

    assert environment["MARIANA_FIREBASE_PROJECT_ID"] == "configured-project"
    assert environment["MARIANA_FIREBASE_FOCUS_FUNCTION_URL"] == "https://example.invalid/focus"
    assert environment["MARIANA_FOCUS_YOUTUBE_IDS"] == "abcdefghijk,12345678901"
    assert "UNRELATED_SECRET" not in environment


def test_passcode_is_verified_without_persisting_plaintext(service):
    focus, credentials, _transport, _clock = service
    focus.setup_passcode("long-study-passcode", "long-study-passcode")

    verifier = next(iter(credentials.values.values()))
    assert "long-study-passcode" not in verifier
    assert verify_passcode("long-study-passcode", verifier)
    assert not verify_passcode("wrong-passcode", verifier)

    with pytest.raises(FocusModeError, match="confirmation"):
        focus.setup_passcode("long-study-passcode", "different-value")


def test_focus_activation_fails_closed_until_every_prerequisite_exists(service):
    focus, _credentials, transport, clock = service
    with pytest.raises(FocusModeError, match="passcode"):
        focus.activate()

    focus.setup_passcode("long-study-passcode", "long-study-passcode")
    transport.ready = False
    with pytest.raises(FocusModeError, match="Firebase"):
        focus.activate()

    transport.ready = True
    with pytest.raises(FocusModeError, match="phone"):
        focus.activate()

    focus.state.paired_devices.append(PairedFocusDevice("phone-device-0001", "Phone", clock()))
    selected = focus.activate(media_id="abcdefghijk")
    assert selected.media_id == "abcdefghijk"
    assert focus.status()["active"] is True


def test_pairing_records_only_verified_device_metadata(service):
    focus, _credentials, transport, _clock = service
    invitation = focus.begin_pairing()
    assert invitation["code"] == "ABCDEFGH23"
    assert focus.refresh_pairing() is None

    transport.paired = True
    device = focus.refresh_pairing()
    assert device == PairedFocusDevice("phone-device-0001", "Study phone", 1_000.0)
    assert focus.status()["paired_devices"] == [{
        "device_id": "phone-device-0001", "label": "Study phone", "paired_at": 1_000.0,
    }]


def test_full_unlock_requires_both_codes_and_countdown(service):
    focus, _credentials, transport, clock = service
    focus.setup_passcode("long-study-passcode", "long-study-passcode")
    focus.state.paired_devices.append(PairedFocusDevice("phone-device-0001", "Phone", clock()))
    focus.activate(media_id="abcdefghijk")

    with pytest.raises(FocusModeError, match="incorrect"):
        focus.begin_unlock("wrong-passcode")
    request_id = focus.begin_unlock("long-study-passcode")
    assert request_id == "unlock-request-1"
    assert focus.submit_phone_code("ABCDEFGH23") == "KLMNPQRS45"
    assert focus.poll_unlock() is False

    transport.approved = True
    assert focus.poll_unlock() is False
    assert focus.status()["countdown_seconds"] == 3
    clock.value += 2.9
    assert focus.poll_unlock() is False
    clock.value += 0.1
    assert focus.poll_unlock() is True
    assert focus.status()["active"] is False


def test_active_focus_mode_blocks_other_media_and_distracting_commands(service):
    focus, _credentials, _transport, clock = service
    focus.setup_passcode("long-study-passcode", "long-study-passcode")
    focus.state.paired_devices.append(PairedFocusDevice("phone-device-0001", "Phone", clock()))
    focus.activate(media_id="abcdefghijk")

    allowed = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=abcdefghijk",
        resolver_data={"youtube_id": "abcdefghijk"},
    )
    assert focus.assert_media_allowed(allowed) is allowed
    with pytest.raises(FocusModeError, match="switching"):
        focus.assert_media_allowed(MediaRef(MediaSource.YOUTUBE, "https://youtu.be/12345678901"))
    with pytest.raises(FocusModeError, match="approved focus media"):
        focus.assert_media_allowed(MediaRef(MediaSource.LOCAL, "C:/music/song.mp3"))

    assert focus.allows_command(["pause"])
    assert focus.allows_command(["focus", "status"])
    assert not focus.allows_command(["find", "song"])
    assert not focus.allows_command(["next"])


def test_state_persists_without_passcode_or_media_urls(service):
    focus, credentials, transport, clock = service
    focus.setup_passcode("long-study-passcode", "long-study-passcode")
    focus.state.paired_devices.append(PairedFocusDevice("phone-device-0001", "Phone", clock()))
    focus.activate(media_id="abcdefghijk")

    restored = FocusModeService(
        focus.store,
        credentials=credentials,
        transport=transport,
        approved_youtube_ids=["abcdefghijk"],
        clock=clock,
    )
    assert restored.status()["active"] is True
    payload = focus.store.path.read_text(encoding="utf-8")
    assert "long-study-passcode" not in payload
    assert "youtube.com" not in payload
