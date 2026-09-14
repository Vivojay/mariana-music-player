"""Fail-closed focus-mode state and Firebase challenge coordination."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import stat
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .credentials import CredentialError, CredentialStore
from .models import MediaRef, MediaSource

SCHEMA_VERSION = 1
PASSCODE_REFERENCE = "focus/passcode-verifier"
FIREBASE_DESKTOP_TOKEN_REFERENCE = "focus/firebase-desktop-token"
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 10
PAIRING_TTL_SECONDS = 300
UNLOCK_TTL_SECONDS = 300
COUNTDOWN_SECONDS = 3
MAX_ATTEMPTS = 5
ATTEMPT_LOCK_SECONDS = 60
MIN_PASSCODE_LENGTH = 8
MAX_RESPONSE_BYTES = 65_536
MAX_STATE_BYTES = 65_536
MAX_PAIRED_DEVICES = 8
RECOVERY_MESSAGE = (
    "Saved Focus Mode data needs recovery. Playback is locked. Restore a known-good active "
    "focus-state.json backup, then use focus recover to recheck it. Recovery never unlocks Focus Mode."
)
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_CHALLENGE_ID = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_PASSCODE_VERIFIER = re.compile(r"scrypt\$32768\$8\$1\$([0-9a-f]{32})\$([0-9a-f]{64})")


class FocusModeError(RuntimeError):
    """A safe focus-mode refusal suitable for user-facing output."""


class FocusTransport(Protocol):
    """Narrow challenge transport; it never controls playback."""

    def configured(self) -> bool: ...

    def begin_pairing(self, desktop_instance_id: str) -> dict[str, Any]: ...

    def pairing_status(self, request_id: str) -> dict[str, Any] | None: ...

    def begin_unlock(self, desktop_instance_id: str, device_id: str) -> dict[str, Any]: ...

    def verify_phone_code(self, request_id: str, code: str) -> dict[str, Any]: ...

    def unlock_status(self, request_id: str) -> dict[str, Any] | None: ...


def _now() -> float:
    return time.time()


def _clean_identifier(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not _CHALLENGE_ID.fullmatch(text):
        raise FocusModeError(f"{label} is invalid")
    return text


def _challenge_code(value: object) -> str:
    code = str(value or "").strip().upper()
    if len(code) != CODE_LENGTH or any(character not in CODE_ALPHABET for character in code):
        raise FocusModeError(f"The verification code must contain {CODE_LENGTH} letters or numbers")
    return code


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _passcode_verifier(passcode: str, *, salt: bytes | None = None) -> str:
    if not isinstance(passcode, str) or len(passcode) < MIN_PASSCODE_LENGTH:
        raise FocusModeError(f"The focus passcode must contain at least {MIN_PASSCODE_LENGTH} characters")
    salt = salt or secrets.token_bytes(16)
    if not isinstance(salt, bytes) or len(salt) != 16:
        raise FocusModeError("The focus passcode salt is invalid")
    digest = hashlib.scrypt(
        passcode.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, dklen=32,
        maxmem=64 * 1024 * 1024,
    )
    return f"scrypt$32768$8$1${salt.hex()}${digest.hex()}"


def verify_passcode(passcode: str, verifier: str) -> bool:
    if not isinstance(passcode, str) or not isinstance(verifier, str):
        return False
    match = _PASSCODE_VERIFIER.fullmatch(verifier)
    if match is None:
        return False
    salt, expected = match.groups()
    try:
        digest = hashlib.scrypt(
            passcode.encode("utf-8"),
            salt=bytes.fromhex(salt),
            n=2**15,
            r=8,
            p=1,
            dklen=32,
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (TypeError, ValueError, OverflowError):
        return False


@dataclass(frozen=True, slots=True, eq=False)
class FocusActivation:
    """Process-local rollback capability; only the exact issued object has authority."""

    media_id: str


@dataclass(frozen=True, slots=True)
class PairedFocusDevice:
    device_id: str
    label: str
    paired_at: float

    @classmethod
    def from_dict(cls, value: object) -> PairedFocusDevice | None:
        if not isinstance(value, dict):
            return None
        raw_paired_at = value.get("paired_at")
        if isinstance(raw_paired_at, bool) or not isinstance(raw_paired_at, (int, float)):
            return None
        try:
            device_id = _clean_identifier(value.get("device_id"), label="Paired device")
            label = str(value.get("label") or "Phone").strip()[:80]
            paired_at = float(raw_paired_at)
        except (FocusModeError, TypeError, ValueError, OverflowError):
            return None
        if not label or not math.isfinite(paired_at) or paired_at <= 0:
            return None
        return cls(device_id, label, paired_at)


@dataclass(slots=True)
class FocusState:
    schema_version: int = SCHEMA_VERSION
    desktop_instance_id: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    active: bool = False
    activated_at: float | None = None
    active_media_id: str | None = None
    paired_devices: list[PairedFocusDevice] = field(default_factory=list)
    pairing_request_id: str | None = None
    pairing_expires_at: float | None = None
    unlock_request_id: str | None = None
    unlock_device_id: str | None = None
    unlock_stage: str | None = None
    unlock_expires_at: float | None = None
    countdown_started_at: float | None = None
    failed_attempts: int = 0
    passcode_blocked_until: float | None = None

    def public_dict(
        self,
        *,
        passcode_set: bool,
        firebase_configured: bool,
        media_count: int,
        now: float,
    ) -> dict[str, Any]:
        remaining = None
        if self.countdown_started_at is not None:
            remaining = max(0, math.ceil(COUNTDOWN_SECONDS - (now - self.countdown_started_at)))
        return {
            "schema_version": self.schema_version,
            "active": self.active,
            "activated_at": self.activated_at,
            "active_media_id": self.active_media_id,
            "passcode_set": passcode_set,
            "firebase_configured": firebase_configured,
            "approved_media_count": media_count,
            "paired_devices": [
                {"device_id": item.device_id, "label": item.label, "paired_at": item.paired_at}
                for item in self.paired_devices
            ],
            "pairing_pending": self.pairing_request_id is not None,
            "unlock_stage": self.unlock_stage,
            "countdown_seconds": remaining,
            "passcode_retry_after": (
                max(0, math.ceil(self.passcode_blocked_until - now))
                if self.passcode_blocked_until is not None and self.passcode_blocked_until > now
                else 0
            ),
        }


class FocusStateStore:
    """Atomic local persistence containing no passcodes or transient media URLs."""

    def __init__(self, path: Path):
        self.path = path
        self.guard_path = path.with_name(path.name + '.guard')
        self.recovery_required = False

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        details = path.lstat()
        if not stat.S_ISREG(details.st_mode) or getattr(details, 'st_file_attributes', 0) & 0x400 \
                or details.st_size > MAX_STATE_BYTES:
            raise FocusModeError(RECOVERY_MESSAGE)
        descriptor = None
        try:
            # Nonblocking/no-follow flags prevent a POSIX path replacement from
            # turning a saved document read into a FIFO wait or symlink traversal.
            flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NONBLOCK', 0) \
                | getattr(os, 'O_NOFOLLOW', 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if (opened.st_dev, opened.st_ino) != (details.st_dev, details.st_ino) \
                    or not stat.S_ISREG(opened.st_mode) or getattr(opened, 'st_file_attributes', 0) & 0x400 \
                    or opened.st_size > MAX_STATE_BYTES:
                raise FocusModeError(RECOVERY_MESSAGE)
            with os.fdopen(descriptor, 'rb') as stream:
                descriptor = None
                payload = stream.read(MAX_STATE_BYTES + 1)
        finally:
            if descriptor is not None:
                os.close(descriptor)
        if len(payload) > MAX_STATE_BYTES:
            raise FocusModeError(RECOVERY_MESSAGE)

        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise FocusModeError(RECOVERY_MESSAGE)
                result[key] = value
            return result

        value = json.loads(payload.decode('utf-8'), object_pairs_hook=unique)
        if not isinstance(value, dict):
            raise FocusModeError(RECOVERY_MESSAGE)
        return value

    def _guard(self, required: bool) -> None:
        self._write(self.guard_path, {'schema_version': 1, 'recovery_required': required})

    def lock_recovery(self) -> FocusState:
        self.recovery_required = True
        # Never overwrite damaged evidence. If storage is unavailable, the live
        # process remains locked and the damaged source is checked again on restart.
        with suppress(OSError, UnicodeError, ValueError, RecursionError, FocusModeError):
            try:
                guard = self._read(self.guard_path)
            except FileNotFoundError:
                self._guard(True)
            else:
                if set(guard) == {'schema_version', 'recovery_required'} \
                        and type(guard['schema_version']) is int and guard['schema_version'] == 1 \
                        and guard['recovery_required'] is False:
                    self._guard(True)
        return FocusState(active=True)

    def load(self) -> FocusState:
        try:
            try:
                guard = self._read(self.guard_path)
            except FileNotFoundError:
                guard = None
            if guard is not None and (
                set(guard) != {'schema_version', 'recovery_required'}
                or type(guard['schema_version']) is not int or guard['schema_version'] != 1
                or type(guard['recovery_required']) is not bool or guard['recovery_required']
            ):
                return self.lock_recovery()
            try:
                value = self._read(self.path)
            except FileNotFoundError:
                return FocusState() if guard is None and not self.recovery_required else self.lock_recovery()
            if self.recovery_required:
                return self.lock_recovery()
            state = self._decode(value)
            if guard is None:
                self._guard(False)
            return state
        except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, FocusModeError):
            return self.lock_recovery()

    @staticmethod
    def _decode(value: dict[str, Any]) -> FocusState:
        allowed = set(FocusState.__dataclass_fields__)
        if set(value) - allowed or not {'schema_version', 'desktop_instance_id', 'active'} <= value.keys():
            raise FocusModeError(RECOVERY_MESSAGE)
        if type(value['schema_version']) is not int or value['schema_version'] != SCHEMA_VERSION \
                or type(value['active']) is not bool or not isinstance(value['desktop_instance_id'], str):
            raise FocusModeError(RECOVERY_MESSAGE)
        for key in ('activated_at', 'pairing_expires_at', 'unlock_expires_at',
                    'countdown_started_at', 'passcode_blocked_until'):
            raw = value.get(key)
            if raw is not None and (type(raw) not in (float, int) or _finite_timestamp(raw) is None):
                raise FocusModeError(RECOVERY_MESSAGE)
        for key in ('pairing_request_id', 'unlock_request_id', 'unlock_device_id'):
            raw = value.get(key)
            if raw is not None and (not isinstance(raw, str) or not _CHALLENGE_ID.fullmatch(raw)):
                raise FocusModeError(RECOVERY_MESSAGE)
        raw_media = value.get('active_media_id')
        if raw_media is not None and (not isinstance(raw_media, str) or not _YOUTUBE_ID.fullmatch(raw_media)):
            raise FocusModeError(RECOVERY_MESSAGE)
        raw_devices = value.get('paired_devices', [])
        if not isinstance(raw_devices, list) or len(raw_devices) > MAX_PAIRED_DEVICES:
            raise FocusModeError(RECOVERY_MESSAGE)
        devices = [PairedFocusDevice.from_dict(raw) for raw in raw_devices]
        if any(device is None for device in devices):
            raise FocusModeError(RECOVERY_MESSAGE)
        valid_devices = [device for device in devices if device is not None]
        if len({device.device_id for device in valid_devices}) != len(valid_devices):
            raise FocusModeError(RECOVERY_MESSAGE)
        attempts = value.get('failed_attempts', 0)
        stage = value.get('unlock_stage')
        if type(attempts) is not int or not 0 <= attempts <= MAX_ATTEMPTS \
                or stage not in (None, 'awaiting_phone_code', 'awaiting_phone_confirmation', 'countdown'):
            raise FocusModeError(RECOVERY_MESSAGE)
        state = FocusState(
            desktop_instance_id=value['desktop_instance_id'],
            active=value['active'],
            activated_at=_finite_timestamp(value.get("activated_at")),
            active_media_id=_youtube_id_or_none(value.get("active_media_id")),
            paired_devices=valid_devices,
            pairing_request_id=_challenge_id_or_none(value.get("pairing_request_id")),
            pairing_expires_at=_finite_timestamp(value.get("pairing_expires_at")),
            unlock_request_id=_challenge_id_or_none(value.get("unlock_request_id")),
            unlock_device_id=_challenge_id_or_none(value.get("unlock_device_id")),
            unlock_stage=stage,
            unlock_expires_at=_finite_timestamp(value.get("unlock_expires_at")),
            countdown_started_at=_finite_timestamp(value.get("countdown_started_at")),
            failed_attempts=attempts,
            passcode_blocked_until=_finite_timestamp(value.get("passcode_blocked_until")),
        )
        state.desktop_instance_id = _clean_identifier(
            state.desktop_instance_id, label="Desktop instance",
        )
        if state.active != (state.active_media_id is not None and state.activated_at is not None) \
                or (not state.active and (state.active_media_id is not None or state.activated_at is not None)):
            raise FocusModeError(RECOVERY_MESSAGE)
        if state.active and not state.paired_devices:
            raise FocusModeError(RECOVERY_MESSAGE)
        if (state.pairing_request_id is None) != (state.pairing_expires_at is None):
            raise FocusModeError(RECOVERY_MESSAGE)
        if state.unlock_stage is None:
            if any(value is not None for value in (
                state.unlock_request_id, state.unlock_device_id, state.unlock_expires_at, state.countdown_started_at,
            )):
                raise FocusModeError(RECOVERY_MESSAGE)
        elif not state.active or state.unlock_request_id is None or state.unlock_expires_at is None \
                or state.unlock_device_id not in {device.device_id for device in state.paired_devices} \
                or ((state.unlock_stage == 'countdown') != (state.countdown_started_at is not None)):
            raise FocusModeError(RECOVERY_MESSAGE)
        if state.pairing_expires_at is not None and state.pairing_expires_at <= _now():
            state.pairing_request_id = None
            state.pairing_expires_at = None
        if state.unlock_expires_at is not None and state.unlock_expires_at <= _now():
            _clear_unlock(state)
        return state

    def save(self, state: FocusState) -> None:
        if self.recovery_required:
            raise FocusModeError(RECOVERY_MESSAGE)
        if not self.guard_path.exists():
            self._guard(False)
        self._write(self.path, asdict(state))

    def recover(self) -> FocusState:
        """Reload only a complete active backup; never convert recovery into an unlock."""
        if not self.recovery_required:
            return self.load()
        try:
            state = self._decode(self._read(self.path))
            if not state.active or not state.paired_devices:
                raise FocusModeError(RECOVERY_MESSAGE)
            # Imported countdowns are not authority to unlock after recovery.
            _clear_unlock(state)
            state.pairing_request_id = None
            state.pairing_expires_at = None
            self._write(self.path, asdict(state))
            self._guard(False)
        except (OSError, UnicodeError, ValueError, TypeError, OverflowError, RecursionError, FocusModeError) as error:
            self.lock_recovery()
            raise FocusModeError(RECOVERY_MESSAGE) from error
        self.recovery_required = False
        return state

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or (path.exists() and (
            not path.is_file() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400
        )):
            raise FocusModeError(RECOVERY_MESSAGE)
        descriptor, name = tempfile.mkstemp(prefix=".focus-state-", suffix=".tmp", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def _finite_timestamp(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _youtube_id_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text if _YOUTUBE_ID.fullmatch(text) else None


def _challenge_id_or_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text if _CHALLENGE_ID.fullmatch(text) else None


def _clear_unlock(state: FocusState) -> None:
    # Cancelling or expiring a flow is not passcode authorization. Preserve the
    # failed-attempt budget so cleanup cannot provide unlimited new guesses.
    state.unlock_request_id = None
    state.unlock_device_id = None
    state.unlock_stage = None
    state.unlock_expires_at = None
    state.countdown_started_at = None


class _NoFocusRedirects(HTTPRedirectHandler):
    """Keep challenge credentials bound to the configured Function endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        with suppress(OSError):
            fp.close()
        raise FocusModeError("Firebase focus verification redirects are not permitted")


