"""Credential verifier strength, bounded work, and lifecycle race regressions."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from mariana import paired_transport as transport
from mariana import paired_trust as trust


def test_peer_supplied_weak_credential_uses_salted_stretched_verifier(tmp_path):
    path = tmp_path / "trust.json"
    service = trust.PairedReadOnlyService(trust.TrustStore(path))
    invitation, _ = service.invitation()
    token = "A" * 43
    server = object.__new__(transport.PairedServer)
    server._endpoint = SimpleNamespace(address="127.0.0.1", port=12345)
    server.service = service
    request = server._route("POST /v1/pairing HTTP/1.1", {
        "host": "127.0.0.1:12345", "content-type": "application/json",
    }, json.dumps({"invitation": invitation, "credential": token, "label": "Peer"}).encode())
    identifier = request["request_id"]
    service.approve(identifier, verified_proof=request["proof"])
    document = json.loads(path.read_text())
    stored = document["devices"][identifier]["digest"]
    assert document["schema_version"] == 2
    assert stored != hashlib.sha256(token.encode()).hexdigest()
    expected = hashlib.pbkdf2_hmac(
        "sha256", token.encode(), b"mariana-paired-device-v2\x00" + bytes.fromhex(identifier), 600_000, dklen=32,
    ).hex()
    assert stored == expected and request["proof"] == expected[:16]
    assert token not in path.read_text()
    assert trust.TrustStore(path).authenticates(identifier, token)


def test_same_credential_has_different_per_device_verifiers():
    token = secrets.token_urlsafe(32)
    first, second = secrets.token_hex(16), secrets.token_hex(16)
    assert trust.token_digest(token, first) != trust.token_digest(token, second)


@pytest.mark.parametrize("token", [None, 123, [], "", "a" * 42, "a" * 44, "é" * 43, "a" * 42 + "\n"])
def test_invalid_credential_rejected_before_derivation(monkeypatch, token):
    monkeypatch.setattr(trust.hashlib, "pbkdf2_hmac", lambda *_a, **_k: pytest.fail("Invalid input reached KDF"))
    with pytest.raises(trust.PairingError, match="credential"):
        trust.token_digest(token, "a" * 32)


@pytest.mark.parametrize("identifier", [None, 1, [], "", "a" * 31, "a" * 33, "A" * 32, "g" * 32])
def test_invalid_device_salt_rejected_before_derivation(monkeypatch, identifier):
    monkeypatch.setattr(trust.hashlib, "pbkdf2_hmac", lambda *_a, **_k: pytest.fail("Invalid input reached KDF"))
    with pytest.raises(trust.PairingError):
        trust.token_digest("a" * 43, identifier)


@pytest.mark.parametrize("version", [1, 3, 0])
def test_legacy_or_unknown_trust_version_requires_explicit_repair(tmp_path, version):
    path = tmp_path / "trust.json"
    original = json.dumps({"schema_version": version, "devices": {}}).encode()
    path.write_bytes(original)
    with pytest.raises(trust.PairingError, match="re-pair"):
        trust.TrustStore(path)
    assert path.read_bytes() == original


def test_unknown_revoked_and_malformed_devices_do_no_expensive_work(tmp_path, monkeypatch):
    store = trust.TrustStore(tmp_path / "trust.json")
    store.approve("a" * 32, "Peer", "b" * 64, now=time.time())
    store.revoke("a" * 32)
    monkeypatch.setattr(trust, "token_digest", lambda *_a: pytest.fail("Ineligible device reached KDF"))
    for identifier in ("a" * 32, "b" * 32, "invalid", None, []):
        assert not store.authenticates(identifier, "A" * 43)


def test_revocation_during_derivation_is_observed_without_holding_trust_lock(tmp_path, monkeypatch):
    path = tmp_path / "trust.json"
    store, other = trust.TrustStore(path), trust.TrustStore(path)
    store.approve("a" * 32, "Peer", "b" * 64, now=time.time())
    entered, release = threading.Event(), threading.Event()

    def derive(*_args):
        entered.set()
        assert release.wait(5)
        return "b" * 64

    monkeypatch.setattr(trust, "token_digest", derive)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(store.authenticates, "a" * 32, "A" * 43)
        try:
            assert entered.wait(2)
            other.revoke("a" * 32)
        finally:
            release.set()
        assert result.result(timeout=2) is False


@pytest.mark.parametrize("change", ["close", "expire", "activate", "reject"])
def test_pairing_derivation_cannot_outlive_request(tmp_path, monkeypatch, change):
    clock = {"now": 10.0}
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"),
                                        monotonic=lambda: clock["now"])
    invitation, _ = service.invitation()

    def derive(_token, identifier):
        if change == "close":
            service.close()
        elif change == "expire":
            clock["now"] += 301
        elif change == "activate":
            service.activate()
        else:
            service.reject(identifier)
        return "b" * 64

    monkeypatch.setattr(trust, "token_digest", derive)
    with pytest.raises(trust.PairingError):
        service.request(invitation, "A" * 43, "Peer")
    assert service.pending() == []
    assert not service.trust.devices()


def test_invalid_invitation_and_unknown_poll_do_not_derive(tmp_path, monkeypatch):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    service.invitation()
    monkeypatch.setattr(trust, "token_digest", lambda *_a: pytest.fail("Unauthorized request reached KDF"))
    with pytest.raises(trust.PairingError):
        service.request("A" * 43, "B" * 43, "Peer")
    with pytest.raises(trust.PairingError):
        service.poll("a" * 32, "B" * 43)


def test_shutdown_during_authorization_never_returns_status(tmp_path, monkeypatch):
    store = trust.TrustStore(tmp_path / "trust.json")
    service = trust.PairedReadOnlyService(store)

    def authenticate(*_args):
        service.close()
        return True

    monkeypatch.setattr(store, "authenticates", authenticate)
    with pytest.raises(trust.PairingError, match="stopped"):
        service.status("a" * 32, "A" * 43)


def test_kdf_concurrency_is_bounded_and_overload_is_nonblocking(monkeypatch):
    ready, release = threading.Barrier(3), threading.Event()
    monkeypatch.setattr(trust, "_KDF_SLOTS", threading.BoundedSemaphore(2))

    def derive(*_args, **_kwargs):
        ready.wait(timeout=3)
        assert release.wait(5)
        return b"x" * 32

    monkeypatch.setattr(trust.hashlib, "pbkdf2_hmac", derive)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(trust.token_digest, "A" * 43, "a" * 32)
        second = executor.submit(trust.token_digest, "B" * 43, "b" * 32)
        try:
            ready.wait(timeout=3)
            with pytest.raises(trust.PairingError, match="busy"):
                trust.token_digest("C" * 43, "c" * 32)
        finally:
            release.set()
        assert first.result(timeout=2) == second.result(timeout=2) == (b"x" * 32).hex()


@pytest.mark.parametrize("error", [ValueError, OverflowError, MemoryError])
def test_kdf_failure_is_safe_and_releases_capacity(monkeypatch, error):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(trust, "_KDF_SLOTS", slots)

    def reject(*_args, **_kwargs):
        raise error("private runtime detail")

    monkeypatch.setattr(trust.hashlib, "pbkdf2_hmac", reject)
    with pytest.raises(trust.PairingError, match="verification is unavailable") as caught:
        trust.token_digest("A" * 43, "a" * 32)
    assert "private" not in str(caught.value)
    assert slots.acquire(blocking=False)
    slots.release()


def test_derivation_failure_leaves_no_approvable_request_or_reusable_invitation(tmp_path, monkeypatch):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    invitation, _ = service.invitation()

    def busy(*_args):
        raise trust.PairingError("Verification is busy")

    monkeypatch.setattr(trust, "token_digest", busy)
    with pytest.raises(trust.PairingError, match="busy"):
        service.request(invitation, "A" * 43, "Peer")
    assert service.pending() == []
    monkeypatch.setattr(trust, "token_digest", lambda *_a: pytest.fail("Consumed invitation reached KDF"))
    with pytest.raises(trust.PairingError, match="already used"):
        service.request(invitation, "A" * 43, "Peer")


def test_revoked_approved_poll_rejects_before_derivation(tmp_path, monkeypatch):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    invitation, _ = service.invitation()
    monkeypatch.setattr(trust, "token_digest", lambda *_a: "b" * 64)
    request = service.request(invitation, "A" * 43, "Peer")
    identifier = request["request_id"]
    service.approve(identifier, verified_proof=request["proof"])
    service.trust.revoke(identifier)
    monkeypatch.setattr(trust, "token_digest", lambda *_a: pytest.fail("Revoked poll reached KDF"))
    with pytest.raises(trust.PairingError, match="unavailable"):
        service.poll(identifier, "A" * 43)


@pytest.mark.parametrize("change", ["close", "expire", "revoke"])
def test_poll_rechecks_lifetime_and_trust_after_derivation(tmp_path, monkeypatch, change):
    clock = {"now": 10.0}
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"),
                                        monotonic=lambda: clock["now"])
    invitation, _ = service.invitation()
    monkeypatch.setattr(trust, "token_digest", lambda *_a: "b" * 64)
    request = service.request(invitation, "A" * 43, "Peer")
    identifier = request["request_id"]
    service.approve(identifier, verified_proof=request["proof"])

    def derive(*_args):
        if change == "close":
            service.close()
        elif change == "expire":
            clock["now"] += 301
        else:
            service.trust.revoke(identifier)
        return "b" * 64

    monkeypatch.setattr(trust, "token_digest", derive)
    if change == "revoke":
        assert service.poll(identifier, "A" * 43)["state"] == "pending"
    else:
        with pytest.raises(trust.PairingError, match="unavailable"):
            service.poll(identifier, "A" * 43)


def test_pairing_derivation_does_not_lock_status_or_expose_incomplete_proof(tmp_path, monkeypatch):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    invitation, _ = service.invitation()
    entered, release = threading.Event(), threading.Event()
    identifiers = []

    def derive(_token, identifier):
        identifiers.append(identifier)
        entered.set()
        assert release.wait(5)
        return "b" * 64

    monkeypatch.setattr(trust, "token_digest", derive)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(service.request, invitation, "A" * 43, "Peer")
        try:
            assert entered.wait(2)
            assert service.pending() == []
            with pytest.raises(trust.PairingError, match="proof"):
                service.approve(identifiers[0], verified_proof="b" * 16)
            service.close()
        finally:
            release.set()
        with pytest.raises(trust.PairingError, match="stopped"):
            result.result(timeout=2)


def test_client_transport_validates_credential_without_deriving(monkeypatch):
    monkeypatch.setattr(transport, "token_digest", lambda *_a: pytest.fail("Syntax validation invoked KDF"))

    def refuse(*_args, **_kwargs):
        raise OSError("No network in this test")

    monkeypatch.setattr(transport.socket, "create_connection", refuse)
    with pytest.raises(trust.PairingError, match="connection"):
        transport.PairedClient._call(SimpleNamespace(address="127.0.0.1", port=12345),
                                    "GET", "/v1/status", credential="A" * 43, device_id="a" * 32)


def test_client_rejects_invitation_expiring_during_proof_derivation(tmp_path, monkeypatch):
    clock = {"now": time.time(), "mono": 10.0}
    endpoint = SimpleNamespace(fingerprint="b" * 64)
    monkeypatch.setattr(transport.PinnedEndpoint, "from_dict", lambda _value: endpoint)
    monkeypatch.setattr(transport.time, "time", lambda: clock["now"])
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock["mono"])
    client = transport.PairedClient(tmp_path / "peer.json")
    expires = clock["now"] + 120
    invitation = {"schema_version": 1, "endpoint": {}, "secret": "A" * 43, "expires_at": expires}
    monkeypatch.setattr(client, "_call", lambda *_a, **_k: {
        "request_id": "a" * 32, "expires_at": expires, "proof": "c" * 16,
    })

    def derive(*_args):
        clock["mono"] += 121
        return "c" * 64

    monkeypatch.setattr(transport, "token_digest", derive)
    with pytest.raises(trust.PairingError, match="expired during"):
        client.begin(invitation, label="Peer", verified_fingerprint=endpoint.fingerprint)
    assert client._pending is None and not client.path.exists()
