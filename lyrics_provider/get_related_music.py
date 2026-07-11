"""Fetch and persist Shazam recommendations for a recognized track."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import yaml
from shazamio import Shazam


APP_DIR = Path(__file__).resolve().parents[1]
RELATED_SONGS_PATH = APP_DIR / "data" / "related_songs.yml"


def _youtube_url(track):
    for section in track.get("sections") or []:
        youtube_url = section.get("youtubeurl")
        if youtube_url:
            return youtube_url
    for action in (track.get("hub") or {}).get("actions") or []:
        if action.get("type") == "uri" and "youtube" in str(action.get("uri", "")).lower():
            return action["uri"]
    return None


def _normalize_related_track(track):
    metadata = []
    lyrics = []
    for section in track.get("sections") or []:
        if section.get("type") == "SONG":
            metadata = section.get("metadata") or []
        elif section.get("type") == "LYRICS":
            lyrics = section.get("text") or []
    return {
        "display_name": (track.get("share") or {}).get("subject") or track.get("title"),
        "youtube_url": _youtube_url(track),
        "is_explicit": (track.get("hub") or {}).get("explicit"),
        "shazam_id": track.get("key"),
        "metadata": metadata,
        "lyrics": lyrics,
        "genres": track.get("genres") or {},
    }


async def _fetch_related(shazam_id: int, limit: int = 10):
    response = await Shazam().related_tracks(track_id=shazam_id, limit=limit, offset=0)
    tracks = response.get("tracks") or response.get("data") or []
    return [_normalize_related_track(track) for track in tracks]


def get_related_music(shazam_id):
    related_songs_info = asyncio.run(_fetch_related(int(shazam_id)))
    if related_songs_info:
        RELATED_SONGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with RELATED_SONGS_PATH.open("a", encoding="utf-8") as stream:
            yaml.safe_dump(related_songs_info, stream, allow_unicode=True, sort_keys=False)
    return related_songs_info


if __name__ == "__main__" and len(sys.argv) == 2:
    get_related_music(sys.argv[1])
