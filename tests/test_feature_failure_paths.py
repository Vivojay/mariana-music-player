import builtins
import subprocess
import threading
import time
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest
import requests

from mariana import broadcast, credentials, loudness
from mariana.broadcast import BroadcastError, BroadcastProfile, BroadcastState, IcecastBroadcaster, ProgramRing
from mariana.credentials import CredentialError, CredentialStore, ListenerAuthTunnel
from mariana.loudness import LoudnessProfile, ReplayGainMode


class MemoryCredentials:
    def __init__(self, value="password"):
        self.value = value

    def get(self, _reference):
        return self.value


@pytest.mark.parametrize(
    "changes",
    [
        {"bitrate_kbps": 8},
        {"username": "bad:name"},
        {"station_name": "bad\nname"},
        {"mount": "relative"},
        {"server_url": "https://example.test?token=nope"},
    ],
)
def test_broadcast_profile_rejects_every_unsafe_field(changes):
    values = {"name": "p", "server_url": "https://example.test", "mount": "/stream"}
    values.update(changes)
    with pytest.raises(BroadcastError):
        BroadcastProfile(**values).validate()


def test_snapshot_mp3_command_ring_bytes_and_nonblocking_drop(monkeypatch):
    snapshot = broadcast.BroadcastSnapshot(BroadcastState.LIVE, "p", "mp3", 192, 1, 2, "Title")
    assert snapshot.to_dict()["state"] == "live"
    profile = BroadcastProfile("p", "https://example.test", "/stream", codec="mp3", public=True)
    monkeypatch.setattr(broadcast, "find_executable", lambda *_args: "ffmpeg")
    broadcaster = IcecastBroadcaster({"p": profile}, credentials=MemoryCredentials())
    command = broadcaster._command(profile, 1234)
    assert "libmp3lame" in command and "audio/mpeg" in command and "1" in command
    broadcaster.offer(np.ones((1, 2), dtype=np.float32), 1)  # Idle offers are discarded.
    assert broadcaster.ring.read(timeout=0) is None

    ring = ProgramRing(blocks=2, frames_per_block=2)
    ring.write(np.ones((3, 2), dtype=np.float32).tobytes(), 3)
    assert len(ring.read()) == 16 and len(ring.read()) == 8
    ring.write(b"", 0)
    assert ring.dropped == 1
    ring._lock.acquire()
    try:
        ring.write(np.ones((1, 2), dtype=np.float32), 1)
    finally:
        ring._lock.release()
    assert ring.dropped == 2
    ring.clear()


class ReceiveStream:
    def __init__(self, *values):
        self.values = iter(values)
        self.sent = []
        self.closed = False

    def recv(self, _size):
        return next(self.values, b"")

    def sendall(self, value):
        self.sent.append(value)

    def settimeout(self, _value):
        pass

    def close(self):
        self.closed = True


class ScriptedStream(ReceiveStream):
    def recv(self, _size):
        value = next(self.values, b"")
        if isinstance(value, BaseException):
            raise value
        return value


