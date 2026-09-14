"""Lazy application composition for explicit read-only local desktop pairing.

All provisioning, persistence and network operations use one bounded worker.
Ordinary status inspection is a cached read and never starts a listener.
"""

from __future__ import annotations

import copy
import json
import math
import os
import queue
import re
import tempfile
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

from .models import PlaybackSnapshot
from .output_targets import OutputTargetError, bind_output_target
from .paired_transport import PairedClient, PairedServer, private_address
from .paired_trust import (
    DIGEST,
    IDENTIFIER,
    PairedReadOnlyService,
    PairingError,
    PairingSecrets,
    TrustStore,
    _read_document,
    device_label,
)
from .playback_status import _clean_display_text

_ARITIES = {"host": 2, "stop": 0, "invite": 1, "requests": 0, "approve": 2, "reject": 1,
            "devices": 0, "revoke": 1, "connect": 3, "poll": 0, "now": 0, "cancel": 0, "disconnect": 0}
OPERATIONS = frozenset(_ARITIES)
_OPERATION_ERROR = "Companion operation failed; playback is unchanged"


def _arguments(operation: str, arguments: tuple[Any, ...]) -> tuple[Any, ...]:
    """Validate and freeze all control inputs before starting any worker or I/O."""
    if not isinstance(operation, str) or operation not in OPERATIONS:
        raise PairingError("Unknown read-only companion operation")
    if len(arguments) != _ARITIES[operation]:
        raise PairingError("Incorrect arguments for this companion operation")
    if operation == "host":
        address, port = arguments
        if not isinstance(address, str) or isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
            raise PairingError("Host requires a private IPv4 address and a port from 0 to 65535")
        return private_address(address), port
    if operation in {"invite", "connect"}:
        path = arguments[0]
        if not isinstance(path, str) or not path.strip() or len(path) > 4096 or any(ord(char) < 32 for char in path):
            raise PairingError("Choose a valid local invitation file")
    if operation in {"approve", "reject", "revoke"} and (
        not isinstance(arguments[0], str) or not IDENTIFIER.fullmatch(arguments[0])
    ):
        raise PairingError("Invalid companion request or device identifier")
    if operation == "approve" and (not isinstance(arguments[1], str)
                                   or not re.fullmatch(r"[a-f0-9]{16}", arguments[1])):
        raise PairingError("Approval requires the matching 16-character device proof")
    if operation == "connect":
        if not isinstance(arguments[1], str) or not DIGEST.fullmatch(arguments[1]):
            raise PairingError("Connection requires the independently verified server fingerprint")
        return arguments[0], arguments[1], device_label(arguments[2])
    return arguments


