"""Explicit local desktop trust; no listener, cloud account, or playback control."""

from __future__ import annotations

import hashlib
import hmac
import importlib
import importlib.util
import json
import math
import os
import re
import secrets
import ssl
import stat
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import CodeType, ModuleType
from typing import Any, Protocol

from .credentials import CredentialStore
from .models import MediaSource, PlaybackSnapshot, PlaybackState
from .playback_status import _clean_display_text, project_playback_status

SCHEMA_VERSION = 1
SERVICE_NAME = "io.github.vivojay.mariana.paired-desktops"
TLS_NAME = "paired.mariana.local"
MAX_DEVICES = 32
MAX_PENDING = 8
MAX_STATE_BYTES = 128 * 1024
TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")
IDENTIFIER = re.compile(r"^[a-f0-9]{32}$")
DIGEST = re.compile(r"^[a-f0-9]{64}$")
_TLS_FACTORY_LOCK = threading.Lock()
_TLS_MODULE: ModuleType | None = None


class PairingError(RuntimeError):
    """A safe local pairing refusal, with no credentials or transport detail."""


def pinned_tls_context(protocol: int) -> ssl.SSLContext:
    """Use unmodified stdlib TLS without changing the application's HTTPS policy.

    System trust injection replaces ssl.SSLContext globally and verifies even
    an unhandshaken server socket. An independent namespace also keeps stdlib
    property globals intact; merely caching the original class is insufficient.
    Only the already-imported stdlib module's loader supplies code, never a path
    from an invitation, working directory, or user configuration.
    """
    global _TLS_MODULE
    with _TLS_FACTORY_LOCK:
        if _TLS_MODULE is None:
            name = "mariana._paired_standard_ssl"
            try:
                spec = ssl.__spec__
                loader = spec.loader if spec is not None else None
                get_code = getattr(loader, "get_code", None)
                if not callable(get_code):
                    raise ValueError
                code = get_code("ssl")
                if not isinstance(code, CodeType) or name in sys.modules:
                    raise ValueError
                module = ModuleType(name)
                module.__package__ = "mariana"
                module.__loader__ = loader
                module.__spec__ = importlib.util.spec_from_loader(name, loader)
                # Enum conversion in ssl requires its own registered namespace.
                sys.modules[name] = module
                try:
                    exec(code, module.__dict__)
                except Exception:
                    sys.modules.pop(name, None)
                    raise
                _TLS_MODULE = module
            except Exception:
                raise PairingError("The independent verified TLS runtime is unavailable") from None
        context = _TLS_MODULE.SSLContext(protocol)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


class PairingSecrets(Protocol):
    def get(self, reference: str) -> str | None: ...
    def set(self, reference: str, value: str) -> None: ...
    def delete(self, reference: str) -> None: ...


