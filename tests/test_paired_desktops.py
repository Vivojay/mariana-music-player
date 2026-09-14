"""Private-device approval, pinned TLS and bounded read-only lifecycle contracts."""

from __future__ import annotations

import json
import secrets
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from mariana import paired_transport as transport
from mariana import paired_trust as trust
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture(autouse=True)
def application_tls_policy():
    from mariana.tls import enable_system_trust_store

    assert enable_system_trust_store()


class MemorySecrets:
    def __init__(self):
        self.values = {}
        self.calls = []

    def get(self, reference):
        self.calls.append(("get", reference))
        return self.values.get(reference)

    def set(self, reference, value):
        self.calls.append(("set", reference))
        self.values[reference] = value

    def delete(self, reference):
        self.calls.append(("delete", reference))
        self.values.pop(reference, None)


@pytest.fixture
def paired(tmp_path):
    credentials = MemorySecrets()
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    server = transport.PairedServer(service, tmp_path / "identity.json", credentials=credentials)
    endpoint = server.start("127.0.0.1")
    try:
        yield server, service, credentials, endpoint
    finally:
        server.close()


def connect(server, service, credentials, path):
    client = transport.PairedClient(path, credentials=credentials)
    invitation = server.invitation()
    response = client.begin(invitation, label="Listening room", verified_fingerprint=invitation["endpoint"]["fingerprint"])
    assert client.poll() == {"state": "pending", "device_id": None, "permissions": []}
    service.approve(response["request_id"], verified_proof=response["proof"])
    assert client.poll() == {"state": "approved", "device_id": response["request_id"], "permissions": ["status.read"]}
    return client, response["request_id"]


def test_disabled_construction_has_no_listener_secret_access_or_files(tmp_path, monkeypatch):
    credentials = MemorySecrets()
    monkeypatch.setattr(socket, "socket", lambda *_a, **_k: pytest.fail("Unexpected network access"))
    monkeypatch.setattr(threading.Thread, "start", lambda _s: pytest.fail("Unexpected worker"))
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    server = transport.PairedServer(service, tmp_path / "identity.json", credentials=credentials)
    transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
    assert not server.running
    assert credentials.calls == []
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(trust.PairingError, match="Start the local"):
        server.invitation()
    server.close()


def test_real_pinned_tls_explicit_approval_restart_and_revocation(paired, tmp_path):
    server, service, credentials, endpoint = paired
    client, identifier = connect(server, service, credentials, tmp_path / "peer.json")
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=example1234", title="A performance")
    service.update_status(PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=17, duration=60))
    status = client.status()
    assert status["title"] == "A performance"
    assert status["state"] == "playing" and status["position_seconds"] == 17
    assert set(status) == {"schema_version", "state", "title", "artist", "source", "position_seconds",
                           "duration_seconds", "finite", "live"}
    token = next(value for key, value in credentials.values.items() if key.startswith("peer-token/"))
    assert token not in (tmp_path / "peer.json").read_text()
    assert token not in (tmp_path / "trust.json").read_text()
    server.close()
    reloaded_service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    restarted = transport.PairedServer(reloaded_service, tmp_path / "identity.json", credentials=credentials)
    try:
        restarted_endpoint = restarted.start("127.0.0.1", port=endpoint.port)
        assert restarted_endpoint.fingerprint == endpoint.fingerprint
        reloaded_client = transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
        assert reloaded_client.status()["state"] == "idle"
        reloaded_service.trust.revoke(identifier)
        with pytest.raises(trust.PairingError, match="refused"):
            reloaded_client.status()
    finally:
        restarted.close()


