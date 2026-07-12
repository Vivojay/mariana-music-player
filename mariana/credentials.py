"""OS-keychain backed credential references; secrets are never persisted by Mariana."""

from __future__ import annotations

import base64
import os
import re
import socket
import ssl
import threading
from urllib.parse import urlparse

SERVICE_NAME = "io.github.vivojay.mariana.icecast"


class CredentialError(RuntimeError):
    pass


def environment_name(reference: str) -> str:
    normalized = re.sub(r"[^A-Z0-9]+", "_", reference.upper()).strip("_")
    if not normalized:
        raise CredentialError("Credential references must contain a letter or number")
    return f"MARIANA_ICECAST_PASSWORD_{normalized}"


class CredentialStore:
    def __init__(self, service: str = SERVICE_NAME):
        self.service = service

    @staticmethod
    def _keyring():
        try:
            import keyring
            from keyring.errors import KeyringError
        except ImportError as error:
            raise CredentialError("The keyring dependency is unavailable") from error
        return keyring, KeyringError

    def get(self, reference: str) -> str | None:
        if value := os.environ.get(environment_name(reference)):
            return value
        keyring, keyring_error = self._keyring()
        try:
            return keyring.get_password(self.service, reference)
        except keyring_error as error:
            raise CredentialError("The operating-system credential store is unavailable") from error

    def set(self, reference: str, password: str) -> None:
        if not password:
            raise CredentialError("An empty password is not accepted")
        keyring, keyring_error = self._keyring()
        try:
            keyring.set_password(self.service, reference, password)
        except keyring_error as error:
            raise CredentialError("The operating-system credential store rejected the password") from error

    def delete(self, reference: str) -> bool:
        keyring, keyring_error = self._keyring()
        try:
            if keyring.get_password(self.service, reference) is None:
                return False
            keyring.delete_password(self.service, reference)
        except keyring_error as error:
            raise CredentialError("The operating-system credential store rejected the operation") from error
        return True

    def status(self, reference: str) -> dict[str, str | bool]:
        env = environment_name(reference)
        if os.environ.get(env):
            return {"available": True, "source": "environment", "environment": env}
        return {"available": self.get(reference) is not None, "source": "keyring", "environment": env}


class ListenerAuthTunnel:
    """Loopback HTTP proxy that injects private-stream auth outside FFmpeg arguments."""

    def __init__(self, upstream_url: str, username: str, reference: str, credentials: CredentialStore | None = None):
        parsed = urlparse(upstream_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CredentialError("Authenticated streams must use HTTP or HTTPS")
        self.upstream_url = upstream_url
        self.username = username
        self.reference = reference
        self.credentials = credentials or CredentialStore()
        self._stop = threading.Event()
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self.error: str | None = None

    def start(self) -> str:
        if not self.credentials.get(self.reference):
            raise CredentialError(f"No credential is available for reference {self.reference!r}")
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(2)
        self._server.settimeout(0.5)
        port = int(self._server.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name="mariana-listener-auth", daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{port}/stream"

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                client, _address = self._server.accept() if self._server else (None, None)
            except TimeoutError:
                continue
            except OSError:
                return
            if client:
                try:
                    self._relay(client)
                except (OSError, CredentialError) as error:
                    self.error = f"Private stream transport failed: {error}"

    @staticmethod
    def _headers(stream: socket.socket) -> bytes:
        payload = bytearray()
        while b"\r\n\r\n" not in payload:
            chunk = stream.recv(4096)
            if not chunk:
                raise OSError("The decoder closed before sending HTTP headers")
            payload.extend(chunk)
            if len(payload) > 65_536:
                raise OSError("The decoder sent oversized HTTP headers")
        return bytes(payload)

    def _relay(self, client: socket.socket) -> None:
        upstream: socket.socket | None = None
        try:
            request = self._headers(client)
            head, body = request.split(b"\r\n\r\n", 1)
            lines = head.split(b"\r\n")
            method = lines[0].split(b" ", 1)[0]
            if method not in {b"GET", b"HEAD"}:
                raise OSError("Unexpected private-stream request method")
            parsed = urlparse(self.upstream_url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            upstream = socket.create_connection((parsed.hostname, port), timeout=10)
            if parsed.scheme == "https":
                upstream = ssl.create_default_context().wrap_socket(upstream, server_hostname=parsed.hostname)
            password = self.credentials.get(self.reference)
            if not password:
                raise CredentialError(f"No credential is available for reference {self.reference!r}")
            authorization = base64.b64encode(f"{self.username}:{password}".encode()).decode("ascii")
            target = (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
            forwarded = [method + b" " + target.encode("ascii") + b" HTTP/1.1"]
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
            upstream.settimeout(1)
            while not self._stop.is_set():
                try:
                    chunk = upstream.recv(65_536)
                except TimeoutError:
                    continue
                if not chunk:
                    break
                client.sendall(chunk)
        finally:
            client.close()
            if upstream:
                upstream.close()

    def close(self) -> None:
        self._stop.set()
        if self._server:
            self._server.close()
            self._server = None
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
