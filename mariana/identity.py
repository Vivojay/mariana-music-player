"""Chromaprint-only identification, MusicBrainz enrichment, and LRCLIB lyrics."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import threading
import time
import wave
from array import array
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

import requests
from mutagen import File as MutagenFile  # pyright: ignore[reportMissingImports]
from mutagen import MutagenError  # pyright: ignore[reportMissingImports]

from .database import MarianaDatabase
from .models import IdentityStatus, LyricsResult, MediaRef, MediaSource, TrackIdentity
from .playback import CHANNELS, CREATE_NO_WINDOW, SAMPLE_RATE, SAMPLE_WIDTH, PlaybackError, find_executable
from .version import __version__

APP_NAME = "Mariana"
APP_VERSION = __version__
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (https://github.com/Vivojay/mariana-music-player)"
ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2"
LRCLIB_URL = "https://lrclib.net/api"
MIN_FINGERPRINT_SECONDS = 8
MIN_SCORE = 0.85
MIN_MARGIN = 0.05
MAX_DURATION_DIFFERENCE = 5.0
MAX_LYRICS_FILE_BYTES = 4 * 1024 * 1024
MAX_LYRICS_RESPONSE_BYTES = 8 * 1024 * 1024


class IdentificationError(RuntimeError):
    pass


def find_fpcalc(configured: str | None = None) -> str:
    return find_executable("fpcalc", configured)


def _run_fpcalc(path: Path | str, fpcalc_bin: str | None = None) -> tuple[float, str]:
    try:
        executable = find_fpcalc(fpcalc_bin)
    except PlaybackError as error:
        raise IdentificationError(
            "Chromaprint fpcalc is unavailable; run 'tools setup' to configure or install it"
        ) from error
    try:
        result = subprocess.run(
            [executable, "-json", "-length", "120", str(path)],
            capture_output=True,
            text=True,
            timeout=150,
            check=True,
            creationflags=CREATE_NO_WINDOW,
        )
        payload = json.loads(result.stdout)
        duration, fingerprint = float(payload["duration"]), payload["fingerprint"]
        if not math.isfinite(duration) or duration <= 0 or not isinstance(fingerprint, str) or not fingerprint or len(fingerprint) > 1_000_000:
            raise ValueError("Invalid fingerprint output")
        return duration, fingerprint
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise IdentificationError(f"Chromaprint could not fingerprint the audio: {error}") from error


def fingerprint_file(path: Path | str, fpcalc_bin: str | None = None) -> tuple[float, str]:
    return _run_fpcalc(Path(path), fpcalc_bin)


def fingerprint_pcm(pcm: bytes, fpcalc_bin: str | None = None) -> tuple[float, str]:
    duration = len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    if duration < MIN_FINGERPRINT_SECONDS:
        raise IdentificationError(f"At least {MIN_FINGERPRINT_SECONDS} seconds of audio are required")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
        path = Path(temporary.name)
    try:
        float_samples = array("f")
        float_samples.frombytes(pcm)
        signed_samples = array(
            "h",
            (int(max(-1.0, min(1.0, sample)) * 32767) for sample in float_samples),
        )
        with wave.open(str(path), "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(signed_samples.tobytes())
        return _run_fpcalc(path, fpcalc_bin)
    finally:
        path.unlink(missing_ok=True)


class AcoustIDClient:
    def __init__(self, api_key: str | None = None, *, session=None, timeout: float = 15):
        self.api_key = api_key or os.getenv("ACOUSTID_API_KEY")
        self.session = session or requests.Session()
        self.timeout = timeout

    def identify(self, duration: float, fingerprint: str, expected_duration: float | None = None) -> TrackIdentity:
        if not self.api_key:
            return TrackIdentity(IdentityStatus.UNAVAILABLE, metadata={"reason": "ACOUSTID_API_KEY is not configured"})
        try:
            response = self.session.get(
                ACOUSTID_URL,
                params={
                    "client": self.api_key,
                    "duration": round(duration),
                    "fingerprint": fingerprint,
                    "meta": "recordings releasegroups compress",
                    "format": "json",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=self.timeout,
            )
            response.raise_for_status()
            results = sorted(response.json().get("results", []), key=lambda item: item.get("score", 0), reverse=True)
        except (requests.RequestException, ValueError, AttributeError) as error:
            return TrackIdentity(IdentityStatus.OFFLINE, metadata={"reason": str(error)})
        if not results:
            return TrackIdentity(IdentityStatus.NO_MATCH, provenance=["acoustid"])
        best = results[0]
        score = float(best.get("score", 0))
        runner_up = float(results[1].get("score", 0)) if len(results) > 1 else 0.0
        recordings = best.get("recordings") or []
        recording = recordings[0] if recordings else {}
        candidate_duration = recording.get("duration")
        duration_ok = True
        if expected_duration is not None and candidate_duration is not None:
            duration_ok = abs(float(candidate_duration) - expected_duration) <= MAX_DURATION_DIFFERENCE
        if score < MIN_SCORE or score - runner_up < MIN_MARGIN or not duration_ok or not recording.get("id"):
            return TrackIdentity(
                IdentityStatus.AMBIGUOUS,
                acoustid=best.get("id"),
                confidence=score,
                provenance=["acoustid"],
                metadata={"runner_up": runner_up, "duration_ok": duration_ok},
            )
        artists = recording.get("artists") or []
        releasegroups = recording.get("releasegroups") or []
        return TrackIdentity(
            IdentityStatus.IDENTIFIED,
            acoustid=best.get("id"),
            recording_mbid=recording.get("id"),
            title=recording.get("title"),
            artist=", ".join(artist.get("name", "") for artist in artists if artist.get("name")) or None,
            album=releasegroups[0].get("title") if releasegroups else None,
            duration=float(candidate_duration) if candidate_duration is not None else None,
            confidence=score,
            provenance=["chromaprint", "acoustid"],
        )


class MusicBrainzClient:
    def __init__(
        self,
        *,
        session=None,
        timeout: float = 15,
        minimum_interval: float = 1.0,
        retries: int = 3,
        backoff: float = 0.5,
    ):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.minimum_interval = minimum_interval
        self.retries = max(1, retries)
        self.backoff = max(0.0, backoff)
        self._last_request = 0.0
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}

    def _request(
        self,
        endpoint: str,
        *,
        params: dict[str, Any],
        cache_key: str,
        refresh: bool = False,
    ) -> dict[str, Any] | None:
        if not refresh and cache_key in self._cache:
            return self._cache[cache_key]
        with self._lock:
            payload = None
            for attempt in range(self.retries):
                delay = self.minimum_interval - (time.monotonic() - self._last_request)
                if delay > 0:
                    time.sleep(delay)
                try:
                    response = self.session.get(
                        f"{MUSICBRAINZ_URL}/{endpoint.lstrip('/')}",
                        params=params,
                        headers={"User-Agent": USER_AGENT},
                        timeout=self.timeout,
                    )
                    self._last_request = time.monotonic()
                    response.raise_for_status()
                    payload = response.json()
                    break
                except (requests.RequestException, ValueError, AttributeError):
                    if attempt + 1 < self.retries:
                        time.sleep(self.backoff * (2**attempt))
            if payload is None:
                return self._cache.get(cache_key)
        if not isinstance(payload, dict):
            return None
        self._cache[cache_key] = payload
        return payload

    def recording(self, mbid: str, refresh: bool = False) -> dict[str, Any] | None:
        return self._request(
            f"recording/{mbid}",
            params={"fmt": "json", "inc": "artists+releases+work-rels+tags"},
            cache_key=mbid,
            refresh=refresh,
        )

    def search_releases(
        self,
        query: str,
        *,
        limit: int = 10,
        offset: int = 0,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        normalized = query.strip()
        if not normalized or limit < 1:
            return []
        payload = self._request(
            "release/",
            params={
                "fmt": "json",
                "query": normalized,
                "limit": min(100, limit),
                "offset": max(0, offset),
            },
            cache_key=f"release-search:{normalized.casefold()}:{limit}:{offset}",
            refresh=refresh,
        )
        return [
            item
            for item in (payload or {}).get("releases", [])
            if isinstance(item, dict) and item.get("id") and item.get("title")
        ]

    def release(self, mbid: str, refresh: bool = False) -> dict[str, Any] | None:
        return self._request(
            f"release/{mbid}",
            params={
                "fmt": "json",
                "inc": "recordings+artist-credits+release-groups+media",
            },
            cache_key=f"release:{mbid}",
            refresh=refresh,
        )

    def enrich(self, identity: TrackIdentity) -> TrackIdentity:
        if identity.status != IdentityStatus.IDENTIFIED or not identity.recording_mbid:
            return identity
        data = self.recording(identity.recording_mbid)
        if not data:
            return identity
        credits = data.get("artist-credit") or []
        artists = [credit.get("name") for credit in credits if credit.get("name")]
        releases = data.get("releases") or []
        relations = data.get("relations") or []
        work = next((relation.get("work") for relation in relations if relation.get("target-type") == "work"), None)
        identity.title = data.get("title") or identity.title
        identity.artist = ", ".join(artists) or identity.artist
        identity.album = (releases[0].get("title") if releases else None) or identity.album
        identity.work_mbid = work.get("id") if work else identity.work_mbid
        identity.metadata["musicbrainz"] = data
        if "musicbrainz" not in identity.provenance:
            identity.provenance.append("musicbrainz")
        return identity


def _plain_from_lrc(value: str) -> str:
    lines = []
    for line in value.splitlines():
        cleaned = re.sub(r"^(?:\[[0-9:.]+\])+", "", line).strip()
        if cleaned and not re.match(r"^\[[a-z]+:.*\]$", cleaned, flags=re.IGNORECASE):
            lines.append(cleaned)
    return "\n".join(lines)


def _tag_text_values(value: Any) -> tuple[str, ...]:
    text = getattr(value, "text", value)
    if isinstance(text, str):
        return (text,)
    if isinstance(text, (list, tuple)):
        return tuple(item for item in text if isinstance(item, str))
    return ()


def _lrc_from_sylt(value: Any) -> tuple[str | None, str | None]:
    entries = getattr(value, "text", None)
    if not isinstance(entries, (list, tuple)):
        return None, None
    plain = []
    timed = []
    # ID3 SYLT uses 1 for MPEG frames and 2 for absolute milliseconds.
    # Unknown units remain plain lyrics; do not invent a time conversion.
    milliseconds = getattr(value, "format", None) == 2
    for entry in entries:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        text, timestamp = entry
        if not isinstance(text, str):
            continue
        plain.append(text)
        if milliseconds and isinstance(timestamp, int) and not isinstance(timestamp, bool) and timestamp >= 0:
            minutes, remainder = divmod(timestamp, 60_000)
            seconds, fraction = divmod(remainder, 1_000)
            timed.append(f"[{minutes:02d}:{seconds:02d}.{fraction:03d}]{text}")
    return ("\n".join(timed) or None, "\n".join(plain) or None)


def local_lyrics(media: MediaRef) -> LyricsResult | None:
    if media.source != MediaSource.LOCAL:
        return None
    path = Path(media.original_uri)
    sidecar = path.with_suffix(".lrc")
    try:
        if sidecar.is_file() and sidecar.stat().st_size <= MAX_LYRICS_FILE_BYTES:
            # The extra byte detects growth between stat and read. Oversized,
            # unreadable or incorrectly encoded sidecars fall through to tags.
            with sidecar.open("rb") as source:
                payload = source.read(MAX_LYRICS_FILE_BYTES + 1)
            if len(payload) <= MAX_LYRICS_FILE_BYTES:
                synced = payload.decode("utf-8-sig")
                return LyricsResult(
                    IdentityStatus.IDENTIFIED,
                    plain=_plain_from_lrc(synced),
                    synced=synced,
                    provider="local-sidecar",
                    attribution=str(sidecar),
                    retrieved_at=time.time(),
                )
    except (OSError, UnicodeError):
        pass
    try:
        audio = MutagenFile(path)
        tags = getattr(audio, "tags", None)
        if tags:
            synced_candidates = []
            plain_candidates = []
            for key in tags:
                value = tags[key]
                key_text = str(key).lower()
                if key_text.startswith("sylt"):
                    synced, plain = _lrc_from_sylt(value)
                    if synced:
                        synced_candidates.append(synced)
                    if plain:
                        plain_candidates.append(plain)
                elif "syncedlyrics" in key_text or "synced_lyrics" in key_text:
                    synced_candidates.extend(_tag_text_values(value))
                elif "lyrics" in key_text or key_text.startswith("uslt"):
                    plain_candidates.extend(_tag_text_values(value))
            if synced_candidates or plain_candidates:
                synced = synced_candidates[0] if synced_candidates else None
                plain = plain_candidates[0] if plain_candidates else None
                return LyricsResult(
                    IdentityStatus.IDENTIFIED,
                    plain=plain or (_plain_from_lrc(synced) if synced else None),
                    synced=synced,
                    provider="embedded",
                    attribution="embedded file metadata",
                    retrieved_at=time.time(),
                )
    except (OSError, ValueError, TypeError, MutagenError):
        pass
    return None


class LRCLIBClient:
    def __init__(self, *, session=None, timeout: float = 15):
        self.session = session or requests.Session()
        self.timeout = timeout

    def _get(self, endpoint: str, params: dict[str, Any]) -> Any:
        response = self.session.get(
            f"{LRCLIB_URL}/{endpoint}", params=params, headers={"User-Agent": USER_AGENT},
            timeout=self.timeout, stream=True,
        )
        try:
            if response.status_code == 404:
                return None
            response.raise_for_status()
            headers = getattr(response, "headers", {})
            declared = headers.get("Content-Length") if hasattr(headers, "get") else None
            if declared is not None:
                try:
                    declared_bytes = int(declared)
                except (TypeError, ValueError):
                    declared_bytes = 0  # The streamed limit remains authoritative.
                if declared_bytes > MAX_LYRICS_RESPONSE_BYTES:
                    raise ValueError("Lyrics response exceeds the supported size")
            iterator = getattr(response, "iter_content", None)
            if not callable(iterator):
                # Compatibility for injected in-memory response adapters. Real
                # requests.Response objects always use the bounded stream below.
                payload = response.json()
                if len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) > MAX_LYRICS_RESPONSE_BYTES:
                    raise ValueError("Lyrics response exceeds the supported size")
                return payload
            payload = bytearray()
            deadline = time.monotonic() + max(0.1, self.timeout)
            chunks = iterator(chunk_size=16_384)
            if not isinstance(chunks, Iterable) or isinstance(chunks, (str, bytes, bytearray)):
                raise ValueError("Lyrics response stream is malformed")
            for chunk in chunks:
                if time.monotonic() > deadline:
                    raise requests.Timeout("Lyrics response exceeded the time limit")
                if not isinstance(chunk, bytes):
                    raise ValueError("Lyrics response stream is malformed")
                if not chunk:
                    continue
                if len(payload) + len(chunk) > MAX_LYRICS_RESPONSE_BYTES:
                    raise ValueError("Lyrics response exceeds the supported size")
                payload.extend(chunk)
            return json.loads(payload)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _result(payload: dict[str, Any], confidence: float) -> LyricsResult:
        return LyricsResult(
            IdentityStatus.IDENTIFIED,
            plain=payload.get("plainLyrics"),
            synced=payload.get("syncedLyrics"),
            provider="LRCLIB",
            provider_id=str(payload.get("id")) if payload.get("id") is not None else None,
            retrieved_at=time.time(),
            attribution="Lyrics provided by LRCLIB",
            identity_confidence=confidence,
        )

    def find(self, identity: TrackIdentity) -> LyricsResult:
        if not identity.title or not identity.artist:
            return LyricsResult(IdentityStatus.NO_LYRICS, provider="LRCLIB")
        exact = {
            "track_name": identity.title,
            "artist_name": identity.artist,
            "album_name": identity.album or "",
            "duration": round(identity.duration) if identity.duration is not None else 0,
        }
        try:
            payload = self._get("get", exact)
            if payload and (payload.get("plainLyrics") or payload.get("syncedLyrics")):
                return self._result(payload, identity.confidence)
            results = self._get("search", {"track_name": identity.title, "artist_name": identity.artist}) or []
            for candidate in results:
                if candidate.get("plainLyrics") or candidate.get("syncedLyrics"):
                    return self._result(candidate, identity.confidence)
        except (requests.RequestException, ValueError, AttributeError):
            return LyricsResult(IdentityStatus.OFFLINE, provider="LRCLIB")
        return LyricsResult(IdentityStatus.NO_LYRICS, provider="LRCLIB")


class IdentificationService:
    def __init__(
        self,
        database: MarianaDatabase,
        *,
        acoustid: AcoustIDClient | None = None,
        musicbrainz: MusicBrainzClient | None = None,
        lrclib: LRCLIBClient | None = None,
        fpcalc_bin: str | None = None,
    ):
        self.database = database
        self.acoustid = acoustid or AcoustIDClient()
        self.musicbrainz = musicbrainz or MusicBrainzClient()
        self.lrclib = lrclib or LRCLIBClient()
        self.fpcalc_bin = fpcalc_bin

    @staticmethod
    def _file_signature(media: MediaRef) -> str | None:
        if media.source != MediaSource.LOCAL:
            return None
        stat = Path(media.original_uri).stat()
        return f"{stat.st_size}:{stat.st_mtime_ns}:{stat.st_ctime_ns}"

    def saved_fingerprint(self, media: MediaRef) -> tuple[float, str] | None:
        """Read the existing identification store without a provider request."""
        if media.capabilities.live or not media.capabilities.finite:
            return None
        row = self.database.fetchone(
            "SELECT identity_json, fingerprint, fingerprint_duration FROM track_identities WHERE stable_id=?",
            (media.stable_id,),
        )
        if not row or not row["fingerprint"] or not row["fingerprint_duration"]:
            return None
        if media.source == MediaSource.LOCAL:
            metadata = json.loads(row["identity_json"]).get("metadata", {})
            try:
                if metadata.get("fingerprint_file_signature") != self._file_signature(media):
                    return None
            except OSError:
                return None
        return float(row["fingerprint_duration"]), str(row["fingerprint"])

    def calculate_fingerprint(self, media: MediaRef, pcm: bytes | None = None) -> tuple[float, str]:
        """Calculate locally, without recognition requests or playback changes.

        A fingerprint-only row is not an identification result. A subsequent
        explicit identify operation can enrich it without repeating calculation.
        """
        if media.capabilities.live or not media.capabilities.finite or not media.capabilities.fingerprintable:
            raise IdentificationError("Whole-media fingerprints require finite audio; use 'media identify listen' for a live segment")
        before = self._file_signature(media)
        if media.source == MediaSource.LOCAL:
            duration, fingerprint = fingerprint_file(media.original_uri, self.fpcalc_bin)
            if self._file_signature(media) != before:
                raise IdentificationError("The local file changed during fingerprint calculation; retry the command")
        else:
            if pcm is None:
                raise IdentificationError("Play this online item before calculating its fingerprint")
            duration, fingerprint = fingerprint_pcm(pcm, self.fpcalc_bin)
        pending = TrackIdentity(
            IdentityStatus.UNAVAILABLE,
            provenance=["chromaprint"],
            metadata={"fingerprint_only": True, "fingerprint_file_signature": before,
                      "reason": "Fingerprint calculated; recognition has not been requested"},
        )
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO track_identities(stable_id,identity_json,fingerprint,fingerprint_duration,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(stable_id) DO UPDATE SET identity_json=excluded.identity_json, "
                "fingerprint=excluded.fingerprint,fingerprint_duration=excluded.fingerprint_duration,updated_at=excluded.updated_at",
                (media.stable_id, json.dumps(pending.to_dict()), fingerprint, duration, time.time()),
            )
        return duration, fingerprint

    def identify(self, media: MediaRef, pcm: bytes | None = None, refresh: bool = False) -> TrackIdentity:
        if not refresh:
            row = self.database.fetchone("SELECT identity_json FROM track_identities WHERE stable_id=?", (media.stable_id,))
            if row:
                cached = TrackIdentity.from_dict(json.loads(row["identity_json"]))
                if not cached.metadata.get("fingerprint_only"):
                    return cached
                if saved := self.saved_fingerprint(media):
                    return self.identify_fingerprint(media, *saved)
        try:
            if pcm is not None:
                duration, fingerprint = fingerprint_pcm(pcm, self.fpcalc_bin)
            elif media.source == MediaSource.LOCAL:
                duration, fingerprint = fingerprint_file(media.original_uri, self.fpcalc_bin)
            else:
                return TrackIdentity(IdentityStatus.INSUFFICIENT_AUDIO)
        except IdentificationError as error:
            status = IdentityStatus.INSUFFICIENT_AUDIO if "seconds" in str(error) else IdentityStatus.UNAVAILABLE
            return TrackIdentity(status, metadata={"reason": str(error)})
        return self.identify_fingerprint(media, duration, fingerprint)

    def identify_fingerprint(self, media: MediaRef, duration: float, fingerprint: str) -> TrackIdentity:
        """Enrich a fingerprint already calculated by the library profiler."""
        return self._identify_fingerprint(
            media,
            duration,
            fingerprint,
            expected_duration=media.duration,
            persist=True,
        )

    def identify_pcm_window(self, media: MediaRef, pcm: bytes) -> TrackIdentity:
        """Identify one invocation-time PCM window without changing whole-media identity."""
        try:
            duration, fingerprint = fingerprint_pcm(pcm, self.fpcalc_bin)
        except IdentificationError as error:
            status = (
                IdentityStatus.INSUFFICIENT_AUDIO
                if "seconds" in str(error)
                else IdentityStatus.UNAVAILABLE
            )
            return TrackIdentity(status, metadata={"reason": str(error)})
        return self._identify_fingerprint(
            media,
            duration,
            fingerprint,
            expected_duration=None,
            persist=False,
        )

    def _identify_fingerprint(
        self,
        media: MediaRef,
        duration: float,
        fingerprint: str,
        *,
        expected_duration: float | None,
        persist: bool,
    ) -> TrackIdentity:
        identity = self.acoustid.identify(duration, fingerprint, expected_duration)
        identity = self.musicbrainz.enrich(identity)
        if persist:
            if media.source == MediaSource.LOCAL:
                with suppress(OSError):
                    identity.metadata["fingerprint_file_signature"] = self._file_signature(media)
            with self.database.transaction() as connection:
                connection.execute(
                    "INSERT INTO track_identities(stable_id, identity_json, fingerprint, fingerprint_duration, updated_at) "
                    "VALUES(?, ?, ?, ?, ?) ON CONFLICT(stable_id) DO UPDATE SET "
                    "identity_json=excluded.identity_json, fingerprint=excluded.fingerprint, "
                    "fingerprint_duration=excluded.fingerprint_duration, updated_at=excluded.updated_at",
                    (media.stable_id, json.dumps(identity.to_dict()), fingerprint, duration, time.time()),
                )
        return identity

    def lyrics(self, media: MediaRef, identity: TrackIdentity, refresh: bool = False) -> LyricsResult:
        local = local_lyrics(media)
        if local:
            return local
        cache_key = identity.recording_mbid or hashlib.sha256(
            f"{identity.artist}\0{identity.title}\0{identity.album}\0{identity.duration}".encode()
        ).hexdigest()
        if not refresh:
            row = self.database.fetchone("SELECT * FROM lyrics_cache WHERE cache_key=?", (cache_key,))
            if row:
                return LyricsResult(
                    status=IdentityStatus(row["status"]),
                    plain=row["plain_lyrics"],
                    synced=row["synced_lyrics"],
                    provider=row["provider"],
                    provider_id=row["provider_id"],
                    retrieved_at=row["retrieved_at"],
                    attribution=f"Lyrics provided by {row['provider']}",
                    identity_confidence=row["identity_confidence"],
                )
        result = self.lrclib.find(identity)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO lyrics_cache(cache_key, status, provider, plain_lyrics, synced_lyrics, provider_id, "
                "identity_confidence, retrieved_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(cache_key) "
                "DO UPDATE SET status=excluded.status, provider=excluded.provider, plain_lyrics=excluded.plain_lyrics, "
                "synced_lyrics=excluded.synced_lyrics, provider_id=excluded.provider_id, "
                "identity_confidence=excluded.identity_confidence, retrieved_at=excluded.retrieved_at",
                (
                    cache_key,
                    result.status.value,
                    result.provider or "LRCLIB",
                    result.plain,
                    result.synced,
                    result.provider_id,
                    result.identity_confidence,
                    result.retrieved_at or time.time(),
                ),
            )
        return result