def test_icecast_tunnel_header_and_rejection_failures(monkeypatch):
    with pytest.raises(OSError, match="closed"):
        broadcast.IcecastAuthTunnel._read_headers(ReceiveStream(b""))
    with pytest.raises(OSError, match="oversized"):
        broadcast.IcecastAuthTunnel._read_headers(ReceiveStream(b"x" * 65_537))

    profile = BroadcastProfile("p", "http://example.test", "/stream")
    tunnel = broadcast.IcecastAuthTunnel(profile, MemoryCredentials())
    invalid = ReceiveStream(b"GET / HTTP/1.1\r\n\r\n")
    with pytest.raises(OSError, match="Unexpected"):
        tunnel._relay(invalid)
    assert invalid.closed

    upstream = ReceiveStream(b"HTTP/1.1 409 Conflict\r\n\r\n")
    monkeypatch.setattr(broadcast.socket, "create_connection", lambda *_args, **_kwargs: upstream)
    client = ReceiveStream(b"PUT /local HTTP/1.1\r\nHost: local\r\n\r\n")
    with pytest.raises(OSError, match="status 409"):
        tunnel._relay(client)
    assert upstream.closed and client.closed

    no_secret = broadcast.IcecastAuthTunnel(profile, MemoryCredentials(None))
    upstream = ReceiveStream()
    monkeypatch.setattr(broadcast.socket, "create_connection", lambda *_args, **_kwargs: upstream)
    with pytest.raises(CredentialError, match="No credential"):
        no_secret._relay(ReceiveStream(b"SOURCE / HTTP/1.1\r\n\r\n"))

    secure = broadcast.IcecastAuthTunnel(
        BroadcastProfile("p", "https://example.test", "/stream"), MemoryCredentials()
    )
    upstream = ReceiveStream(b"HTTP/1.1 401 Unauthorized\r\n\r\n")
    context = SimpleNamespace(wrap_socket=lambda stream, **_kwargs: stream)
    monkeypatch.setattr(broadcast.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(broadcast.socket, "create_connection", lambda *_args, **_kwargs: upstream)
    with pytest.raises(OSError, match="401"):
        secure._relay(ReceiveStream(b"PUT / HTTP/1.1\r\n\r\n"))


def test_icecast_serve_records_transport_errors_after_timeout():
    class Server:
        def __init__(self): self.calls = 0
        def accept(self):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            raise OSError("closed")

    tunnel = broadcast.IcecastAuthTunnel(
        BroadcastProfile("p", "http://example.test", "/stream"), MemoryCredentials()
    )
    tunnel._server = Server()
    tunnel._serve()
    assert "closed" in tunnel.error


def test_icecast_relay_covers_bidirectional_timeout_and_payload(monkeypatch):
    upstream = ScriptedStream(
        b"HTTP/1.1 200 OK\r\n\r\n",
        TimeoutError(),
        b"server-data",
        b"",
    )
    client = ScriptedStream(
        b"PUT /local HTTP/1.1\r\nHost: local\r\n\r\n",
        TimeoutError(),
        b"client-data",
        b"",
    )
    monkeypatch.setattr(broadcast.socket, "create_connection", lambda *_args, **_kwargs: upstream)

    class ImmediateThread:
        def __init__(self, target, args=(), **_kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(broadcast.threading, "Thread", ImmediateThread)
    tunnel = broadcast.IcecastAuthTunnel(
        BroadcastProfile("p", "http://example.test", "/stream"), MemoryCredentials()
    )
    tunnel._relay(client)
    assert b"server-data" in client.sent
    assert b"client-data" in upstream.sent


def test_broadcaster_start_reconnect_cleanup_and_metadata_failures(monkeypatch):
    profile = BroadcastProfile("p", "https://example.test", "/stream")
    broadcaster = IcecastBroadcaster({"p": profile}, credentials=MemoryCredentials(None))
    with pytest.raises(BroadcastError, match="Unknown"):
        broadcaster.start("missing")
    with pytest.raises(BroadcastError, match="No credential"):
        broadcaster.start("p")
    assert not broadcaster.metadata("No active profile")

    class FailingTunnel:
        def __init__(self, *_args):
            pass

        def start(self):
            raise BroadcastError("rejected")

    states = []
    broadcaster = IcecastBroadcaster(
        {"p": profile}, credentials=MemoryCredentials(), tunnel_factory=FailingTunnel,
        on_update=lambda item: states.append(item.state),
    )
    broadcaster.RECONNECT_DELAYS = (0.01,)
    broadcaster.start("p")
    deadline = time.monotonic() + 1
    while BroadcastState.RECONNECTING not in states and time.monotonic() < deadline:
        time.sleep(0.005)
    assert BroadcastState.RECONNECTING in states
    with pytest.raises(BroadcastError, match="already active"):
        broadcaster.start("p")
    broadcaster.stop()
    broadcaster.stop()

    class Process:
        stdin = BytesIO()
        waits = 0

        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout):
            self.waits += 1
            if self.waits < 3:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)
            return 0
        def kill(self): self.killed = True

    process = Process()
    broadcaster._process = process
    broadcaster._job = SimpleNamespace(close=lambda: states.append("job-closed"))
    broadcaster._close_attempt()
    assert process.killed and "job-closed" in states

    broadcaster._profile = profile
    broadcaster._state = BroadcastState.LIVE
    broadcaster.credentials = MemoryCredentials(None)
    assert not broadcaster.metadata("Title")
    broadcaster.credentials = MemoryCredentials()
    broadcaster._last_metadata_update = 0
    monkeypatch.setattr(broadcast.requests, "get", lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.Timeout()))
    assert not broadcaster.metadata("Another title")
    assert "Metadata update failed" in broadcaster.snapshot().error


