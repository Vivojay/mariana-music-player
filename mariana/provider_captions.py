"""Ephemeral provider caption choices; downloading always requires selection."""

from __future__ import annotations

import contextlib
import hashlib
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import islice
from urllib.parse import urlsplit

from .captions import (
    MAX_CAPTION_BYTES,
    MAX_CAPTION_TRACKS,
    CaptionError,
    CaptionTrack,
    _safe_label,
    caption_language,
    parse_captions,
)
from .video_sources import VideoTrack, _open_response, _request_headers

PROVIDER_CAPTION_TIMEOUT = 15.0


@dataclass(frozen=True, slots=True)
class ProviderCaptionCandidate:
    key: str
    label: str
    language: str | None
    source: str
    codec: str
    transport: VideoTrack = field(repr=False)

    def projection(self) -> dict[str, object]:
        return {"id": self.key, "label": self.label, "language": self.language,
                "source": self.source, "codec": self.codec, "default": False, "forced": False}


def provider_caption_tracks(info: Mapping[str, object]) -> tuple[ProviderCaptionCandidate, ...]:
    """Keep one supported text encoding per provider language/kind, without I/O.

    A key identifies a choice within the current resolution only. Credentials,
    signed URLs and original provider objects never enter public projections.
    """
    result: list[ProviderCaptionCandidate] = []
    common = info.get("http_headers")
    for field_name, source in (("subtitles", "provider"), ("automatic_captions", "provider-generated")):
        catalogue = info.get(field_name)
        if not isinstance(catalogue, Mapping):
            continue
        for raw_language, rows in islice(catalogue.items(), 128):
            if len(result) >= MAX_CAPTION_TRACKS:
                return tuple(result)
            if not isinstance(raw_language, str) or not isinstance(rows, list):
                continue
            language = None
            with contextlib.suppress(CaptionError):
                language = caption_language(raw_language)
            # Live chat and provider-specific event streams are not subtitles.
            if language is None:
                continue
            supported = [row for row in rows[:32] if isinstance(row, Mapping)
                         and isinstance(row.get("ext"), str) and row["ext"] in {"vtt", "srt"}
                         and isinstance(row.get("url"), str)]
            supported.sort(key=lambda row: row["ext"] != "vtt")
            for row in supported:
                uri = str(row["url"])
                try:
                    parsed = urlsplit(uri)
                    if (not 0 < len(uri) <= 16384 or parsed.scheme not in {"http", "https"}
                            or not parsed.hostname or parsed.username is not None or parsed.password is not None
                            or any(ord(char) < 32 for char in uri)):
                        continue
                    if isinstance(common, Mapping) and len(common) > 64:
                        continue
                    headers = dict(common) if isinstance(common, Mapping) else {}
                    specific = row.get("http_headers")
                    if isinstance(specific, Mapping):
                        if len(specific) > 64:
                            continue
                        headers.update(specific)
                    if any(not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items()):
                        continue
                    transport = VideoTrack(uri, headers)
                    # Keep only the existing transport allowlist, and reject authentication without I/O.
                    transport = VideoTrack(uri, _request_headers(transport))
                except (ValueError, TypeError):
                    continue
                name = row.get("name")
                label = _safe_label((name if isinstance(name, str) and name else raw_language)[:512])
                label = label.replace(chr(127), "")
                label = _safe_label(f"{label[:85]} ({'generated' if source == 'provider-generated' else 'provider'})")
                key = hashlib.sha256(f"{source}:{raw_language}:{row['ext']}:{uri}".encode()).hexdigest()[:32]
                result.append(ProviderCaptionCandidate(key, label, language, source, str(row["ext"]), transport))
                break
    return tuple(result)


def load_provider_caption(candidate: ProviderCaptionCandidate, cancel: threading.Event) -> CaptionTrack:
    """Fetch selected public text in memory with pinned DNS, limits and safe errors."""
    deadline = time.monotonic() + PROVIDER_CAPTION_TIMEOUT
    try:
        connection, response = _open_response(candidate.transport, "GET", cancel, deadline)
        try:
            if response.status != 200:
                raise CaptionError(
                    "Provider captions unavailable or expired; choose Audio only, then Video, and select again"
                )
            encoding = (response.getheader("Content-Encoding") or "identity").lower()
            content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].lower()
            if encoding != "identity" or content_type not in {
                "", "text/vtt", "text/plain", "text/srt", "application/x-subrip",
                "application/srt", "application/octet-stream",
            }:
                raise CaptionError("Provider did not return supported caption text")
            length = response.getheader("Content-Length")
            expected = int(length) if length is not None else None
            if expected is not None and not 0 < expected <= MAX_CAPTION_BYTES:
                raise CaptionError("Provider captions exceed the 2 MiB limit")
            data = bytearray()
            while True:
                if cancel.is_set() or time.monotonic() >= deadline:
                    raise CaptionError("Caption retrieval was cancelled or timed out")
                chunk = response.read1(min(65536, MAX_CAPTION_BYTES + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > MAX_CAPTION_BYTES:
                    raise CaptionError("Provider captions exceed the 2 MiB limit")
            if not data or (expected is not None and len(data) != expected):
                raise CaptionError("Provider captions were incomplete")
            if cancel.is_set() or time.monotonic() >= deadline:
                raise CaptionError("Caption retrieval was cancelled or timed out")
            return parse_captions(data.decode("utf-8-sig"), label=candidate.label, source=candidate.source)
        finally:
            connection.close()
    except CaptionError:
        raise
    except Exception:
        raise CaptionError("Provider captions could not be retrieved; playback is unchanged") from None
