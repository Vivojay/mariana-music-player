"""Curated and Radio Browser stations with bounded playlist resolution and health state."""

from __future__ import annotations

from dataclasses import dataclass, field
import configparser
import io
import json
import subprocess
import time
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from .database import MarianaDatabase
from .identity import USER_AGENT
from .playback import CREATE_NO_WINDOW, find_executable


RADIO_BROWSER_URL = "https://de1.api.radio-browser.info/json"
MAX_PLAYLIST_DEPTH = 3


@dataclass(slots=True)
class RadioStation:
    station_id: str
    slug: str
    name: str
    provider: str
    endpoints: list[str]
    homepage: str | None = None
    country: str | None = None
    language: str | None = None
    tags: list[str] = field(default_factory=list)
    favorite: bool = False
    last_healthy_endpoint: str | None = None
    last_checked: float | None = None
    failure_count: int = 0


CURATED_STATIONS = [
    RadioStation(
        "somafm-groove-salad",
        "groove-salad",
        "SomaFM Groove Salad",
        "SomaFM",
        ["https://somafm.com/m3u/groovesalad.m3u"],
        homepage="https://somafm.com/groovesalad/",
        country="United States",
        language="English",
        tags=["ambient", "downtempo"],
    ),
    RadioStation(
        "somafm-secret-agent",
        "secret-agent",
        "SomaFM Secret Agent",
        "SomaFM",
        ["https://somafm.com/m3u/secretagent.m3u"],
        homepage="https://somafm.com/secretagent/",
        country="United States",
        language="English",
        tags=["lounge", "spy"],
    ),
    RadioStation(
        "antenne-bayern",
        "antenne-bayern",
        "ANTENNE BAYERN",
        "ANTENNE BAYERN",
        [
            "https://stream.antenne.de/antenne/stream/mp3",
            "https://stream.antenne.de/antenne/stream/aacp",
        ],
        homepage="https://www.antenne.de/",
        country="Germany",
        language="German",
        tags=["pop", "hits"],
    ),
]


class RadioError(RuntimeError):
    pass


def _playlist_kind(url: str, content_type: str, text: str) -> str | None:
    path = urlparse(url).path.lower()
    content_type = content_type.lower()
    if path.endswith(".pls") or "scpls" in content_type or text.lstrip().lower().startswith("[playlist]"):
        return "pls"
    if path.endswith((".m3u", ".m3u8")) or "mpegurl" in content_type or text.lstrip().startswith("#EXTM3U"):
        return "hls" if "#EXT-X-" in text else "m3u"
    return None


def _parse_playlist(url: str, kind: str, text: str) -> list[str]:
    if kind == "pls":
        parser = configparser.ConfigParser()
        try:
            parser.read_file(io.StringIO(text))
            section = parser["playlist"]
        except (configparser.Error, KeyError) as error:
            raise RadioError(f"Malformed PLS playlist at {url}: {error}") from error
        pairs = sorted(
            ((int(key[4:]), value.strip()) for key, value in section.items() if key.lower().startswith("file")),
            key=lambda pair: pair[0],
        )
        return [urljoin(url, value) for _, value in pairs if value]
    return [
        urljoin(url, line.strip())
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def resolve_playlist(
    url: str,
    *,
    session=None,
    timeout: float = 10,
    max_depth: int = MAX_PLAYLIST_DEPTH,
    _seen: set[str] | None = None,
) -> list[str]:
    if max_depth < 0:
        raise RadioError("Playlist recursion limit exceeded")
    seen = _seen if _seen is not None else set()
    if url in seen:
        raise RadioError(f"Playlist cycle detected at {url}")
    seen.add(url)
    client = session or requests.Session()
    try:
        response = client.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout, stream=True)
        response.raise_for_status()
    except requests.RequestException as error:
        raise RadioError(f"Radio endpoint is unavailable: {error}") from error
    content_type = response.headers.get("Content-Type", "")
    path = urlparse(url).path.lower()
    playlist_hint = path.endswith((".m3u", ".m3u8", ".pls")) or any(
        marker in content_type.lower() for marker in ("mpegurl", "scpls")
    )
    if content_type.lower().startswith("audio/") and not playlist_hint:
        response.close() if hasattr(response, "close") else None
        return [url]
    if hasattr(response, "iter_content"):
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=16_384):
            chunks.append(chunk)
            size += len(chunk)
            if size >= 1_000_000:
                break
        text = b"".join(chunks)[:1_000_000].decode("utf-8", errors="replace")
    else:
        text = response.text[:1_000_000]
    response.close() if hasattr(response, "close") else None
    kind = _playlist_kind(url, content_type, text)
    if kind is None:
        return [url]
    if kind == "hls":
        return [url]
    candidates = _parse_playlist(url, kind, text)
    if not candidates:
        raise RadioError(f"Playlist at {url} contained no stream endpoints")
    resolved = []
    failures = []
    for candidate in candidates:
        try:
            resolved.extend(
                resolve_playlist(
                    candidate,
                    session=client,
                    timeout=timeout,
                    max_depth=max_depth - 1,
                    _seen=seen,
                )
            )
        except RadioError as error:
            failures.append(str(error))
    if not resolved:
        raise RadioError("; ".join(failures) or f"Could not resolve {url}")
    return list(dict.fromkeys(resolved))