@pytest.mark.parametrize("tunnel_error", ["rejected", None])
def test_broadcaster_connection_error_and_timeout_branches(monkeypatch, tunnel_error):
    class Tunnel:
        connected = SimpleNamespace(wait=lambda _timeout: False)
        error = tunnel_error
        def __init__(self, *_args): pass
        def start(self): return 1
        def close(self): pass

    class Process:
        _handle = 1
        stdin = BytesIO()
        stderr = BytesIO()
        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout=None): return 0
        def kill(self): pass

    monkeypatch.setattr(broadcast, "find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr(broadcast, "WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))
    profile = BroadcastProfile("p", "https://example.test", "/stream")
    broadcaster = IcecastBroadcaster(
        {"p": profile}, credentials=MemoryCredentials(), tunnel_factory=Tunnel,
        process_factory=lambda *_args, **_kwargs: Process(),
    )
    broadcaster._profile = profile
    monkeypatch.setattr(broadcaster._stop, "wait", lambda _delay: True)
    broadcaster._run()
    assert broadcaster.snapshot().state == BroadcastState.IDLE


def test_broadcaster_missing_stdin_process_error_and_test_states(monkeypatch):
    class Tunnel:
        connected = SimpleNamespace(wait=lambda _timeout: True)
        error = None
        def __init__(self, *_args): pass
        def start(self): return 1
        def close(self): pass

    class Process:
        _handle = 1
        stdin = None
        stderr = BytesIO(b"encoder rejected")
        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout=None): return 0
        def kill(self): pass

    monkeypatch.setattr(broadcast, "find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr(broadcast, "WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))
    profile = BroadcastProfile("p", "https://example.test", "/stream")
    broadcaster = IcecastBroadcaster(
        {"p": profile}, credentials=MemoryCredentials(), tunnel_factory=Tunnel,
        process_factory=lambda *_args, **_kwargs: Process(),
    )
    broadcaster._profile = profile
    monkeypatch.setattr(broadcaster._stop, "wait", lambda _delay: True)
    broadcaster._run()
    assert broadcaster.snapshot().state == BroadcastState.IDLE

    broadcaster = IcecastBroadcaster({"p": profile}, credentials=MemoryCredentials())
    monkeypatch.setattr(broadcaster, "start", lambda _name: setattr(broadcaster, "_state", BroadcastState.LIVE))
    monkeypatch.setattr(broadcaster, "stop", lambda: None)
    assert broadcaster.test("p", timeout=0.1)
    monkeypatch.setattr(broadcaster, "start", lambda _name: setattr(broadcaster, "_state", BroadcastState.FAILED))
    assert not broadcaster.test("p", timeout=0.1)
    monkeypatch.setattr(broadcaster, "start", lambda _name: setattr(broadcaster, "_state", BroadcastState.CONNECTING))
    assert not broadcaster.test("p", timeout=0)
    assert not broadcaster.test("p", timeout=0.06)