def test_recipient_credentials_are_distinct_and_disconnect_is_scoped(paired, tmp_path):
    server, service, credentials, _ = paired
    first, first_id = connect(server, service, credentials, tmp_path / "first.json")
    second, second_id = connect(server, service, credentials, tmp_path / "second.json")
    assert first_id != second_id
    assert first._state and second._state
    assert first._state["credential_reference"] != second._state["credential_reference"]
    assert not service.trust.authenticates(first_id, credentials.get(second._state["credential_reference"]))
    first_reference = first._state["credential_reference"]
    first.disconnect()
    assert not (tmp_path / "first.json").exists()
    assert second.status()["state"] == "idle"
    assert credentials.get(first_reference) is None
    assert len(service.trust.devices()) == 2  # Client forget is not host revocation.


def test_certificate_key_is_encrypted_and_not_rotated_on_missing_secret(paired, tmp_path):
    _server, _service, credentials, endpoint = paired
    identity_path = tmp_path / "identity.json"
    saved = identity_path.read_bytes()
    document = json.loads(saved)
    assert "BEGIN ENCRYPTED PRIVATE KEY" in document["encrypted_key"]
    passphrase = credentials.values[document["key_reference"]]
    assert passphrase.encode() not in saved
    assert not list(tmp_path.glob(".paired-tls-*"))
    assert trust.server_identity(identity_path, credentials).fingerprint == endpoint.fingerprint
    credentials.values.clear()
    with pytest.raises(trust.PairingError, match="unavailable"):
        trust.server_identity(identity_path, credentials)
    assert identity_path.read_bytes() == saved


def test_wrong_pin_never_sends_pairing_payload(paired, tmp_path, monkeypatch):
    server, _service, credentials, endpoint = paired
    invitation = server.invitation()
    client = transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
    monkeypatch.setattr(client, "_call", lambda *_a, **_k: pytest.fail("Must verify the fingerprint first"))
    with pytest.raises(trust.PairingError, match="verification"):
        client.begin(invitation, label="Other device", verified_fingerprint="0" * 64)
    with pytest.raises(trust.PairingError, match="fingerprint"):
        replace(endpoint, fingerprint="0" * 64)


def test_other_server_certificate_is_rejected_before_application_request(paired, tmp_path, monkeypatch):
    server, service, credentials, endpoint = paired
    other_identity = trust.server_identity(tmp_path / "other-identity.json", credentials)
    wrong_server = transport.PinnedEndpoint(endpoint.address, endpoint.port, other_identity.certificate, other_identity.fingerprint)
    calls = []
    monkeypatch.setattr(service, "request", lambda *_a: calls.append("request"))
    with pytest.raises(trust.PairingError, match="verified"):
        transport.PairedClient._call(wrong_server, "POST", "/v1/pairing", payload={
            "invitation": server.invitation()["secret"], "credential": secrets.token_urlsafe(32), "label": "Guest",
        })
    assert calls == []


def test_private_status_uses_shared_sanitization_and_never_resolver_data(tmp_path):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    credential = secrets.token_urlsafe(32)
    identifier = "a" * 32
    service.trust.approve(identifier, "Desk", trust.token_digest(credential, identifier), now=time.time())
    media = MediaRef(MediaSource.URL, "https://private.invalid/play?token=secret", title="token=secret",
                     artist="C:\\private\\artist", resolver_data={"cookie": "secret"})
    service.update_status(PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=2))
    result = service.status(identifier, credential)
    encoded = json.dumps(result)
    assert "secret" not in encoded and "private" not in encoded and "cookie" not in encoded
    assert result["title"] == "Online media" and result["artist"] is None
    assert result["duration_seconds"] is None


def test_invitation_one_use_expiry_and_clock_rollback(tmp_path):
    clock = {"wall": time.time(), "mono": 10.0}
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"),
                                        now=lambda: clock["wall"], monotonic=lambda: clock["mono"])
    secret, _ = service.invitation(ttl_seconds=3)
    credential = secrets.token_urlsafe(32)
    request = service.request(secret, credential, "Desk")
    with pytest.raises(trust.PairingError, match="already used"):
        service.request(secret, secrets.token_urlsafe(32), "Another")
    with pytest.raises(trust.PairingError, match="proof"):
        service.approve(request["request_id"], verified_proof="0" * 16)
    assert service.poll(request["request_id"], credential)["state"] == "pending"
    clock["wall"] -= 86400
    clock["mono"] += 3
    assert service.pending() == []
    with pytest.raises(trust.PairingError, match="unavailable"):
        service.poll(request["request_id"], credential)
    secret, _ = service.invitation(ttl_seconds=1)
    clock["mono"] += 1
    with pytest.raises(trust.PairingError, match="expired"):
        service.request(secret, credential, "Desk")


