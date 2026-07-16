"""Conservative, read-only matching of online media to indexed local files."""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse

from .database import MarianaDatabase
from .media_details import extract_youtube_id
from .models import IdentityStatus, MediaRef, MediaSource, canonical_uri

_ONLINE_SOURCES = {
    MediaSource.YOUTUBE,
    MediaSource.URL,
    MediaSource.PODCAST,
    MediaSource.RECOMMENDATION,
}
_SENSITIVE_QUERY_KEY = re.compile(
    r"(?i)(?:auth|cookie|credential|expires?|key|password|session|signature|signed|token)"
)
_URL_LIKE = re.compile(r"(?i)(?:[a-z][a-z0-9+.-]*://|www\.)")
_PATH_LIKE = re.compile(r"(?i)(?:^[a-z]:[\\/]|^\\\\|^/|^~[\\/])")
_YEAR = re.compile(r"(?:19|20)\d{2}")


class LocalMatchStatus(StrEnum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


class LocalMatchConfidence(StrEnum):
    EXACT_SOURCE = "Exact source"
    EXACT_ACOUSTIC = "Exact acoustic match"
    VERIFIED_RECORDING = "Verified recording"
    STRONG_METADATA = "Strong metadata match"


@dataclass(frozen=True, slots=True)
class LocalMatchResult:
    """Safe result which deliberately cannot serialize a path or source URL."""

    status: LocalMatchStatus
    library_id: str | None = None
    library_index: int | None = None
    title: str | None = None
    artist: str | None = None
    confidence: LocalMatchConfidence | None = None
    evidence: str | None = None


@dataclass(frozen=True, slots=True)
class _Evidence:
    confidence: LocalMatchConfidence
    label: str
    priority: int


_SOURCE = _Evidence(LocalMatchConfidence.EXACT_SOURCE, "same durable source", 1)
_ACOUSTIC = _Evidence(LocalMatchConfidence.EXACT_ACOUSTIC, "same cached Chromaprint", 2)
_RECORDING = _Evidence(LocalMatchConfidence.VERIFIED_RECORDING, "same confirmed recording MBID", 3)
_METADATA = _Evidence(LocalMatchConfidence.STRONG_METADATA, "corroborated metadata and duration", 4)


def _normalized(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split())


def _safe_display(value: object, *, fallback: str | None = None) -> str | None:
    if not isinstance(value, str):
        return fallback
    text = "".join(character for character in value if not unicodedata.category(character).startswith("C"))
    text = " ".join(text.split()).strip()
    if not text or _URL_LIKE.search(text) or _PATH_LIKE.search(text):
        return fallback
    return text[:157].rstrip() + ("..." if len(text) > 160 else "")


def _positive_duration(value: object) -> float | None:
    try:
        duration = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return duration if math.isfinite(duration) and duration > 0 else None


def _youtube_id(media: MediaRef | None = None, metadata: dict[str, Any] | None = None) -> str | None:
    values = metadata or {}
    if media is not None:
        for key in ("video_id", "youtube_id"):
            candidate = str(media.resolver_data.get(key) or "")
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
                return candidate
        return extract_youtube_id({"webpage_url": media.original_uri})
    return extract_youtube_id(values)


def _safe_public_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    if any(_SENSITIVE_QUERY_KEY.search(key) for key, _item in parse_qsl(parsed.query, keep_blank_values=True)):
        return None
    return canonical_uri(MediaSource.URL, value)


def _identity(value: object) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _confirmed_recording(identity: dict[str, Any]) -> str | None:
    if identity.get("status") != IdentityStatus.IDENTIFIED.value:
        return None
    recording = str(identity.get("recording_mbid") or "").strip()
    provenance = {_normalized(value) for value in identity.get("provenance") or []}
    if not recording or not {"acoustid", "chromaprint"}.issubset(provenance):
        return None
    return recording.casefold()


def _year(value: object) -> str | None:
    match = _YEAR.search(str(value or ""))
    return match.group(0) if match else None


def _path_key(value: object) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(value)))).casefold()


