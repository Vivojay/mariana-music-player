import base64
import socket
import threading
import time
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import urlparse

import numpy as np
import pytest

from mariana.broadcast import (
    BroadcastError,
    BroadcastProfile,
    BroadcastState,
    IcecastAuthTunnel,
    IcecastBroadcaster,
    ProgramRing,
)
from mariana.credentials import CredentialError, CredentialStore, ListenerAuthTunnel, environment_name


class MemoryCredentials:
    def __init__(self, value="secret-value"):
        self.value = value

    def get(self, _reference):
        return self.value


def profile(**changes):
    values = {
        "name": "home",
        "server_url": "https://radio.example:8443",
        "mount": "/mariana.opus",
    }
    values.update(changes)
    return BroadcastProfile(**values)


def test_profile_validation_and_settings_isolate_bad_profiles():
    profile().validate()
    with pytest.raises(BroadcastError):
        profile(server_url="ftp://example.test").validate()
    with pytest.raises(BroadcastError):
        profile(server_url="https://user:password@example.test").validate()
    with pytest.raises(BroadcastError):
        profile(mount="/../admin").validate()
    with pytest.raises(BroadcastError):
        profile(codec="aac").validate()
    broadcaster = IcecastBroadcaster.from_settings({
        "profiles": {
            "good": {"server url": "https://example.test", "mount": "/stream"},
            "bad": {"server url": "ftp://example.test", "mount": "/stream"},
        }
    })
    assert list(broadcaster.profiles) == ["good"]
    assert "bad" in broadcaster.configuration_errors


def test_program_ring_is_bounded_and_never_accumulates_stale_audio():
    ring = ProgramRing(blocks=2, frames_per_block=2)
    ring.write(np.ones((2, 2), dtype=np.float32), 2)
    ring.write(np.full((2, 2), 2, dtype=np.float32), 2)
    ring.write(np.full((2, 2), 3, dtype=np.float32), 2)
    assert ring.dropped == 1
    assert np.frombuffer(ring.read(), dtype=np.float32)[0] == 2
    assert np.frombuffer(ring.read(), dtype=np.float32)[0] == 3
    assert ring.read(timeout=0) is None


def test_credential_environment_override_and_keyring_errors(monkeypatch):
    reference = "Home Stream"
    variable = environment_name(reference)
    monkeypatch.setenv(variable, "from-environment")
    store = CredentialStore()
    assert store.get(reference) == "from-environment"
    assert store.status(reference)["source"] == "environment"
    monkeypatch.delenv(variable)

    class Error(Exception):
        pass

    backend = SimpleNamespace(get_password=lambda *_args: None, set_password=lambda *_args: (_ for _ in ()).throw(Error()))
    monkeypatch.setattr(store, "_keyring", lambda: (backend, Error))
    with pytest.raises(CredentialError, match="rejected"):
        store.set(reference, "value")


def test_auth_tunnel_injects_secret_only_upstream():
    received = []
    ready = threading.Event()
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def upstream():
        ready.set()
        connection, _address = server.accept()
        payload = bytearray()
        while b"\r\n\r\n" not in payload:
            payload.extend(connection.recv(4096))
        received.append(bytes(payload))
        connection.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n")
        connection.close()
        server.close()

    threading.Thread(target=upstream, daemon=True).start()
    ready.wait(1)
    value = profile(server_url=f"http://127.0.0.1:{port}", username="source-user")
    tunnel = IcecastAuthTunnel(value, MemoryCredentials())
    local_port = tunnel.start()
    client = socket.create_connection(("127.0.0.1", local_port))
    client.sendall(b"PUT /local HTTP/1.1\r\nHost: local\r\nAuthorization: Basic local-only\r\n\r\n")
    assert client.recv(1024).startswith(b"HTTP/1.1 200")
    tunnel.close()
    authorization = base64.b64encode(b"source-user:secret-value")
    assert b"PUT /mariana.opus HTTP/1.1" in received[0]
    assert b"Authorization: Basic " + authorization in received[0]
    assert b"local-only" not in received[0]