class RadioCatalog:
    def __init__(self, database: MarianaDatabase, *, session=None, browser_url: str = RADIO_BROWSER_URL):
        self.database = database
        self.session = session or requests.Session()
        self.browser_url = browser_url.rstrip("/")
        self.seed()

    def _save(self, station: RadioStation) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO radio_stations(
                    station_id, slug, name, provider, homepage, country, language, tags_json,
                    endpoints_json, favorite, last_healthy_endpoint, last_checked, failure_count
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(station_id) DO UPDATE SET
                    slug=excluded.slug, name=excluded.name, provider=excluded.provider,
                    homepage=excluded.homepage, country=excluded.country, language=excluded.language,
                    tags_json=excluded.tags_json, endpoints_json=excluded.endpoints_json,
                    favorite=MAX(radio_stations.favorite, excluded.favorite)
                """,
                (
                    station.station_id,
                    station.slug,
                    station.name,
                    station.provider,
                    station.homepage,
                    station.country,
                    station.language,
                    json.dumps(station.tags),
                    json.dumps(station.endpoints),
                    int(station.favorite),
                    station.last_healthy_endpoint,
                    station.last_checked,
                    station.failure_count,
                ),
            )

    def seed(self) -> None:
        for station in CURATED_STATIONS:
            self._save(station)

    @staticmethod
    def _from_row(row) -> RadioStation:
        return RadioStation(
            station_id=row["station_id"],
            slug=row["slug"],
            name=row["name"],
            provider=row["provider"],
            endpoints=json.loads(row["endpoints_json"]),
            homepage=row["homepage"],
            country=row["country"],
            language=row["language"],
            tags=json.loads(row["tags_json"]),
            favorite=bool(row["favorite"]),
            last_healthy_endpoint=row["last_healthy_endpoint"],
            last_checked=row["last_checked"],
            failure_count=row["failure_count"],
        )

    def list(self, *, favorites: bool = False) -> list[RadioStation]:
        condition = "WHERE favorite=1 AND enabled=1" if favorites else "WHERE enabled=1"
        return [
            self._from_row(row)
            for row in self.database.fetchall(f"SELECT * FROM radio_stations {condition} ORDER BY name")
        ]

    def get(self, slug_or_id: str) -> RadioStation:
        row = self.database.fetchone(
            "SELECT * FROM radio_stations WHERE enabled=1 AND (slug=? OR station_id=?)",
            (slug_or_id, slug_or_id),
        )
        if not row:
            raise RadioError(f"Unknown radio station: {slug_or_id}")
        return self._from_row(row)

    def favorite(self, slug_or_id: str, enabled: bool = True) -> RadioStation:
        station = self.get(slug_or_id)
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE radio_stations SET favorite=? WHERE station_id=?", (int(enabled), station.station_id)
            )
        return self.get(slug_or_id)

    def search(self, query: str, *, limit: int = 20, import_results: bool = True) -> list[RadioStation]:
        try:
            response = self.session.get(
                f"{self.browser_url}/stations/search",
                params={"name": query, "hidebroken": "true", "limit": min(max(limit, 1), 100), "order": "votes"},
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ValueError("Radio Browser returned a non-list response")
        except (requests.RequestException, ValueError, AttributeError) as error:
            raise RadioError(f"Radio Browser search failed: {error}") from error
        stations = []
        for item in payload:
            if str(item.get("lastcheckok", "1")) not in {"1", "true", "True"}:
                continue
            endpoint = item.get("url_resolved") or item.get("url")
            station_id = item.get("stationuuid")
            if not endpoint or not station_id:
                continue
            slug = "rb-" + station_id[:12].lower()
            station = RadioStation(
                station_id=station_id,
                slug=slug,
                name=item.get("name") or slug,
                provider="Radio Browser",
                endpoints=[endpoint],
                homepage=item.get("homepage") or None,
                country=item.get("country") or None,
                language=item.get("language") or None,
                tags=[tag.strip() for tag in (item.get("tags") or "").split(",") if tag.strip()],
            )
            stations.append(station)
            if import_results:
                self._save(station)
        return stations

    def endpoints(self, station: RadioStation) -> list[str]:
        ordered = list(station.endpoints)
        if station.last_healthy_endpoint in ordered:
            ordered.remove(station.last_healthy_endpoint)
            ordered.insert(0, station.last_healthy_endpoint)
        resolved = []
        for endpoint in ordered:
            try:
                resolved.extend(resolve_playlist(endpoint, session=self.session))
            except RadioError:
                continue
        if not resolved:
            raise RadioError(f"No usable endpoint remains for {station.name}")
        return list(dict.fromkeys(resolved))

    def health(self, slug_or_id: str, *, ffmpeg_bin: str | None = None, force: bool = False) -> dict[str, Any]:
        station = self.get(slug_or_id)
        backoff = min(3600, 30 * (2 ** min(station.failure_count, 7)))
        if not force and station.last_checked and time.time() - station.last_checked < backoff:
            return {"status": "backoff", "retry_after": station.last_checked + backoff, "station": station.name}
        executable = find_executable("ffmpeg", ffmpeg_bin)
        errors = []
        for endpoint in self.endpoints(station):
            try:
                subprocess.run(
                    [
                        executable,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-rw_timeout",
                        "10000000",
                        "-i",
                        endpoint,
                        "-map",
                        "0:a:0",
                        "-t",
                        "5",
                        "-f",
                        "null",
                        "-",
                    ],
                    capture_output=True,
                    timeout=12,
                    check=True,
                    creationflags=CREATE_NO_WINDOW,
                )
                now = time.time()
                with self.database.transaction() as connection:
                    connection.execute(
                        "UPDATE radio_stations SET last_healthy_endpoint=?, last_checked=?, failure_count=0 "
                        "WHERE station_id=?",
                        (endpoint, now, station.station_id),
                    )
                return {"status": "healthy", "endpoint": endpoint, "station": station.name, "checked_at": now}
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        now = time.time()
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE radio_stations SET last_checked=?, failure_count=failure_count+1 WHERE station_id=?",
                (now, station.station_id),
            )
        return {"status": "failed", "errors": errors, "station": station.name, "checked_at": now}