class LocalMediaMatcher:
    """Match one finite online item without resolving, fingerprinting, or writing."""

    def __init__(self, database: MarianaDatabase, *, verify_final_path: bool = True) -> None:
        self.database = database
        self.verify_final_path = verify_final_path

    def match(self, media: MediaRef | None) -> LocalMatchResult:
        duration = _positive_duration(media.duration) if media is not None else None
        if (
            media is None
            or media.source not in _ONLINE_SOURCES
            or not media.capabilities.finite
            or media.capabilities.live
            or duration is None
        ):
            return LocalMatchResult(LocalMatchStatus.UNSUPPORTED)

        current_identity_row = self.database.fetchone(
            "SELECT identity_json,fingerprint,fingerprint_duration FROM track_identities WHERE stable_id=?",
            (media.stable_id,),
        )
        current_identity = _identity(current_identity_row["identity_json"] if current_identity_row else None)
        current_fingerprint = str(current_identity_row["fingerprint"] or "") if current_identity_row else ""
        current_fingerprint_duration = _positive_duration(
            current_identity_row["fingerprint_duration"] if current_identity_row else None
        )
        current_recording = _confirmed_recording(current_identity)
        current_youtube_id = _youtube_id(media)
        current_url = _safe_public_url(media.original_uri)

        rows = self.database.fetchall(
            "SELECT f.*,i.identity_json,i.fingerprint AS identity_fingerprint,"
            "i.fingerprint_duration AS identity_fingerprint_duration "
            "FROM library_files f LEFT JOIN track_identities i ON i.stable_id=f.library_id "
            "WHERE f.state='available' ORDER BY f.path_key"
        )
        download_sources = {
            _path_key(row["output_path"]): _safe_public_url(row["canonical_url"])
            for row in self.database.fetchall(
                "SELECT output_path,canonical_url FROM download_items "
                "WHERE state='completed' AND output_path IS NOT NULL"
            )
        }
        evidence_by_id: dict[str, list[_Evidence]] = {}
        row_by_id: dict[str, tuple[int, Any, dict[str, Any]]] = {}

        for index, row in enumerate(rows, 1):
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
            if not isinstance(metadata, dict):
                metadata = {}
            library_id = str(row["library_id"])
            row_by_id[library_id] = (index, row, metadata)
            found: list[_Evidence] = []

            local_youtube_id = _youtube_id(metadata=metadata)
            local_url = _safe_public_url(metadata.get("webpage_url") or metadata.get("purl"))
            managed_url = download_sources.get(_path_key(row["canonical_path"]))
            if (
                (current_youtube_id and local_youtube_id == current_youtube_id)
                or (current_url and current_url in {local_url, managed_url})
            ):
                found.append(_SOURCE)

            local_fingerprint = str(row["fingerprint"] or row["identity_fingerprint"] or "")
            local_fingerprint_duration = _positive_duration(
                row["fingerprint_duration"] or row["identity_fingerprint_duration"]
            )
            if (
                current_fingerprint
                and current_fingerprint == local_fingerprint
                and current_fingerprint_duration is not None
                and local_fingerprint_duration is not None
                and abs(current_fingerprint_duration - local_fingerprint_duration) <= 2
            ):
                found.append(_ACOUSTIC)

            local_recording = _confirmed_recording(_identity(row["identity_json"]))
            if current_recording and local_recording == current_recording:
                found.append(_RECORDING)

            local_duration = _positive_duration(metadata.get("duration"))
            same_core = (
                bool(_normalized(media.title))
                and _normalized(media.title) == _normalized(metadata.get("title"))
                and bool(_normalized(media.artist))
                and _normalized(media.artist) == _normalized(metadata.get("artist"))
                and local_duration is not None
                and abs(duration - local_duration) <= 2
            )
            same_album = bool(_normalized(media.album)) and _normalized(media.album) == _normalized(metadata.get("album"))
            current_release = _normalized(media.resolver_data.get("release_mbid"))
            same_release = bool(current_release) and current_release == _normalized(metadata.get("release_mbid"))
            current_year = _year(media.resolver_data.get("date") or media.resolver_data.get("year"))
            same_year = bool(current_year) and current_year == _year(metadata.get("date"))
            if same_core and (same_album or same_release or same_year):
                found.append(_METADATA)

            if found:
                evidence_by_id[library_id] = found

        if not evidence_by_id:
            return LocalMatchResult(LocalMatchStatus.NO_MATCH)
        if len(evidence_by_id) != 1:
            return LocalMatchResult(LocalMatchStatus.AMBIGUOUS)

        library_id, evidence = next(iter(evidence_by_id.items()))
        index, row, metadata = row_by_id[library_id]
        if self.verify_final_path and not Path(row["canonical_path"]).is_file():
            return LocalMatchResult(LocalMatchStatus.NO_MATCH)
        strongest = min(evidence, key=lambda item: item.priority)
        return LocalMatchResult(
            LocalMatchStatus.MATCHED,
            library_id=library_id,
            library_index=index,
            title=_safe_display(media.title)
            or _safe_display(metadata.get("title"), fallback="Local media"),
            artist=_safe_display(media.artist) or _safe_display(metadata.get("artist")),
            confidence=strongest.confidence,
            evidence=strongest.label,
        )
