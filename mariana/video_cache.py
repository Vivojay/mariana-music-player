"""Session-only, bounded source-picture cache. Never stores remote references on disk."""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler

from .video_sources import MAX_PROXY_BYTES, VideoSourceError, VideoTrack, _open_response, _TrackProxy

BLOCK_BYTES = 256 * 1024
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)")
_REQUEST_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class VideoByteCache:
    """One representation, an LRU byte budget, and serialized cache misses.

    The miss lock coalesces overlapping main/Mini requests. It is never acquired
    by the playback/control thread. Only one 256 KiB source request runs at once.
    """

    def __init__(self, *, limit_mib: int = 64, idle_seconds: int = 600,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = max(16, min(256, int(limit_mib))) * 1024 * 1024
        self.idle_seconds = max(30, min(1800, int(idle_seconds)))
        self.clock = clock
        self.last_used = clock()
        self.blocks: OrderedDict[int, bytes] = OrderedDict()
        self.size = 0
        self.total = 0
        self.mime = "video/mp4"
        self.validator: str | None = None
        self.track: VideoTrack | None = None
        self.downloaded = 0
        self.reused = 0
        self._lock = threading.RLock()
        self._miss = threading.Lock()
        self._epoch = 0

    def clear(self) -> None:
        with self._lock:
            self.blocks.clear()
            self.size = 0
            self._epoch += 1

    def expired(self) -> bool:
        return self.clock() - self.last_used >= self.idle_seconds

    def statistics(self) -> dict[str, int]:
        with self._lock:
            return {"cached_bytes": self.size, "limit_bytes": self.limit,
                    "downloaded_bytes": self.downloaded, "reused_bytes": self.reused,
                    "idle_seconds": self.idle_seconds}

    @staticmethod
    def _descriptor(response, start: int, end: int | None = None) -> tuple[int, int, str | None, str]:
        if response.status in {401, 403, 410}:
            raise VideoSourceError("Video access expired; select Video again. Audio is unchanged")
        match = _CONTENT_RANGE.fullmatch(response.getheader("Content-Range") or "")
        if response.status != 206 or match is None:
            raise VideoSourceError("Video requires verified byte-range support")
        first, last, total = map(int, match.groups())
        if (first != start or not first <= last < total <= MAX_PROXY_BYTES
                or (end is not None and last != min(end, total - 1))
                or response.getheader("Content-Length") != str(last - first + 1)):
            raise VideoSourceError("Video provider returned an inconsistent range")
        mime = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
        if mime not in {"video/mp4", "video/webm", "application/octet-stream"}:
            raise VideoSourceError("Video provider returned an unsupported file type")
        encoding = response.getheader("Content-Encoding")
        if encoding and encoding.lower() != "identity":
            raise VideoSourceError("Compressed video transport is unsupported")
        etag = response.getheader("ETag")
        validator = etag if etag and len(etag) <= 256 and not etag.startswith("W/") else None
        return total, last, validator, mime

    def bind(self, track: VideoTrack, cancel: threading.Event) -> None:
        """Validate a freshly resolved representation before reusing any bytes."""
        connection, response = _open_response(track, "GET", cancel, time.monotonic() + 15,
                                              byte_range="bytes=0-0")
        try:
            total, _, validator, _mime = self._descriptor(response, 0, 0)
            if len(response.read(2)) != 1 or cancel.is_set():
                raise VideoSourceError("Video metadata range is incomplete or cancelled")
        finally:
            connection.close()
        with self._lock:
            previous = self.track
            same_format = previous is not None and (
                previous.format_id, previous.codec, previous.container, previous.width, previous.height, previous.fps
            ) == (track.format_id, track.codec, track.container, track.width, track.height, track.fps)
            # Without a strong validator only the very same resolved URL is reusable.
            reusable = (previous is not None and same_format and total == self.total and not self.expired()
                        and ((validator is not None and validator == self.validator)
                             or (validator is None and self.validator is None and previous.uri == track.uri)))
            if not reusable:
                self.clear()
            self.track, self.total, self.validator = track, total, validator
            self.mime = "video/webm" if track.container == "webm" else "video/mp4"
            self.last_used = self.clock()
            self.downloaded += 1

    def block(self, index: int, cancel: threading.Event) -> bytes:
        while not self._miss.acquire(timeout=0.05):
            if cancel.is_set():
                raise VideoSourceError("Video retrieval was cancelled")
        try:
            with self._lock:
                if cancel.is_set():
                    raise VideoSourceError("Video retrieval was cancelled")
                self.last_used = self.clock()
                if index in self.blocks:
                    self.blocks.move_to_end(index)
                    result = self.blocks[index]
                    self.reused += len(result)
                    return result
                track, epoch = self.track, self._epoch
                start = index * BLOCK_BYTES
                end = min(start + BLOCK_BYTES, self.total) - 1
                if track is None or not 0 <= start <= end:
                    raise VideoSourceError("Video byte range is unavailable")
                if self.downloaded + end - start + 1 > MAX_PROXY_BYTES:
                    raise VideoSourceError("Video transfer budget reached; audio remains available")
            connection, response = _open_response(track, "GET", cancel, time.monotonic() + 15,
                                                  byte_range=f"bytes={start}-{end}")
            try:
                total, _, validator, _mime = self._descriptor(response, start, end)
                if total != self.total or validator != self.validator:
                    self.clear()
                    raise VideoSourceError("Video source changed; select Video again")
                chunks = bytearray()
                deadline = self.clock() + 15
                while len(chunks) < end - start + 1:
                    if cancel.is_set() or self.clock() > deadline:
                        raise VideoSourceError("Video retrieval was cancelled or timed out")
                    chunk = response.read1(min(64 * 1024, end - start + 1 - len(chunks)))
                    if not chunk:
                        raise VideoSourceError("Video provider returned an incomplete range")
                    chunks.extend(chunk)
                    with self._lock:
                        self.downloaded += len(chunk)
                result = bytes(chunks)
            finally:
                connection.close()
            with self._lock:
                if cancel.is_set() or epoch != self._epoch:
                    raise VideoSourceError("Video retrieval was cancelled")
                while self.blocks and self.size + len(result) > self.limit:
                    _, removed = self.blocks.popitem(last=False)
                    self.size -= len(removed)
                self.blocks[index] = result
                self.size += len(result)
            return result
        finally:
            self._miss.release()


class CachedVideoProxy(_TrackProxy):
    """Host-only capability; the renderer receives neither this URL nor the provider URL."""

    def __init__(self, cache: VideoByteCache, cancel: threading.Event,
                 on_error: Callable[[str], None] | None = None) -> None:
        assert cache.track is not None
        super().__init__(cache.track, cancel)
        self.cache = cache
        self.on_error = on_error
        self._clients = threading.BoundedSemaphore(4)

    def handle(self, handler: BaseHTTPRequestHandler, *, include_body: bool) -> None:
        if handler.path != f"/{self.token}/media" or self.cancel.is_set():
            handler.send_error(404)
            return
        if not self._clients.acquire(blocking=False):
            handler.send_error(503)
            return
        sent_headers = False
        try:
            raw = handler.headers.get("Range")
            matched = _REQUEST_RANGE.fullmatch(raw) if raw else None
            total = self.cache.total
            if raw and (matched is None or not any(matched.groups())):
                handler.send_error(416)
                return
            start = int(matched[1]) if matched and matched[1] else (
                max(0, total - int(matched[2])) if matched else 0)
            end = min(total - 1, int(matched[2])) if matched and matched[1] and matched[2] else total - 1
            if not 0 <= start <= end < total:
                handler.send_error(416)
                return
            # Check availability before committing response headers.
            first = self.cache.block(start // BLOCK_BYTES, self.cancel) if include_body else b""
            handler.send_response(206 if raw else 200)
            handler.send_header("Content-Type", self.cache.mime)
            handler.send_header("Content-Length", str(end - start + 1))
            handler.send_header("Accept-Ranges", "bytes")
            handler.send_header("Cache-Control", "no-store")
            handler.send_header("Connection", "close")
            if raw:
                handler.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            handler.end_headers()
            sent_headers = True
            handler.close_connection = True
            if include_body:
                while start <= end and not self.cancel.is_set():
                    data = first or self.cache.block(start // BLOCK_BYTES, self.cancel)
                    first = b""
                    offset = start % BLOCK_BYTES
                    count = min(len(data) - offset, end - start + 1)
                    handler.wfile.write(data[offset:offset + count])
                    handler.wfile.flush()
                    start += count
        except VideoSourceError as error:
            if not self.cancel.is_set() and self.on_error is not None:
                self.on_error(str(error))
            if not sent_headers:
                handler.send_error(502)
            handler.close_connection = True
        except OSError:
            if not sent_headers:
                handler.send_error(502)
            handler.close_connection = True
        finally:
            self._clients.release()
