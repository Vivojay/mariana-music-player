from array import array
from pathlib import Path

import pytest
import requests

from mariana.database import MarianaDatabase
from mariana.identity import (
    AcoustIDClient,
    IdentificationError,
    IdentificationService,
    LRCLIBClient,
    MusicBrainzClient,
    fingerprint_pcm,
    local_lyrics,
)
from mariana.models import IdentityStatus, MediaRef, MediaSource, TrackIdentity
from mariana.playback import PlaybackError


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def acoustid_result(score=0.94, runner=0.2, duration=181):
    return {
        "results": [
            {
                "score": score,
                "id": "acoustid",
                "recordings": [
                    {
                        "id": "recording",
                        "title": "Song",
                        "duration": duration,
                        "artists": [{"name": "Artist"}],
                        "releasegroups": [{"title": "Album"}],
                    }
                ],
            },
            {"score": runner, "id": "runner", "recordings": [{"id": "other"}]},
        ]
    }


def test_acoustid_conservative_policy_and_missing_key():
    unavailable = AcoustIDClient(api_key="", session=Session([])).identify(180, "fp")
    assert unavailable.status == IdentityStatus.UNAVAILABLE

    client = AcoustIDClient(api_key="key", session=Session([Response(acoustid_result())]))
    match = client.identify(180, "fp", 180)
    assert match.status == IdentityStatus.IDENTIFIED
    assert (match.recording_mbid, match.title, match.artist, match.album) == (
        "recording",
        "Song",
        "Artist",
        "Album",
    )

    ambiguous_payloads = [
        acoustid_result(score=0.84),
        acoustid_result(score=0.9, runner=0.87),
        acoustid_result(duration=200),
    ]
    for payload in ambiguous_payloads:
        result = AcoustIDClient(api_key="key", session=Session([Response(payload)])).identify(180, "fp", 180)
        assert result.status == IdentityStatus.AMBIGUOUS


def test_acoustid_no_match_and_offline():
    assert (
        AcoustIDClient(api_key="key", session=Session([Response({"results": []})])).identify(1, "fp").status
        == IdentityStatus.NO_MATCH
    )
    assert (
        AcoustIDClient(api_key="key", session=Session([requests.Timeout("offline")])).identify(1, "fp").status
        == IdentityStatus.OFFLINE
    )


def test_musicbrainz_enrichment_cache_and_failure_fallback():
    payload = {
        "title": "Canonical",
        "artist-credit": [{"name": "Artist"}],
        "releases": [{"title": "Album"}],
        "relations": [{"target-type": "work", "work": {"id": "work"}}],
    }
    session = Session([Response(payload)])
    client = MusicBrainzClient(session=session, minimum_interval=0)
    identity = client.enrich(TrackIdentity(IdentityStatus.IDENTIFIED, recording_mbid="recording"))
    assert (identity.title, identity.work_mbid) == ("Canonical", "work")
    assert client.recording("recording") == payload
    assert len(session.calls) == 1


def test_musicbrainz_retries_with_backoff_and_recovers(monkeypatch):
    session = Session([requests.Timeout("first"), requests.Timeout("second"), Response({"title": "Recovered"})])
    sleeps = []
    monkeypatch.setattr("mariana.identity.time.sleep", sleeps.append)
    client = MusicBrainzClient(session=session, minimum_interval=0, retries=3, backoff=0.25)
    assert client.recording("recording")["title"] == "Recovered"
    assert sleeps == [0.25, 0.5]


def test_lrclib_exact_search_no_lyrics_and_offline():
    identity = TrackIdentity(
        IdentityStatus.IDENTIFIED, title="Song", artist="Artist", album="Album", duration=180, confidence=0.9
    )
    exact = LRCLIBClient(session=Session([Response({"id": 1, "plainLyrics": "words"})])).find(identity)
    assert exact.plain == "words" and exact.provider == "LRCLIB"
    search = LRCLIBClient(
        session=Session([Response(None, 404), Response([{"id": 2, "syncedLyrics": "[00:01]words"}])])
    ).find(identity)
    assert search.synced == "[00:01]words"
    missing = LRCLIBClient(session=Session([Response(None, 404), Response([])])).find(identity)
    assert missing.status == IdentityStatus.NO_LYRICS
    offline = LRCLIBClient(session=Session([requests.Timeout("offline")])).find(identity)
    assert offline.status == IdentityStatus.OFFLINE


