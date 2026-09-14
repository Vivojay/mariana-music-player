"""Transient video tracks and bounded public-file transport, never renderer data."""

from __future__ import annotations

import http.client
import ipaddress
import re
import secrets
import socket
import ssl
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

if TYPE_CHECKING:
    from .provider_captions import ProviderCaptionCandidate

MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_PROXY_BYTES = 4 * 1024 * 1024 * 1024
_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class VideoSourceError(ValueError):
    """A static, display-safe video-source error."""


@dataclass(frozen=True, slots=True)
class VideoTrack:
    uri: str = field(repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    codec: str | None = None
    format_id: str | None = None
    container: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None


@dataclass(frozen=True, slots=True)
class VideoTracks:
    """Selected tracks from one resolution; credentials are transient and private."""

    video: VideoTrack
    audio: VideoTrack | None = None
    duration: float | None = None
    expires_at: float | None = None
    captions: tuple[ProviderCaptionCandidate, ...] = field(default=(), repr=False)


def _connection(url: str) -> tuple[http.client.HTTPConnection, str]:
    """Pin a validated public address, retaining hostname TLS verification."""
    parsed = urlsplit(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or any(ord(char) < 32 for char in url)):
        raise VideoSourceError("Video requires a public HTTP or HTTPS file")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    answers = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    addresses = list(dict.fromkeys(str(answer[4][0]) for answer in answers))
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise VideoSourceError("Private network video references are not supported")
    # Connect to the checked address, not a second DNS lookup of the hostname.
    sock = socket.create_connection((addresses[0], port), timeout=5)
    try:
        if parsed.scheme == "https":
            context = ssl.create_default_context()
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            sock = context.wrap_socket(sock, server_hostname=parsed.hostname)
        sock.settimeout(5)
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=5)
        connection.sock = sock
        return connection, (parsed.path or "/") + (f"?{parsed.query}" if parsed.query else "")
    except BaseException:
        sock.close()
        raise


def _request_headers(track: VideoTrack) -> dict[str, str]:
    headers = {"User-Agent": "Mariana-Video/1", "Accept": "*/*", "Accept-Encoding": "identity"}
    for key, value in track.headers.items():
        if key.casefold() in {"cookie", "authorization", "proxy-authorization"}:
            raise VideoSourceError("This video requires an unsupported authenticated transport")
        if key.casefold() in {"user-agent", "referer", "origin", "accept"}:
            if len(value) > 8192 or any(ord(char) < 32 for char in value):
                raise VideoSourceError("Video request metadata is invalid")
            headers[key] = value
    return headers


def _open_response(
    track: VideoTrack,
    method: str,
    cancel: threading.Event,
    deadline: float,
    *,
    byte_range: str | None = None,
) -> tuple[http.client.HTTPConnection, http.client.HTTPResponse]:
    headers = _request_headers(track)
    if byte_range is not None:
        if _RANGE.fullmatch(byte_range) is None:
            raise VideoSourceError("Video byte range is invalid")
        headers["Range"] = byte_range
    url = track.uri
    for redirect in range(4):
        if cancel.is_set() or time.monotonic() >= deadline:
            raise VideoSourceError("Video retrieval was cancelled or timed out")
        connection, target = _connection(url)
        try:
            # DNS/TLS setup may outlive the budget or a user's cancellation.
            # Do not send a new request after that work finally returns.
            if cancel.is_set() or time.monotonic() >= deadline:
                raise VideoSourceError("Video retrieval was cancelled or timed out")
            connection.request(method, target, headers=headers)
            response = connection.getresponse()
            if response.status not in {301, 302, 303, 307, 308}:
                return connection, response
            location = response.getheader("Location")
            if not location or redirect == 3:
                raise VideoSourceError("Video redirected too many times")
            next_url = urljoin(url, location)
            if urlsplit(url).scheme == "https" and urlsplit(next_url).scheme != "https":
                raise VideoSourceError("Video redirect would downgrade transport security")
            if urlsplit(url).netloc != urlsplit(next_url).netloc:
                headers = {"User-Agent": "Mariana-Video/1", "Accept": "*/*", "Accept-Encoding": "identity"}
                if byte_range is not None:
                    headers["Range"] = byte_range
            url = next_url
            connection.close()
        except BaseException:
            connection.close()
            raise
    raise VideoSourceError("Video redirected too many times")