class KeyringPairingSecrets:
    """Reuse the OS keyring dependency, deliberately without environment overrides."""

    def __init__(self) -> None:
        self._selected: Any = None

    def _backend(self) -> Any:
        if self._selected is not None:
            return self._selected
        keyring, _ = CredentialStore._keyring()
        configured = keyring.get_keyring()
        supported = {
            "win32": (("keyring.backends.Windows", "WinVaultKeyring"),),
            "darwin": (("keyring.backends.macOS", "Keyring"),),
            "linux": (("keyring.backends.SecretService", "Keyring"),
                      ("keyring.backends.kwallet", "DBusKeyring")),
        }.get(sys.platform, ())

        def protected(backend: Any) -> bool:
            for module, name in supported:
                if type(backend).__module__ == module and type(backend).__name__ == name:
                    return type(backend) is getattr(importlib.import_module(module), name)
            return False

        from keyring.backends.chainer import ChainerBackend

        if type(configured) is ChainerBackend:
            children = list(configured.backends)
            if not children or not all(protected(child) for child in children):
                raise PairingError("Pairing requires a supported operating-system protected credential store")
            # Choose once, without calling the chain's fallback/search methods.
            configured = children[0]
        if not protected(configured):
            raise PairingError("Pairing requires a supported operating-system protected credential store")
        if sys.platform == "win32":
            protected_backend: Any = copy(configured)
            # CRED_PERSIST_LOCAL_MACHINE, not roaming enterprise persistence.
            protected_backend.persist = 2
            configured = protected_backend
        self._selected = configured
        return configured

    def get(self, reference: str) -> str | None:
        try:
            keyring = self._backend()
            return keyring.get_password(SERVICE_NAME, reference)
        except Exception:
            raise PairingError("The operating-system credential store is unavailable") from None

    def set(self, reference: str, value: str) -> None:
        if not value:
            raise PairingError("An empty pairing credential is not accepted")
        try:
            keyring = self._backend()
            keyring.set_password(SERVICE_NAME, reference, value)
            if keyring.get_password(SERVICE_NAME, reference) != value:
                raise PairingError("The credential was not retained")
        except Exception:
            raise PairingError("The operating-system credential store rejected the credential") from None

    def delete(self, reference: str) -> None:
        try:
            keyring = self._backend()
            if keyring.get_password(SERVICE_NAME, reference) is not None:
                keyring.delete_password(SERVICE_NAME, reference)
        except Exception:
            raise PairingError("The operating-system credential store rejected removal") from None