def test_invitation_concurrent_consumption_approves_only_one(tmp_path):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    secret, _ = service.invitation()

    def consume(_index):
        try:
            return service.request(secret, secrets.token_urlsafe(32), "Desk")
        except trust.PairingError:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(consume, range(12)))
    assert sum(response is not None for response in responses) == 1
    assert len(service.pending()) == 1


def test_pending_capacity_rejection_and_explicit_cancel(paired, tmp_path):
    server, service, credentials, endpoint = paired
    client = transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
    response = client.begin(server.invitation(), label="Desk", verified_fingerprint=endpoint.fingerprint)
    service.reject(response["request_id"])
    with pytest.raises(trust.PairingError, match="refused"):
        client.poll()
    client.cancel_pending()
    for _ in range(trust.MAX_PENDING):
        secret, _ = service.invitation()
        service.request(secret, secrets.token_urlsafe(32), "Desk")
    secret, _ = service.invitation()
    with pytest.raises(trust.PairingError, match="Too many"):
        service.request(secret, secrets.token_urlsafe(32), "Desk")
    assert len(service.pending()) == trust.MAX_PENDING
    service.close()
    assert service.pending() == []


def test_cross_instance_revocation_is_never_resurrected(tmp_path):
    path = tmp_path / "trust.json"
    first, second = trust.TrustStore(path), trust.TrustStore(path)
    token = secrets.token_urlsafe(32)
    first.approve("a" * 32, "Desk", trust.token_digest(token, "a" * 32), now=time.time())
    assert second.authenticates("a" * 32, token)
    first.revoke("a" * 32)
    assert not second.authenticates("a" * 32, token)
    second.approve("b" * 32, "Other", trust.token_digest(secrets.token_urlsafe(32), "b" * 32), now=time.time())
    assert not trust.TrustStore(path).authenticates("a" * 32, token)


