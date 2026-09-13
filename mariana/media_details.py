"""Media inspection and safe, metadata-derived short filenames."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse, urlunparse

YOUTUBE_ID = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
PLACEHOLDER_METADATA = {
    "unknown",
    "unknown artist",
    "unknown title",
    "youtube audio",
    "youtube video",
    "untitled",
    "untitled youtube media",
    "untitled youtube result",
    "n/a",
    "none",
}
SOURCE_TITLE_KEYS = ("source_title", "youtube_title", "download_title")
SOURCE_CREATOR_KEYS = (
    "source_artist",
    "youtube_artist",
    "source_uploader",
    "source_channel",
    "uploader",
    "channel",
)
EMBEDDED_CREATOR_KEYS = ("artist", "releaser", "distributor", "publisher", "label")
PRIVATE_REFERENCE = re.compile(r"(?:https?://|(?:^|\s)[A-Za-z]:[\\/]|(?:^|\s)/(?:Users|home|private|tmp)/)", re.I)
PROBE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._+-]{0,31}$", re.I)

PROVIDER_METADATA_KEYS = (
    "provider",
    "provider_media_id",
    "publisher",
    "publisher_id",
    "published",
    "views",
    "likes",
    "dislikes",
    "comments",
    "reposts",
    "followers",
    "concurrent_viewers",
)
_PROVIDER_COUNT_KEYS = frozenset(
    {"views", "likes", "dislikes", "comments", "reposts", "followers", "concurrent_viewers"}
)
# Counts cross JSON/desktop boundaries; keep integer precision there.
_MAX_PROVIDER_COUNT = (1 << 53) - 1
_MAX_PROVIDER_TEXT_LENGTH = 512
_MAX_FILE_SIZE = (1 << 63) - 1
_DETAIL_LABELS = {
    "library_id": "Library ID",
    "canonical_path": "Canonical path",
    "provider_media_id": "Provider media ID",
    "publisher_id": "Publisher ID",
}


def display_media_uri(value: str) -> str:
    """Display an online location without authentication or transient queries."""
    try:
        parsed = urlparse(value)
    except ValueError:
        return "[invalid online reference]"
    if parsed.scheme.casefold() not in {"http", "https"}:
        return value
    host = parsed.hostname or ""
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"} and parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return f"https://www.youtube.com/watch?v={video_id}"
    try:
        if ":" in host:
            host = f"[{host}]"
        if parsed.port:
            host += f":{parsed.port}"
    except ValueError:
        return "[invalid online reference]"
    safe = urlunparse((parsed.scheme, host, parsed.path, "", "", ""))
    return safe + (" [query omitted]" if parsed.query else "")


def display_media_error(value: str) -> str:
    """Apply the same URL boundary to provider messages and their log copies."""
    return re.sub(r"https?://[^\s<>\"']+", lambda match: display_media_uri(match.group()), value, flags=re.I)


class MediaDiagnosticLogger:
    """Keep provider diagnostics useful without forwarding private URL data.

    The extractor logger protocol receives already formatted message strings.
    Deliberately accept no exception objects, tracebacks, or extra payloads.
    """

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def debug(self, message: str) -> None:
        self._logger.debug("%s", display_media_error(message))

    def warning(self, message: str) -> None:
        self._logger.warning("%s", display_media_error(message))

    def error(self, message: str) -> None:
        self._logger.error("%s", display_media_error(message))


_PROBE_LABELS = {
    "3g2": "3G2",
    "3gp": "3GP",
    "aac": "AAC",
    "ac3": "AC-3",
    "aiff": "AIFF",
    "alac": "ALAC",
    "eac3": "E-AC-3",
    "flac": "FLAC",
    "m4a": "M4A",
    "matroska": "Matroska",
    "mjpeg": "MJPEG",
    "mj2": "MJ2",
    "mov": "MOV",
    "mp3": "MP3",
    "mp4": "MP4",
    "mpeg": "MPEG",
    "ogg": "Ogg",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "wav": "WAV",
    "webm": "WebM",
    "wma": "WMA",
}


@dataclass(frozen=True, slots=True)
class ShortFilenamePlan:
    filename: str | None
    confidence: str
    source: str
    reason: str | None = None


def format_file_size(value: object) -> str:
    """Return a compact IEC byte size without accepting invalid catalog data."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return "Unknown"
    try:
        size = int(value)
    except (TypeError, ValueError, OverflowError):
        return "Unknown"
    if not 0 <= size <= _MAX_FILE_SIZE:
        return "Unknown"
    if size < 1024:
        return f"{size} B"
    amount = float(size)
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        amount /= 1024
        if amount < 1024 or unit == "TiB":
            rendered = f"{amount:.1f}".rstrip("0").rstrip(".")
            return f"{rendered} {unit}"
    return "Unknown"


