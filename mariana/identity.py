"""Chromaprint-only identification, MusicBrainz enrichment, and LRCLIB lyrics."""

from __future__ import annotations

from array import array
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import wave
from typing import Any

import requests
from mutagen import File as MutagenFile, MutagenError

from .database import MarianaDatabase
from .models import IdentityStatus, LyricsResult, MediaRef, MediaSource, TrackIdentity
from .playback import CHANNELS, SAMPLE_RATE, SAMPLE_WIDTH, CREATE_NO_WINDOW, find_executable


APP_NAME = "Mariana"
APP_VERSION = "0.7.0-dev"
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (https://github.com/Vivojay/mariana-music-player)"
ACOUSTID_URL = "https://api.acoustid.org/v2/lookup"
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2"
LRCLIB_URL = "https://lrclib.net/api"
MIN_FINGERPRINT_SECONDS = 8
MIN_SCORE = 0.85
MIN_MARGIN = 0.05
MAX_DURATION_DIFFERENCE = 5.0


class IdentificationError(RuntimeError):
    pass


def find_fpcalc(configured: str | None = None) -> str:
    if configured:
        return find_executable("fpcalc", configured)
    local = Path(__file__).resolve().parents[1] / ".tools" / "chromaprint-1.6.0"
    matches = list(local.rglob("fpcalc.exe")) if local.exists() else []
    if matches:
        return str(matches[0].resolve())
    return find_executable("fpcalc")


def _run_fpcalc(path: Path | str, fpcalc_bin: str | None = None) -> tuple[float, str]:
    executable = find_fpcalc(fpcalc_bin)
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
        return float(payload["duration"]), str(payload["fingerprint"])
    except (OSError, subprocess.SubprocessError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise IdentificationError(f"Chromaprint could not fingerprint the audio: {error}") from error


def fingerprint_file(path: Path | str, fpcalc_bin: str | None = None) -> tuple[float, str]:
    return _run_fpcalc(Path(path), fpcalc_bin)


def fingerprint_pcm(pcm: bytes, fpcalc_bin: str | None = None) -> tuple[float, str]:
    duration = len(pcm) / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)
    if duration < MIN_FINGERPRINT_SECONDS:
        raise IdentificationError(f"At least {MIN_FINGERPRINT_SECONDS} seconds of audio are required")
    temporary = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    path = Path(temporary.name)
    temporary.close()
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
                    "duration": int(round(duration)),
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

    def recording(self, mbid: str, refresh: bool = False) -> dict[str, Any] | None:
        if not refresh and mbid in self._cache:
            return self._cache[mbid]
        with self._lock:
            payload = None
            for attempt in range(self.retries):
                delay = self.minimum_interval - (time.monotonic() - self._last_request)
                if delay > 0:
                    time.sleep(delay)
                try:
                    response = self.session.get(
                        f"{MUSICBRAINZ_URL}/recording/{mbid}",
                        params={"fmt": "json", "inc": "artists+releases+work-rels+tags"},
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
                return self._cache.get(mbid)
        self._cache[mbid] = payload
        return payload

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


def local_lyrics(media: MediaRef) -> LyricsResult | None:
    if media.source != MediaSource.LOCAL:
        return None
    path = Path(media.original_uri)
    sidecar = path.with_suffix(".lrc")
    if sidecar.is_file():
        synced = sidecar.read_text(encoding="utf-8-sig")
        return LyricsResult(
            IdentityStatus.IDENTIFIED,
            plain=_plain_from_lrc(synced),
            synced=synced,
            provider="local-sidecar",
            attribution=str(sidecar),
            retrieved_at=time.time(),
        )
    try:
        audio = MutagenFile(path)
        tags = getattr(audio, "tags", None)
        if tags:
            candidates = []
            for key in tags.keys():
                value = tags[key]
                key_text = str(key).lower()
                if "lyrics" in key_text or key_text.startswith("uslt"):
                    candidates.append(getattr(value, "text", value))
            if candidates:
                plain = str(candidates[0])
                return LyricsResult(
                    IdentityStatus.IDENTIFIED,
                    plain=plain,
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
            f"{LRCLIB_URL}/{endpoint}", params=params, headers={"User-Agent": USER_AGENT}, timeout=self.timeout
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

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
            "duration": int(round(identity.duration)) if identity.duration is not None else 0,
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

    def identify(self, media: MediaRef, pcm: bytes | None = None, refresh: bool = False) -> TrackIdentity:
        if not refresh:
            row = self.database.fetchone("SELECT identity_json FROM track_identities WHERE stable_id=?", (media.stable_id,))
            if row:
                return TrackIdentity.from_dict(json.loads(row["identity_json"]))
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
        identity = self.acoustid.identify(duration, fingerprint, media.duration)
        identity = self.musicbrainz.enrich(identity)
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