def test_sidecar_lrc_wins_and_plain_text_is_normalized(tmp_path: Path):
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"")
    audio.with_suffix(".lrc").write_text("[ar:Artist]\n[00:01.00]First\n[00:02.00][00:03.00]Second", encoding="utf-8")
    lyrics = local_lyrics(MediaRef(MediaSource.LOCAL, str(audio)))
    assert lyrics.synced.startswith("[ar:Artist]")
    assert lyrics.plain == "First\nSecond"


def test_fingerprint_pcm_validates_length_and_writes_int16_wav(monkeypatch):
    with pytest.raises(IdentificationError, match="At least"):
        fingerprint_pcm(b"")
    samples = array("f", [0.5, -0.5] * 48_000 * 8).tobytes()
    captured = {}

    def fake(path, _binary):
        import wave

        with wave.open(str(path), "rb") as source:
            captured.update(width=source.getsampwidth(), channels=source.getnchannels(), rate=source.getframerate())
        return 8.0, "fingerprint"

    monkeypatch.setattr("mariana.identity._run_fpcalc", fake)
    assert fingerprint_pcm(samples) == (8.0, "fingerprint")
    assert captured == {"width": 2, "channels": 2, "rate": 48_000}


def test_identification_and_lyrics_are_persistently_cached(tmp_path: Path, monkeypatch):
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "song.wav"), duration=180)
    identity = TrackIdentity(
        IdentityStatus.IDENTIFIED, recording_mbid="recording", title="Song", artist="Artist", confidence=0.91
    )

    class AcoustID:
        calls = 0

        def identify(self, *_args):
            self.calls += 1
            return identity

    class MusicBrainz:
        def enrich(self, value):
            return value

    class Lyrics:
        calls = 0

        def find(self, _identity):
            self.calls += 1
            from mariana.models import LyricsResult

            return LyricsResult(
                IdentityStatus.IDENTIFIED,
                plain="words",
                provider="LRCLIB",
                provider_id="1",
                retrieved_at=10,
                identity_confidence=0.91,
            )

    acoustid, lyrics = AcoustID(), Lyrics()
    monkeypatch.setattr("mariana.identity.fingerprint_file", lambda *_args: (180, "fp"))
    with MarianaDatabase(tmp_path / "mariana.db") as database:
        service = IdentificationService(database, acoustid=acoustid, musicbrainz=MusicBrainz(), lrclib=lyrics)
        assert service.identify(media).recording_mbid == "recording"
        assert service.identify(media).recording_mbid == "recording"
        assert acoustid.calls == 1
        assert service.lyrics(media, identity).plain == "words"
        assert service.lyrics(media, identity).plain == "words"
        assert lyrics.calls == 1


def test_missing_fpcalc_returns_typed_unavailable_identity(tmp_path: Path, monkeypatch):
    media_path = tmp_path / "song.wav"
    media_path.write_bytes(b"audio")
    media = MediaRef(MediaSource.LOCAL, str(media_path))
    monkeypatch.setattr(
        "mariana.identity.find_fpcalc",
        lambda _configured=None: (_ for _ in ()).throw(PlaybackError("missing")),
    )
    with MarianaDatabase(tmp_path / "mariana.db") as database:
        result = IdentificationService(database).identify(media)
    assert result.status == IdentityStatus.UNAVAILABLE
    assert "tools setup" in result.metadata["reason"]


def test_lyrics_provider_reports_missing_fpcalc_without_a_traceback(tmp_path: Path, monkeypatch):
    from lyrics_provider import get_lyrics

    media_path = tmp_path / "song.mp3"
    media_path.write_bytes(b"audio")
    monkeypatch.setattr(
        "mariana.identity.find_fpcalc",
        lambda _configured=None: (_ for _ in ()).throw(PlaybackError("missing")),
    )
    with MarianaDatabase(tmp_path / "mariana.db") as database:
        service = IdentificationService(database)
        get_lyrics.configure(service, None)
        text, heading = get_lyrics.get_lyrics(10, False, songfile=str(media_path))
    assert heading == "Lyrics identification unavailable"
    assert "tools setup" in text
