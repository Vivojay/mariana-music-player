"""Best-effort Discord Rich Presence over the desktop client's local RPC."""

from __future__ import annotations

import importlib
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from mariana.presence import PresenceProjection


class DiscordPresenceFailureCode(StrEnum):
    NOT_CONFIGURED = "not_configured"
    SDK_UNAVAILABLE = "sdk_unavailable"
    CLIENT_UNAVAILABLE = "client_unavailable"
    TRANSPORT_ERROR = "transport_error"


class DiscordConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RETRYING = "retrying"
    CLOSED = "closed"


@dataclass(frozen=True, slots=True)
class DiscordPresenceStatus:
    state: DiscordConnectionState
    failure_code: DiscordPresenceFailureCode | None = None
    message: str | None = None
    last_success_at: float | None = None


class _DiscordTransport(Protocol):
    def update(self, **values: Any) -> Any: ...

    def clear(self) -> Any: ...

    def close(self) -> Any: ...


TransportFactory = Callable[[str], _DiscordTransport]


def _default_transport(application_id: str) -> _DiscordTransport:
    try:
        module = importlib.import_module("pypresence")
    except ImportError as error:
        raise RuntimeError("the local Discord RPC library is unavailable") from error
    transport = module.Presence(application_id)
    transport.connect()
    return transport


class DiscordPresencePublisher:
    """Latest-wins local RPC publisher with bounded retries and no user secrets."""

    def __init__(
        self,
        application_id: str | None,
        *,
        transport_factory: TransportFactory = _default_transport,
        minimum_interval: float = 15.0,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 5.0, 15.0, 30.0, 60.0),
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self._application_id = str(application_id or "").strip()
        self._transport_factory = transport_factory
        self._minimum_interval = max(0.0, minimum_interval)
        self._retry_delays = retry_delays or (60.0,)
        self._monotonic = monotonic
        self._wall_time = wall_time
        self._condition = threading.Condition()
        self._transport: _DiscordTransport | None = None
        self._pending = False
        self._projection: PresenceProjection | None = None
        self._disconnect_after = False
        self._urgent = False
        self._stopping = False
        self._thread: threading.Thread | None = None
        self._last_update = float("-inf")
        self._status = DiscordPresenceStatus(DiscordConnectionState.DISCONNECTED)

    def status(self) -> DiscordPresenceStatus:
        with self._condition:
            return self._status

    def _set_status(
        self,
        state: DiscordConnectionState,
        code: DiscordPresenceFailureCode | None = None,
        message: str | None = None,
        *,
        success: bool = False,
    ) -> None:
        last_success = self._wall_time() if success else self._status.last_success_at
        self._status = DiscordPresenceStatus(state, code, message, last_success)

    def _ensure_worker(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(target=self._run, name="mariana-discord-presence", daemon=True)
            self._thread.start()

    def publish(self, projection: PresenceProjection) -> None:
        self._ensure_worker()
        with self._condition:
            self._projection = projection
            self._disconnect_after = False
            self._pending = True
            self._condition.notify_all()

    def clear(self, *, disconnect: bool = False) -> None:
        with self._condition:
            if self._transport is None and not (self._thread and self._thread.is_alive()):
                return
        self._ensure_worker()
        with self._condition:
            self._projection = None
            self._disconnect_after = disconnect
            self._urgent = True
            self._pending = True
            self._condition.notify_all()

    def refresh(self) -> None:
        with self._condition:
            self._last_update = float("-inf")
            self._pending = self._projection is not None
            self._urgent = True
            self._condition.notify_all()

    @staticmethod
    def _payload(projection: PresenceProjection) -> dict[str, Any]:
        values: dict[str, Any] = {
            "details": projection.details,
            "state": projection.state,
            "start": projection.start_timestamp,
            "end": projection.end_timestamp,
        }
        try:
            module = importlib.import_module("pypresence")
            values["activity_type"] = module.ActivityType.LISTENING
        except (AttributeError, ImportError):
            pass
        return {key: value for key, value in values.items() if value is not None}

    def _disconnect(self) -> None:
        transport = self._transport
        self._transport = None
        if transport is not None:
            with suppress(Exception):
                transport.close()

    def _connect(self) -> bool:
        if self._transport is not None:
            return True
        if not self._application_id:
            self._set_status(
                DiscordConnectionState.DISCONNECTED,
                DiscordPresenceFailureCode.NOT_CONFIGURED,
                "Mariana's Discord application ID is not configured in this build.",
            )
            return False
        self._set_status(DiscordConnectionState.CONNECTING)
        try:
            self._transport = self._transport_factory(self._application_id)
        except RuntimeError as error:
            code = (
                DiscordPresenceFailureCode.SDK_UNAVAILABLE
                if "library is unavailable" in str(error)
                else DiscordPresenceFailureCode.CLIENT_UNAVAILABLE
            )
            self._set_status(DiscordConnectionState.RETRYING, code, str(error))
            return False
        except Exception:
            self._set_status(
                DiscordConnectionState.RETRYING,
                DiscordPresenceFailureCode.CLIENT_UNAVAILABLE,
                "Discord desktop is unavailable or local RPC could not be opened.",
            )
            return False
        self._set_status(DiscordConnectionState.CONNECTED)
        return True

    def _run(self) -> None:
        retry_index = 0
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._stopping)
                if self._stopping:
                    break
                projection = self._projection
                disconnect_after = self._disconnect_after
                urgent = self._urgent
                self._pending = False
                self._urgent = False

            if projection is None and self._transport is None:
                continue
            if not urgent:
                wait_for = self._minimum_interval - (self._monotonic() - self._last_update)
                if wait_for > 0:
                    with self._condition:
                        self._condition.wait(timeout=wait_for)
                        if self._pending or self._stopping:
                            continue
            if projection is not None and not self._connect():
                delay = self._retry_delays[min(retry_index, len(self._retry_delays) - 1)]
                retry_index += 1
                with self._condition:
                    self._pending = True
                    self._condition.wait(timeout=delay)
                continue
            try:
                if self._transport is not None:
                    if projection is None:
                        self._transport.clear()
                    else:
                        self._transport.update(**self._payload(projection))
                    self._last_update = self._monotonic()
                    retry_index = 0
                    self._set_status(DiscordConnectionState.CONNECTED, success=True)
                if disconnect_after:
                    self._disconnect()
                    self._set_status(DiscordConnectionState.DISCONNECTED)
            except Exception:
                self._disconnect()
                self._set_status(
                    DiscordConnectionState.RETRYING,
                    DiscordPresenceFailureCode.TRANSPORT_ERROR,
                    "Discord rejected or lost the local Rich Presence connection.",
                )
                if projection is not None:
                    delay = self._retry_delays[min(retry_index, len(self._retry_delays) - 1)]
                    retry_index += 1
                    with self._condition:
                        self._pending = True
                        self._condition.wait(timeout=delay)

        transport = self._transport
        self._transport = None
        if transport is not None:
            with suppress(Exception):
                transport.clear()
            with suppress(Exception):
                transport.close()
        with self._condition:
            self._set_status(DiscordConnectionState.CLOSED)

    def close(self, timeout: float = 1.0) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(max(0.0, min(timeout, 1.0)))