def test_credential_store_all_keyring_paths(monkeypatch):
    store = CredentialStore()

    class Error(Exception):
        pass

    values = {}
    backend = SimpleNamespace(
        get_password=lambda _service, reference: values.get(reference),
        set_password=lambda _service, reference, value: values.__setitem__(reference, value),
        delete_password=lambda _service, reference: values.pop(reference),
    )
    monkeypatch.setattr(store, "_keyring", lambda: (backend, Error))
    store.set("ref", "secret")
    assert store.get("ref") == "secret"
    assert store.status("ref")["available"]
    assert store.delete("missing") is False
    assert store.delete("ref") is True
    with pytest.raises(CredentialError, match="empty"):
        store.set("ref", "")
    with pytest.raises(CredentialError):
        credentials.environment_name("!!!")

    broken = SimpleNamespace(get_password=lambda *_args: (_ for _ in ()).throw(Error()))
    monkeypatch.setattr(store, "_keyring", lambda: (broken, Error))
    with pytest.raises(CredentialError, match="unavailable"):
        store.get("ref")

    real_import = builtins.__import__
    monkeypatch.setattr(
        builtins,
        "__import__",
        lambda name, *args, **kwargs: (_ for _ in ()).throw(ImportError())
        if name == "keyring" else real_import(name, *args, **kwargs),
    )
    with pytest.raises(CredentialError, match="dependency"):
        CredentialStore._keyring()


def test_real_keyring_module_contract_is_importable():
    keyring, error = CredentialStore._keyring()
    assert callable(keyring.get_password) and issubclass(error, Exception)


def test_credential_delete_backend_error(monkeypatch):
    class Error(Exception):
        pass

    backend = SimpleNamespace(get_password=lambda *_args: "exists", delete_password=lambda *_args: (_ for _ in ()).throw(Error()))
    store = CredentialStore()
    monkeypatch.setattr(store, "_keyring", lambda: (backend, Error))
    with pytest.raises(CredentialError, match="rejected"):
        store.delete("ref")


def test_listener_tunnel_rejects_invalid_requests_and_missing_secrets():
    with pytest.raises(CredentialError, match="HTTP"):
        ListenerAuthTunnel("ftp://example.test", "u", "r")
    tunnel = ListenerAuthTunnel("https://example.test/private", "u", "r", MemoryCredentials(None))
    with pytest.raises(CredentialError, match="No credential"):
        tunnel.start()
    with pytest.raises(OSError, match="closed"):
        ListenerAuthTunnel._headers(ReceiveStream(b""))
    with pytest.raises(OSError, match="oversized"):
        ListenerAuthTunnel._headers(ReceiveStream(b"x" * 65_537))
    tunnel = ListenerAuthTunnel("http://example.test/private", "u", "r", MemoryCredentials())
    client = ReceiveStream(b"POST /stream HTTP/1.1\r\n\r\n")
    with pytest.raises(OSError, match="Unexpected"):
        tunnel._relay(client)
    assert client.closed


def test_listener_serve_error_tls_and_missing_secret_branches(monkeypatch):
    tunnel = ListenerAuthTunnel("http://example.test/private", "u", "r", MemoryCredentials())

    class Server:
        def __init__(self): self.calls = 0
        def accept(self):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            return ReceiveStream(b"POST / HTTP/1.1\r\n\r\n"), None

    tunnel._server = Server()
    thread = threading.Thread(target=tunnel._serve)
    thread.start()
    deadline = time.monotonic() + 1
    while tunnel.error is None and time.monotonic() < deadline:
        time.sleep(0.005)
    tunnel._stop.set()
    thread.join(1)
    assert "Unexpected" in tunnel.error

    secure = ListenerAuthTunnel("https://example.test/private", "u", "r", MemoryCredentials(None))
    upstream = ReceiveStream()
    context = SimpleNamespace(wrap_socket=lambda stream, **_kwargs: stream)
    monkeypatch.setattr(credentials.ssl, "create_default_context", lambda: context)
    monkeypatch.setattr(credentials.socket, "create_connection", lambda *_args, **_kwargs: upstream)
    with pytest.raises(CredentialError, match="No credential"):
        secure._relay(ReceiveStream(b"GET / HTTP/1.1\r\n\r\n"))

    server = SimpleNamespace(accept=lambda: (_ for _ in ()).throw(OSError("closed")))
    tunnel = ListenerAuthTunnel("http://example.test", "u", "r", MemoryCredentials())
    tunnel._server = server
    tunnel._serve()


