"""Media inspection and safe, metadata-derived short filenames."""

from __future__ import annotations

import re
from collections.abc import Mapping
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


def clean_component(value: Any, *, fallback: str = "") -> str:
    text = INVALID_FILENAME.sub("-", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip(" .-")
    if text.upper() in RESERVED_NAMES:
        text = f"_{text}"
    return text or fallback


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


def short_filename(path: Path | str, metadata: Mapping[str, Any]) -> str:
    """Build `creator - title year [YouTube ID].ext` without inventing fields."""
    path = Path(path)
    creator = next(
        (
            clean_component(metadata.get(key))
            for key in ("artist", "releaser", "distributor", "publisher", "label")
            if clean_component(metadata.get(key))
        ),
        "Unknown Artist",
    )
    title = clean_component(metadata.get("title"), fallback=clean_component(path.stem, fallback="Untitled"))
    year = extract_year(metadata.get("date") or metadata.get("year"))
    youtube_id = extract_youtube_id(metadata, path.name)
    suffixes = [year, f"[{youtube_id}]" if youtube_id else None]
    stem = clean_component(f"{creator} - {title} {' '.join(item for item in suffixes if item)}")
    # Leave room for the extension and for typical Windows parent paths.
    maximum = max(32, 220 - len(path.suffix))
    return f"{stem[:maximum].rstrip(' .')}{path.suffix.casefold()}"


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
