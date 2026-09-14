"""Opt-in pinned TLS transport for one read-only paired-desktop contract."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import re
import secrets
import socket
import ssl
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paired_trust import (
    DIGEST,
    IDENTIFIER,
    SCHEMA_VERSION,
    TLS_NAME,
    KeyringPairingSecrets,
    PairedReadOnlyService,
    PairingError,
    PairingSecrets,
    ServerIdentity,
    _atomic_document,
    _read_document,
    _state_lock,
    companion_status,
    device_label,
    pinned_tls_context,
    server_identity,
    strict_json,
    token_digest,
    validate_token,
)

MAX_HEADERS = 8192
MAX_BODY = 4096
REQUEST_SECONDS = 5.0
MAX_CONNECTIONS = 4
_LOCAL_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8",
))


def private_address(value: str) -> str:
    if not isinstance(value, str):
        raise PairingError("Choose an explicit local private IPv4 address")
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        raise PairingError("Choose an explicit local private IPv4 address") from None
    if not isinstance(address, ipaddress.IPv4Address) or not any(address in network for network in _LOCAL_NETWORKS):
        raise PairingError("Pairing is limited to private IPv4 interfaces or loopback")
    return str(address)


def _receive(connection: socket.socket, *, maximum_body: int = MAX_BODY) -> tuple[str, dict[str, str], bytes]:
    deadline = time.monotonic() + REQUEST_SECONDS
    payload = bytearray()
    while b"\r\n\r\n" not in payload:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or len(payload) >= MAX_HEADERS:
            raise PairingError("Request headers exceed their time or size limit")
        connection.settimeout(min(2.0, remaining))
        chunk = connection.recv(min(1024, MAX_HEADERS - len(payload)))
        if not chunk:
            raise PairingError("Incomplete request")
        payload.extend(chunk)
    raw_head, body = payload.split(b"\r\n\r\n", 1)
    try:
        lines = raw_head.decode("ascii").split("\r\n")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            key, value = line.split(":", 1)
            key = key.lower()
            if not re.fullmatch(r"[a-z0-9-]+", key) or key in headers or any(ord(c) < 32 for c in value):
                raise ValueError
            headers[key] = value.strip()
        length_text = headers.get("content-length", "0")
        if not re.fullmatch(r"[0-9]{1,5}", length_text) or "transfer-encoding" in headers:
            raise ValueError
        length = int(length_text)
        if length > maximum_body or len(body) > length:
            raise ValueError
    except (ValueError, UnicodeError):
        raise PairingError("Invalid bounded request") from None
    while len(body) < length:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PairingError("Request body exceeded its time limit")
        connection.settimeout(min(2.0, remaining))
        chunk = connection.recv(length - len(body))
        if not chunk:
            raise PairingError("Incomplete request body")
        body.extend(chunk)
    return lines[0], headers, bytes(body)


@dataclass(frozen=True, slots=True)
class PinnedEndpoint:
    address: str
    port: int
    certificate: str
    fingerprint: str

    def __post_init__(self) -> None:
        private_address(self.address)
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise PairingError("Invalid pairing port")
        if not isinstance(self.certificate, str) or len(self.certificate) > 8192 \
                or not isinstance(self.fingerprint, str) or not DIGEST.fullmatch(self.fingerprint):
            raise PairingError("Invalid pairing certificate")
        try:
            actual = hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.certificate)).hexdigest()
        except (ValueError, UnicodeError):
            raise PairingError("Invalid pairing certificate") from None
        if not hmac.compare_digest(actual, self.fingerprint):
            raise PairingError("Pairing certificate does not match its fingerprint")

    def context(self) -> ssl.SSLContext:
        # No system CA fallback and no CERT_NONE: the explicitly verified server
        # certificate is the sole trust anchor, with normal time/name validation.
        context = pinned_tls_context(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=self.certificate)
        return context

    def to_dict(self) -> dict[str, Any]:
        return {"address": self.address, "port": self.port, "certificate": self.certificate,
                "fingerprint": self.fingerprint}

    @classmethod
    def from_dict(cls, value: object) -> PinnedEndpoint:
        if not isinstance(value, dict) or set(value) != {"address", "port", "certificate", "fingerprint"}:
            raise PairingError("Invalid pairing endpoint")
        return cls(**value)


class PairedServer:
    """No sockets, threads or keyring access until start(address) is called."""

    def __init__(self, service: PairedReadOnlyService, identity_path: Path,
                 *, credentials: PairingSecrets | None = None) -> None:
        self.service = service
        self.identity_path = identity_path
        self.credentials = credentials or KeyringPairingSecrets()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._workers: set[threading.Thread] = set()
        self._clients: set[socket.socket] = set()
        self._identity: ServerIdentity | None = None
        self._endpoint: PinnedEndpoint | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._socket is not None and not self._stop.is_set()

    def start(self, address: str, *, port: int = 0) -> PinnedEndpoint:
        address = private_address(address)
        if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise PairingError("Invalid pairing port")
        with self._lock:
            if self._socket is not None or self._workers or (self._thread is not None and self._thread.is_alive()):
                raise PairingError("Paired listener is already running or shutting down")
            identity = server_identity(self.identity_path, self.credentials)
            connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                connection.bind((address, port))
                connection.listen(MAX_CONNECTIONS)
                connection.settimeout(0.2)
            except OSError:
                connection.close()
                raise PairingError("The selected local interface could not be opened") from None
            self._stop.clear()
            self.service.activate()
            self._identity = identity
            self._socket = connection
            self._endpoint = PinnedEndpoint(address, connection.getsockname()[1], identity.certificate, identity.fingerprint)
            self._thread = threading.Thread(target=self._accept, name="mariana-paired-listener", daemon=True)
            try:
                self._thread.start()
            except RuntimeError:
                self._stop.set()
                self._socket = self._thread = None
                connection.close()
                self.service.close()
                raise PairingError("The local paired listener could not start") from None
            return self._endpoint

    def invitation(self, *, ttl_seconds: int = 300) -> dict[str, Any]:
        with self._lock:
            if not self.running or self._endpoint is None:
                raise PairingError("Start the local paired listener before inviting a device")
            secret, expires = self.service.invitation(ttl_seconds=ttl_seconds)
            return {"schema_version": SCHEMA_VERSION, "endpoint": self._endpoint.to_dict(),
                    "secret": secret, "expires_at": expires}

    def _accept(self) -> None:
        while not self._stop.is_set():
            try:
                listener = self._socket
                if listener is None:
                    return
                connection, peer = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                private_address(peer[0])
            except PairingError:
                connection.close()
                continue
            if not self._slots.acquire(blocking=False):
                connection.close()
                continue
            with self._lock:
                if self._stop.is_set():
                    connection.close()
                    self._slots.release()
                    return
                self._clients.add(connection)
                worker = threading.Thread(target=self._serve, args=(connection,),
                                          name="mariana-paired-request", daemon=True)
                self._workers.add(worker)
                try:
                    worker.start()
                except RuntimeError:
                    self._workers.discard(worker)
                    self._clients.discard(connection)
                    connection.close()
                    self._slots.release()

    def _serve(self, connection: socket.socket) -> None:
        active = connection
        try:
            identity = self._identity
            if identity is None:
                return
            connection.settimeout(2)
            active = identity.context.wrap_socket(connection, server_side=True, do_handshake_on_connect=False)
            with self._lock:
                self._clients.discard(connection)
                self._clients.add(active)
                if self._stop.is_set():
                    return
            active.do_handshake()
            first, headers, body = _receive(active)
            try:
                result = self._route(first, headers, body)
                code = 200
            except PairingError as error:
                result, code = {"error": str(error)}, 403
            payload = json.dumps(result, ensure_ascii=True, allow_nan=False).encode("utf-8")
            if len(payload) > MAX_BODY:
                raise PairingError("Companion response exceeds its size limit")
            response = (f"HTTP/1.1 {code} {'OK' if code == 200 else 'Forbidden'}\r\n"
                        f"Content-Length: {len(payload)}\r\nContent-Type: application/json\r\n"
                        "Cache-Control: no-store\r\nConnection: close\r\n\r\n").encode("ascii")
            active.sendall(response + payload)
        except (OSError, ValueError, PairingError):
            # Peer data and TLS exceptions can contain credentials. There is no
            # raw request/exception logging path, and no playback error callback.
            pass
        finally:
            active.close()
            connection.close()
            with self._lock:
                self._clients.discard(active)
                self._clients.discard(connection)
                self._workers.discard(threading.current_thread())
            self._slots.release()

    def _route(self, first: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
        endpoint = self._endpoint
        if endpoint is None or headers.get("host") != f"{endpoint.address}:{endpoint.port}" or "origin" in headers:
            raise PairingError("Unexpected companion request origin")
        if first == "POST /v1/pairing HTTP/1.1":
            if headers.get("content-type") != "application/json":
                raise PairingError("Pairing requests require JSON")
            try:
                value = strict_json(body)
            except PairingError:
                raise PairingError("Invalid pairing request") from None
            if not isinstance(value, dict) or set(value) != {"invitation", "credential", "label"}:
                raise PairingError("Invalid pairing request")
            return self.service.request(value["invitation"], value["credential"], value["label"])
        if body or not headers.get("authorization", "").startswith("Bearer "):
            raise PairingError("A paired-device credential is required")
        credential = headers["authorization"][7:]
        if first == "GET /v1/status HTTP/1.1":
            return self.service.status(headers.get("x-mariana-device", ""), credential)
        match = re.fullmatch(r"GET /v1/pairing/([a-f0-9]{32}) HTTP/1.1", first)
        if match:
            return self.service.poll(match[1], credential)
        raise PairingError("This paired listener provides read-only status, not control or file access")

    def close(self) -> bool:
        """Stop authorization and sockets; report any workers still draining."""
        self._stop.set()
        with self._lock:
            listener, self._socket = self._socket, None
            clients, workers = list(self._clients), list(self._workers)
            listener_thread = self._thread
            self.service.close()
        if listener is not None:
            listener.close()
        for client in clients:
            with suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            client.close()
        deadline = time.monotonic() + 3
        joined = ([listener_thread] if listener_thread else []) + workers
        for worker in joined:
            if worker is not threading.current_thread():
                worker.join(timeout=max(0, deadline - time.monotonic()))
        with self._lock:
            return self._socket is None and not self._clients and not self._workers \
                and all(not worker.is_alive() for worker in joined)


class PairedClient:
    """Backend-side client. Tokens stay in the keyring, never in metadata files."""

    def __init__(self, state_path: Path, *, credentials: PairingSecrets | None = None) -> None:
        self.path = state_path
        self.credentials = credentials or KeyringPairingSecrets()
        self._pending: tuple[PinnedEndpoint, str, str] | None = None
        self._pending_deadline = 0.0
        self._state: dict[str, Any] | None = None
        if state_path.exists():
            state = _read_document(state_path, 16 * 1024)
            if set(state) != {"schema_version", "endpoint", "device_id", "credential_reference"} \
                    or not isinstance(state["device_id"], str) or not IDENTIFIER.fullmatch(state["device_id"]) \
                    or not isinstance(state["credential_reference"], str):
                raise PairingError("Stored companion connection is invalid")
            endpoint = PinnedEndpoint.from_dict(state["endpoint"])
            if state["credential_reference"] != f"peer-token/{endpoint.fingerprint}/{state['device_id']}":
                raise PairingError("Stored companion credential belongs to another server")
            self._state = state

    @staticmethod
    def _call(endpoint: PinnedEndpoint, method: str, path: str, *, payload: dict[str, Any] | None = None,
              credential: str | None = None, device_id: str | None = None) -> dict[str, Any]:
        if credential is not None:
            validate_token(credential)
        if device_id is not None and not IDENTIFIER.fullmatch(device_id):
            raise PairingError("Invalid paired-device identity")
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8") if payload is not None else b""
        if len(body) > MAX_BODY or method not in {"GET", "POST"} or not re.fullmatch(r"/v1/[a-z0-9/]+", path):
            raise PairingError("Invalid bounded companion operation")
        try:
            with socket.create_connection((endpoint.address, endpoint.port), timeout=2) as connection, \
                    endpoint.context().wrap_socket(connection, server_hostname=TLS_NAME) as secure:
                    actual = hashlib.sha256(secure.getpeercert(binary_form=True) or b"").hexdigest()
                    if not hmac.compare_digest(actual, endpoint.fingerprint):
                        raise PairingError("Server certificate changed; no credentials were sent")
                    headers = [f"{method} {path} HTTP/1.1", f"Host: {endpoint.address}:{endpoint.port}",
                               f"Content-Length: {len(body)}", "Connection: close", "Content-Type: application/json"]
                    if credential is not None:
                        headers.append(f"Authorization: Bearer {credential}")
                    if device_id is not None:
                        headers.append(f"X-Mariana-Device: {device_id}")
                    secure.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body)
                    first, response_headers, raw = _receive(secure)
                    if first != "HTTP/1.1 200 OK" or response_headers.get("content-type") != "application/json":
                        raise PairingError("Paired request was refused or its authorization expired")
                    value = strict_json(raw)
                    if not isinstance(value, dict):
                        raise PairingError("Invalid companion response")
                    return value
        except PairingError:
            raise
        except (OSError, ValueError):
            raise PairingError("The pinned companion connection could not be verified or completed") from None

    def begin(self, invitation: dict[str, Any], *, label: str, verified_fingerprint: str) -> dict[str, Any]:
        if self._pending is not None and self._pending_deadline <= time.monotonic():
            self.cancel_pending()
        if self._state is not None or self._pending is not None:
            raise PairingError("This companion connection already has a pairing identity")
        if not isinstance(invitation, dict) or set(invitation) != {"schema_version", "endpoint", "secret", "expires_at"} \
                or type(invitation["schema_version"]) is not int or invitation["schema_version"] != SCHEMA_VERSION:
            raise PairingError("Invalid pairing invitation")
        expiry = invitation["expires_at"]
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not 0 < expiry <= 1e12 \
                or not math.isfinite(expiry) \
                or not 0 < expiry - time.time() <= 305:
            raise PairingError("Pairing invitation is expired or outside its short validity window")
        deadline = time.monotonic() + min(300, expiry - time.time())
        endpoint = PinnedEndpoint.from_dict(invitation["endpoint"])
        if not isinstance(verified_fingerprint, str) or not DIGEST.fullmatch(verified_fingerprint) \
                or not hmac.compare_digest(endpoint.fingerprint, verified_fingerprint):
            raise PairingError("Explicit matching server-fingerprint verification is required")
        validate_token(invitation["secret"])
        credential = secrets.token_urlsafe(32)
        response = self._call(endpoint, "POST", "/v1/pairing", payload={
            "invitation": invitation["secret"], "credential": credential, "label": device_label(label),
        })
        identifier = response.get("request_id")
        if set(response) != {"request_id", "expires_at", "proof"} \
                or response["expires_at"] != expiry or not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) \
                or response.get("proof") != token_digest(credential, identifier)[:16]:
            raise PairingError("Unexpected pairing verification response")
        if time.monotonic() >= deadline or time.time() >= expiry:
            raise PairingError("Pairing invitation expired during device verification")
        self._pending = (endpoint, identifier, credential)
        self._pending_deadline = deadline
        return response

    def poll(self) -> dict[str, Any]:
        if self._pending is not None and self._pending_deadline <= time.monotonic():
            self.cancel_pending()
        if self._pending is None:
            raise PairingError("No pending companion request")
        endpoint, identifier, credential = self._pending
        response = self._call(endpoint, "GET", f"/v1/pairing/{identifier}", credential=credential)
        if set(response) != {"state", "device_id", "permissions"} or not isinstance(response["state"], str) \
                or response["state"] not in {"pending", "approved"} \
                or (response["state"] == "pending" and (response["device_id"] is not None or response["permissions"] != [])):
            raise PairingError("Unexpected companion approval response")
        if response.get("state") == "approved":
            if response.get("device_id") != identifier or response.get("permissions") != ["status.read"]:
                raise PairingError("Unexpected companion permissions")
            reference = f"peer-token/{endpoint.fingerprint}/{identifier}"
            state = {"schema_version": SCHEMA_VERSION, "endpoint": endpoint.to_dict(),
                     "device_id": identifier, "credential_reference": reference}
            with _state_lock(self.path):
                if self.path.exists():
                    raise PairingError("A saved companion connection already exists; it was not replaced")
                self.credentials.set(reference, credential)
                try:
                    _atomic_document(self.path, state)
                except PairingError:
                    self.credentials.delete(reference)
                    raise
            self._state, self._pending = state, None
        return response

    def cancel_pending(self) -> None:
        """Drop only this unpersisted client attempt; host request still expires."""
        self._pending = None
        self._pending_deadline = 0.0

    def disconnect(self) -> None:
        """Forget this client's saved credential, not host trust or other peers."""
        self.cancel_pending()
        if self._state is None:
            return
        with _state_lock(self.path):
            current = _read_document(self.path, 16 * 1024)
            if current != self._state:
                raise PairingError("Saved companion connection changed; it was not removed")
            self.credentials.delete(self._state["credential_reference"])
            self.path.unlink()
            self._state = None

    def status(self) -> dict[str, Any]:
        if self._state is None:
            raise PairingError("Pair this companion before requesting status")
        credential = self.credentials.get(self._state["credential_reference"])
        if not credential:
            raise PairingError("The companion credential is unavailable")
        return companion_status(self._call(PinnedEndpoint.from_dict(self._state["endpoint"]), "GET", "/v1/status",
                                           credential=credential, device_id=self._state["device_id"]))