def _probe_tokens(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return [
        token.casefold()
        for token in (item.strip() for item in value.split(","))
        if PROBE_TOKEN.fullmatch(token)
    ][:8]


def _probe_label(value: str) -> str:
    return _PROBE_LABELS.get(value, value.upper())


def format_probed_media_type(format_name: object, codec_name: object) -> str:
    """Format FFprobe container/codec facts without consulting the filename suffix."""
    formats = _probe_tokens(format_name)
    codecs = _probe_tokens(codec_name)
    if "webm" in formats:
        container = "WebM"
    elif "mp3" in formats:
        container = "MP3"
    elif "flac" in formats:
        container = "FLAC"
    elif "ogg" in formats:
        container = "Ogg"
    elif "wav" in formats:
        container = "WAV"
    elif any(item in formats for item in ("mp4", "m4a")):
        container = "MP4/M4A"
    elif formats:
        container = "/".join(_probe_label(item) for item in formats[:3])
    else:
        container = ""

    codec = _probe_label(codecs[0]) if codecs else ""
    if codec and codecs[0] not in formats and codec.casefold() != container.casefold():
        return f"{container} / {codec}" if container else codec
    return container or codec or "Unknown"


def clean_component(value: Any, *, fallback: str = "") -> str:
    text = INVALID_FILENAME.sub("-", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .-")
    if text.upper() in RESERVED_NAMES:
        text = f"_{text}"
    return text or fallback


def normalized_provider_metadata(value: object) -> dict[str, str | int]:
    """Allowlist provider facts that are safe to expose through media inspection."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str | int] = {}
    for key in PROVIDER_METADATA_KEYS:
        item = value.get(key)
        if key in _PROVIDER_COUNT_KEYS:
            if isinstance(item, str):
                text = item.strip()
                if not re.fullmatch(r"[0-9]{1,16}", text):
                    continue
                item = int(text)
            if isinstance(item, int) and not isinstance(item, bool) and 0 <= item <= _MAX_PROVIDER_COUNT:
                result[key] = item
            continue
        if not isinstance(item, (str, int)) or isinstance(item, bool):
            continue
        if isinstance(item, int) and not -(10**_MAX_PROVIDER_TEXT_LENGTH) < item < 10**_MAX_PROVIDER_TEXT_LENGTH:
            continue
        text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(item))
        text = re.sub(r"\s+", " ", text).strip()
        if not text or len(text) > _MAX_PROVIDER_TEXT_LENGTH or PRIVATE_REFERENCE.search(text):
            continue
        result[key] = text
    return result


def trusted_metadata_text(value: Any, *, youtube_id: str | None = None) -> str | None:
    """Return a normalized value only when it is safe and not a known placeholder."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or PRIVATE_REFERENCE.search(text):
        return None
    reduced = text
    if youtube_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", youtube_id):
        reduced = re.sub(rf"\s*\[{re.escape(youtube_id)}\]\s*", " ", reduced, flags=re.I)
    reduced = re.sub(r"\s*\[(?:audio|video)\]\s*$", "", reduced, flags=re.I)
    reduced = re.sub(r"^unknown artist\s*-\s*", "", reduced, flags=re.I)
    normalized = re.sub(r"[^a-z0-9]+", " ", reduced.casefold()).strip()
    if normalized in PLACEHOLDER_METADATA:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", reduced.strip(" []")):
        return None
    return text


def _first_trusted(
    metadata: Mapping[str, Any],
    keys: tuple[str, ...],
    *,
    youtube_id: str | None,
) -> tuple[str | None, str | None]:
    for key in keys:
        if value := trusted_metadata_text(metadata.get(key), youtube_id=youtube_id):
            return value, key
    return None, None


def deduplicate_media_title(
    value: Any,
    *,
    creator: str | None = None,
    youtube_id: str | None = None,
) -> str:
    """Remove identity components that the filename builder adds separately."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if youtube_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", youtube_id):
        text = re.sub(
            rf"(?<![A-Za-z0-9_-])\[?{re.escape(youtube_id)}\]?(?![A-Za-z0-9_-])",
            " ",
            text,
            flags=re.I,
        )
    text = re.sub(r"^unknown artist\s*-\s*", "", text, flags=re.I)
    if creator:
        text = re.sub(rf"^{re.escape(creator)}\s*-\s*", "", text, count=1, flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" .-")


def extract_year(value: Any) -> str | None:
    match = re.search(r"(?:19|20)\d{2}", str(value or ""))
    return match.group(0) if match else None


def extract_youtube_id(metadata: Mapping[str, Any], source: Path | str | None = None) -> str | None:
    values = [
        metadata.get("youtube_id"),
        metadata.get("webpage_url"),
        metadata.get("purl"),
        metadata.get("comment"),
        metadata.get("description"),
    ]
    for value in values:
        text = str(value or "")
        parsed = urlparse(text)
        if parsed.hostname and parsed.hostname.casefold() in {"youtu.be", "www.youtu.be"}:
            candidate = parsed.path.strip("/").split("/", 1)[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                return candidate
        if parsed.hostname and "youtube.com" in parsed.hostname.casefold():
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                return candidate
        if match := YOUTUBE_ID.search(text):
            return match.group(1)
    if match := re.search(r"\[([A-Za-z0-9_-]{11})\]", str(source or "")):
        return match.group(1)
    return None


def short_filename_plan(path: Path | str, metadata: Mapping[str, Any]) -> ShortFilenamePlan:
    """Plan a confidence-aware `creator - title year [YouTube ID].ext` name."""
    path = Path(path)
    youtube_id = extract_youtube_id(metadata, path.name)
    source_title, source_title_key = _first_trusted(
        metadata,
        SOURCE_TITLE_KEYS,
        youtube_id=youtube_id,
    )
    embedded_title = trusted_metadata_text(metadata.get("title"), youtube_id=youtube_id)
    title = source_title or embedded_title
    source_creator, source_creator_key = _first_trusted(
        metadata,
        SOURCE_CREATOR_KEYS,
        youtube_id=youtube_id,
    )
    embedded_creator, _ = _first_trusted(
        metadata,
        EMBEDDED_CREATOR_KEYS,
        youtube_id=youtube_id,
    )
    creator = source_creator or embedded_creator
    title = deduplicate_media_title(title, creator=creator, youtube_id=youtube_id)
    if not trusted_metadata_text(title, youtube_id=youtube_id):
        return ShortFilenamePlan(
            None,
            "insufficient",
            "placeholder or missing metadata",
            "Insufficient trusted metadata for safe rename.",
        )
    clean_title = clean_component(title)
    clean_creator = clean_component(creator)
    year = extract_year(metadata.get("date") or metadata.get("year"))
    suffixes = [year if year and year not in clean_title else None, f"[{youtube_id}]" if youtube_id else None]
    identity = f"{clean_creator} - {clean_title}" if clean_creator else clean_title
    stem = clean_component(f"{identity} {' '.join(item for item in suffixes if item)}")
    # Leave room for the extension and for typical Windows parent paths.
    maximum = max(32, 220 - len(path.suffix))
    filename = f"{stem[:maximum].rstrip(' .')}{path.suffix.casefold()}"
    cached_source = bool(source_title_key or source_creator_key)
    return ShortFilenamePlan(
        filename,
        "high" if cached_source else "medium",
        "cached source metadata" if cached_source else "embedded metadata",
    )


def short_filename(path: Path | str, metadata: Mapping[str, Any]) -> str:
    """Build a safe short filename or reject insufficient metadata."""
    plan = short_filename_plan(path, metadata)
    if plan.filename is None:
        raise ValueError(plan.reason or "Insufficient trusted metadata for safe rename.")
    return plan.filename


def flattened_details(info: Mapping[str, Any]) -> list[tuple[str, str]]:
    metadata = info.get("metadata") or {}
    rows: list[tuple[str, str]] = []
    preferred = (
        "library_id",
        "canonical_path",
        "state",
        "size",
        "mtime_ns",
        "content_signature",
        "fingerprint_duration",
    )
    for key in preferred:
        if info.get(key) is not None:
            value = str(info[key])
            if key == "canonical_path":
                value = display_media_uri(value)
            rows.append((_DETAIL_LABELS.get(key, key.replace("_", " ").title()), value))
    metadata_order = (
        "source",
        "title",
        "artist",
        "album",
        "duration",
        "provider",
        "provider_media_id",
        "publisher",
        "publisher_id",
        "published",
        "views",
        "likes",
        "dislikes",
        "comments",
        "reposts",
        "followers",
        "concurrent_viewers",
    )
    ordered_keys = [key for key in metadata_order if key in metadata]
    ordered_keys.extend(sorted(key for key in metadata if key not in metadata_order))
    for key in ordered_keys:
        value = metadata[key]
        if value is not None and value != "" and value != [] and value != {}:
            rendered = f"{value:,}" if key in _PROVIDER_COUNT_KEYS and isinstance(value, int) else str(value)
            rows.append((_DETAIL_LABELS.get(key, key.replace("_", " ").title()), rendered))
    if info.get("fingerprint"):
        fingerprint = str(info["fingerprint"])
        rows.append(("Chromaprint", f"{len(fingerprint)} characters; use 'media fingerprint --full' to print it"))
    if info.get("loudness"):
        rows.append(("ReplayGain", str(info["loudness"])))
    return rows
