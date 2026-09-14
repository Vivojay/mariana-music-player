"""Fail-closed persisted trust and bounded companion transport behavior."""

from __future__ import annotations

import io
import json
import secrets
import socket
import stat
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from mariana import paired_transport as transport
from mariana import paired_trust as trust


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
def endpoint(tmp_path):
    credentials = MemorySecrets()
    identity = trust.server_identity(tmp_path / "identity.json", credentials)
    return transport.PinnedEndpoint("127.0.0.1", 12345, identity.certificate, identity.fingerprint), credentials


def saved_client(tmp_path, endpoint, credentials):
    identifier, token = "a" * 32, secrets.token_urlsafe(32)
    reference = f"peer-token/{endpoint.fingerprint}/{identifier}"
    document = {"schema_version": 1, "endpoint": endpoint.to_dict(), "device_id": identifier,
                "credential_reference": reference}
    path = tmp_path / "peer.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    credentials.set(reference, token)
    return transport.PairedClient(path, credentials=credentials), document, token


@pytest.mark.parametrize("field,value", [
    ("label", "Device\nInjected"), ("digest", "not-a-digest"), ("permissions", []),
    ("permissions", ["files.read"]), ("paired_at", True), ("paired_at", 0),
    ("paired_at", "yesterday"), ("revoked", 0),
])
def test_corrupt_persisted_device_never_uses_cached_authorization(tmp_path, field, value):
    path = tmp_path / "trust.json"
    store = trust.TrustStore(path)
    token = secrets.token_urlsafe(32)
    store.approve("a" * 32, "Listening room", trust.token_digest(token), now=time.time())
    assert store.authenticates("a" * 32, token)
    document = json.loads(path.read_text(encoding="utf-8"))
    document["devices"]["a" * 32][field] = value
    tampered = json.dumps(document).encode()
    path.write_bytes(tampered)
    for operation in (lambda: store.authenticates("a" * 32, token), store.devices,
                      lambda: store.approve("b" * 32, "Another", "c" * 64, now=time.time())):
        with pytest.raises(trust.PairingError):
            operation()
        assert path.read_bytes() == tampered


@pytest.mark.parametrize("payload", [
    b"\xff", b"[]", b'{"schema_version":true,"devices":{}}',
    b'{"schema_version":1,"devices":{},"unknown":"secret"}',
    b'{"schema_version":1,"devices":[]}', b"x" * (trust.MAX_STATE_BYTES + 1),
], ids=["invalid-utf8", "wrong-root", "boolean-version", "unknown-field", "wrong-devices", "oversized"])
def test_unreadable_or_wrong_shape_state_is_not_replaced(tmp_path, payload):
    path = tmp_path / "trust.json"
    path.write_bytes(payload)
    with pytest.raises(trust.PairingError) as caught:
        trust.TrustStore(path)
    assert path.read_bytes() == payload
    assert "secret" not in str(caught.value) and str(path) not in str(caught.value)
    assert not list(tmp_path.glob(".paired-state-*"))


def test_removed_trust_file_revokes_cached_access_without_recreating_state(tmp_path):
    path = tmp_path / "trust.json"
    store = trust.TrustStore(path)
    token = secrets.token_urlsafe(32)
    store.approve("a" * 32, "Listening room", trust.token_digest(token), now=time.time())
    path.unlink()
    assert not store.authenticates("a" * 32, token)
    assert store.devices() == [] and not path.exists()