def token_digest(token: str) -> str:
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise PairingError("Invalid pairing credential")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def device_label(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80 or not value.isprintable():
        raise PairingError("Device name must contain 1 to 80 printable characters")
    return value.strip()


def strict_json(payload: bytes) -> Any:
    """Reject ambiguous keys and non-JSON numeric constants before authorization."""
    depth, quoted, escaped = 0, False, False
    for character in payload:
        if quoted:
            if escaped:
                escaped = False
            elif character == 92:
                escaped = True
            elif character == 34:
                quoted = False
        elif character == 34:
            quoted = True
        elif character in (91, 123):
            depth += 1
            if depth > 16:
                raise PairingError("Invalid structured pairing data")
        elif character in (93, 125):
            depth -= 1
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def invalid_constant(_value: str) -> None:
        raise ValueError("Non-finite JSON constant")

    try:
        return json.loads(payload, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (RecursionError, UnicodeError, ValueError):
        raise PairingError("Invalid structured pairing data") from None


def companion_status(value: object) -> dict[str, Any]:
    """Keep even a paired peer's response inside the narrow display contract."""
    fields = {"schema_version", "state", "title", "artist", "source", "position_seconds",
              "duration_seconds", "finite", "live"}
    if not isinstance(value, dict) or set(value) != fields or type(value["schema_version"]) is not int \
            or value["schema_version"] != SCHEMA_VERSION or not isinstance(value["state"], str) \
            or value["state"] not in {str(state) for state in PlaybackState} \
            or (value["source"] is not None and not isinstance(value["source"], str)) \
            or value["source"] not in {None, *(str(source) for source in MediaSource)} \
            or type(value["finite"]) is not bool or type(value["live"]) is not bool:
        raise PairingError("Invalid companion status")
    for key in ("position_seconds", "duration_seconds"):
        number = value[key]
        if number is None and key == "duration_seconds":
            continue
        if isinstance(number, bool) or not isinstance(number, (int, float)) \
                or not 0 <= number <= 1e12 or not math.isfinite(number):
            raise PairingError("Invalid companion status position")
    result = dict(value)
    for key, maximum in (("title", 240), ("artist", 160)):
        if value[key] is not None and not isinstance(value[key], str):
            raise PairingError("Invalid companion display text")
        result[key] = _clean_display_text(value[key], maximum=maximum)
    return result


def _read_document(path: Path, limit: int = MAX_STATE_BYTES) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        expected = path.lstat()
        if not stat.S_ISREG(expected.st_mode) or expected.st_size > limit:
            raise ValueError
        # Refuse special files before opening, and bind the read to that same
        # regular file. Nonblocking/no-follow flags also protect the POSIX
        # open race; fstat verifies the descriptor on every supported platform.
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > limit \
                or (opened.st_dev, opened.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            payload = stream.read(limit + 1)
        if len(payload) > limit:
            raise ValueError
        document = strict_json(payload)
        if not isinstance(document, dict) or type(document.get("schema_version")) is not int \
                or document.get("schema_version") != SCHEMA_VERSION:
            raise ValueError
        return document
    except (OSError, ValueError, UnicodeError, PairingError):
        raise PairingError("Stored pairing state is invalid; it was not replaced") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _atomic_document(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_STATE_BYTES or path.is_symlink():
        raise PairingError("Pairing state exceeds its storage boundary")
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".paired-state-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        raise PairingError("Pairing state could not be saved; existing trust was preserved") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    """Nonblocking process lock; the stable lock inode is deliberately retained."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    if lock_path.is_symlink():
        raise PairingError("Pairing state lock is not a regular local file")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError:
            raise PairingError("Pairing state is busy; retry the explicit operation") from None
        yield
    finally:
        if locked:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class ServerIdentity:
    certificate: str
    fingerprint: str
    context: ssl.SSLContext


def server_identity(path: Path, credentials: PairingSecrets) -> ServerIdentity:
    """Provision only on explicit start; never silently replace an existing identity."""
    with _state_lock(path):
        return _server_identity(path, credentials)


def _server_identity(path: Path, credentials: PairingSecrets) -> ServerIdentity:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    if path.exists():
        document = _read_document(path, 16 * 1024)
        if set(document) != {"schema_version", "key_reference", "certificate", "encrypted_key"}:
            raise PairingError("Stored server identity is invalid")
        reference = document.get("key_reference")
        if not isinstance(reference, str) or not re.fullmatch(r"server-key/[a-f0-9]{32}", reference):
            raise PairingError("Stored server identity is invalid")
        passphrase = credentials.get(reference)
        if not passphrase:
            raise PairingError("The server identity key is unavailable; pairing remains disabled")
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Mariana paired desktop")])
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(TLS_NAME)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256())
        )
        reference = f"server-key/{secrets.token_hex(16)}"
        passphrase = secrets.token_urlsafe(32)
        document = {
            "schema_version": SCHEMA_VERSION,
            "key_reference": reference,
            "certificate": certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
            "encrypted_key": key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(passphrase.encode("ascii")),
            ).decode("ascii"),
        }
        credentials.set(reference, passphrase)
        try:
            _atomic_document(path, document)
        except PairingError:
            credentials.delete(reference)
            raise
    try:
        pem = document["certificate"]
        encrypted = document["encrypted_key"]
        if not isinstance(pem, str) or not isinstance(encrypted, str) or "ENCRYPTED PRIVATE KEY" not in encrypted:
            raise ValueError
        certificate = x509.load_pem_x509_certificate(pem.encode("ascii"))
        now = datetime.now(UTC)
        if not certificate.not_valid_before_utc <= now < certificate.not_valid_after_utc:
            raise PairingError("Server certificate expired or is not yet valid; explicit identity renewal is required")
        context = pinned_tls_context(ssl.PROTOCOL_TLS_SERVER)
        # ssl requires filenames. These temporary files contain only the public
        # certificate and encrypted key; the passphrase never leaves the keyring/memory.
        with tempfile.TemporaryDirectory(prefix=".paired-tls-", dir=path.parent) as folder:
            certificate_path, key_path = Path(folder) / "certificate.pem", Path(folder) / "encrypted-key.pem"
            certificate_path.write_text(pem, encoding="ascii")
            key_path.write_text(encrypted, encoding="ascii")
            context.load_cert_chain(certificate_path, key_path, password=passphrase)
        return ServerIdentity(pem, certificate.fingerprint(hashes.SHA256()).hex(), context)
    except PairingError:
        raise
    except (ValueError, KeyError, OSError, UnicodeError):
        raise PairingError("The protected server identity could not be loaded") from None


class TrustStore:
    """Atomic host-side metadata. Only high-entropy token digests are persisted."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._devices: dict[str, dict[str, Any]] = {}
        if path.exists():
            value = _read_document(path)
            devices = value.get("devices")
            if set(value) != {"schema_version", "devices"} or not isinstance(devices, dict) or len(devices) > MAX_DEVICES:
                raise PairingError("Stored device trust is invalid")
            for identifier, device in devices.items():
                if not isinstance(device, dict) or set(device) != {"label", "digest", "permissions", "paired_at", "revoked"}:
                    raise PairingError("Stored device trust is invalid")
                if not IDENTIFIER.fullmatch(identifier) or not isinstance(device["digest"], str) \
                        or not DIGEST.fullmatch(device["digest"]) or device["permissions"] != ["status.read"] \
                        or not isinstance(device["revoked"], bool):
                    raise PairingError("Stored device trust is invalid")
                device_label(device["label"])
                timestamp = device["paired_at"]
                if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) \
                        or not 0 < timestamp <= 1e12 or not math.isfinite(timestamp):
                    raise PairingError("Stored device trust is invalid")
            self._devices = devices

    def _commit(self, devices: dict[str, dict[str, Any]]) -> None:
        _atomic_document(self.path, {"schema_version": SCHEMA_VERSION, "devices": devices})
        self._devices = devices

    @contextmanager
    def _current(self) -> Iterator[None]:
        with self._lock, _state_lock(self.path):
            # Every auth/write sees persisted revocation, including another
            # process's update. Never authorize from a stale in-memory copy.
            self._devices = TrustStore(self.path)._devices
            yield

    def approve(self, identifier: str, label: str, digest: str, *, now: float) -> None:
        with self._current():
            if len(self._devices) >= MAX_DEVICES or identifier in self._devices:
                raise PairingError("Device trust capacity reached; no existing trust was replaced")
            if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) \
                    or not isinstance(digest, str) or not DIGEST.fullmatch(digest) \
                    or isinstance(now, bool) or not isinstance(now, (int, float)) \
                    or not 0 < now <= 1e12 or not math.isfinite(now):
                raise PairingError("Invalid device identity")
            self._commit({**self._devices, identifier: {
                "label": device_label(label), "digest": digest, "permissions": ["status.read"],
                "paired_at": now, "revoked": False,
            }})

    def authenticates(self, identifier: str, credential: str) -> bool:
        try:
            digest = token_digest(credential)
        except PairingError:
            return False
        with self._current():
            device = self._devices.get(identifier)
            return bool(device and not device["revoked"] and hmac.compare_digest(device["digest"], digest))

    def revoke(self, identifier: str) -> None:
        with self._current():
            if identifier not in self._devices:
                raise PairingError("Unknown paired device")
            self._commit({**self._devices, identifier: {**self._devices[identifier], "revoked": True}})

    def devices(self) -> list[dict[str, Any]]:
        with self._current():
            return [{"device_id": identifier, "label": row["label"], "paired_at": row["paired_at"],
                     "revoked": row["revoked"], "permissions": list(row["permissions"])}
                    for identifier, row in self._devices.items()]


class PairedReadOnlyService:
    """Host approval boundary; its network adapter has no playback callbacks."""

    def __init__(self, trust: TrustStore, *, now: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.trust = trust
        self.now = now
        self.monotonic = monotonic
        self._lock = threading.RLock()
        self._invitation: tuple[str, float, float] | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._status: dict[str, Any] = {}
        self._closed = threading.Event()
        self.update_status(PlaybackSnapshot(PlaybackState.IDLE))

    def update_status(self, snapshot: PlaybackSnapshot) -> None:
        projection = project_playback_status(snapshot).to_dict()
        # Public companion status is narrower than the installation's desktop
        # contract: no library IDs, queue contents, ratings, paths or error logs.
        status = {key: projection[key] for key in (
            "state", "title", "artist", "source", "position_seconds", "duration_seconds", "finite", "live",
        )}
        with self._lock:
            self._status = companion_status({"schema_version": SCHEMA_VERSION, **status})

    def activate(self) -> None:
        """Start a new listener lifetime without dropping durable trust."""
        with self._lock:
            self._invitation = None
            self._pending.clear()
            self._closed.clear()

    def invitation(self, *, ttl_seconds: int = 300) -> tuple[str, float]:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 300:
            raise PairingError("Pairing invitations last between 1 and 300 seconds")
        with self._lock:
            if self._closed.is_set():
                raise PairingError("The pairing service is stopped")
            secret, expires = secrets.token_urlsafe(32), self.now() + ttl_seconds
            self._invitation = (token_digest(secret), expires, self.monotonic() + ttl_seconds)
            return secret, expires

    def _expire(self) -> None:
        self._pending = {key: row for key, row in self._pending.items() if row["deadline"] > self.monotonic()}

    def request(self, invitation: str, credential: str, label: str) -> dict[str, Any]:
        invite_digest, credential_digest, label = token_digest(invitation), token_digest(credential), device_label(label)
        with self._lock:
            if self._closed.is_set():
                raise PairingError("The pairing service is stopped")
            self._expire()
            if self._invitation is None or self._invitation[2] <= self.monotonic() \
                    or not hmac.compare_digest(self._invitation[0], invite_digest):
                raise PairingError("Pairing invitation is invalid, expired, or already used")
            if len(self._pending) >= MAX_PENDING:
                raise PairingError("Too many pending pairing requests")
            expires, deadline = self._invitation[1:]
            self._invitation = None
            identifier = secrets.token_hex(16)
            self._pending[identifier] = {"label": label, "digest": credential_digest,
                                        "expires_at": expires, "deadline": deadline, "approved": False}
            return {"request_id": identifier, "expires_at": expires, "proof": credential_digest[:16]}

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._closed.is_set():
                return []
            self._expire()
            return [{"request_id": key, "label": row["label"], "expires_at": row["expires_at"],
                     "proof": row["digest"][:16]} for key, row in self._pending.items() if not row["approved"]]

    def approve(self, identifier: str, *, verified_proof: str) -> None:
        with self._lock:
            if self._closed.is_set():
                raise PairingError("The pairing service is stopped")
            self._expire()
            row = self._pending.get(identifier)
            if row is None or row["approved"] or not isinstance(verified_proof, str) \
                    or not re.fullmatch(r"[a-f0-9]{16}", verified_proof) \
                    or not hmac.compare_digest(row["digest"][:16], verified_proof):
                raise PairingError("Pairing request or verified device proof is invalid")
            self.trust.approve(identifier, row["label"], row["digest"], now=self.now())
            row["approved"] = True

    def poll(self, identifier: str, credential: str) -> dict[str, Any]:
        digest = token_digest(credential)
        with self._lock:
            if self._closed.is_set():
                raise PairingError("The pairing service is stopped")
            self._expire()
            row = self._pending.get(identifier)
            if row is None or not hmac.compare_digest(row["digest"], digest):
                raise PairingError("Pairing request is unavailable")
            approved = row["approved"] and self.trust.authenticates(identifier, credential)
            return {"state": "approved" if approved else "pending", "device_id": identifier if approved else None,
                    "permissions": ["status.read"] if approved else []}

    def reject(self, identifier: str) -> None:
        with self._lock:
            if self._closed.is_set():
                raise PairingError("The pairing service is stopped")
            row = self._pending.get(identifier)
            if row is None or row["approved"]:
                raise PairingError("No pending request to reject")
            del self._pending[identifier]

    def status(self, identifier: str, credential: str) -> dict[str, Any]:
        if self._closed.is_set():
            raise PairingError("The pairing service is stopped")
        if not self.trust.authenticates(identifier, credential):
            raise PairingError("Device is not authorized for companion status")
        with self._lock:
            return dict(self._status)

    def close(self) -> None:
        self._closed.set()
        if self._lock.acquire(blocking=False):
            try:
                self._invitation = None
                self._pending.clear()
            finally:
                self._lock.release()