def test_atomic_failure_keeps_existing_trust_and_process_lock_is_nonblocking(tmp_path, monkeypatch):
    path = tmp_path / "trust.json"
    store = trust.TrustStore(path)
    token = secrets.token_urlsafe(32)
    store.approve("a" * 32, "Desk", trust.token_digest(token, "a" * 32), now=time.time())
    saved = path.read_bytes()
    with trust._state_lock(path), pytest.raises(trust.PairingError, match="busy"):
        store.revoke("a" * 32)
    monkeypatch.setattr(trust.os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(trust.PairingError, match="preserved"):
        store.revoke("a" * 32)
    assert path.read_bytes() == saved
    assert store.authenticates("a" * 32, token)
    assert not list(tmp_path.glob(".paired-state-*"))


@pytest.mark.parametrize("payload", [b'{"a":1,"a":2}', b'{"outer":{"a":1,"a":2}}',
                                      b'{"number":NaN}', b'{"number":Infinity}', b"[" * 17 + b"]" * 17],
                         ids=["duplicate", "nested-duplicate", "nan", "infinite", "depth"])
def test_strict_json_rejects_ambiguous_or_unbounded_values(payload):
    with pytest.raises(trust.PairingError, match="structured"):
        trust.strict_json(payload)


@pytest.mark.parametrize("field,value", [("state", []), ("source", {}), ("position_seconds", 10**3900),
                                         ("duration_seconds", float("nan")), ("finite", 1), ("title", []),
                                         ("schema_version", True), ("position_seconds", -1)])
def test_companion_response_schema_is_fail_closed(tmp_path, field, value):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    payload = dict(service._status)
    payload[field] = value
    with pytest.raises(trust.PairingError):
        trust.companion_status(payload)


@pytest.mark.parametrize("address", ["0.0.0.0", "8.8.8.8", "169.254.169.254", "localhost", "::1", "fe80::1", 167772161])
def test_listener_requires_explicit_private_ipv4(address):
    with pytest.raises(trust.PairingError):
        transport.private_address(address)


@pytest.mark.parametrize("backend_name", ["null", "fail"])
def test_plain_or_unavailable_keyring_is_rejected(monkeypatch, backend_name):
    from importlib import import_module

    backend = import_module(f"keyring.backends.{backend_name}").Keyring()
    monkeypatch.setattr(trust.CredentialStore, "_keyring", lambda: (SimpleNamespace(get_keyring=lambda: backend), Exception))
    with pytest.raises(trust.PairingError, match="credential store"):
        trust.KeyringPairingSecrets().set("server-key/" + "a" * 32, "secret")


def test_protected_backend_selection_ignores_environment_and_rejects_chain_fallback(monkeypatch):
    from keyring.backends.chainer import ChainerBackend
    from keyring.backends.Windows import WinVaultKeyring

    backend = WinVaultKeyring()
    calls = []
    values = {}
    monkeypatch.setattr(trust.sys, "platform", "win32")
    monkeypatch.setattr(backend, "get_password", lambda service, reference: values.get((service, reference)))
    monkeypatch.setattr(backend, "set_password", lambda service, reference, value: (
        calls.append((service, reference)), values.__setitem__((service, reference), value)))
    monkeypatch.setattr(backend, "delete_password", lambda service, reference: values.pop((service, reference)))
    monkeypatch.setattr(trust.CredentialStore, "_keyring", lambda: (SimpleNamespace(get_keyring=lambda: backend), Exception))
    monkeypatch.setenv("MARIANA_ICECAST_PASSWORD_EXAMPLE", "environment-secret")
    store = trust.KeyringPairingSecrets()
    assert store.get("example") is None
    store.set("example", "protected-secret")
    assert store.get("example") == "protected-secret"
    assert calls == [(trust.SERVICE_NAME, "example")]
    store.delete("example")
    assert store.get("example") is None
    chain = ChainerBackend()
    monkeypatch.setattr(ChainerBackend, "backends", [backend, SimpleNamespace(priority=100)])
    monkeypatch.setattr(trust.CredentialStore, "_keyring", lambda: (SimpleNamespace(get_keyring=lambda: chain), Exception))
    with pytest.raises(trust.PairingError):
        trust.KeyringPairingSecrets().set("example", "must-not-fallback")
    assert calls == [(trust.SERVICE_NAME, "example")]


def test_missing_protected_store_refuses_provisioning_without_key_file(tmp_path):
    class Unavailable(MemorySecrets):
        def set(self, reference, value):
            raise trust.PairingError("Protected store unavailable")

    server = transport.PairedServer(trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json")),
                                   tmp_path / "identity.json", credentials=Unavailable())
    with pytest.raises(trust.PairingError, match="unavailable"):
        server.start("127.0.0.1")
    assert not server.running and not (tmp_path / "identity.json").exists()


@pytest.mark.parametrize("headers,body", [
    (b"Content-Length: 0\r\nContent-Length: 0", b""),
    (b"Transfer-Encoding: chunked", b""),
    (b"Content-Length: 4097", b""),
    (b"Content-Length: 0", b"pipelined"),
    (b"X-Large: " + b"x" * transport.MAX_HEADERS, b""),
])
def test_bounded_http_rejects_ambiguous_headers_and_oversized_inputs(headers, body):
    class Input:
        def __init__(self, value):
            self.value = value

        def settimeout(self, _timeout):
            pass

        def recv(self, length):
            result, self.value = self.value[:length], self.value[length:]
            return result

    stream = Input(b"POST /v1/pairing HTTP/1.1\r\n" + headers + b"\r\n\r\n" + body)
    with pytest.raises(trust.PairingError):
        transport._receive(cast(socket.socket, stream))


def test_tls_rejects_control_origin_and_duplicate_json_without_consuming_invitation(paired):
    server, service, _credentials, endpoint = paired
    invitation = server.invitation()
    credential = secrets.token_urlsafe(32)
    body = json.dumps({"invitation": invitation["secret"], "credential": credential, "label": "Desk"}).encode()
    duplicate = body[:-1] + b',"label":"Different"}'
    headers = {"host": f"{endpoint.address}:{endpoint.port}", "content-type": "application/json"}
    with pytest.raises(trust.PairingError, match="Invalid pairing"):
        server._route("POST /v1/pairing HTTP/1.1", headers, duplicate)
    with pytest.raises(trust.PairingError, match="origin"):
        server._route("POST /v1/pairing HTTP/1.1", {**headers, "origin": "https://example.invalid"}, body)
    with pytest.raises(trust.PairingError, match="read-only"):
        server._route("POST /v1/play HTTP/1.1", {**headers, "authorization": f"Bearer {credential}"}, b"")
    assert service.pending() == []
    result = server._route("POST /v1/pairing HTTP/1.1", headers, body)
    assert result["proof"] == trust.token_digest(credential, result["request_id"])[:16]


def test_shutdown_bounds_open_tls_handshakes_and_releases_all_workers(paired):
    server, _service, _credentials, endpoint = paired
    clients = [socket.create_connection((endpoint.address, endpoint.port), timeout=1) for _ in range(8)]
    try:
        deadline = time.monotonic() + 1
        while len(server._workers) < transport.MAX_CONNECTIONS and time.monotonic() < deadline:
            time.sleep(0.005)
        assert len(server._workers) <= transport.MAX_CONNECTIONS
        workers = list(server._workers)
        started = time.monotonic()
        server.close()
        assert time.monotonic() - started < 3.5
        assert not server.running and not server._workers and not server._clients
        assert all(not worker.is_alive() for worker in workers)
    finally:
        for client in clients:
            client.close()


def test_listener_thread_failure_rolls_back_socket(paired, monkeypatch):
    server, _service, _credentials, endpoint = paired
    server.close()
    monkeypatch.setattr(threading.Thread, "start", lambda _s: (_ for _ in ()).throw(RuntimeError("exhausted")))
    with pytest.raises(trust.PairingError, match="could not start"):
        server.start(endpoint.address, port=endpoint.port)
    assert not server.running and not server._workers
    server.close()


def test_tls_context_requires_verified_name_date_and_exact_certificate(paired):
    _server, _service, _credentials, endpoint = paired
    context = endpoint.context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2
    assert len(context.get_ca_certs(binary_form=True)) == 0  # Pinned server is deliberately not a CA.
    assert type(context).__module__ == "mariana._paired_standard_ssl"
    assert ssl.SSLContext.__module__ == "truststore._api"


@pytest.mark.parametrize("value", [True, 0, -1, 301, 1.5])
def test_invalid_invitation_duration_is_rejected(tmp_path, value):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    with pytest.raises(trust.PairingError):
        service.invitation(ttl_seconds=value)


def test_duplicate_or_privilege_expanded_stored_state_is_not_replaced(tmp_path):
    path = tmp_path / "trust.json"
    duplicate = b'{"schema_version":1,"devices":{},"devices":{}}'
    path.write_bytes(duplicate)
    with pytest.raises(trust.PairingError):
        trust.TrustStore(path)
    assert path.read_bytes() == duplicate
    malicious = {"schema_version": trust.TRUST_SCHEMA_VERSION, "devices": {"a" * 32: {
        "label": "Desk", "digest": "b" * 64, "permissions": ["status.read", "playback.control"],
        "paired_at": time.time(), "revoked": False,
    }}}
    path.write_text(json.dumps(malicious))
    with pytest.raises(trust.PairingError):
        trust.TrustStore(path)
    assert json.loads(path.read_text()) == malicious


def test_same_server_can_stop_and_restart_existing_pair_without_new_invitation(paired, tmp_path):
    server, service, credentials, endpoint = paired
    client, _ = connect(server, service, credentials, tmp_path / "peer.json")
    server.close()
    assert service._closed.is_set()
    reopened = server.start(endpoint.address, port=endpoint.port)
    assert reopened.fingerprint == endpoint.fingerprint
    assert client.status()["state"] == "idle"
    assert service.pending() == []


def test_service_shutdown_does_not_wait_for_busy_approval_lock(tmp_path):
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    acquired, release = threading.Event(), threading.Event()

    def hold():
        with service._lock:
            acquired.set()
            release.wait(timeout=3)

    worker = threading.Thread(target=hold)
    worker.start()
    assert acquired.wait(timeout=1)
    try:
        started = time.monotonic()
        service.close()
        assert time.monotonic() - started < 0.2
    finally:
        release.set()
        worker.join(timeout=1)
    assert service.pending() == []
    with pytest.raises(trust.PairingError, match="stopped"):
        service.approve("a" * 32, verified_proof="b" * 16)


def test_client_expired_attempt_can_be_replaced_without_restarting(paired, tmp_path):
    server, _service, credentials, endpoint = paired
    client = transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
    old = client.begin(server.invitation(), label="Desk", verified_fingerprint=endpoint.fingerprint)
    client._pending_deadline = 0
    new = client.begin(server.invitation(), label="Desk", verified_fingerprint=endpoint.fingerprint)
    assert old["request_id"] != new["request_id"]
    assert not (tmp_path / "peer.json").exists()


@pytest.mark.parametrize("response", [
    {"state": [], "device_id": None, "permissions": []},
    {"state": "pending", "device_id": None, "permissions": ["playback.control"]},
    {"state": "approved", "device_id": "f" * 32, "permissions": ["status.read"]},
    {"state": "approved", "device_id": "a" * 32, "permissions": ["status.read", "files.read"]},
    {"state": "pending", "device_id": None, "permissions": [], "private_path": "/home/secret"},
])
def test_client_rejects_unexpected_approval_state_without_persisting(tmp_path, paired, monkeypatch, response):
    _server, _service, credentials, endpoint = paired
    client = transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
    client._pending = (endpoint, "a" * 32, secrets.token_urlsafe(32))
    client._pending_deadline = time.monotonic() + 300
    before = dict(credentials.values)
    monkeypatch.setattr(client, "_call", lambda *_a, **_k: response)
    with pytest.raises(trust.PairingError):
        client.poll()
    assert credentials.values == before and not (tmp_path / "peer.json").exists()


def test_failed_client_persistence_does_not_leave_or_overwrite_credential(paired, tmp_path, monkeypatch):
    server, service, credentials, endpoint = paired
    client = transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
    response = client.begin(server.invitation(), label="Desk", verified_fingerprint=endpoint.fingerprint)
    service.approve(response["request_id"], verified_proof=response["proof"])
    before = dict(credentials.values)
    monkeypatch.setattr(transport, "_atomic_document", lambda *_a: (_ for _ in ()).throw(trust.PairingError("disk")))
    with pytest.raises(trust.PairingError, match="disk"):
        client.poll()
    assert credentials.values == before and not (tmp_path / "peer.json").exists()
    assert client._pending is not None


def test_wrong_key_passphrase_refuses_without_replacing_identity(paired, tmp_path):
    _server, _service, credentials, _endpoint = paired
    path = tmp_path / "identity.json"
    original = path.read_bytes()
    reference = json.loads(original)["key_reference"]
    credentials.values[reference] = "wrong-passphrase"
    with pytest.raises(trust.PairingError, match="could not be loaded"):
        trust.server_identity(path, credentials)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".paired-tls-*"))


