"""Local fault-injection checks for focus challenges and protected credentials."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
from typing import cast
from urllib.error import URLError
from urllib.request import HTTPHandler, HTTPSHandler, build_opener
from urllib.response import addinfourl

import pytest

from mariana import focus_mode as focus
from mariana.credentials import CredentialError, CredentialStore
from mariana.models import MediaRef, MediaSource
from tests.test_focus_mode import Clock, Credentials, Transport

PASSCODE = "example-focus-passcode"


@pytest.fixture(autouse=True)
def no_external_services(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("This regression must not contact a network or real credential store")

    monkeypatch.setattr(focus, "build_opener", forbidden)
    monkeypatch.setattr(CredentialStore, "_keyring", forbidden)


@pytest.fixture(scope="module")
def verifier():
    return focus._passcode_verifier(PASSCODE, salt=b"local-test-salt!")


@pytest.fixture
def bundle(tmp_path, monkeypatch, verifier):
    clock, credentials = Clock(1_800_000_000.0), Credentials()
    monkeypatch.setattr(focus, "_now", clock)
    credentials.values[focus.PASSCODE_REFERENCE] = verifier
    transport = Transport(clock)
    store = focus.FocusStateStore(tmp_path / "focus-state.json")
    service = focus.FocusModeService(
        store, credentials=cast(CredentialStore, credentials), transport=transport,
        approved_youtube_ids=["abcdefghijk", "12345678901"], clock=clock,
    )
    service.state.paired_devices = [focus.PairedFocusDevice("phone-device-0001", "Phone", clock())]
    activation = service.activate(media_id="abcdefghijk")
    return SimpleNamespace(
        service=service, store=store, clock=clock, credentials=credentials, transport=transport, activation=activation,
    )


def reload_service(bundle):
    return focus.FocusModeService(
        bundle.store, credentials=cast(CredentialStore, bundle.credentials), transport=bundle.transport,
        approved_youtube_ids=["abcdefghijk"], clock=bundle.clock,
    )


def test_failed_passcodes_and_retry_delay_survive_restart_without_contacting_transport(bundle):
    service = bundle.service
    for _ in range(focus.MAX_ATTEMPTS):
        with pytest.raises(focus.FocusModeError, match="incorrect"):
            service.begin_unlock("incorrect-example")
    assert bundle.transport.calls == []
    restored = reload_service(bundle)
    assert restored.status()["active"] is True
    assert restored.status()["passcode_retry_after"] == focus.ATTEMPT_LOCK_SECONDS
    with pytest.raises(focus.FocusModeError, match="Too many failed attempts"):
        restored.begin_unlock(PASSCODE)
    assert bundle.transport.calls == []
    bundle.clock.value += focus.ATTEMPT_LOCK_SECONDS
    assert restored.begin_unlock(PASSCODE) == "unlock-request-1"
    assert restored.status()["active"] is True
    assert len(bundle.transport.calls) == 1
    assert bundle.store.load().passcode_blocked_until is None


@pytest.mark.parametrize("device_id", ["unknown-device-0001", "invalid"])
def test_unknown_unlock_recipient_is_rejected_without_a_remote_challenge(bundle, device_id):
    before = bundle.store.path.read_bytes()
    with pytest.raises(focus.FocusModeError, match=r"not paired|invalid"):
        bundle.service.begin_unlock(PASSCODE, device_id=device_id)
    assert bundle.transport.calls == []
    assert bundle.service.status()["active"] is True
    assert bundle.service.state.unlock_request_id is None
    assert bundle.store.path.read_bytes() == before


@pytest.mark.parametrize("response", [
    {"request_id": "bad", "expires_at": 1_800_000_100},
    {"request_id": "unlock-request-1", "expires_at": None},
    {"request_id": "unlock-request-1", "expires_at": 1_800_000_000},
    {"request_id": "unlock-request-1", "expires_at": float("inf")},
    {"request_id": "unlock-request-1", "expires_at": 1_800_001_000},
])
def test_invalid_challenge_response_keeps_focus_locked_and_saved_state_unchanged(bundle, monkeypatch, response):
    before = bundle.store.path.read_bytes()
    monkeypatch.setattr(bundle.transport, "begin_unlock", lambda *_args: response)
    with pytest.raises(focus.FocusModeError, match="invalid"):
        bundle.service.begin_unlock(PASSCODE)
    assert bundle.service.state.active
    assert bundle.service.state.unlock_stage is None
    assert bundle.store.path.read_bytes() == before
    assert reload_service(bundle).status()["active"] is True


@pytest.mark.parametrize("stage", ["awaiting_phone_code", "awaiting_phone_confirmation", "countdown"])
def test_cancelled_unlock_stays_cancelled_after_restart_and_late_approval(bundle, stage):
    service = bundle.service
    service.begin_unlock(PASSCODE)
    if stage != "awaiting_phone_code":
        service.submit_phone_code("ABCDEFGH23")
    if stage == "countdown":
        bundle.transport.approved = True
        assert service.poll_unlock() is False
    assert service.state.unlock_stage == stage
    service.cancel_pending_unlock()
    previous_calls = list(bundle.transport.calls)
    restored = reload_service(bundle)
    bundle.transport.approved = True
    bundle.clock.value += 10
    assert restored.poll_unlock() is False
    assert restored.status()["active"] is True
    assert restored.status()["unlock_stage"] is None
    assert bundle.transport.calls == previous_calls
    assert bundle.store.load().active
    assert bundle.store.load().unlock_request_id is None


@pytest.mark.parametrize("operation", ["phone_code", "approval"])
def test_expired_unlock_does_not_send_code_or_poll_remote_approval(bundle, operation):
    service = bundle.service
    service.begin_unlock(PASSCODE)
    if operation == "approval":
        service.submit_phone_code("ABCDEFGH23")
    previous_calls = list(bundle.transport.calls)
    bundle.clock.value += focus.UNLOCK_TTL_SECONDS
    with pytest.raises(focus.FocusModeError, match="expired"):
        if operation == "phone_code":
            service.submit_phone_code("ABCDEFGH23")
        else:
            service.poll_unlock()
    assert service.state.active and service.state.unlock_stage is None
    assert bundle.transport.calls == previous_calls
    assert bundle.store.load().active and bundle.store.load().unlock_request_id is None


def test_awaiting_phone_confirmation_survives_restart_without_local_unlock(bundle):
    service = bundle.service
    service.begin_unlock(PASSCODE)
    service.submit_phone_code("ABCDEFGH23")
    restored = reload_service(bundle)
    assert restored.state.unlock_request_id == service.state.unlock_request_id
    assert restored.state.unlock_stage == "awaiting_phone_confirmation"
    assert restored.poll_unlock() is False
    assert restored.state.active and restored.state.countdown_started_at is None
    assert bundle.store.load().active


@pytest.mark.parametrize("lateness", [0, 1])
def test_approval_arriving_after_challenge_expiry_cannot_start_unlock_countdown(bundle, monkeypatch, lateness):
    service = bundle.service
    service.begin_unlock(PASSCODE)
    service.submit_phone_code("ABCDEFGH23")

    def late_approval(_request_id):
        bundle.clock.value += focus.UNLOCK_TTL_SECONDS + lateness
        return {"approved": True}

    monkeypatch.setattr(bundle.transport, "unlock_status", late_approval)
    with pytest.raises(focus.FocusModeError, match="expired"):
        service.poll_unlock()
    bundle.clock.value += focus.COUNTDOWN_SECONDS + 1
    assert service.poll_unlock() is False
    assert service.status()["active"] is True
    assert service.state.unlock_stage is None
    assert bundle.store.load().active


@pytest.mark.parametrize("lateness", [0, 1])
def test_phone_verification_finishing_at_expiry_cannot_publish_return_code(bundle, monkeypatch, lateness):
    service = bundle.service
    service.begin_unlock(PASSCODE)

    def late_verification(_request_id, _code):
        bundle.clock.value += focus.UNLOCK_TTL_SECONDS + lateness
        return {"desktop_code": "KLMNPQRS45"}

    monkeypatch.setattr(bundle.transport, "verify_phone_code", late_verification)
    with pytest.raises(focus.FocusModeError, match="expired"):
        service.submit_phone_code("ABCDEFGH23")
    assert service.state.active and service.state.unlock_stage is None
    assert service.state.countdown_started_at is None
    assert service.poll_unlock() is False
    saved = bundle.store.load()
    assert saved.active and saved.unlock_request_id is None
    assert saved.countdown_started_at is None
    assert "KLMNPQRS45" not in bundle.store.path.read_text(encoding="utf-8")


@pytest.mark.parametrize("lateness", [0, 1])
def test_pairing_confirmation_finishing_at_expiry_cannot_persist_device(bundle, monkeypatch, lateness):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    existing = tuple(service.state.paired_devices)
    service.begin_pairing()

    def late_pairing(_request_id):
        bundle.clock.value += focus.PAIRING_TTL_SECONDS + lateness
        return {"paired": True, "device_id": "phone-device-0002", "label": "Late phone"}

    monkeypatch.setattr(bundle.transport, "pairing_status", late_pairing)
    with pytest.raises(focus.FocusModeError, match="expired"):
        service.refresh_pairing()
    assert tuple(service.state.paired_devices) == existing
    assert service.state.pairing_request_id is None and service.state.pairing_expires_at is None
    saved = bundle.store.load()
    assert tuple(saved.paired_devices) == existing and saved.pairing_request_id is None
    assert "phone-device-0002" not in bundle.store.path.read_text(encoding="utf-8")


def test_atomic_state_write_failure_preserves_existing_lock_and_removes_temporary_file(bundle, monkeypatch):
    original = bundle.store.path.read_bytes()
    replacement = focus.FocusState(**{
        **asdict(bundle.service.state), "active": False, "paired_devices": bundle.service.state.paired_devices,
    })

    def disk_failure(*_args):
        raise OSError("Synthetic atomic replacement refusal")

    monkeypatch.setattr(focus.os, "replace", disk_failure)
    with pytest.raises(OSError, match="replacement refusal"):
        bundle.store.save(replacement)
    assert bundle.store.path.read_bytes() == original
    assert bundle.store.load().active
    assert list(bundle.store.path.parent.glob(".focus-state-*.tmp")) == []


class Response:
    def __init__(self, payload: bytes, status: int = 200):
        self.payload, self.status = payload, status
        self.read_sizes: list[int] = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        return self.payload[:size]


class RedirectResponse(addinfourl):
    msg = "Found"


@pytest.fixture
def http_transport(monkeypatch):
    credentials, requests = Credentials(), []
    environment: dict[str, str] = dict.fromkeys(focus.FirebaseFocusTransport.REQUIRED_ENV, "test-configured-value")
    environment["MARIANA_FIREBASE_FOCUS_FUNCTION_URL"] = "https://focus.example.invalid/function"
    response = Response(b'{"ok":true,"data":{}}')
    transport = focus.FirebaseFocusTransport(
        environment=environment, credentials=cast(CredentialStore, credentials), timeout=100,
    )

    def open_response(request, *, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(focus, "build_opener", lambda *_handlers: SimpleNamespace(open=open_response))
    return SimpleNamespace(
        transport=transport, credentials=credentials, response=response, requests=requests,
    )


@pytest.mark.parametrize("payload", [
    b'not-json', b'[]', b'{"ok":false,"data":{}}', b'{"ok":1,"data":{}}',
    b'{"ok":true,"data":[]}', b'{"ok":true}', b'\xff', b'[' * 2_000 + b']' * 2_000,
])
def test_malformed_transport_envelopes_are_rejected_and_response_closed(http_transport, payload):
    http_transport.response.payload = payload
    with pytest.raises(focus.FocusModeError, match=r"unavailable|invalid response"):
        http_transport.transport.unlock_status("unlock-request-1")
    assert http_transport.response.closed
    assert http_transport.response.read_sizes == [65_537]
    assert http_transport.requests[0][1] == 10


@pytest.mark.parametrize("operation, field", [("pairing_status", "paired"), ("unlock_status", "approved")])
@pytest.mark.parametrize("approval", [False, 1, "true", None])
def test_transport_requires_explicit_boolean_approval(http_transport, operation, field, approval):
    http_transport.response.payload = json.dumps({"ok": True, "data": {field: approval}}).encode()
    assert getattr(http_transport.transport, operation)("challenge-id-0001") is None
    assert http_transport.response.closed


def test_transport_rejects_oversized_valid_json_envelope(http_transport):
    envelope = b'{"ok":true,"data":{"approved":true}}'
    http_transport.response.payload = envelope + b" " * (65_537 - len(envelope))
    with pytest.raises(focus.FocusModeError, match="oversized response"):
        http_transport.transport.unlock_status("unlock-request-1")
    assert http_transport.response.closed
    assert http_transport.response.read_sizes == [65_537]


def test_transport_accepts_valid_response_at_exact_byte_limit(http_transport):
    envelope = b'{"ok":true,"data":{"approved":true}}'
    http_transport.response.payload = envelope + b" " * (65_536 - len(envelope))
    assert http_transport.transport.unlock_status("unlock-request-1") == {"approved": True}
    assert http_transport.response.closed and http_transport.response.read_sizes == [65_537]


def test_transport_does_not_parse_unsuccessful_http_response(http_transport):
    http_transport.response.status = 503
    http_transport.response.payload = b'{"ok":true,"data":{"approved":true}}'
    with pytest.raises(focus.FocusModeError, match="unavailable"):
        http_transport.transport.unlock_status("unlock-request-1")
    assert http_transport.response.closed and http_transport.response.read_sizes == []


def test_pairing_token_is_protected_not_returned_or_written_to_public_state(http_transport, bundle):
    token = "test-only-private-desktop-token-1234567890"
    data = {"desktop_token": token, "request_id": "pairing-request-1",
            "code": "ABCDEFGH23", "expires_at": bundle.clock() + 300}
    http_transport.response.payload = json.dumps({"ok": True, "data": data}).encode()
    result = http_transport.transport.begin_pairing(bundle.service.state.desktop_instance_id)
    assert result == {key: value for key, value in data.items() if key != "desktop_token"}
    assert http_transport.credentials.values == {focus.FIREBASE_DESKTOP_TOKEN_REFERENCE: token}
    assert token not in repr(result)
    assert token not in json.dumps(bundle.service.status())
    assert token not in bundle.store.path.read_text(encoding="utf-8")
    http_transport.response.payload = b'{"ok":true,"data":{"approved":false}}'
    assert http_transport.transport.unlock_status("unlock-request-1") is None
    request = http_transport.requests[-1][0]
    assert request.get_header("X-mariana-desktop-token") == token
    assert token.encode() not in request.data


@pytest.mark.parametrize("token", [None, "short", 123, []])
def test_invalid_pairing_token_is_not_saved(http_transport, token):
    http_transport.response.payload = json.dumps({"ok": True, "data": {"desktop_token": token}}).encode()
    with pytest.raises(focus.FocusModeError, match="invalid desktop pairing token"):
        http_transport.transport.begin_pairing("desktop-instance-0001")
    assert http_transport.credentials.values == {}


def test_credential_read_failure_does_not_send_any_request_or_expose_private_detail(http_transport, monkeypatch):
    def unavailable(_reference):
        raise CredentialError("private-token-and-account-detail")

    monkeypatch.setattr(http_transport.credentials, "get", unavailable)
    with pytest.raises(focus.FocusModeError, match="credential store is unavailable") as caught:
        http_transport.transport.unlock_status("unlock-request-1")
    assert http_transport.requests == []
    assert "private-token" not in str(caught.value)


def test_pairing_token_write_failure_does_not_publish_unprotected_credentials(http_transport, monkeypatch):
    token = "private-desktop-token-that-must-be-protected"
    http_transport.response.payload = json.dumps({"ok": True, "data": {"desktop_token": token}}).encode()

    def rejected(_reference, _value):
        raise CredentialError("Private storage detail")

    monkeypatch.setattr(http_transport.credentials, "set", rejected)
    with pytest.raises(focus.FocusModeError, match="could not be protected") as caught:
        http_transport.transport.begin_pairing("desktop-instance-0001")
    assert token not in str(caught.value) and "Private storage detail" not in str(caught.value)
    assert http_transport.credentials.values == {}
    assert http_transport.response.closed


@pytest.mark.parametrize('operation', ['setup', 'pair', 'revoke'])
def test_active_restrictions_prevent_identity_configuration_changes(bundle, operation):
    before = bundle.store.path.read_bytes()
    credentials = dict(bundle.credentials.values)
    calls = list(bundle.transport.calls)
    with pytest.raises(focus.FocusModeError, match='active'):
        if operation == 'setup':
            bundle.service.setup_passcode('replacement-passcode', 'replacement-passcode')
        elif operation == 'pair':
            bundle.service.begin_pairing()
        else:
            bundle.service.revoke_device('phone-device-0001')
    assert bundle.store.path.read_bytes() == before
    assert bundle.credentials.values == credentials and bundle.transport.calls == calls


def test_pairing_expired_before_poll_never_queries_transport(bundle):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    service.begin_pairing()
    calls = list(bundle.transport.calls)
    bundle.clock.value += focus.PAIRING_TTL_SECONDS
    with pytest.raises(focus.FocusModeError, match='expired'):
        service.refresh_pairing()
    assert bundle.transport.calls == calls
    assert service.state.pairing_request_id is None
    with pytest.raises(focus.FocusModeError, match='No phone pairing'):
        service.refresh_pairing()


@pytest.mark.parametrize('expiry', [None, 0, float('inf'), 100_000])
def test_invalid_pairing_expiry_does_not_persist_an_invitation(bundle, monkeypatch, expiry):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    before = bundle.store.path.read_bytes()
    monkeypatch.setattr(bundle.transport, 'begin_pairing', lambda _instance: {
        'request_id': 'pairing-request-1', 'code': 'ABCDEFGH23', 'expires_at': expiry,
    })
    with pytest.raises(focus.FocusModeError, match='invalid pairing expiry'):
        service.begin_pairing()
    assert service.state.pairing_request_id is None and bundle.store.path.read_bytes() == before


@pytest.mark.parametrize('verifier', ['unknown$32768$8$1$00$00', 'malformed', 'scrypt$bad$8$1$00$00'])
def test_malformed_passcode_verifier_never_opens_remote_unlock(bundle, monkeypatch, verifier):
    monkeypatch.setattr(bundle.credentials, 'get', lambda _reference: verifier)
    calls = list(bundle.transport.calls)
    with pytest.raises(focus.FocusModeError, match='incorrect'):
        bundle.service.begin_unlock(PASSCODE)
    assert bundle.service.state.active and bundle.transport.calls == calls


def test_short_or_unstorable_passcode_never_appears_configured(bundle, monkeypatch):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    credentials = dict(bundle.credentials.values)
    with pytest.raises(focus.FocusModeError, match='at least'):
        service.setup_passcode('short', 'short')
    assert bundle.credentials.values == credentials
    monkeypatch.setattr(bundle.credentials, 'set', lambda *_args: (_ for _ in ()).throw(CredentialError('private detail')))
    with pytest.raises(focus.FocusModeError, match='could not be stored') as caught:
        service.setup_passcode('new-passcode', 'new-passcode')
    assert 'private detail' not in str(caught.value)
    assert bundle.credentials.values == credentials


@pytest.mark.parametrize('configured', [False, True])
def test_unconfigured_or_insecure_transport_never_sends_a_request(http_transport, configured):
    if configured:
        http_transport.transport.environment['MARIANA_FIREBASE_FOCUS_FUNCTION_URL'] = 'http://focus.example.invalid'
    else:
        http_transport.transport.environment.clear()
    with pytest.raises(focus.FocusModeError, match=r'HTTPS|not configured'):
        http_transport.transport.unlock_status('unlock-request-1')
    assert http_transport.requests == []


def test_unavailable_passcode_store_does_not_clear_existing_focus_lock(bundle, monkeypatch):
    before = bundle.store.path.read_bytes()

    def unavailable(_reference):
        raise CredentialError("Private account detail")

    monkeypatch.setattr(bundle.credentials, "get", unavailable)
    with pytest.raises(focus.FocusModeError, match="credential store is unavailable"):
        bundle.service.begin_unlock(PASSCODE)
    assert bundle.service.state.active and bundle.service.state.unlock_stage is None
    assert bundle.store.path.read_bytes() == before
    assert bundle.transport.calls == []


def test_transport_failure_has_safe_user_error_and_keeps_focus_locked(bundle, monkeypatch):
    service = bundle.service
    service.begin_unlock(PASSCODE)
    service.submit_phone_code("ABCDEFGH23")

    def unavailable(_request_id):
        raise focus.FocusModeError("Firebase focus verification is unavailable")

    monkeypatch.setattr(bundle.transport, "unlock_status", unavailable)
    with pytest.raises(focus.FocusModeError, match="unavailable"):
        service.poll_unlock()
    assert service.state.active and service.state.countdown_started_at is None
    assert bundle.store.load().active


def test_network_exception_does_not_expose_remote_error_details(http_transport, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise URLError("https://private.example.invalid/?token=PRIVATE_TEST_TOKEN")

    monkeypatch.setattr(focus, "build_opener", lambda *_handlers: SimpleNamespace(open=unavailable))
    with pytest.raises(focus.FocusModeError, match="unavailable") as caught:
        http_transport.transport.unlock_status("unlock-request-1")
    assert "PRIVATE_TEST_TOKEN" not in str(caught.value)
    assert "private.example" not in str(caught.value)


@pytest.mark.parametrize("destination", [
    "https://other.example.invalid/collect?private=destination-secret",
    "http://focus.example.invalid/downgrade?private=destination-secret",
    "https://focus.example.invalid/another-function?private=destination-secret",
])
def test_focus_endpoint_redirects_cannot_forward_credentials_or_make_second_request(
    http_transport, monkeypatch, destination,
):
    requests, responses = [], []
    token = "private-test-token-not-for-another-endpoint"
    http_transport.credentials.values[focus.FIREBASE_DESKTOP_TOKEN_REFERENCE] = token

    def fake_open(request):
        requests.append(request)
        headers = Message()
        headers["Location"] = destination
        response = RedirectResponse(BytesIO(b""), headers, request.full_url, code=302)
        responses.append(response)
        return response

    class LocalHTTP(HTTPHandler):
        def http_open(self, request):
            return fake_open(request)

    class LocalHTTPS(HTTPSHandler):
        def https_open(self, request):
            return fake_open(request)

    monkeypatch.setattr(
        focus, "build_opener", lambda *handlers: build_opener(*handlers, LocalHTTP(), LocalHTTPS()),
    )
    with pytest.raises(focus.FocusModeError, match="redirects are not permitted") as caught:
        http_transport.transport.unlock_status("unlock-request-1")
    assert len(requests) == 1
    assert requests[0].full_url == "https://focus.example.invalid/function"
    assert requests[0].get_header("X-mariana-desktop-token") == token
    assert token not in str(caught.value) and "destination-secret" not in str(caught.value)
    assert destination not in str(caught.value)
    assert responses and all(response.closed for response in responses)


@pytest.mark.parametrize("media_id", ["abcdefghijk", "12345678901"])
def test_activation_cannot_replace_an_existing_focus_lock(bundle, media_id):
    before = bundle.store.path.read_bytes()
    with pytest.raises(focus.FocusModeError, match="already active"):
        bundle.service.activate(media_id=media_id)
    assert bundle.store.path.read_bytes() == before
    assert bundle.service.state.active_media_id == "abcdefghijk"


def test_restored_service_cannot_rollback_an_activation_it_did_not_create(bundle):
    restored = reload_service(bundle)
    restored.rollback_activation(bundle.activation)
    assert restored.state.active
    assert bundle.store.load().active


def test_stale_rollback_cannot_unlock_a_later_activation_of_the_same_media(bundle):
    service, stale = bundle.service, bundle.activation
    service.rollback_activation(stale)
    current = service.activate(media_id="abcdefghijk")
    service.rollback_activation(stale)
    assert service.state.active and bundle.store.load().active
    service.rollback_activation(current)
    assert not service.state.active and not bundle.store.load().active


def test_confirmed_activation_no_longer_permits_rollback(bundle):
    bundle.service.confirm_activation(bundle.activation)
    bundle.service.rollback_activation(bundle.activation)
    assert bundle.service.state.active and bundle.store.load().active


@pytest.mark.parametrize("uri,hint", [
    ("https://www.youtube.com/watch?v=12345678901", "abcdefghijk"),
    ("https://elsewhere.invalid/watch?v=abcdefghijk", None),
    ("https://www.youtube.com.evil.invalid/watch?v=abcdefghijk", "abcdefghijk"),
    ("https://evil.invalid/?next=https://youtu.be/abcdefghijk", None),
    ("https://www.youtube.com/watch?v=abcdefghijk&v=12345678901", None),
    ("https://user:pass@www.youtube.com/watch?v=abcdefghijk", None),
    ("https://www.youtube.com:bad/watch?v=abcdefghijk", None),
    ("https://www.youtube.com/watch?v=abcdefghijk", "12345678901"),
])
def test_media_gate_binds_allowed_identity_to_actual_resolver_uri(bundle, uri, hint):
    media = MediaRef(MediaSource.YOUTUBE, uri, resolver_data={"youtube_id": hint} if hint else {})
    with pytest.raises(focus.FocusModeError, match="switching"):
        bundle.service.assert_media_allowed(media)
    assert bundle.service.state.active


def test_pending_pairing_cannot_change_devices_after_activation(bundle):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    service.begin_pairing()
    service.activate(media_id="abcdefghijk")
    before, calls = bundle.store.path.read_bytes(), list(bundle.transport.calls)
    bundle.transport.paired = True
    with pytest.raises(focus.FocusModeError, match="active"):
        service.refresh_pairing()
    assert bundle.transport.calls == calls
    assert bundle.store.path.read_bytes() == before


def test_ninth_paired_device_cannot_create_an_unrestorable_saved_state(bundle, monkeypatch):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    service.state.paired_devices = [
        focus.PairedFocusDevice(f"phone-device-{index:04}", "Phone", bundle.clock()) for index in range(8)
    ]
    service.begin_pairing()
    before = bundle.store.path.read_bytes()
    monkeypatch.setattr(bundle.transport, "pairing_status", lambda _request: {
        "paired": True, "device_id": "phone-device-0009", "label": "Ninth",
    })
    with pytest.raises(focus.FocusModeError, match="limit"):
        service.refresh_pairing()
    assert bundle.store.path.read_bytes() == before
    assert len(service.state.paired_devices) == 8
    assert not reload_service(bundle).recovery_required


def test_passcode_replacement_is_serialized_before_concurrent_activation(bundle, monkeypatch):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    entered, release, activating, finished = (threading.Event() for _ in range(4))
    errors, order = [], []
    original_hash = focus._passcode_verifier
    original_set = bundle.credentials.set

    def record_replacement(reference, value):
        original_set(reference, value)
        order.append("setup")

    def blocked_hash(passcode):
        entered.set()
        assert release.wait(3)
        return original_hash(passcode)

    def setup():
        try:
            service.setup_passcode("replacement-passcode", "replacement-passcode")
        except BaseException as error:
            errors.append(error)

    def activate():
        activating.set()
        try:
            service.activate(media_id="abcdefghijk")
            order.append("activate")
        except BaseException as error:
            errors.append(error)
        finally:
            finished.set()

    monkeypatch.setattr(focus, "_passcode_verifier", blocked_hash)
    monkeypatch.setattr(bundle.credentials, "set", record_replacement)
    setter = threading.Thread(target=setup)
    activator = threading.Thread(target=activate)
    setter.start()
    try:
        assert entered.wait(2)
        activator.start()
        assert activating.wait(2)
        assert not finished.wait(0.25), "Activation raced past pending passcode replacement"
    finally:
        release.set()
        setter.join(3)
        if activator.ident is not None:
            activator.join(3)
    assert not setter.is_alive() and not activator.is_alive()
    assert errors == [] and order == ["setup", "activate"]
    assert service.state.active
    assert focus.verify_passcode("replacement-passcode", bundle.credentials.values[focus.PASSCODE_REFERENCE])


@pytest.mark.parametrize("verifier", [
    "scrypt$32768$8$2$" + "00" * 16 + "$" + "00" * 32,
    "scrypt$32768$8$1000000$" + "00" * 16 + "$" + "00" * 32,
    "scrypt$2$1$1$" + "00" * 16 + "$" + "00" * 32,
    "scrypt$32768$8$1$00$" + "00" * 32,
    "scrypt$32768$8$1$" + "00" * 16 + "$00",
    123, [], {},
])
def test_untrusted_verifier_cannot_select_hash_work_or_crash(verifier, monkeypatch):
    def forbidden_hash(*_args, **_kwargs):
        pytest.fail("Malformed verifier must be rejected before hashing")

    monkeypatch.setattr(focus.hashlib, "scrypt", forbidden_hash)
    assert focus.verify_passcode(PASSCODE, verifier) is False


def test_saved_document_descriptor_must_be_regular_before_reading(bundle, monkeypatch):
    import stat

    original = focus.os.fstat
    descriptors = []

    def nonregular(descriptor):
        details = original(descriptor)
        descriptors.append(descriptor)
        return SimpleNamespace(
            st_dev=details.st_dev, st_ino=details.st_ino,
            st_mode=stat.S_IFIFO, st_file_attributes=0, st_size=details.st_size,
        )

    monkeypatch.setattr(focus.os, "fstat", nonregular)
    with pytest.raises(focus.FocusModeError, match="recovery"):
        bundle.store._read(bundle.store.path)
    assert descriptors
    with pytest.raises(OSError):
        original(descriptors[-1])


@pytest.mark.parametrize("operation", ["phone_code", "approval"])
def test_inflight_challenge_can_be_cancelled_without_waiting_for_transport(bundle, monkeypatch, operation):
    service = bundle.service
    service.begin_unlock(PASSCODE)
    if operation == "approval":
        service.submit_phone_code("ABCDEFGH23")
    entered, release, cancelled = (threading.Event() for _ in range(3))
    errors, returned = [], []

    def blocked_response(*_args):
        entered.set()
        assert release.wait(3)
        return {"approved": True, "desktop_code": "KLMNPQRS45"}

    def request():
        try:
            returned.append(service.poll_unlock() if operation == "approval" else service.submit_phone_code("ABCDEFGH23"))
        except focus.FocusModeError as error:
            errors.append(error)

    def cancel():
        service.cancel_pending_unlock()
        cancelled.set()

    name = "unlock_status" if operation == "approval" else "verify_phone_code"
    monkeypatch.setattr(bundle.transport, name, blocked_response)
    worker, canceller = threading.Thread(target=request), threading.Thread(target=cancel)
    worker.start()
    try:
        assert entered.wait(2)
        canceller.start()
        assert cancelled.wait(0.5), "Cancellation waited for the remote response while holding the state lock"
        assert service.status()["active"] and service.state.unlock_stage is None
    finally:
        release.set()
        worker.join(3)
        if canceller.ident is not None:
            canceller.join(3)
    assert not worker.is_alive() and not canceller.is_alive()
    assert returned == [] and len(errors) == 1
    assert service.state.active and bundle.store.load().unlock_stage is None


@pytest.mark.parametrize("uri", [
    "https://www.youtube.com/watch?v=abcdefghijk",
    "https://youtu.be/abcdefghijk?t=10",
    "https://www.youtube.com/shorts/abcdefghijk",
    "https://www.youtube.com/embed/abcdefghijk",
    "https://www.youtube.com/live/abcdefghijk",
    "https://music.youtube.com/watch?v=abcdefghijk",
])
def test_genuine_supported_provider_urls_remain_playable(bundle, uri):
    media = MediaRef(MediaSource.YOUTUBE, uri)
    assert bundle.service.assert_media_allowed(media) is media


def test_forged_receipt_cannot_confirm_or_rollback_activation(bundle):
    forged = focus.FocusActivation(bundle.activation.media_id)
    assert not bundle.service.confirm_activation(forged)
    assert not bundle.service.rollback_activation(forged)
    assert not bundle.service.rollback_activation(bundle.activation.media_id)
    assert bundle.service.state.active
    assert bundle.service.rollback_activation(bundle.activation)
    assert not bundle.service.state.active


def test_phone_metadata_refresh_at_device_limit_remains_restorable(bundle, monkeypatch):
    service = bundle.service
    service.rollback_activation(bundle.activation)
    service.state.paired_devices = [
        focus.PairedFocusDevice(f"phone-device-{index:04}", "Phone", bundle.clock()) for index in range(8)
    ]
    service.begin_pairing()
    monkeypatch.setattr(bundle.transport, "pairing_status", lambda _request: {
        "paired": True, "device_id": "phone-device-0001", "label": "Updated phone",
    })
    assert service.refresh_pairing().label == "Updated phone"
    assert len(service.state.paired_devices) == 8
    assert not reload_service(bundle).recovery_required


@pytest.mark.parametrize("operation", ["phone_code", "approval"])
def test_late_reply_cannot_advance_replacement_flow_even_when_remote_id_is_reused(bundle, monkeypatch, operation):
    service = bundle.service
    service.begin_unlock(PASSCODE)
    original_verify = bundle.transport.verify_phone_code
    if operation == "approval":
        service.submit_phone_code("ABCDEFGH23")
    entered, release = threading.Event(), threading.Event()
    errors, returned = [], []

    def blocked(*_args):
        entered.set()
        assert release.wait(3)
        return {"approved": True, "desktop_code": "KLMNPQRS45"}

    def request():
        try:
            returned.append(service.poll_unlock() if operation == "approval" else service.submit_phone_code("ABCDEFGH23"))
        except focus.FocusModeError as error:
            errors.append(error)

    monkeypatch.setattr(bundle.transport, "unlock_status" if operation == "approval" else "verify_phone_code", blocked)
    worker = threading.Thread(target=request)
    worker.start()
    try:
        assert entered.wait(2)
        service.cancel_pending_unlock()
        assert service.begin_unlock(PASSCODE) == "unlock-request-1"
        if operation == "approval":
            monkeypatch.setattr(bundle.transport, "verify_phone_code", original_verify)
            service.submit_phone_code("ABCDEFGH23")
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert returned == [] and len(errors) == 1
    assert "replaced" in str(errors[0])
    assert service.state.active and service.state.countdown_started_at is None
    assert service.state.unlock_stage == ("awaiting_phone_code" if operation == "phone_code"
                                          else "awaiting_phone_confirmation")
    assert bundle.store.load().unlock_stage == service.state.unlock_stage


def test_authorized_unlock_invalidates_receipt_before_same_media_reactivation(bundle):
    service, stale = bundle.service, bundle.activation
    service.begin_unlock(PASSCODE)
    service.submit_phone_code("ABCDEFGH23")
    bundle.transport.approved = True
    service.poll_unlock()
    bundle.clock.value += focus.COUNTDOWN_SECONDS
    assert service.poll_unlock()
    current = service.activate(media_id="abcdefghijk")
    assert not service.rollback_activation(stale)
    assert service.state.active
    assert service.confirm_activation(current)
    assert not service.rollback_activation(current)
    assert bundle.store.load().active


@pytest.mark.parametrize("nested", [False, True])
def test_recovery_notice_runs_after_all_service_locks_release(bundle, monkeypatch, nested):
    from contextlib import nullcontext

    service = bundle.service
    callbacks, readers, acquired = [], [], []

    def notify():
        callbacks.append("recovery")
        finished = threading.Event()

        def read_state():
            assert service.recovery_status()["required"]
            finished.set()

        reader = threading.Thread(target=read_state)
        readers.append(reader)
        reader.start()
        acquired.append(finished.wait(2))

    service._on_recovery = notify
    monkeypatch.setattr(bundle.store, "save", lambda _state: (_ for _ in ()).throw(OSError("test failure")))
    try:
        with service._state_lock() if nested else nullcontext():
            with pytest.raises(focus.FocusModeError, match="recovery"):
                service.cancel_pending_unlock()
            if nested:
                assert callbacks == []
        assert callbacks == ["recovery"] and acquired == [True]
        assert not service._pending_activation
    finally:
        for reader in readers:
            reader.join(2)
    assert not any(reader.is_alive() for reader in readers)
    assert service.recovery_required and service.state.active


def test_cancelling_unlock_does_not_reset_failed_passcode_budget(bundle):
    service = bundle.service
    for _ in range(focus.MAX_ATTEMPTS - 1):
        with pytest.raises(focus.FocusModeError, match="incorrect"):
            service.begin_unlock("incorrect-example")
        service.cancel_pending_unlock()
    restored = reload_service(bundle)
    assert restored.state.failed_attempts == focus.MAX_ATTEMPTS - 1
    with pytest.raises(focus.FocusModeError, match="incorrect"):
        restored.begin_unlock("incorrect-example")
    with pytest.raises(focus.FocusModeError, match="Too many failed attempts"):
        restored.begin_unlock(PASSCODE)
    assert bundle.transport.calls == []
    assert restored.state.active