def test_listener_relay_handles_timeout_payload_and_eof(monkeypatch):
    upstream = ScriptedStream(TimeoutError(), b"audio", b"")
    client = ScriptedStream(b"GET /stream HTTP/1.1\r\nIcy-MetaData: 1\r\n\r\n")
    monkeypatch.setattr(credentials.socket, "create_connection", lambda *_args, **_kwargs: upstream)
    tunnel = ListenerAuthTunnel("http://example.test/private", "u", "r", MemoryCredentials())
    tunnel._relay(client)
    assert b"audio" in client.sent


def test_loudness_remaining_policy_and_analyzer_errors(tmp_path, monkeypatch):
    profile = LoudnessProfile("track", album_gain_db=-2)
    assert not profile.has_track and profile.has_album
    assert loudness.effective_gain_db(profile, ReplayGainMode.TRACK) == 0
    assert loudness.effective_gain_db(
        LoudnessProfile("track", track_gain_db=30, track_peak=0.2),
        ReplayGainMode.TRACK,
        preamp_db=99,
        prevent_clipping=False,
    ) == 24
    analyzer = loudness.RSGainAnalyzer()
    assert analyzer.analyze([]) == {}
    monkeypatch.setattr(loudness, "find_tool_executable", lambda *_args: None)
    with pytest.raises(loudness.LoudnessError, match="not found"):
        analyzer.analyze([tmp_path / "x.wav"])
    monkeypatch.setattr(loudness, "find_tool_executable", lambda *_args: "rsgain")
    monkeypatch.setattr(
        loudness.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("rsgain", 1)),
    )
    with pytest.raises(loudness.LoudnessError, match="failed"):
        analyzer.analyze([tmp_path / "x.wav"])
    monkeypatch.setattr(loudness.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout="", stderr=""))
    with pytest.raises(loudness.LoudnessError, match="no usable"):
        analyzer.analyze([tmp_path / "x.wav"])


def test_listener_and_source_tunnel_empty_accept_and_current_thread_close(monkeypatch):
    class StopAfterOne:
        def __init__(self):
            self.calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls > 1

        def set(self):
            pass

    listener = ListenerAuthTunnel("http://example.test/private", "u", "r", MemoryCredentials())
    listener._stop = StopAfterOne()
    listener._server = None
    listener._serve()
    listener._thread = threading.current_thread()
    listener.close()

    source = broadcast.IcecastAuthTunnel(
        BroadcastProfile("p", "http://example.test", "/stream"),
        MemoryCredentials(),
    )
    source._stop = StopAfterOne()
    source._server = None
    source._serve()
    source._thread = threading.current_thread()
    source.close()


def test_broadcast_feed_and_cleanup_faults_are_isolated(monkeypatch):
    broadcaster = IcecastBroadcaster(
        {"p": BroadcastProfile("p", "http://example.test", "/stream")},
        credentials=MemoryCredentials(),
    )

    class MissingInput:
        stdin = None

        def poll(self):
            return None

    broadcaster._feed_encoder(MissingInput(), b"silence")
    assert "unavailable" in (broadcaster._feed_error or "")

    class BrokenInput:
        def close(self):
            raise OSError("closed")

    class BrokenProcess:
        stdin = BrokenInput()

        def __init__(self):
            self.killed = False

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    process = BrokenProcess()
    broadcaster._process = process
    broadcaster._close_attempt()
    assert process.killed

    broadcaster._thread = threading.current_thread()
    broadcaster._state = BroadcastState.LIVE
    broadcaster.stop()
    assert broadcaster.snapshot().state == BroadcastState.IDLE

    broadcaster._stop.set()
    broadcaster._feed_error = None
    broadcaster._feed_encoder(MissingInput(), b"silence")
    assert broadcaster._feed_error is None