class FirebaseFocusTransport:
    """HTTPS adapter for a Firebase Function; placeholder values fail closed."""

    REQUIRED_ENV = (
        "MARIANA_FIREBASE_PROJECT_ID",
        "MARIANA_FIREBASE_API_KEY",
        "MARIANA_FIREBASE_APP_ID",
        "MARIANA_FIREBASE_FOCUS_FUNCTION_URL",
        "MARIANA_FIREBASE_RECAPTCHA_ENTERPRISE_SITE_KEY",
    )

    def __init__(
        self,
        *,
        environment: dict[str, str] | None = None,
        timeout: float = 5.0,
        credentials: CredentialStore | None = None,
    ):
        self.environment = environment if environment is not None else os.environ
        self.timeout = max(1.0, min(10.0, float(timeout)))
        self.credentials = credentials or CredentialStore(service="io.github.vivojay.mariana.focus")

    def configured(self) -> bool:
        values = [str(self.environment.get(name) or "").strip() for name in self.REQUIRED_ENV]
        return all(values) and not any(
            value.startswith(("replace-", "your-", "https://example.")) for value in values
        )

    def _call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.configured():
            raise FocusModeError("Firebase focus verification is not configured")
        url = str(self.environment["MARIANA_FIREBASE_FOCUS_FUNCTION_URL"]).strip()
        if not url.startswith("https://"):
            raise FocusModeError("Firebase focus verification must use HTTPS")
        body = json.dumps({"operation": operation, "payload": payload}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Mariana-Project": str(self.environment["MARIANA_FIREBASE_PROJECT_ID"]),
        }
        try:
            desktop_token = self.credentials.get(FIREBASE_DESKTOP_TOKEN_REFERENCE)
        except CredentialError as error:
            raise FocusModeError("The operating-system credential store is unavailable") from error
        if desktop_token:
            headers["X-Mariana-Desktop-Token"] = desktop_token
        request = Request(url, data=body, method="POST", headers=headers)
        try:
            with build_opener(_NoFocusRedirects()).open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise FocusModeError("Firebase focus verification is unavailable")
                content = response.read(MAX_RESPONSE_BYTES + 1)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise FocusModeError("Firebase focus verification returned an oversized response")
                result = json.loads(content)
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise FocusModeError("Firebase focus verification is unavailable") from error
        if not isinstance(result, dict) or result.get("ok") is not True or not isinstance(result.get("data"), dict):
            raise FocusModeError("Firebase focus verification returned an invalid response")
        return result["data"]

    def begin_pairing(self, desktop_instance_id: str) -> dict[str, Any]:
        data = self._call("pairing.begin", {"desktop_instance_id": desktop_instance_id})
        token = data.pop("desktop_token", None)
        if not isinstance(token, str) or len(token) < 32:
            raise FocusModeError("Firebase returned an invalid desktop pairing token")
        try:
            self.credentials.set(FIREBASE_DESKTOP_TOKEN_REFERENCE, token)
        except CredentialError as error:
            raise FocusModeError("The desktop pairing token could not be protected") from error
        return data

    def pairing_status(self, request_id: str) -> dict[str, Any] | None:
        data = self._call("pairing.status", {"request_id": request_id})
        return data if data.get("paired") is True else None

    def begin_unlock(self, desktop_instance_id: str, device_id: str) -> dict[str, Any]:
        return self._call("unlock.begin", {
            "desktop_instance_id": desktop_instance_id, "device_id": device_id,
        })

    def verify_phone_code(self, request_id: str, code: str) -> dict[str, Any]:
        return self._call("unlock.verify-phone-code", {"request_id": request_id, "code": code})

    def unlock_status(self, request_id: str) -> dict[str, Any] | None:
        data = self._call("unlock.status", {"request_id": request_id})
        return data if data.get("approved") is True else None