def test_listener_tunnel_injects_credentials_without_exposing_upstream_url():
    received = []
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    def upstream():
        connection, _address = server.accept()
        payload = bytearray()
        while b"\r\n\r\n" not in payload:
            payload.extend(connection.recv(4096))
        received.append(bytes(payload))
        connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: audio/mpeg\r\n\r\naudio")
        connection.close()
        server.close()

    threading.Thread(target=upstream, daemon=True).start()
    tunnel = ListenerAuthTunnel(
        f"http://127.0.0.1:{port}/private?channel=one", "listener", "radio:test", MemoryCredentials()
    )
    local = tunnel.start()
    assert "private" not in local and "channel" not in local and "secret-value" not in local
    client = socket.create_connection(("127.0.0.1", urlparse(local).port))
    client.sendall(b"GET /stream HTTP/1.1\r\nHost: local\r\nIcy-MetaData: 1\r\n\r\n")
    assert client.recv(1024).startswith(b"HTTP/1.1 200")
    tunnel.close()
    assert b"GET /private?channel=one HTTP/1.1" in received[0]
    assert b"Icy-MetaData: 1" in received[0]
    assert base64.b64encode(b"listener:secret-value") in received[0]


def test_auth_tunnel_response_relay_stops_without_reading_after_cancellation():
    tunnel = IcecastAuthTunnel(profile(), MemoryCredentials())
    tunnel._stop.set()
    client = SimpleNamespace(sendall=lambda _data: pytest.fail("cancelled relay must not write"))
    upstream = SimpleNamespace(recv=lambda _size: pytest.fail("cancelled relay must not read"))

    tunnel._relay_responses(client, upstream)


class FakeTunnel:
    def __init__(self, _profile, _credentials):
        self.connected = threading.Event()
        self.connected.set()
        self.error = None

    def start(self):
        return 43210

    def close(self):
        pass


class FakeProcess:
    _handle = 1

    def __init__(self):
        self.stdin = BytesIO()
        self.stderr = BytesIO()
        self.running = True

    def poll(self):
        return None if self.running else 0

    def terminate(self):
        self.running = False

    def wait(self, timeout=None):
        del timeout
        self.running = False
        return 0

    def kill(self):
        self.running = False


def test_broadcaster_command_has_no_secret_and_transport_is_independent(monkeypatch):
    created = []
    updates = []

    def factory(command, **_kwargs):
        created.append(command)
        return FakeProcess()

    monkeypatch.setattr("mariana.broadcast.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.broadcast.WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))
    broadcaster = IcecastBroadcaster(
        {"home": profile()}, credentials=MemoryCredentials(), process_factory=factory,
        tunnel_factory=FakeTunnel, on_update=updates.append,
    )
    broadcaster.start("home")
    deadline = time.monotonic() + 1
    while broadcaster.snapshot().state != BroadcastState.LIVE and time.monotonic() < deadline:
        time.sleep(0.01)
    assert broadcaster.snapshot().state == BroadcastState.LIVE
    broadcaster.offer(np.ones((8, 2), dtype=np.float32), 8)
    assert all("secret-value" not in argument for argument in created[0])
    assert created[0][-1] == "icecast://127.0.0.1:43210/mariana.opus"
    broadcaster.stop()
    assert broadcaster.snapshot().state == BroadcastState.IDLE
    assert any(update.state == BroadcastState.LIVE for update in updates)


def test_metadata_updates_are_throttled_and_do_not_expose_password(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

    monkeypatch.setattr("mariana.broadcast.requests.get", lambda url, **kwargs: calls.append((url, kwargs)) or Response())
    broadcaster = IcecastBroadcaster({"home": profile()}, credentials=MemoryCredentials())
    broadcaster._profile = profile()
    broadcaster._state = BroadcastState.LIVE
    assert broadcaster.metadata("Artist - Track")
    assert not broadcaster.metadata("Artist - Track")
    assert calls[0][1]["auth"] == ("source", "secret-value")
    assert "secret-value" not in calls[0][0]