def test_unexpected_worker_start_failure_does_not_leak_connection_slot(paired, monkeypatch):
    server, _service, _credentials, endpoint = paired
    original = threading.Thread.start

    def start(worker):
        if worker.name == "mariana-paired-request":
            raise RuntimeError("exhausted")
        original(worker)

    monkeypatch.setattr(threading.Thread, "start", start)
    with socket.create_connection((endpoint.address, endpoint.port), timeout=1) as connection:
        connection.settimeout(1)
        assert connection.recv(1) == b""
    assert server.running and not server._workers and not server._clients
    assert all(server._slots.acquire(blocking=False) for _ in range(transport.MAX_CONNECTIONS))
    for _ in range(transport.MAX_CONNECTIONS):
        server._slots.release()


def test_expired_certificate_requires_explicit_renewal(paired, tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    _server, _service, credentials, _endpoint = paired
    path = tmp_path / "identity.json"
    saved = path.read_bytes()

    class FutureDatetime:
        @staticmethod
        def now(_zone):
            return datetime.now(UTC) + timedelta(days=367)

    monkeypatch.setattr(trust, "datetime", FutureDatetime)
    with pytest.raises(trust.PairingError, match="renewal"):
        trust.server_identity(path, credentials)
    assert path.read_bytes() == saved


def test_device_capacity_does_not_evict_existing_trust(tmp_path, monkeypatch):
    monkeypatch.setattr(trust, "MAX_DEVICES", 1)
    store = trust.TrustStore(tmp_path / "trust.json")
    credential = secrets.token_urlsafe(32)
    store.approve("a" * 32, "Desk", trust.token_digest(credential, "a" * 32), now=time.time())
    with pytest.raises(trust.PairingError, match="capacity"):
        store.approve("b" * 32, "Other", trust.token_digest(secrets.token_urlsafe(32), "b" * 32), now=time.time())
    assert store.authenticates("a" * 32, credential)
    assert len(store.devices()) == 1


def test_literal_brackets_and_escaped_quotes_in_json_are_not_nesting():
    payload = {"label": "brackets " + "[" * 30 + ' "quoted" ' + "}" * 30}
    assert trust.strict_json(json.dumps(payload).encode()) == payload


def test_pinned_tls_loader_failure_is_closed_and_does_not_change_global_https(monkeypatch):
    injected = ssl.SSLContext
    monkeypatch.setattr(trust, "_TLS_MODULE", None)
    monkeypatch.setattr(ssl, "__spec__", SimpleNamespace(loader=SimpleNamespace(get_code=lambda _name: None)))
    with pytest.raises(trust.PairingError, match="runtime is unavailable"):
        trust.pinned_tls_context(ssl.PROTOCOL_TLS_CLIENT)
    assert ssl.SSLContext is injected


def test_actual_application_initialization_retains_independent_pinned_tls(paired, tmp_path):
    import main

    server, service, credentials, _endpoint = paired
    assert main.SYSTEM_TRUST_STORE_ENABLED
    client, _ = connect(server, service, credentials, tmp_path / "application-peer.json")
    assert client.status()["state"] == "idle"
    assert ssl.SSLContext.__module__ == "truststore._api"


def test_close_reports_stalled_request_worker_and_can_finish_later(paired, monkeypatch):
    server, service, _credentials, endpoint = paired
    entered, release = threading.Event(), threading.Event()
    original = server._route

    def stalled(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)

    monkeypatch.setattr(server, "_route", stalled)
    with socket.create_connection((endpoint.address, endpoint.port), timeout=2) as connection, \
            endpoint.context().wrap_socket(connection, server_hostname=trust.TLS_NAME) as secure:
        secure.sendall((f"GET /v1/status HTTP/1.1\r\nHost: {endpoint.address}:{endpoint.port}\r\n"
                        "Content-Length: 0\r\n\r\n").encode())
        assert entered.wait(2)
        try:
            started = time.monotonic()
            assert server.close() is False
            assert time.monotonic() - started < 3.5
            assert service._closed.is_set() and not server.running
            assert any(worker.is_alive() for worker in server._workers)
        finally:
            release.set()
    assert server.close() is True
    assert not server._workers and not server._clients
