"""Compatibility helpers backed exclusively by Chromaprint and open metadata services."""

from __future__ import annotations

from pathlib import Path

from mariana.database import MarianaDatabase
from mariana.identity import IdentificationService
from mariana.models import IdentityStatus, MediaRef, MediaSource


_database = None
_service = None


def _get_service() -> IdentificationService:
    global _database, _service
    if _service is None:
        _database = MarianaDatabase()
        _service = IdentificationService(_database)
    return _service


def get_song_info(songfile, display_id=False, get_related=False, get_title_only=False, **_legacy):
    del get_related
    path = Path(songfile)
    if not path.is_file():
        raise OSError(f"Audio file does not exist: {path}")
    identity = _get_service().identify(MediaRef(MediaSource.LOCAL, str(path.resolve())))
    if identity.status != IdentityStatus.IDENTIFIED:
        return None if get_title_only else {}
    if display_id:
        print(f"Recording MBID: {identity.recording_mbid or 'N/A'}")
    display_name = " — ".join(value for value in (identity.artist, identity.title) if value)
    if get_title_only:
        return display_name or identity.title
    return {
        "display_name": display_name or identity.title,
        "recording_mbid": identity.recording_mbid,
        "work_mbid": identity.work_mbid,
        "metadata": identity.metadata,
        "genres": (identity.metadata.get("musicbrainz") or {}).get("tags", []),
        "lyrics": [],
        "confidence": identity.confidence,
        "provenance": identity.provenance,
    }
