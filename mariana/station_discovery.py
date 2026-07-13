"""Validated, track-seeded station candidate discovery."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beta.youtube_media import media_info, search
from recommendation_engine.engine import Candidate, Recommendation, RecommendationEngine
from recommendation_engine.listenbrainz import ListenBrainzClient

from .database import MarianaDatabase
from .identity import MusicBrainzClient
from .models import IdentityStatus, MediaCapabilities, MediaRef, MediaSource, TrackIdentity

VALID_STATION_SCOPES = {"hybrid", "local", "online"}


class StationSeedError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class DiscoveredTrack:
    media: MediaRef
    score: float
    reasons: list[str]
    provider: str


def _identity(database: MarianaDatabase, media: MediaRef) -> TrackIdentity | None:
    row = database.fetchone("SELECT identity_json FROM track_identities WHERE stable_id=?", (media.stable_id,))
    if not row:
        return None
    try:
        return TrackIdentity.from_dict(json.loads(row["identity_json"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _identified_music(database: MarianaDatabase, media: MediaRef) -> bool:
    identity = _identity(database, media)
    return bool(
        identity
        and identity.status == IdentityStatus.IDENTIFIED
        and identity.title
        and identity.artist
        and identity.confidence >= 0.85
    )


def validate_station_seed(database: MarianaDatabase, media: MediaRef) -> MediaRef:
    """Return a verified finite music seed or raise a typed, user-safe error."""
    if media.capabilities.live or not media.capabilities.finite:
        raise StationSeedError("live_media", "Stations require a finite music track; live media is unsupported.")
    if media.source == MediaSource.LOCAL:
        indexed = database.fetchone(
            "SELECT state FROM library_files WHERE library_id=? OR path_key=?",
            (media.stable_id, str(Path(media.original_uri).expanduser().resolve()).casefold()),
        )
        if not indexed or indexed["state"] != "available":
            raise StationSeedError("unindexed_local", "The local seed must be available in Mariana's indexed library.")
        if not ((media.title and media.artist) or _identified_music(database, media)):
            raise StationSeedError(
                "unverified_music", "The local seed needs artist/title tags or a confirmed fingerprint identity."
            )
        return media
    if media.source == MediaSource.YOUTUBE:
        data = media.resolver_data
        categories = {str(value).casefold() for value in data.get("categories", [])}
        verified = bool(data.get("is_music") or "music" in categories or (data.get("track") and data.get("artist")))
        if not verified and not _identified_music(database, media):
            raise StationSeedError(
                "unverified_video", "The YouTube seed was not confirmed as music by metadata or fingerprint identity."
            )
        return media
    descriptions = {
        MediaSource.PODCAST: "Podcast episodes cannot seed a music station.",
        MediaSource.RADIO: "Live catalog radio cannot seed a track station; use the radio commands.",
        MediaSource.URL: "Arbitrary media URLs cannot seed a station until they have a confirmed music identity.",
        MediaSource.RECOMMENDATION: "Resolve the recommendation to its real music source before starting a station.",
    }
    raise StationSeedError("unsupported_source", descriptions.get(media.source, "This media source cannot seed a station."))


def _artist_mbid(media: MediaRef, identity: TrackIdentity | None) -> str | None:
    direct = media.resolver_data.get("artist_mbid")
    if direct:
        return str(direct)
    metadata = identity.metadata.get("musicbrainz", {}) if identity else {}
    credits = metadata.get("artist-credit") or []
    for credit in credits:
        artist = credit.get("artist") if isinstance(credit, dict) else None
        if isinstance(artist, dict) and artist.get("id"):
            return str(artist["id"])
    return None


class StationDiscovery:
    """Progressive candidate source with injectable network boundaries."""

    def __init__(
        self,
        database: MarianaDatabase,
        recommender: RecommendationEngine,
        *,
        listenbrainz: ListenBrainzClient | None = None,
        musicbrainz: MusicBrainzClient | None = None,
        youtube_search: Callable[..., list[dict[str, Any]]] = search,
        youtube_info: Callable[..., dict[str, Any]] = media_info,
        browser_profile: str | None = None,
    ) -> None:
        self.database = database
        self.recommender = recommender
        self.listenbrainz = listenbrainz or ListenBrainzClient()
        self.musicbrainz = musicbrainz or MusicBrainzClient()
        self.youtube_search = youtube_search
        self.youtube_info = youtube_info
        self.browser_profile = browser_profile

    def local_candidates(self, seed: MediaRef, scope: str) -> list[Candidate]:
        candidates = []
        for candidate in self.recommender.candidates_from_history():
            media = candidate.media
            if media.stable_id == seed.stable_id or media.capabilities.live or not media.capabilities.finite:
                continue
            if scope == "online" and media.source == MediaSource.LOCAL:
                continue
            if scope == "local" and media.source != MediaSource.LOCAL:
                continue
            if media.source == MediaSource.LOCAL and not Path(media.original_uri).is_file():
                continue
            if media.source not in {MediaSource.LOCAL, MediaSource.YOUTUBE}:
                continue
            if not media.title or not media.artist:
                continue
            candidates.append(candidate)
        return candidates

    def rank(
        self,
        seed: MediaRef,
        candidates: Iterable[Candidate],
        *,
        limit: int,
        excluded: set[str],
    ) -> list[DiscoveredTrack]:
        recent = [Candidate(seed)]
        ranked = self.recommender.recommend(candidates, limit=limit, recent=recent, exclude_ids=excluded)
        return [
            DiscoveredTrack(item.media, item.score, ["similar to station seed", *item.reasons], "local-history")
            for item in ranked
        ]

    def _known_recordings(self) -> dict[str, MediaRef]:
        result: dict[str, MediaRef] = {}
        for candidate in self.recommender.candidates_from_history():
            mbid = candidate.media.resolver_data.get("recording_mbid")
            if mbid:
                result[str(mbid)] = candidate.media
        return result

    def online_candidates(
        self,
        seed: MediaRef,
        *,
        scope: str,
        limit: int,
        excluded: set[str],
    ) -> list[Candidate]:
        identity = _identity(self.database, seed)
        artist_mbid = _artist_mbid(seed, identity)
        if not artist_mbid:
            return []
        recordings = self.listenbrainz.artist_radio(artist_mbid, count=max(limit * 2, 10))
        known = self._known_recordings()
        candidates: list[Candidate] = []
        for item in recordings:
            recording_mbid = str(item.get("recording_mbid") or item.get("recording_msid") or "")
            if not recording_mbid:
                continue
            if known_media := known.get(recording_mbid):
                if known_media.stable_id not in excluded and not (
                    scope == "online" and known_media.source == MediaSource.LOCAL
                ):
                    candidates.append(Candidate(known_media, collaborative_score=float(item.get("score") or 0.5)))
                continue
            recording = self.musicbrainz.recording(recording_mbid)
            if not recording:
                continue
            title = str(recording.get("title") or "").strip()
            credits = recording.get("artist-credit") or []
            artists = [str(credit.get("name")) for credit in credits if isinstance(credit, dict) and credit.get("name")]
            artist = ", ".join(artists)
            if not title or not artist:
                continue
            results = self.youtube_search(
                f"{artist} {title}", limit=1, browser_profile=self.browser_profile
            )
            if not results or not results[0].get("url"):
                continue
            canonical = str(results[0]["url"])
            details = self.youtube_info(canonical, detailed=True, browser_profile=self.browser_profile)
            categories = [str(value) for value in details.get("categories", [])]
            is_music = bool(details.get("track") and details.get("artist")) or any(
                value.casefold() == "music" for value in categories
            )
            if not is_music or details.get("is_live"):
                continue
            media = MediaRef(
                MediaSource.YOUTUBE,
                canonical,
                title=title,
                artist=artist,
                album=details.get("album"),
                duration=details.get("duration"),
                resolver_data={
                    "youtube": True,
                    "is_music": True,
                    "categories": categories,
                    "recording_mbid": recording_mbid,
                    "artist_mbid": artist_mbid,
                },
                provenance="station-listenbrainz",
                capabilities=MediaCapabilities(metadata_available=True),
            )
            if media.stable_id not in excluded:
                candidates.append(Candidate(media, collaborative_score=float(item.get("score") or 0.5)))
            if len(candidates) >= limit:
                break
        return candidates

    def discover(
        self,
        seed: MediaRef,
        *,
        scope: str = "hybrid",
        limit: int = 10,
        excluded: set[str] | None = None,
    ) -> list[DiscoveredTrack]:
        if scope not in VALID_STATION_SCOPES:
            raise ValueError(f"Unknown station scope: {scope}")
        verified = validate_station_seed(self.database, seed)
        excluded_ids = set(excluded or ()) | {verified.stable_id}
        local = self.local_candidates(verified, scope)
        ranked = self.rank(verified, local, limit=limit, excluded=excluded_ids)
        if scope == "local" or len(ranked) >= limit:
            return ranked[:limit]
        remaining = limit - len(ranked)
        online = self.online_candidates(
            verified,
            scope=scope,
            limit=remaining,
            excluded=excluded_ids | {r.media.stable_id for r in ranked},
        )
        online_ranked: list[Recommendation] = self.recommender.recommend(
            online,
            limit=remaining,
            recent=[Candidate(verified)],
            exclude_ids=excluded_ids | {item.media.stable_id for item in ranked},
        )
        ranked.extend(
            DiscoveredTrack(
                item.media,
                item.score,
                ["ListenBrainz artist radio", "MusicBrainz recording match", *item.reasons],
                "listenbrainz",
            )
            for item in online_ranked
        )
        return ranked[:limit]