def focus_environment(path: Path, *, base: dict[str, str] | None = None) -> dict[str, str]:
    """Load only focus-related development values without overriding real environment values."""
    environment = dict(os.environ if base is None else base)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return environment
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name.startswith("MARIANA_FIREBASE_") or name == "MARIANA_FOCUS_YOUTUBE_IDS":
            environment.setdefault(name, value.strip().strip("\"'"))
    return environment


class FocusModeService:
    """Persistent focus gate with an external, human-mediated unlock handshake."""

    def __init__(
        self,
        store: FocusStateStore,
        *,
        credentials: CredentialStore | None = None,
        transport: FocusTransport | None = None,
        approved_youtube_ids: list[str] | tuple[str, ...] = (),
        clock: Callable[[], float] = _now,
        on_recovery: Callable[[], None] | None = None,
    ):
        self.store = store
        self.credentials = credentials or CredentialStore(service="io.github.vivojay.mariana.focus")
        self.transport = transport or FirebaseFocusTransport()
        self.clock = clock
        self._on_recovery = on_recovery
        self._lock = threading.RLock()
        self._state_lock_depth = 0
        self._recovery_notice_pending = False
        self._pending_activation: FocusActivation | None = None
        self._unlock_revision = 0
        self._approved_ids = tuple(dict.fromkeys(
            media_id for value in approved_youtube_ids
            if (media_id := _youtube_id_or_none(value)) is not None
        ))
        self.state = store.load()

    @contextmanager
    def _state_lock(self) -> Iterator[None]:
        """Notify the host only after the outermost state operation unlocks."""
        self._lock.acquire()
        self._state_lock_depth += 1
        try:
            yield
        finally:
            self._state_lock_depth -= 1
            notify = self._state_lock_depth == 0 and self._recovery_notice_pending
            if notify:
                self._recovery_notice_pending = False
            self._lock.release()
            if notify and self._on_recovery is not None:
                # A worker-start fallback may stop output synchronously here.
                # No state lock may be held while it acquires playback locks.
                with suppress(Exception):
                    self._on_recovery()

    @property
    def recovery_required(self) -> bool:
        return self.store.recovery_required

    def recovery_status(self) -> dict[str, Any]:
        with self._state_lock():
            return {'required': self.recovery_required, 'message': RECOVERY_MESSAGE if self.recovery_required else None}

    def recover_saved_state(self) -> dict[str, Any]:
        with self._state_lock():
            if self.recovery_required:
                self._pending_activation = None
                self._unlock_revision += 1
                # No transport requests, credential replacement, or passcode reset.
                # Normal passcode/phone authorization is still required to unlock.
                self.state = self.store.recover()
            return self.recovery_status()

    def _require_healthy(self) -> None:
        if self.recovery_required:
            raise FocusModeError(RECOVERY_MESSAGE)

    def _persist(self) -> None:
        try:
            self.store.save(self.state)
        except (OSError, FocusModeError) as error:
            self._pending_activation = None
            self._unlock_revision += 1
            self.state = self.store.lock_recovery()
            self._recovery_notice_pending = True
            raise FocusModeError(RECOVERY_MESSAGE) from error

    def _passcode_verifier(self) -> str | None:
        try:
            return self.credentials.get(PASSCODE_REFERENCE)
        except CredentialError as error:
            raise FocusModeError("The operating-system credential store is unavailable") from error

    def status(self) -> dict[str, Any]:
        with self._state_lock():
            self._advance_countdown()
            result = self.state.public_dict(
                passcode_set=False if self.recovery_required else self._passcode_verifier() is not None,
                firebase_configured=self.transport.configured(),
                media_count=len(self._approved_ids),
                now=self.clock(),
            )
            result['recovery_required'] = self.recovery_required
            result['recovery_message'] = RECOVERY_MESSAGE if self.recovery_required else None
            return result

    def setup_passcode(self, passcode: str, confirmation: str) -> None:
        with self._state_lock():
            self._require_healthy()
            if self.state.active:
                raise FocusModeError("The focus passcode cannot be changed while focus mode is active")
            if passcode != confirmation:
                raise FocusModeError("The passcode confirmation does not match")
            verifier = _passcode_verifier(passcode)
            try:
                self.credentials.set(PASSCODE_REFERENCE, verifier)
            except CredentialError as error:
                raise FocusModeError("The focus passcode could not be stored in the operating-system keychain") from error

    def begin_pairing(self) -> dict[str, Any]:
        with self._state_lock():
            self._require_healthy()
            if self.state.active:
                raise FocusModeError("Pairing cannot be changed while focus mode is active")
            data = self.transport.begin_pairing(self.state.desktop_instance_id)
            request_id = _clean_identifier(data.get("request_id"), label="Pairing request")
            code = _challenge_code(data.get("code"))
            expires_at = _finite_timestamp(data.get("expires_at"))
            if expires_at is None or expires_at <= self.clock() or expires_at > self.clock() + PAIRING_TTL_SECONDS + 30:
                raise FocusModeError("Firebase returned an invalid pairing expiry")
            self.state.pairing_request_id = request_id
            self.state.pairing_expires_at = expires_at
            self._persist()
            return {"request_id": request_id, "code": code, "expires_at": expires_at}

    def refresh_pairing(self) -> PairedFocusDevice | None:
        with self._state_lock():
            self._require_healthy()
            if self.state.active:
                raise FocusModeError("Pairing cannot be changed while focus mode is active")
            request_id = self.state.pairing_request_id
            if request_id is None:
                raise FocusModeError("No phone pairing is pending")
            if not self.state.pairing_expires_at or self.state.pairing_expires_at <= self.clock():
                self.state.pairing_request_id = None
                self.state.pairing_expires_at = None
                self._persist()
                raise FocusModeError("The phone pairing invitation expired")
            data = self.transport.pairing_status(request_id)
            if not self.state.pairing_expires_at or self.state.pairing_expires_at <= self.clock():
                self.state.pairing_request_id = None
                self.state.pairing_expires_at = None
                self._persist()
                raise FocusModeError("The phone pairing invitation expired")
            if data is None:
                return None
            device = PairedFocusDevice(
                _clean_identifier(data.get("device_id"), label="Paired device"),
                str(data.get("label") or "Phone").strip()[:80] or "Phone",
                self.clock(),
            )
            remaining = [
                existing for existing in self.state.paired_devices if existing.device_id != device.device_id
            ]
            if len(remaining) >= MAX_PAIRED_DEVICES:
                raise FocusModeError("The paired phone limit has been reached; revoke a phone before adding another")
            self.state.paired_devices = [*remaining, device]
            self.state.pairing_request_id = None
            self.state.pairing_expires_at = None
            self._persist()
            return device

    def revoke_device(self, device_id: str) -> bool:
        with self._state_lock():
            self._require_healthy()
            if self.state.active:
                raise FocusModeError("Paired devices cannot be revoked while focus mode is active")
            normalized = _clean_identifier(device_id, label="Paired device")
            remaining = [item for item in self.state.paired_devices if item.device_id != normalized]
            changed = len(remaining) != len(self.state.paired_devices)
            if changed:
                self.state.paired_devices = remaining
                self._persist()
            return changed

    def activate(self, *, media_id: str | None = None) -> FocusActivation:
        """Persist a new lock and issue a receipt for the host's playback attempt.

        Confirm the exact receipt after playback succeeds, or roll it back if
        playback fails. Receipts are never restored from disk or transferable
        between service instances, even for the same media and wall-clock time.
        """
        with self._state_lock():
            self._require_healthy()
            if self.state.active:
                raise FocusModeError("Focus mode is already active; unlock before enabling it again")
            if self._passcode_verifier() is None:
                raise FocusModeError("Set a focus passcode before enabling focus mode")
            if not self.transport.configured():
                raise FocusModeError("Configure Firebase phone verification before enabling focus mode")
            if not self.state.paired_devices:
                raise FocusModeError("Pair at least one phone before enabling focus mode")
            if not self._approved_ids:
                raise FocusModeError("Configure at least one approved focus-media YouTube ID")
            selected = _youtube_id_or_none(media_id) if media_id else secrets.choice(self._approved_ids)
            if selected not in self._approved_ids:
                raise FocusModeError("That media item is not in the approved focus set")
            self.state.active = True
            self.state.activated_at = self.clock()
            self.state.active_media_id = selected
            self.state.pairing_request_id = None
            self.state.pairing_expires_at = None
            _clear_unlock(self.state)
            self._unlock_revision += 1
            self._persist()
            activation = FocusActivation(selected)
            self._pending_activation = activation
            return activation

    def confirm_activation(self, activation: FocusActivation) -> bool:
        """Consume rollback authority once the host successfully starts playback."""
        with self._state_lock():
            self._require_healthy()
            if activation is not self._pending_activation or not isinstance(activation, FocusActivation):
                return False
            self._pending_activation = None
            return True

    def rollback_activation(self, activation: FocusActivation) -> bool:
        """Undo only the activation that failed before playback could start."""
        with self._state_lock():
            self._require_healthy()
            if isinstance(activation, FocusActivation) and activation is self._pending_activation \
                    and self.state.active and self.state.active_media_id == activation.media_id:
                self._pending_activation = None
                self.state.active = False
                self.state.activated_at = None
                self.state.active_media_id = None
                _clear_unlock(self.state)
                self._unlock_revision += 1
                self._persist()
                return True
            return False

    @property
    def approved_youtube_ids(self) -> tuple[str, ...]:
        return self._approved_ids

    def begin_unlock(self, passcode: str, *, device_id: str | None = None) -> str:
        with self._state_lock():
            self._require_healthy()
            if not self.state.active:
                raise FocusModeError("Focus mode is not active")
            if self.state.passcode_blocked_until is not None:
                if self.state.passcode_blocked_until > self.clock():
                    remaining = math.ceil(self.state.passcode_blocked_until - self.clock())
                    raise FocusModeError(f"Too many failed attempts; try again in {remaining} seconds")
                self.state.passcode_blocked_until = None
                self.state.failed_attempts = 0
            verifier = self._passcode_verifier()
            if verifier is None or not verify_passcode(passcode, verifier):
                self.state.failed_attempts = min(MAX_ATTEMPTS, self.state.failed_attempts + 1)
                if self.state.failed_attempts >= MAX_ATTEMPTS:
                    self.state.failed_attempts = 0
                    self.state.passcode_blocked_until = self.clock() + ATTEMPT_LOCK_SECONDS
                self._persist()
                raise FocusModeError("The focus passcode is incorrect")
            self.state.failed_attempts = 0
            self.state.passcode_blocked_until = None
            device = self._device(device_id)
            data = self.transport.begin_unlock(self.state.desktop_instance_id, device.device_id)
            request_id = _clean_identifier(data.get("request_id"), label="Unlock request")
            expires_at = _finite_timestamp(data.get("expires_at"))
            if expires_at is None or expires_at <= self.clock() or expires_at > self.clock() + UNLOCK_TTL_SECONDS + 30:
                raise FocusModeError("Firebase returned an invalid unlock expiry")
            self.state.unlock_request_id = request_id
            self.state.unlock_device_id = device.device_id
            self.state.unlock_stage = "awaiting_phone_code"
            self.state.unlock_expires_at = expires_at
            self.state.countdown_started_at = None
            self._unlock_revision += 1
            self._persist()
            return request_id

    def submit_phone_code(self, code: str) -> str:
        with self._state_lock():
            self._require_healthy()
            self._require_unlock_stage("awaiting_phone_code")
            request_id, revision = str(self.state.unlock_request_id), self._unlock_revision
            phone_code = _challenge_code(code)
        data = self.transport.verify_phone_code(request_id, phone_code)
        with self._state_lock():
            self._require_current_unlock(request_id, revision, "awaiting_phone_code")
            desktop_code = _challenge_code(data.get("desktop_code"))
            self.state.unlock_stage = "awaiting_phone_confirmation"
            self._persist()
            return desktop_code

    def poll_unlock(self) -> bool:
        with self._state_lock():
            self._require_healthy()
            if self.state.unlock_stage != "awaiting_phone_confirmation":
                return self._advance_countdown()
            self._require_unlock_stage("awaiting_phone_confirmation")
            request_id, revision = str(self.state.unlock_request_id), self._unlock_revision
        data = self.transport.unlock_status(request_id)
        with self._state_lock():
            # Cancellation and replacement remain responsive during transport
            # I/O; neither an expired nor a superseded reply has authority.
            self._require_current_unlock(request_id, revision, "awaiting_phone_confirmation")
            if data is not None:
                self.state.unlock_stage = "countdown"
                self.state.countdown_started_at = self.clock()
                self._persist()
            return self._advance_countdown()

    def cancel_pending_unlock(self) -> None:
        with self._state_lock():
            self._require_healthy()
            _clear_unlock(self.state)
            self._unlock_revision += 1
            self._persist()

    def assert_media_allowed(self, media: MediaRef) -> MediaRef:
        with self._state_lock():
            self._require_healthy()
            self._advance_countdown()
            if not self.state.active:
                return media
            if media.source != MediaSource.YOUTUBE:
                raise FocusModeError("Focus mode allows only its approved focus media")
            media_id = _youtube_id_from_ref(media)
            if media_id != self.state.active_media_id or media_id not in self._approved_ids:
                raise FocusModeError("Focus mode prevents switching to other media")
            return media

    def allows_command(self, tokens: list[str]) -> bool:
        with self._state_lock():
            if self.recovery_required:
                return not tokens or tokens[0].casefold() in {
                    'focus', 'help', 'h', '?', 'now', 'now*', 'progress', 'progress*',
                    'prog', 'prog*', 'exit', 'quit',
                    's', 'stop',
                }
            self._advance_countdown()
            if not self.state.active or not tokens:
                return True
            command = tokens[0].casefold()
            return command in {
                "focus", "help", "h", "now", "now*", "progress", "progress*", "prog", "prog*",
                ".*", "pause", "p", "resume", "volume", "vol", "m", "mute", "unmute", "exit",
            }

    def _advance_countdown(self) -> bool:
        if self.recovery_required:
            return False
        if self.state.unlock_stage != "countdown" or self.state.countdown_started_at is None:
            return False
        if self.clock() - self.state.countdown_started_at < COUNTDOWN_SECONDS:
            return False
        self.state.active = False
        self._pending_activation = None
        self._unlock_revision += 1
        self.state.activated_at = None
        self.state.active_media_id = None
        _clear_unlock(self.state)
        self._persist()
        return True

    def _require_current_unlock(self, request_id: str, revision: int, expected: str) -> None:
        self._require_healthy()
        if revision != self._unlock_revision or request_id != self.state.unlock_request_id:
            raise FocusModeError("The focus unlock request was cancelled or replaced")
        self._require_unlock_stage(expected)

    def _require_unlock_stage(self, expected: str) -> None:
        if self.state.unlock_stage != expected or self.state.unlock_request_id is None:
            raise FocusModeError("The focus unlock flow is not at that step")
        if self.state.unlock_expires_at is None or self.state.unlock_expires_at <= self.clock():
            _clear_unlock(self.state)
            self._unlock_revision += 1
            self._persist()
            raise FocusModeError("The focus unlock request expired")

    def _device(self, device_id: str | None) -> PairedFocusDevice:
        if not self.state.paired_devices:
            raise FocusModeError("No phone is paired")
        if device_id is None:
            return self.state.paired_devices[0]
        normalized = _clean_identifier(device_id, label="Paired device")
        for device in self.state.paired_devices:
            if device.device_id == normalized:
                return device
        raise FocusModeError("The selected phone is not paired")


def _youtube_id_from_ref(media: MediaRef) -> str | None:
    # The resolver plays original_uri, not an untrusted catalog/queue hint.
    value = media.original_uri
    if not isinstance(value, str) or len(value) > 4096 or any(ord(character) < 33 for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.port:
            return None
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=64)
        candidate = None
        if parsed.hostname in {'youtu.be', 'www.youtu.be'}:
            match = re.fullmatch(r'/([A-Za-z0-9_-]{11})/?', parsed.path)
            candidate = match.group(1) if match and 'v' not in query else None
        elif parsed.hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}:
            if parsed.path == '/watch' and len(query.get('v', [])) == 1:
                candidate = query['v'][0]
            elif 'v' not in query:
                match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?', parsed.path)
                candidate = match.group(1) if match else None
        if candidate is None or not _YOUTUBE_ID.fullmatch(candidate):
            return None
        hint = media.resolver_data.get('youtube_id')
        return candidate if hint is None or hint == candidate else None
    except ValueError:
        return None