def test_document_read_rejects_nonregular_before_open(tmp_path, monkeypatch):
    path = tmp_path / "invitation.json"
    original_stat, original_open = Path.stat, Path.open
    opened = []

    def details(candidate, *args, **kwargs):
        if candidate == path:
            return SimpleNamespace(st_mode=stat.S_IFIFO, st_size=0, st_dev=1, st_ino=1)
        return original_stat(candidate, *args, **kwargs)

    def read(candidate, *args, **kwargs):
        if candidate == path:
            opened.append(candidate)
            return io.BytesIO(b'{"schema_version":1}')
        return original_open(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", details)
    monkeypatch.setattr(Path, "open", read)
    monkeypatch.setattr(trust.os, "open", lambda *_args, **_kwargs: pytest.fail("Opened a nonregular file"))
    with pytest.raises(trust.PairingError, match="invalid"):
        trust._read_document(path)
    assert opened == []


@pytest.mark.parametrize("changed", ["type", "identity", "size"])
def test_document_read_validates_and_closes_opened_descriptor(tmp_path, monkeypatch, changed):
    path = tmp_path / "invitation.json"
    path.write_bytes(b'{"schema_version":1}')
    original = trust.os.fstat
    descriptors = []

    def changed_details(descriptor):
        descriptors.append(descriptor)
        details = original(descriptor)
        return SimpleNamespace(st_mode=stat.S_IFIFO if changed == "type" else details.st_mode,
                               st_size=trust.MAX_STATE_BYTES + 1 if changed == "size" else details.st_size,
                               st_dev=details.st_dev,
                               st_ino=details.st_ino + 1 if changed == "identity" else details.st_ino)

    monkeypatch.setattr(trust.os, "fstat", changed_details)
    monkeypatch.setattr(trust.os, "fdopen", lambda *_args, **_kwargs: pytest.fail("Read an unverified descriptor"))
    with pytest.raises(trust.PairingError, match="invalid"):
        trust._read_document(path)
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        original(descriptors[0])


def test_document_read_uses_verified_descriptor_without_reopening_path(tmp_path, monkeypatch):
    path = tmp_path / "invitation.json"
    expected = {"schema_version": 1, "label": "Listening room"}
    path.write_text(json.dumps(expected), encoding="utf-8")
    original = trust.os.open
    flags = []

    def opened(candidate, mode):
        flags.append(mode)
        return original(candidate, mode)

    monkeypatch.setattr(trust.os, "open", opened)
    monkeypatch.setattr(Path, "open", lambda *_args, **_kwargs: pytest.fail("Reopened the document path"))
    assert trust._read_document(path) == expected
    assert len(flags) == 1
    for name in ("O_BINARY", "O_NOFOLLOW", "O_NONBLOCK"):
        required = getattr(trust.os, name, 0)
        assert flags[0] & required == required


@pytest.mark.parametrize("change", ["device", "reference", "endpoint", "extra", "missing"])
def test_tampered_client_state_refuses_before_secret_access(tmp_path, endpoint, change):
    peer, credentials = endpoint
    client, document, _token = saved_client(tmp_path, peer, credentials)
    if change == "device":
        document["device_id"] = "b" * 32
    elif change == "reference":
        document["credential_reference"] = "server-key/" + "a" * 32
    elif change == "endpoint":
        document["endpoint"]["fingerprint"] = "0" * 64
    elif change == "extra":
        document["private_path"] = "/private/location"
    else:
        del document["credential_reference"]
    tampered = json.dumps(document).encode()
    client.path.write_bytes(tampered)
    before = dict(credentials.values)
    credentials.calls.clear()
    with pytest.raises(trust.PairingError):
        transport.PairedClient(client.path, credentials=credentials)
    assert credentials.calls == [] and credentials.values == before
    assert client.path.read_bytes() == tampered


@pytest.mark.parametrize("changed", ["replacement", "missing", "corrupt"])
def test_disconnect_preserves_replaced_state_and_all_credentials(tmp_path, endpoint, changed):
    peer, credentials = endpoint
    client, document, _token = saved_client(tmp_path, peer, credentials)
    credentials.set("unrelated", "must remain")
    before = dict(credentials.values)
    if changed == "missing":
        client.path.unlink()
        expected = None
    else:
        document["device_id"] = "b" * 32
        expected = json.dumps(document).encode() if changed == "replacement" else b"corrupt"
        client.path.write_bytes(expected)
    credentials.calls.clear()
    with pytest.raises(trust.PairingError):
        client.disconnect()
    assert credentials.values == before and credentials.calls == []
    assert client._state is not None
    assert (client.path.read_bytes() if client.path.exists() else None) == expected


def test_missing_or_malformed_saved_credential_never_connects(tmp_path, endpoint, monkeypatch):
    peer, credentials = endpoint
    client, document, _token = saved_client(tmp_path, peer, credentials)
    monkeypatch.setattr(transport.socket, "create_connection", lambda *_args, **_kwargs: pytest.fail("No valid credential"))
    for value in (None, "", "bad-token", 123):
        credentials.values[document["credential_reference"]] = value
        with pytest.raises(trust.PairingError):
            client.status()
    assert json.loads(client.path.read_text()) == document


def test_disconnect_secret_removal_failure_preserves_saved_metadata(tmp_path, endpoint, monkeypatch):
    peer, credentials = endpoint
    client, _document, _token = saved_client(tmp_path, peer, credentials)
    before = client.path.read_bytes(), dict(credentials.values)

    def failed(_reference):
        raise trust.PairingError("Protected store rejected removal")

    monkeypatch.setattr(credentials, "delete", failed)
    with pytest.raises(trust.PairingError, match="rejected removal"):
        client.disconnect()
    assert client.path.read_bytes() == before[0] and credentials.values == before[1]
    assert client._state is not None


@pytest.mark.parametrize("response_change", ["proof", "expiry", "identifier", "extra"])
def test_pairing_response_cannot_create_pending_state_with_changed_proof_or_expiry(tmp_path, endpoint, monkeypatch, response_change):
    peer, credentials = endpoint
    client = transport.PairedClient(tmp_path / "peer.json", credentials=credentials)
    expires = time.time() + 120
    invitation = {"schema_version": 1, "endpoint": peer.to_dict(), "secret": secrets.token_urlsafe(32),
                  "expires_at": expires}

    def reply(_endpoint, _method, _path, *, payload):
        response = {"request_id": "a" * 32, "expires_at": expires, "proof": trust.token_digest(payload["credential"])[:16]}
        if response_change == "proof":
            response["proof"] = "wrong"
        elif response_change == "expiry":
            response["expires_at"] = expires + 600
        elif response_change == "identifier":
            response["request_id"] = "../other"
        else:
            response["permissions"] = ["files.read"]
        return response

    before = dict(credentials.values)
    monkeypatch.setattr(client, "_call", reply)
    with pytest.raises(trust.PairingError, match="verification response"):
        client.begin(invitation, label="Listening room", verified_fingerprint=peer.fingerprint)
    assert client._pending is None and client._state is None
    assert credentials.values == before and not client.path.exists()


def test_approval_does_not_replace_connection_saved_by_another_client(tmp_path, endpoint, monkeypatch):
    peer, credentials = endpoint
    path = tmp_path / "peer.json"
    pending = transport.PairedClient(path, credentials=credentials)
    pending._pending = (peer, "b" * 32, secrets.token_urlsafe(32))
    pending._pending_deadline = time.monotonic() + 120
    existing, _document, _token = saved_client(tmp_path, peer, credentials)
    before = path.read_bytes(), dict(credentials.values)
    monkeypatch.setattr(pending, "_call", lambda *_args, **_kwargs: {
        "state": "approved", "device_id": "b" * 32, "permissions": ["status.read"],
    })
    with pytest.raises(trust.PairingError, match="already exists"):
        pending.poll()
    assert path.read_bytes() == before[0] and credentials.values == before[1]
    assert pending._pending is not None and existing._state is not None


class FragmentedInput:
    def __init__(self, chunks, after_read=lambda: None):
        self.chunks = deque(chunks)
        self.after_read = after_read
        self.timeouts = []
        self.requested = []

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def recv(self, maximum):
        self.requested.append(maximum)
        value = self.chunks.popleft() if self.chunks else b""
        piece = value[:maximum]
        if len(value) > maximum:
            self.chunks.appendleft(value[maximum:])
        self.after_read()
        return piece


@pytest.mark.parametrize("payload", [
    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{",
    b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n",
    b"HTTP/1.1 200 OK\r\nX-Label: \xff\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nBroken header\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Length: +1\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Length: 1.0\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nX-Label: unsafe\0value\r\n\r\n",
])
def test_truncated_and_malformed_peer_framing_is_rejected(payload):
    stream = FragmentedInput([payload[:11], payload[11:]])
    with pytest.raises(trust.PairingError):
        transport._receive(cast(socket.socket, stream))
    assert all(0 < timeout <= 2 for timeout in stream.timeouts)
    assert max(stream.requested) <= transport.MAX_HEADERS


@pytest.mark.parametrize("phase", ["header", "body"])
def test_slow_peer_cannot_extend_total_receive_budget(monkeypatch, phase):
    clock = [0.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock[0])

    def elapsed():
        clock[0] += transport.REQUEST_SECONDS

    head = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n" if phase == "body" else b"HTTP/1.1 "
    stream = FragmentedInput([head, b"{}"], after_read=elapsed)
    with pytest.raises(trust.PairingError, match="time"):
        transport._receive(cast(socket.socket, stream))
    assert len(stream.requested) == 1 and list(stream.chunks) == [b"{}"]


def test_exact_body_limit_accepts_fragmented_json_and_bounds_each_read():
    payload = json.dumps({"value": "x" * (transport.MAX_BODY - len('{"value": ""}'))}).encode()
    assert len(payload) == transport.MAX_BODY
    head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(payload)}\r\n\r\n".encode()
    stream = FragmentedInput([head[:13], head[13:], payload[:300], payload[300:]])
    first, headers, body = transport._receive(cast(socket.socket, stream))
    assert first == "HTTP/1.1 200 OK" and headers["content-length"] == str(transport.MAX_BODY)
    assert body == payload and trust.strict_json(body)["value"].startswith("xxx")
    assert max(stream.requested) <= transport.MAX_BODY


@pytest.mark.parametrize("malformed", [b'\xff', b'{"label":1,"label":2}', b'[]'])
def test_real_tls_malformed_json_releases_worker_without_consuming_invitation(tmp_path, malformed):
    credentials = MemorySecrets()
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    server = transport.PairedServer(service, tmp_path / "identity.json", credentials=credentials)
    endpoint = server.start("127.0.0.1")
    try:
        invitation = server.invitation()
        with socket.create_connection((endpoint.address, endpoint.port), timeout=2) as connection, \
                endpoint.context().wrap_socket(connection, server_hostname=trust.TLS_NAME) as secure:
            head = (f"POST /v1/pairing HTTP/1.1\r\nHost: {endpoint.address}:{endpoint.port}\r\n"
                    f"Content-Length: {len(malformed)}\r\nContent-Type: application/json\r\n\r\n").encode()
            secure.sendall(head + malformed)
            first, _headers, body = transport._receive(secure)
            assert first == "HTTP/1.1 403 Forbidden"
            assert trust.strict_json(body) == {"error": "Invalid pairing request"}
        assert service.pending() == []
        token = secrets.token_urlsafe(32)
        result = transport.PairedClient._call(endpoint, "POST", "/v1/pairing", payload={
            "invitation": invitation["secret"], "credential": token, "label": "Valid device",
        })
        assert result["proof"] == trust.token_digest(token)[:16]
        assert len(service.pending()) == 1 and service.trust.devices() == []
    finally:
        server.close()
    assert not server.running and not server._workers and not server._clients
    assert not list(tmp_path.glob(".paired-tls-*"))