def _validate_media_response(response: http.client.HTTPResponse, *, ranged: bool) -> int | None:
    if response.status in {401, 403, 410}:
        raise VideoSourceError("Video access expired or requires authorization; retry video mode")
    if response.status not in ({200, 206} if ranged else {200}):
        raise VideoSourceError("The video provider could not supply a finite file")
    content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
    if content_type.startswith("text/") or content_type in {
        "application/vnd.apple.mpegurl", "application/x-mpegurl", "application/dash+xml",
    }:
        raise VideoSourceError("Streaming manifests are not supported by this video transport yet")
    length = response.getheader("Content-Length")
    try:
        expected = int(length) if length is not None else None
    except ValueError:
        raise VideoSourceError("Video response length is invalid") from None
    limit = MAX_PROXY_BYTES if ranged else MAX_INPUT_BYTES
    if expected is not None and not 0 < expected <= limit:
        raise VideoSourceError("Video response exceeds its transfer limit")
    return expected


def fetch_video_file(track: VideoTrack, destination: Path, cancel: threading.Event) -> None:
    """Retrieve one finite file with a hard byte limit and cooperative time budget.

    Media tools subsequently see only this local file, never a remote manifest.
    Cookies/authorization are deliberately unsupported by this first transport.
    OS DNS lookup cannot be interrupted; cancellation is rechecked before sending.
    """
    deadline = time.monotonic() + 120
    try:
        connection, response = _open_response(track, "GET", cancel, deadline)
        try:
            expected = _validate_media_response(response, ranged=False)
            size = 0
            with destination.open("xb") as output:
                while True:
                    if cancel.is_set() or time.monotonic() > deadline:
                        raise VideoSourceError("Video retrieval was cancelled or timed out")
                    chunk = response.read1(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_INPUT_BYTES:
                        raise VideoSourceError("Video exceeds the 512 MiB input-cache limit")
                    output.write(chunk)
            if not size or (expected is not None and size != expected):
                raise VideoSourceError("The video file was incomplete")
        finally:
            connection.close()
    except VideoSourceError:
        raise
    except Exception:
        raise VideoSourceError("Video retrieval failed; audio playback is unchanged") from None


class _TrackProxy:
    def __init__(self, track: VideoTrack, cancel: threading.Event) -> None:
        self.track = track
        self.cancel = cancel
        self.token = secrets.token_urlsafe(24)
        self.transferred = 0
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_HEAD(self) -> None:
                owner.handle(self, include_body=False)

            def do_GET(self) -> None:
                owner.handle(self, include_body=True)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name="mariana-video-transport", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/{self.token}/media"

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def handle(self, handler: BaseHTTPRequestHandler, *, include_body: bool) -> None:
        if handler.path != f"/{self.token}/media" or self.cancel.is_set():
            handler.send_error(404)
            return
        byte_range = handler.headers.get("Range")
        if byte_range is not None and _RANGE.fullmatch(byte_range) is None:
            handler.send_error(416)
            return
        connection: http.client.HTTPConnection | None = None
        sent_headers = False
        try:
            deadline = time.monotonic() + 40
            connection, response = _open_response(
                self.track, "GET", self.cancel, deadline, byte_range=byte_range,
            )
            expected = _validate_media_response(response, ranged=True)
            if byte_range is not None:
                match = _RANGE.fullmatch(byte_range)
                assert match is not None
                start = int(match.group(1) or 0)
                if start > 0 and response.status != 206:
                    raise VideoSourceError("The video provider does not support bounded seeking")
            handler.send_response(response.status)
            for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "ETag", "Last-Modified"):
                value = response.getheader(name)
                if value:
                    handler.send_header(name, value)
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Connection", "close")
            handler.end_headers()
            sent_headers = True
            handler.close_connection = True
            if not include_body:
                return
            size = 0
            while True:
                if self.cancel.is_set() or time.monotonic() > deadline:
                    raise VideoSourceError("Video retrieval was cancelled or timed out")
                chunk = response.read1(64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                with self.lock:
                    self.transferred += len(chunk)
                    if self.transferred > MAX_PROXY_BYTES:
                        raise VideoSourceError("Video session exceeded its transfer limit")
                handler.wfile.write(chunk)
            if expected is not None and size != expected:
                raise VideoSourceError("The video response was incomplete")
        except (BrokenPipeError, ConnectionResetError):
            return
        except VideoSourceError:
            if not sent_headers:
                handler.send_error(502)
            handler.close_connection = True
        except Exception:
            handler.close_connection = True
        finally:
            if connection is not None:
                connection.close()


@contextmanager
def video_track_proxy(track: VideoTrack, cancel: threading.Event) -> Iterator[str]:
    """Expose one private remote track to media tools through a bounded loopback handle."""
    proxy = _TrackProxy(track, cancel)
    proxy.start()
    try:
        yield proxy.url
    finally:
        proxy.close()
