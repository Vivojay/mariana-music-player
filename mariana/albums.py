"""Edition-aware album discovery, resolution, selection, and persistence."""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
import unicodedata
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from beta.youtube_media import media_info, playlist_entries, search
from recommendation_engine.engine import Candidate, RecommendationEngine, cosine, features

from .database import MarianaDatabase
from .identity import MusicBrainzClient
from .models import (
    AlbumRef,
    AlbumTrack,
    AlbumTrackStatus,
    MediaCapabilities,
    MediaRef,
    MediaSource,
)

VALID_ALBUM_SCOPES = {"local", "online", "hybrid"}
VALID_ALBUM_ORDERS = {"release", "shuffle", "smart", "custom"}


class AlbumError(ValueError):
    pass


class AlbumMetadataClient(Protocol):
    def search_releases(
        self, query: str, *, limit: int = 10, offset: int = 0, refresh: bool = False
    ) -> list[dict[str, Any]]: ...

    def release(self, mbid: str, refresh: bool = False) -> dict[str, Any] | None: ...


def _normalized(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"\w+", text, flags=re.UNICODE))


def _positive_number(value: Any, default: int) -> int:
    try:
        number = int(str(value or "").split("/", 1)[0])
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _artist_credit(payload: dict[str, Any]) -> str | None:
    credits = payload.get("artist-credit") or []
    values = []
    for credit in credits:
        if isinstance(credit, str):
            values.append(credit)
        elif isinstance(credit, dict):
            name = credit.get("name")
            if not name and isinstance(credit.get("artist"), dict):
                name = credit["artist"].get("name")
            if name:
                values.append(str(name))
            if credit.get("joinphrase"):
                values.append(str(credit["joinphrase"]))
    result = "".join(values).strip()
    return result or None


def _album_id(key: str) -> str:
    return "album-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _duration_seconds(value: Any) -> float | None:
    try:
        milliseconds = float(value)
    except (TypeError, ValueError):
        return None
    return milliseconds / 1000


