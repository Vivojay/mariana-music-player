"""Supervised Icecast source broadcasting from Mariana's pre-local-volume program bus."""

from __future__ import annotations

import base64
import os
import socket
import ssl
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any, cast
from urllib.parse import quote, urlencode, urlparse

import numpy as np
import requests

from .credentials import CredentialError, CredentialStore
from .playback import CHANNELS, CREATE_NO_WINDOW, SAMPLE_RATE, WindowsJob, find_executable


class BroadcastError(RuntimeError):
    pass


class BroadcastState(StrEnum):
    IDLE = "idle"
    CONNECTING = "connecting"
    LIVE = "live"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    STOPPING = "stopping"


@dataclass(frozen=True, slots=True)
class BroadcastProfile:
    name: str
    server_url: str
    mount: str
    username: str = "source"
    credential_ref: str | None = None
    codec: str = "opus"
    bitrate_kbps: int = 128
    station_name: str = "Mariana"
    description: str = "Broadcast by Mariana"
    genre: str = "Music"
    public: bool = False

    @classmethod
    def from_mapping(cls, name: str, value: dict[str, Any]) -> BroadcastProfile:
        profile = cls(
            name=name,
            server_url=str(value.get("server url") or ""),
            mount=str(value.get("mount") or ""),
            username=str(value.get("username") or "source"),
            credential_ref=str(value.get("credential reference") or name),
            codec=str(value.get("codec") or "opus").casefold(),
            bitrate_kbps=int(value.get("bitrate kbps") or 128),
            station_name=str(value.get("station name") or "Mariana"),
            description=str(value.get("description") or "Broadcast by Mariana"),
            genre=str(value.get("genre") or "Music"),
            public=bool(value.get("public", False)),
        )
        profile.validate()
        return profile

    def validate(self) -> None:
        parsed = urlparse(self.server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise BroadcastError(f"Broadcast profile {self.name!r} requires an HTTP(S) server URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise BroadcastError("Broadcast server URLs cannot contain credentials, query strings, or fragments")
        if not self.mount.startswith("/") or ".." in self.mount or any(char in self.mount for char in "?#\r\n"):
            raise BroadcastError("Icecast mounts must be absolute paths without traversal or query data")
        if self.codec not in {"opus", "mp3"}:
            raise BroadcastError("Broadcast codec must be opus or mp3")
        if not 16 <= self.bitrate_kbps <= 320:
            raise BroadcastError("Broadcast bitrate must be between 16 and 320 kbps")
        if not self.username or any(char in self.username for char in "\r\n:"):
            raise BroadcastError("Broadcast username is invalid")
        if any("\r" in value or "\n" in value for value in (self.station_name, self.description, self.genre)):
            raise BroadcastError("Broadcast metadata cannot contain line breaks")

    @property
    def reference(self) -> str:
        return self.credential_ref or self.name


@dataclass(frozen=True, slots=True)
class BroadcastSnapshot:
    state: BroadcastState
    profile: str | None = None
    codec: str | None = None
    bitrate_kbps: int | None = None
    reconnects: int = 0
    dropped_blocks: int = 0
    title: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value


class ProgramRing:
    """Preallocated nonblocking PCM ring; stale audio is dropped to bound latency."""

    def __init__(self, blocks: int = 64, frames_per_block: int = 2048):
        self.frames_per_block = frames_per_block
        self._data = np.zeros((blocks, frames_per_block, CHANNELS), dtype=np.float32)
        self._sizes = np.zeros(blocks, dtype=np.int32)
        self._read = 0
        self._write = 0
        self._count = 0
        self._lock = threading.Lock()
        self._ready = threading.Condition(self._lock)
        self.dropped = 0

    def write(self, samples: object, frames: int) -> None:
        if frames <= 0 or not self._lock.acquire(blocking=False):
            self.dropped += 1
            return
        try:
            if isinstance(samples, np.ndarray):
                source = samples
            else:
                source = np.frombuffer(cast(Any, samples), dtype=np.float32).reshape(-1, CHANNELS)
            offset = 0
            remaining = min(frames, source.shape[0])
            while remaining:
                count = min(remaining, self.frames_per_block)
                if self._count == len(self._data):
                    self._read = (self._read + 1) % len(self._data)
                    self._count -= 1
                    self.dropped += 1
                np.copyto(self._data[self._write, :count], source[offset : offset + count], casting="unsafe")
                self._sizes[self._write] = count
                self._write = (self._write + 1) % len(self._data)
                self._count += 1
                offset += count
                remaining -= count
            self._ready.notify()
        finally:
            self._lock.release()

    def read(self, timeout: float = 0.25) -> bytes | None:
        with self._ready:
            if not self._count:
                self._ready.wait(timeout)
            if not self._count:
                return None
            index = self._read
            size = int(self._sizes[index])
            self._read = (self._read + 1) % len(self._data)
            self._count -= 1
            return self._data[index, :size].tobytes()

    def clear(self) -> None:
        with self._ready:
            self._read = self._write = self._count = 0
            self._ready.notify_all()


class IcecastAuthTunnel:
    """Inject upstream authorization inside Mariana so FFmpeg never sees secrets."""

    def __init__(self, profile: BroadcastProfile, credentials: CredentialStore):
        self.profile = profile
        self.credentials = credentials
        self.connected = threading.Event()
        self.error: str | None = None
        self._stop = threading.Event()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self._server.settimeout(0.5)
        port = int(self._server.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name="mariana-icecast-tunnel", daemon=True)
        self._thread.start()
        return port

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    client, _address = self._server.accept() if self._server else (None, None)
                except TimeoutError:
                    continue
                if client:
                    self._relay(client)
                    return
        except (OSError, CredentialError) as error:
            self.error = f"Icecast transport failed: {error}"

    @staticmethod
    def _read_headers(stream: socket.socket) -> tuple[bytes, bytes]:
        payload = bytearray()
        while b"\r\n\r\n" not in payload:
            chunk = stream.recv(4096)
            if not chunk:
                raise OSError("The encoder closed before sending headers")
            payload.extend(chunk)
            if len(payload) > 65_536:
                raise OSError("The encoder sent oversized headers")
        head, body = bytes(payload).split(b"\r\n\r\n", 1)
        return head, body

    def _relay(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            head, body = self._read_headers(client)
            lines = head.split(b"\r\n")
            if not lines or not lines[0].startswith((b"PUT ", b"SOURCE ")):
                raise OSError("Unexpected local encoder request")
            parsed = urlparse(self.profile.server_url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            upstream = socket.create_connection((parsed.hostname, port), timeout=10)
            if parsed.scheme == "https":
                upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=parsed.hostname)
            password = self.credentials.get(self.profile.reference)
            if not password:
                raise CredentialError(f"No credential is available for profile {self.profile.name!r}")
            authorization = base64.b64encode(f"{self.profile.username}:{password}".encode()).decode("ascii")
            request_method = lines[0].split(b" ", 1)[0]
            forwarded = [request_method + b" " + self.profile.mount.encode("ascii") + b" HTTP/1.1"]
            forwarded.extend(
                line for line in lines[1:]
                if not line.lower().startswith((b"authorization:", b"host:", b"connection:"))
            )
            forwarded.extend([
                f"Host: {parsed.hostname}:{port}".encode("ascii"),
                f"Authorization: Basic {authorization}".encode("ascii"),
                b"Connection: close",
            ])
            upstream.sendall(b"\r\n".join(forwarded) + b"\r\n\r\n" + body)
            response_head, response_body = self._read_headers(upstream)
            status_line = response_head.split(b"\r\n", 1)[0]
            match = status_line.split(b" ", 2)
            if len(match) < 2 or not match[1].isdigit() or not 200 <= int(match[1]) < 300:
                code = match[1].decode("ascii", errors="replace") if len(match) > 1 else "invalid"
                raise OSError(f"Icecast rejected the source connection with status {code}")
            client.sendall(response_head + b"\r\n\r\n" + response_body)
            self.connected.set()
            client.settimeout(1)
            upstream.settimeout(1)

            response = threading.Thread(
                target=self._relay_responses,
                args=(client, upstream),
                name="mariana-icecast-response",
                daemon=True,
            )
            response.start()
            while not self._stop.is_set():
                try:
                    data = client.recv(65_536)
                except TimeoutError:
                    continue
                if not data:
                    break
                upstream.sendall(data)
        finally:
            try:
                client.close()
            finally:
                if upstream:
                    upstream.close()

    def _relay_responses(self, client: socket.socket, upstream: socket.socket) -> None:
        try:
            while not self._stop.is_set():
                try:
                    data = upstream.recv(16_384)
                except TimeoutError:
                    continue
                if not data:
                    break
                client.sendall(data)
        except OSError:
            pass

    def close(self) -> None:
        self._stop.set()
        if self._server:
            self._server.close()
            self._server = None
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


class IcecastBroadcaster:
    RECONNECT_DELAYS = (1, 2, 5, 15, 30)

    def __init__(
        self,
        profiles: dict[str, BroadcastProfile],
        *,
        ffmpeg_bin: str | None = None,
        credentials: CredentialStore | None = None,
        process_factory: Callable[..., subprocess.Popen] = subprocess.Popen,
        tunnel_factory: Callable[[BroadcastProfile, CredentialStore], IcecastAuthTunnel] = IcecastAuthTunnel,
        on_update: Callable[[BroadcastSnapshot], None] | None = None,
    ):
        self.profiles = profiles
        self.ffmpeg_bin = ffmpeg_bin
        self.credentials = credentials or CredentialStore()
        self.process_factory = process_factory
        self.tunnel_factory = tunnel_factory
        self.on_update = on_update
        self.ring = ProgramRing()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = BroadcastState.IDLE
        self._profile: BroadcastProfile | None = None
        self._process: subprocess.Popen | None = None
        self._job: WindowsJob | None = None
        self._tunnel: IcecastAuthTunnel | None = None
        self._feed_thread: threading.Thread | None = None
        self._feed_error: str | None = None
        self._reconnects = 0
        self._title: str | None = None
        self._error: str | None = None
        self._last_metadata_update = 0.0
        self._accept_audio = threading.Event()
        self.configuration_errors: dict[str, str] = {}

    @classmethod
    def from_settings(cls, value: dict[str, Any], **kwargs) -> IcecastBroadcaster:
        profiles: dict[str, BroadcastProfile] = {}
        errors: dict[str, str] = {}
        for name, mapping in (value.get("profiles") or {}).items():
            try:
                profiles[name] = BroadcastProfile.from_mapping(name, mapping)
            except (BroadcastError, TypeError, ValueError) as error:
                errors[name] = str(error)
        instance = cls(profiles, **kwargs)
        instance.configuration_errors = errors
        return instance

    def offer(self, samples: object, frames: int) -> None:
        if self._accept_audio.is_set():
            self.ring.write(samples, frames)

    def start(self, name: str) -> None:
        try:
            profile = self.profiles[name]
        except KeyError as error:
            raise BroadcastError(f"Unknown broadcast profile: {name}") from error
        profile.validate()
        if not self.credentials.get(profile.reference):
            raise BroadcastError(f"No credential is available for broadcast profile {name!r}")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise BroadcastError("A broadcast is already active")
            self._profile = profile
            self._state = BroadcastState.CONNECTING
            self._error = None
            self._reconnects = 0
            self._stop.clear()
            self._accept_audio.set()
            self.ring.clear()
            self._thread = threading.Thread(target=self._run, name="mariana-broadcast", daemon=True)
            self._thread.start()
        self._emit()

    def _command(self, profile: BroadcastProfile, port: int) -> list[str]:
        executable = find_executable("ffmpeg", self.ffmpeg_bin)
        codec = ["-c:a", "libopus", "-application", "audio", "-f", "ogg"] if profile.codec == "opus" else [
            "-c:a", "libmp3lame", "-f", "mp3",
        ]
        content_type = "audio/ogg" if profile.codec == "opus" else "audio/mpeg"
        return [
            executable, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "-i", "pipe:0",
            "-vn", *codec, "-b:a", f"{profile.bitrate_kbps}k",
            "-content_type", content_type,
            "-ice_name", profile.station_name,
            "-ice_description", profile.description,
            "-ice_genre", profile.genre,
            "-ice_public", "1" if profile.public else "0",
            f"icecast://127.0.0.1:{port}{quote(profile.mount, safe='/')}",
        ]

    def _run(self) -> None:
        assert self._profile
        profile = self._profile
        failure_count = 0
        while not self._stop.is_set():
            try:
                tunnel = self.tunnel_factory(profile, self.credentials)
                port = tunnel.start()
                process = self.process_factory(
                    self._command(profile, port),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    creationflags=CREATE_NO_WINDOW,
                    start_new_session=os.name != "nt",
                )
                with self._lock:
                    self._tunnel = tunnel
                    self._process = process
                    self._job = WindowsJob(process)
                silence = np.zeros((1024, CHANNELS), dtype=np.float32).tobytes()
                if not process.stdin:
                    raise BroadcastError("FFmpeg broadcast input is unavailable")
                self._feed_error = None
                self._feed_thread = threading.Thread(
                    target=self._feed_encoder,
                    args=(process, silence),
                    name="mariana-broadcast-pcm",
                    daemon=True,
                )
                self._feed_thread.start()
                if tunnel.connected.wait(10):
                    self._set_state(BroadcastState.LIVE)
                    failure_count = 0
                elif tunnel.error:
                    raise BroadcastError(tunnel.error)
                else:
                    raise BroadcastError("Icecast connection timed out")
                while not self._stop.wait(0.1) and process.poll() is None and self._feed_error is None:
                    pass
                if not self._stop.is_set():
                    if self._feed_error:
                        raise BroadcastError(self._feed_error)
                    stderr = process.stderr.read(4096).decode("utf-8", errors="replace") if process.stderr else ""
                    raise BroadcastError(stderr.strip() or tunnel.error or "The Icecast encoder disconnected")
            except (OSError, ValueError, subprocess.SubprocessError, BroadcastError) as error:
                if self._stop.is_set():
                    break
                failure_count += 1
                with self._lock:
                    self._reconnects += 1
                    self._error = str(error)[:1000]
                self._set_state(BroadcastState.RECONNECTING)
                delay = self.RECONNECT_DELAYS[min(failure_count - 1, len(self.RECONNECT_DELAYS) - 1)]
                if self._stop.wait(delay):
                    break
            finally:
                self._close_attempt()
        self._set_state(BroadcastState.IDLE)

    def _feed_encoder(self, process: subprocess.Popen, silence: bytes) -> None:
        try:
            while not self._stop.is_set() and process.poll() is None:
                payload = self.ring.read(timeout=1024 / SAMPLE_RATE) or silence
                if not process.stdin:
                    raise OSError("FFmpeg broadcast input is unavailable")
                process.stdin.write(payload)
        except (OSError, ValueError) as error:
            if not self._stop.is_set():
                self._feed_error = f"FFmpeg broadcast input failed: {error}"

    def _close_attempt(self) -> None:
        with self._lock:
            process, tunnel, job, feed = self._process, self._tunnel, self._job, self._feed_thread
            self._process = self._tunnel = self._job = self._feed_thread = None
        if process and process.poll() is None:
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            except OSError:
                if process.poll() is None:
                    process.kill()
        if feed and feed is not threading.current_thread():
            feed.join(timeout=2)
        if tunnel:
            tunnel.close()
        if job:
            job.close()

    def _set_state(self, state: BroadcastState) -> None:
        with self._lock:
            self._state = state
        self._emit()

    def _emit(self) -> None:
        if self.on_update:
            self.on_update(self.snapshot())

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            if not thread or not thread.is_alive():
                self._state = BroadcastState.IDLE
                return
            self._state = BroadcastState.STOPPING
            self._stop.set()
            self._accept_audio.clear()
        self._emit()
        self._close_attempt()
        if thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            self._thread = None
            self._profile = None
            self._state = BroadcastState.IDLE
        self.ring.clear()
        self._emit()

    close = stop

    def metadata(self, title: str | None) -> bool:
        with self._lock:
            profile = self._profile
            if not profile or self._state not in {BroadcastState.LIVE, BroadcastState.RECONNECTING}:
                return False
            if title == self._title or time.monotonic() - self._last_metadata_update < 1:
                return False
            self._title = title
            self._last_metadata_update = time.monotonic()
        password = self.credentials.get(profile.reference)
        if not password:
            return False
        endpoint = profile.server_url.rstrip("/") + "/admin/metadata?" + urlencode({
            "mount": profile.mount, "mode": "updinfo", "song": title or "Mariana",
        })
        try:
            response = requests.get(
                endpoint,
                auth=(profile.username, password),
                timeout=(5, 10),
                allow_redirects=False,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            with self._lock:
                self._error = f"Metadata update failed: {error.__class__.__name__}"
            self._emit()
            return False
        self._emit()
        return True

    def snapshot(self) -> BroadcastSnapshot:
        with self._lock:
            profile = self._profile
            return BroadcastSnapshot(
                self._state,
                profile.name if profile else None,
                profile.codec if profile else None,
                profile.bitrate_kbps if profile else None,
                self._reconnects,
                self.ring.dropped,
                self._title,
                self._error,
            )

    def test(self, name: str, timeout: float = 15) -> bool:
        self.start(name)
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                state = self.snapshot().state
                if state == BroadcastState.LIVE:
                    return True
                if state == BroadcastState.FAILED:
                    return False
                time.sleep(0.05)
            return False
        finally:
            self.stop()
