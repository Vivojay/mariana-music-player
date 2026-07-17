"""Media inspection and safe, metadata-derived short filenames."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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


@dataclass(frozen=True, slots=True)
class ShortFilenamePlan:
    filename: str | None
    confidence: str
    source: str
    reason: str | None = None


def clean_component(value: Any, *, fallback: str = "") -> str:
    text = INVALID_FILENAME.sub("-", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .-")
    if text.upper() in RESERVED_NAMES:
        text = f"_{text}"
    return text or fallback


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
            rows.append((key.replace("_", " ").title(), str(info[key])))
    for key, value in sorted(metadata.items()):
        if value is not None and value != "" and value != [] and value != {}:
            rows.append((key.replace("_", " ").title(), str(value)))
    if info.get("fingerprint"):
        fingerprint = str(info["fingerprint"])
        rows.append(("Chromaprint", f"{len(fingerprint)} characters; use 'media fingerprint --full' to print it"))
    if info.get("loudness"):
        rows.append(("ReplayGain", str(info["loudness"])))
    return rows