class AlbumCatalog:
    def __init__(
        self,
        database: MarianaDatabase,
        *,
        musicbrainz: AlbumMetadataClient | None = None,
        youtube_search: Callable[..., list[dict[str, Any]]] = search,
        youtube_info: Callable[..., dict[str, Any]] = media_info,
        youtube_playlist: Callable[..., dict[str, Any]] = playlist_entries,
        browser_profile: str | None = None,
    ) -> None:
        self.database = database
        self.musicbrainz = musicbrainz or MusicBrainzClient()
        self.youtube_search = youtube_search
        self.youtube_info = youtube_info
        self.youtube_playlist = youtube_playlist
        self.browser_profile = browser_profile

    def _persist(self, album: AlbumRef) -> AlbumRef:
        now = time.time()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO albums(album_id,release_mbid,title,album_artist,date,country,disambiguation,"
                "album_json,fetched_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(album_id) DO UPDATE SET release_mbid=excluded.release_mbid,"
                "title=excluded.title,album_artist=excluded.album_artist,date=excluded.date,"
                "country=excluded.country,disambiguation=excluded.disambiguation,"
                "album_json=excluded.album_json,fetched_at=excluded.fetched_at,updated_at=excluded.updated_at",
                (
                    album.album_id,
                    album.release_mbid,
                    album.title,
                    album.album_artist,
                    album.date,
                    album.country,
                    album.disambiguation,
                    json.dumps(album.to_dict(), ensure_ascii=False, sort_keys=True),
                    album.fetched_at,
                    now,
                ),
            )
        return album

    @staticmethod
    def _from_row(row) -> AlbumRef:
        try:
            return AlbumRef.from_dict(json.loads(row["album_json"]))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise AlbumError("Stored album data is corrupt") from error

    def get(self, album_id_or_mbid: str) -> AlbumRef:
        row = self.database.fetchone(
            "SELECT * FROM albums WHERE album_id=? OR release_mbid=?",
            (album_id_or_mbid, album_id_or_mbid),
        )
        if not row:
            raise AlbumError(f"Unknown album: {album_id_or_mbid}")
        return self._from_row(row)

    @staticmethod
    def _local_media(row, metadata: dict[str, Any], recording_mbid: str | None) -> MediaRef:
        resolver_data = {
            "library_id": row["library_id"],
            "content_id": row["content_signature"],
            "fingerprint": row["fingerprint"],
            "release_mbid": metadata.get("release_mbid"),
            "recording_mbid": recording_mbid,
            "track_number": metadata.get("track"),
            "disc_number": metadata.get("disc"),
        }
        return MediaRef(
            MediaSource.LOCAL,
            row["canonical_path"],
            stable_id=row["library_id"],
            title=metadata.get("title"),
            artist=metadata.get("artist"),
            album=metadata.get("album"),
            duration=metadata.get("duration"),
            resolver_data={key: value for key, value in resolver_data.items() if value is not None},
            provenance="library-album",
            capabilities=MediaCapabilities(downloadable=False, metadata_available=True),
        )

    def _local_rows(self) -> list[tuple[Any, dict[str, Any], str | None]]:
        rows = self.database.fetchall(
            "SELECT f.*,i.identity_json FROM library_files f "
            "LEFT JOIN track_identities i ON i.stable_id=f.library_id "
            "WHERE f.state='available' ORDER BY f.path_key"
        )
        result = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            recording_mbid = None
            if row["identity_json"]:
                with suppress(TypeError, json.JSONDecodeError):
                    recording_mbid = json.loads(row["identity_json"]).get("recording_mbid")
            result.append((row, metadata, recording_mbid))
        return result

    def local_albums(self) -> list[AlbumRef]:
        groups: dict[str, list[tuple[Any, dict[str, Any], str | None]]] = {}
        for row, metadata, recording_mbid in self._local_rows():
            title = str(metadata.get("album") or "").strip()
            artist = str(metadata.get("album_artist") or metadata.get("artist") or "").strip()
            release_mbid = str(metadata.get("release_mbid") or "").strip()
            if not title or not artist:
                continue
            key = f"mb:{release_mbid}" if release_mbid else f"tags:{_normalized(artist)}:{_normalized(title)}"
            groups.setdefault(key, []).append((row, metadata, recording_mbid))
        albums = []
        for key, values in groups.items():
            first = values[0][1]
            release_mbid = str(first.get("release_mbid") or "").strip() or None
            album = AlbumRef(
                album_id=_album_id(key),
                title=str(first["album"]),
                album_artist=str(first.get("album_artist") or first.get("artist") or "") or None,
                release_mbid=release_mbid,
                date=str(first.get("date") or "") or None,
                tracks=[],
                provenance=["local-library"],
                source_ref=release_mbid,
                resolution_scope="local",
                fetched_at=time.time(),
            )
            for position, (row, metadata, recording_mbid) in enumerate(
                sorted(
                    values,
                    key=lambda value: (
                        _positive_number(value[1].get("disc"), 1),
                        _positive_number(value[1].get("track"), 10**6),
                        value[0]["path_key"],
                    ),
                ),
                1,
            ):
                disc = _positive_number(metadata.get("disc"), 1)
                track_number = _positive_number(metadata.get("track"), position)
                media = self._local_media(row, metadata, recording_mbid)
                media.resolver_data["album_id"] = album.album_id
                album.tracks.append(
                    AlbumTrack(
                        title=media.title or Path(media.original_uri).stem,
                        artist=media.artist or album.album_artist,
                        disc_number=disc,
                        track_number=track_number,
                        position=position,
                        duration=media.duration,
                        recording_mbid=recording_mbid,
                        release_mbid=release_mbid,
                        resolution_status=AlbumTrackStatus.LOCAL,
                        media=media,
                        provenance=["local-library"],
                    )
                )
            albums.append(self._persist(album))
        return sorted(albums, key=lambda value: (_normalized(value.album_artist), _normalized(value.title), value.date or ""))

    @staticmethod
    def _matches_query(album: AlbumRef, query: str) -> bool:
        terms = _normalized(query).split()
        haystack = _normalized(f"{album.album_artist or ''} {album.title} {album.date or ''}")
        return bool(terms) and all(term in haystack for term in terms)

    @staticmethod
    def _release_stub(payload: dict[str, Any]) -> AlbumRef:
        release_mbid = str(payload["id"])
        release_group = payload.get("release-group") or {}
        return AlbumRef(
            album_id=_album_id(f"mb:{release_mbid}"),
            title=str(payload["title"]),
            album_artist=_artist_credit(payload),
            release_mbid=release_mbid,
            release_group_mbid=str(release_group.get("id")) if release_group.get("id") else None,
            date=str(payload.get("date") or "") or None,
            country=str(payload.get("country") or "") or None,
            disambiguation=str(payload.get("disambiguation") or "") or None,
            provenance=["musicbrainz-release"],
            source_ref=release_mbid,
        )

    def search(self, query: str, *, scope: str = "hybrid", limit: int = 10) -> list[AlbumRef]:
        if scope not in VALID_ALBUM_SCOPES:
            raise AlbumError(f"Unknown album scope: {scope}")
        if not query.strip() or limit < 1:
            raise AlbumError("Album search requires a query and positive limit")
        results = []
        if scope in {"local", "hybrid"}:
            results.extend(album for album in self.local_albums() if self._matches_query(album, query))
        if scope in {"online", "hybrid"} and len(results) < limit:
            for payload in self.musicbrainz.search_releases(query, limit=limit):
                stub = self._release_stub(payload)
                stub.resolution_scope = scope
                if any(album.release_mbid == stub.release_mbid for album in results):
                    continue
                results.append(self._persist(stub))
                if len(results) >= limit:
                    break
        results = results[:limit]
        search_id = uuid.uuid4().hex
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM album_search_results WHERE created_at<?", (time.time() - 86_400 * 30,))
            for position, album in enumerate(results, 1):
                connection.execute(
                    "INSERT INTO album_search_results(search_id,position,album_id,query,scope,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (search_id, position, album.album_id, query, scope, time.time()),
                )
        self.database.set_state("album_last_search", {"search_id": search_id, "query": query, "scope": scope})
        return results

    def resolve_reference(self, reference: str) -> AlbumRef:
        value = reference.strip()
        if value.isdigit():
            state = self.database.get_state("album_last_search", {})
            row = self.database.fetchone(
                "SELECT a.* FROM album_search_results r JOIN albums a ON a.album_id=r.album_id "
                "WHERE r.search_id=? AND r.position=?",
                (state.get("search_id"), int(value)),
            )
            if not row:
                raise AlbumError(f"Unknown album search result: {value}")
            return self._from_row(row)
        return self.get(value)

    @staticmethod
    def _remote_tracks(album: AlbumRef, payload: dict[str, Any]) -> list[AlbumTrack]:
        tracks = []
        flattened = 0
        for medium_index, medium in enumerate(payload.get("media") or [], 1):
            if not isinstance(medium, dict):
                continue
            disc = _positive_number(medium.get("position"), medium_index)
            for track_index, entry in enumerate(medium.get("tracks") or [], 1):
                if not isinstance(entry, dict):
                    continue
                raw_recording = entry.get("recording")
                recording: dict[str, Any] = raw_recording if isinstance(raw_recording, dict) else {}
                title = str(recording.get("title") or entry.get("title") or "").strip()
                if not title:
                    continue
                flattened += 1
                tracks.append(
                    AlbumTrack(
                        title=title,
                        artist=_artist_credit(recording) or _artist_credit(entry) or album.album_artist,
                        disc_number=disc,
                        track_number=_positive_number(entry.get("position") or entry.get("number"), track_index),
                        position=flattened,
                        duration=_duration_seconds(entry.get("length") or recording.get("length")),
                        recording_mbid=str(recording.get("id")) if recording.get("id") else None,
                        release_mbid=album.release_mbid,
                        provenance=["musicbrainz-release"],
                    )
                )
        return tracks

    def _match_local(self, track: AlbumTrack) -> tuple[MediaRef | None, bool]:
        candidates = self._local_rows()
        if track.recording_mbid:
            exact = [value for value in candidates if value[2] == track.recording_mbid]
            if exact:
                row, metadata, recording_mbid = exact[0]
                return self._local_media(row, metadata, recording_mbid), False
        matches = []
        for row, metadata, recording_mbid in candidates:
            if _normalized(metadata.get("title")) != _normalized(track.title):
                continue
            if track.artist and _normalized(metadata.get("artist")) != _normalized(track.artist):
                continue
            local_duration = metadata.get("duration")
            if (
                track.duration is not None
                and local_duration is not None
                and abs(float(local_duration) - track.duration) > 5
            ):
                continue
            matches.append((row, metadata, recording_mbid))
        if len(matches) != 1:
            return None, len(matches) > 1
        return self._local_media(*matches[0]), False

    def _youtube_media(self, album: AlbumRef, track: AlbumTrack) -> MediaRef | None:
        results = self.youtube_search(
            f"{track.artist or album.album_artist or ''} {track.title}",
            limit=1,
            browser_profile=self.browser_profile,
        )
        if not results or not results[0].get("url"):
            return None
        canonical = str(results[0]["url"])
        details = self.youtube_info(canonical, detailed=True, browser_profile=self.browser_profile)
        categories = [str(value) for value in details.get("categories", [])]
        is_music = bool(details.get("track") and details.get("artist")) or any(
            value.casefold() == "music" for value in categories
        )
        structured_track = details.get("track")
        structured_artist = details.get("artist")
        if structured_track and _normalized(structured_track) != _normalized(track.title):
            return None
        if (
            structured_track
            and structured_artist
            and track.artist
            and _normalized(structured_artist) != _normalized(track.artist)
        ):
            return None
        video_duration = details.get("duration")
        if (
            track.duration is not None
            and video_duration is not None
            and abs(float(video_duration) - track.duration) > 15
        ):
            return None
        if details.get("is_live") or not is_music:
            return None
        return MediaRef(
            MediaSource.YOUTUBE,
            canonical,
            title=track.title,
            artist=track.artist or album.album_artist,
            album=album.title,
            duration=details.get("duration") or track.duration,
            resolver_data={
                "youtube": True,
                "video_id": results[0].get("id"),
                "is_music": True,
                "categories": categories,
                "recording_mbid": track.recording_mbid,
                "release_mbid": album.release_mbid,
                "album_id": album.album_id,
                "disc_number": track.disc_number,
                "track_number": track.track_number,
            },
            provenance="album-youtube",
            capabilities=MediaCapabilities(metadata_available=True),
        )

    def _resolve_tracks(self, album: AlbumRef, *, scope: str) -> AlbumRef:
        for track in album.tracks:
            media, ambiguous_local = (
                (None, False) if scope == "online" else self._match_local(track)
            )
            if media:
                media.resolver_data.update(
                    {
                        "album_id": album.album_id,
                        "release_mbid": album.release_mbid,
                        "recording_mbid": track.recording_mbid,
                        "disc_number": track.disc_number,
                        "track_number": track.track_number,
                    }
                )
                track.media = media
                track.resolution_status = AlbumTrackStatus.LOCAL
                track.provenance.append("local-library")
                continue
            if scope in {"online", "hybrid"}:
                media = self._youtube_media(album, track)
            if media:
                track.media = media
                track.resolution_status = AlbumTrackStatus.ONLINE
                track.provenance.append("youtube")
            else:
                track.resolution_status = (
                    AlbumTrackStatus.AMBIGUOUS if ambiguous_local else AlbumTrackStatus.UNRESOLVED
                )
        album.fetched_at = time.time()
        return self._persist(album)

    def youtube_album(self, url: str) -> AlbumRef:
        payload = self.youtube_playlist(url, browser_profile=self.browser_profile)
        identifier = str(payload.get("id") or payload.get("url") or url)
        album = AlbumRef(
            album_id=_album_id(f"youtube-playlist:{identifier}"),
            title=str(payload.get("title") or "YouTube playlist"),
            tracks=[],
            provenance=["youtube-playlist"],
            source_ref=str(payload.get("url") or url),
            resolution_scope="online",
            fetched_at=time.time(),
        )
        for position, entry in enumerate(payload["entries"], 1):
            media = MediaRef(
                MediaSource.YOUTUBE,
                str(entry["url"]),
                title=str(entry["title"]),
                artist=entry.get("artist"),
                album=album.title,
                duration=entry.get("duration"),
                resolver_data={
                    "youtube": True,
                    "video_id": entry["id"],
                    "playlist_id": payload.get("id"),
                    "playlist_index": entry.get("playlist_index", position),
                    "album_id": album.album_id,
                    "disc_number": 1,
                    "track_number": position,
                },
                provenance="youtube-playlist-album",
                capabilities=MediaCapabilities(metadata_available=True),
            )
            album.tracks.append(
                AlbumTrack(
                    title=media.title or "Untitled",
                    artist=media.artist,
                    track_number=position,
                    position=position,
                    duration=media.duration,
                    resolution_status=AlbumTrackStatus.ONLINE,
                    media=media,
                    provenance=["youtube-playlist"],
                )
            )
        return self._persist(album)

    def fetch(self, reference: str, *, refresh: bool = False, scope: str | None = None) -> AlbumRef:
        if reference.startswith(("https://www.youtube.com/", "https://youtube.com/", "https://youtu.be/")):
            return self.youtube_album(reference)
        album = self.resolve_reference(reference)
        scope = scope or album.resolution_scope
        if scope not in VALID_ALBUM_SCOPES:
            raise AlbumError(f"Unknown album scope: {scope}")
        album.resolution_scope = scope
        if album.tracks and not refresh:
            return album
        if not album.release_mbid:
            if album.tracks:
                return album
            raise AlbumError("This album has no release identity to fetch")
        payload = self.musicbrainz.release(album.release_mbid, refresh=refresh)
        if not payload:
            raise AlbumError("MusicBrainz could not retrieve this album edition")
        album.title = str(payload.get("title") or album.title)
        album.album_artist = _artist_credit(payload) or album.album_artist
        album.date = str(payload.get("date") or "") or album.date
        album.country = str(payload.get("country") or "") or album.country
        album.disambiguation = str(payload.get("disambiguation") or "") or album.disambiguation
        release_group = payload.get("release-group") or {}
        album.release_group_mbid = str(release_group.get("id")) if release_group.get("id") else album.release_group_mbid
        album.tracks = self._remote_tracks(album, payload)
        if not album.tracks:
            raise AlbumError("This MusicBrainz release contains no recording list")
        return self._resolve_tracks(album, scope=scope)

    @staticmethod
    def select_tracks(album: AlbumRef, selector: str | None = None) -> list[AlbumTrack]:
        ordered = sorted(album.tracks, key=lambda track: (track.disc_number, track.track_number, track.position))
        if not selector:
            return ordered
        by_flat = {track.position: track for track in ordered}
        by_disc = {(track.disc_number, track.track_number): track for track in ordered}

        def one(token: str) -> AlbumTrack:
            if "." in token:
                try:
                    disc_text, track_text = token.split(".", 1)
                    key = (int(disc_text), int(track_text))
                except ValueError as error:
                    raise AlbumError(f"Invalid multidisc track selector: {token}") from error
                track = by_disc.get(key)
            else:
                try:
                    track = by_flat.get(int(token))
                except ValueError as error:
                    raise AlbumError(f"Invalid track selector: {token}") from error
            if not track:
                raise AlbumError(f"Album track does not exist: {token}")
            return track

        selected = []
        for part in selector.split(","):
            token = part.strip()
            if not token:
                raise AlbumError("Track selector contains an empty position")
            if "-" not in token:
                selected.append(one(token))
                continue
            start_text, end_text = token.split("-", 1)
            start, end = one(start_text), one(end_text)
            start_index, end_index = ordered.index(start), ordered.index(end)
            if start_index > end_index:
                raise AlbumError(f"Track range is reversed: {token}")
            selected.extend(ordered[start_index : end_index + 1])
        identities = [(track.disc_number, track.track_number) for track in selected]
        if len(set(identities)) != len(identities):
            raise AlbumError("Track selector contains duplicates")
        return selected

    @staticmethod
    def order_tracks(
        tracks: list[AlbumTrack],
        order: str,
        *,
        seed: int | None = None,
        recommender: RecommendationEngine | None = None,
    ) -> tuple[list[AlbumTrack], int | None]:
        if order not in VALID_ALBUM_ORDERS:
            raise AlbumError(f"Unknown album order: {order}")
        values = list(tracks)
        if order in {"release", "custom"}:
            return values, seed
        if order == "shuffle":
            seed = seed if seed is not None else random.SystemRandom().randrange(2**31)
            random.Random(seed).shuffle(values)
            return values, seed
        if recommender is None:
            raise AlbumError("Smart album order requires the recommendation engine")
        resolved = [track for track in values if track.media]
        vectors = {}
        for track in resolved:
            if track.media is not None:
                vectors[track.position] = features(Candidate(track.media))
        scores = {
            track.position: recommender.ranker.score(vectors[track.position], explore=False, rng=random.Random(seed))
            for track in resolved
        }
        selected = []
        remaining = list(resolved)
        while remaining:
            chosen = max(
                remaining,
                key=lambda track: (
                    0.75 * scores[track.position]
                    - 0.25
                    * max(
                        (cosine(vectors[track.position], vectors[value.position]) for value in selected),
                        default=0,
                    ),
                    -values.index(track),
                ),
            )
            selected.append(chosen)
            remaining.remove(chosen)
        unresolved = [track for track in values if not track.media]
        return selected + unresolved, seed
