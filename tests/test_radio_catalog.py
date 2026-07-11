from pathlib import Path
import subprocess

import pytest
import requests

from mariana.database import MarianaDatabase
from mariana.radio import RadioCatalog, RadioError, resolve_playlist


class Response:
    def __init__(self, text="", payload=None, headers=None, status=200):
        self.text = text
        self._payload = payload
        self.headers = headers or {}
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, mapping=None, search=None):
        self.mapping = mapping or {}
        self.search = search

    def get(self, url, **_kwargs):
        if url.endswith("/stations/search"):
            return Response(payload=self.search)
        value = self.mapping[url]
        if isinstance(value, Exception):
            raise value
        return value


def test_m3u_pls_hls_resolution_and_cycles():
    session = Session(
        {
            "https://x/list.m3u": Response("#EXTM3U\nsub/list.pls\nhttps://x/live.aac", {"unused": 1}),
            "https://x/sub/list.pls": Response("[playlist]\nFile1=https://x/live.mp3\nNumberOfEntries=1"),
            "https://x/live.mp3": Response("binary", headers={"Content-Type": "audio/mpeg"}),
            "https://x/live.aac": Response("binary", headers={"Content-Type": "audio/aac"}),
            "https://x/live.m3u8": Response("#EXTM3U\n#EXT-X-VERSION:3\nsegment.ts"),
        }
    )
    assert resolve_playlist("https://x/list.m3u", session=session) == [
        "https://x/live.mp3",
        "https://x/live.aac",
    ]
    assert resolve_playlist("https://x/live.m3u8", session=session) == ["https://x/live.m3u8"]

    cyclic = Session({"https://x/a.m3u": Response("https://x/a.m3u")})
    with pytest.raises(RadioError, match="cycle"):
        resolve_playlist("https://x/a.m3u", session=cyclic)


def test_malformed_and_empty_playlists_are_typed():
    with pytest.raises(RadioError, match="Malformed PLS"):
        resolve_playlist("https://x/list.pls", session=Session({"https://x/list.pls": Response("[broken")}))
    with pytest.raises(RadioError, match="no stream"):
        resolve_playlist("https://x/list.m3u", session=Session({"https://x/list.m3u": Response("#EXTM3U")}))


def test_catalog_seed_search_import_favorites_and_filter(tmp_path: Path):
    search = [
        {
            "stationuuid": "1234567890abcdef",
            "name": "Good",
            "url_resolved": "https://x/good.mp3",
            "lastcheckok": 1,
            "tags": "jazz, instrumental",
        },
        {"stationuuid": "broken", "name": "Broken", "url": "https://x/bad", "lastcheckok": 0},
    ]
    with MarianaDatabase(tmp_path / "radio.db") as database:
        catalog = RadioCatalog(database, session=Session(search=search))
        assert {station.slug for station in catalog.list()} >= {"groove-salad", "antenne-bayern"}
        results = catalog.search("jazz")
        assert [station.name for station in results] == ["Good"]
        catalog.favorite(results[0].slug)
        assert [station.name for station in catalog.list(favorites=True)] == ["Good"]


def test_health_failover_persists_last_healthy_and_backoff(tmp_path: Path, monkeypatch):
    session = Session(
        {
            "https://somafm.com/m3u/groovesalad.m3u": Response("https://x/bad\nhttps://x/good"),
            "https://x/bad": Response("audio", headers={"Content-Type": "audio/mpeg"}),
            "https://x/good": Response("audio", headers={"Content-Type": "audio/mpeg"}),
        }
    )
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        if "https://x/bad" in command:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("mariana.radio.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.radio.subprocess.run", run)
    with MarianaDatabase(tmp_path / "radio.db") as database:
        catalog = RadioCatalog(database, session=session)
        result = catalog.health("groove-salad", force=True)
        assert result["status"] == "healthy"
        assert result["endpoint"] == "https://x/good"
        assert catalog.get("groove-salad").last_healthy_endpoint == "https://x/good"
        assert catalog.health("groove-salad")["status"] == "backoff"


def test_search_and_health_failures_are_typed_and_persisted(tmp_path: Path, monkeypatch):
    with MarianaDatabase(tmp_path / "radio.db") as database:
        catalog = RadioCatalog(database, session=Session(search=None))
        with pytest.raises(RadioError, match="search failed"):
            catalog.search("anything")

        session = Session(
            {
                "https://somafm.com/m3u/secretagent.m3u": Response("https://x/dead"),
                "https://x/dead": Response("audio", headers={"Content-Type": "audio/mpeg"}),
            }
        )
        catalog.session = session
        monkeypatch.setattr("mariana.radio.find_executable", lambda *_args: "ffmpeg")
        monkeypatch.setattr(
            "mariana.radio.subprocess.run",
            lambda command, **_kwargs: (_ for _ in ()).throw(subprocess.CalledProcessError(1, command)),
        )
        result = catalog.health("secret-agent", force=True)
        assert result["status"] == "failed"
        assert catalog.get("secret-agent").failure_count == 1