class PairedCompanion:
    def __init__(self, root: Path, *, snapshot: Callable[[], PlaybackSnapshot], credentials: PairingSecrets | None = None):
        self.root = root
        self._snapshot = snapshot
        self._credentials = credentials
        self._service: PairedReadOnlyService | None = None
        self._server: PairedServer | None = None
        self._client: PairedClient | None = None
        self._worker: threading.Thread | None = None
        self._pending: queue.Queue[tuple[str, tuple[Any, ...]]] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._closed = threading.Event()
        self._listener_running = False
        self._cleanup_complete = True
        self._result: dict[str, Any] = {"operation": None, "state": "idle", "result": None, "error": None}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"listener_running": self._listener_running,
                    "read_only": True, **copy.deepcopy(self._result)}

    def submit(self, operation: str, *arguments: Any) -> dict[str, Any]:
        arguments = _arguments(operation, arguments)
        with self._lock:
            if self._closed.is_set():
                raise PairingError("Companion service is closed")
            if self._result["state"] in {"pending", "working"}:
                raise PairingError("Wait for the current companion operation; use room status")
            try:
                self._pending.put_nowait((operation, arguments))
            except queue.Full:
                raise PairingError("Companion operation queue is full; try again after it completes") from None
            self._result = {"operation": operation, "state": "pending", "result": None, "error": None}
            if self._worker is None:
                worker = threading.Thread(target=self._run, name="mariana-companion-control", daemon=True)
                try:
                    worker.start()
                except RuntimeError:
                    self._pending.get_nowait()
                    self._pending.task_done()
                    self._result.update(state="error", error="The companion worker could not start")
                    raise PairingError("The companion worker could not start") from None
                self._worker = worker
                self._cleanup_complete = False
        return self.status()

    def _host(self) -> tuple[PairedReadOnlyService, PairedServer]:
        if self._service is None:
            self._service = PairedReadOnlyService(TrustStore(self.root / "trusted-devices.json"))
            self._server = PairedServer(self._service, self.root / "server-identity.json", credentials=self._credentials)
        assert self._server is not None
        return self._service, self._server

    def _remote(self) -> PairedClient:
        if self._client is None:
            self._client = PairedClient(self.root / "companion-connection.json", credentials=self._credentials)
        return self._client

    def _export_invitation(self, server: PairedServer, destination: str) -> dict[str, Any]:
        target = bind_output_target(destination)
        if target.existed:
            raise PairingError("Invitation destination already exists; choose a new file")
        invitation = server.invitation()
        payload = json.dumps(invitation, ensure_ascii=True).encode("utf-8")
        if len(payload) > 16 * 1024:
            raise PairingError("Invitation exceeds its transfer limit")
        descriptor, name = tempfile.mkstemp(prefix=".mariana-invitation-", dir=target.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if self._closed.is_set():
                raise PairingError("Companion service is closed")
            target.activate(temporary)
        finally:
            temporary.unlink(missing_ok=True)
        return {"invitation_saved": True, "fingerprint": invitation["endpoint"]["fingerprint"],
                "notice": "Share only with the intended device. Verify the fingerprint independently. Expires in five minutes."}

    def _perform(self, operation: str, arguments: tuple[Any, ...]) -> Any:
        if operation == "host":
            service, server = self._host()
            service.update_status(self._snapshot())
            endpoint = server.start(arguments[0], port=arguments[1])
            with self._lock:
                self._listener_running = True
            return {"address": endpoint.address, "port": endpoint.port, "fingerprint": endpoint.fingerprint,
                    "notice": "Read-only companion enabled for this run. No firewall or router configuration was changed."}
        if operation == "stop":
            if self._server is not None:
                complete = self._server.close()
                running = self._server.running
                with self._lock:
                    self._listener_running = running
                if complete is not True:
                    raise PairingError("Companion resource cleanup did not complete; retry stop")
            with self._lock:
                self._listener_running = False
            return {"listener_running": False}
        if operation in {"invite", "requests", "approve", "reject", "devices", "revoke"}:
            service, server = self._host()
            if operation == "invite":
                return self._export_invitation(server, arguments[0])
            if operation == "requests":
                return service.pending()
            if operation == "devices":
                return service.trust.devices()
            if operation == "approve":
                service.approve(arguments[0], verified_proof=arguments[1])
                return {"approved": arguments[0], "permissions": ["status.read"]}
            if operation == "reject":
                service.reject(arguments[0])
                return {"rejected": arguments[0]}
            service.trust.revoke(arguments[0])
            return {"revoked": arguments[0]}
        if operation == "cancel":
            if self._client is not None:
                self._client.cancel_pending()
            return {"pending_cancelled": True}
        client = self._remote()
        if operation == "connect":
            invitation = _read_document(Path(arguments[0]).expanduser(), limit=16 * 1024)
            return client.begin(invitation, verified_fingerprint=arguments[1], label=arguments[2])
        if operation == "poll":
            return client.poll()
        if operation == "disconnect":
            client.disconnect()
            return {"disconnected": True, "notice": "The host must separately revoke this device to remove host trust."}
        return client.status()

    def _run(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    operation, arguments = self._pending.get(timeout=.25)
                except queue.Empty:
                    # Only this worker reads transport state. A slow lifecycle
                    # lock or unavailable snapshot must not block cached status.
                    with suppress(Exception):
                        running = bool(self._server and self._server.running)
                        with self._lock:
                            self._listener_running = running
                        if self._service is not None and running:
                            self._service.update_status(self._snapshot())
                    continue
                with self._lock:
                    if self._closed.is_set():
                        self._pending.task_done()
                        break
                    self._result["state"] = "working"
                try:
                    result = self._perform(operation, arguments)
                except Exception as error:
                    message = (_clean_display_text(str(error), maximum=240)
                               if isinstance(error, (PairingError, OutputTargetError)) else None) or _OPERATION_ERROR
                    with self._lock:
                        if not self._closed.is_set():
                            self._result.update(state="error", result=None, error=message)
                else:
                    with self._lock:
                        if not self._closed.is_set():
                            self._result.update(state="ready", result=result, error=None)
                finally:
                    self._pending.task_done()
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        """Run only on the control worker or a serialized cleanup retry worker."""
        complete = True
        try:
            if self._server is not None:
                complete = self._server.close() is True
        except Exception:
            complete = False
        try:
            if self._client is not None:
                self._client.cancel_pending()
        except Exception:
            complete = False
        with self._lock:
            self._cleanup_complete = complete
            if complete:
                self._listener_running = False
                if self._closed.is_set():
                    self._result["error"] = None
            elif self._closed.is_set():
                self._result["error"] = "Companion resource cleanup did not complete"

    def close(self, timeout: float = 2.0) -> bool:
        with self._lock:
            if not self._closed.is_set():
                self._result["error"] = None
            self._closed.set()
            self._result.update(state="closed", result=None)
            worker = self._worker
            while True:
                try:
                    self._pending.get_nowait()
                except queue.Empty:
                    break
                self._pending.task_done()
            if worker is not None and not worker.is_alive() and not self._cleanup_complete:
                # Retry only on a later explicit close, never concurrently with
                # unfinished control work or by blocking the caller on I/O.
                retry = threading.Thread(target=self._cleanup, name="mariana-companion-cleanup", daemon=True)
                try:
                    retry.start()
                except RuntimeError:
                    self._result["error"] = "Companion resource cleanup did not complete"
                else:
                    worker = self._worker = retry
        try:
            budget = float(timeout)
        except (ValueError, TypeError, OverflowError):
            budget = 0.0
        budget = max(0.0, min(budget, 5.0)) if math.isfinite(budget) else 0.0
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=budget)
        return worker is None or (not worker.is_alive() and self._cleanup_complete)
