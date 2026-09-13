"""Identification preserves trustworthy results and rejects incomplete provider/file inputs."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import mariana.identity as identity_module
from mariana.database import MarianaDatabase
from mariana.identity import (
    AcoustIDClient,
    IdentificationError,
    IdentificationService,
    LRCLIBClient,
    MusicBrainzClient,
    local_lyrics,
)
from mariana.models import IdentityStatus, LyricsResult, MediaCapabilities, MediaRef, MediaSource, TrackIdentity


class ProviderSession:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = next(self.responses)
        if isinstance(payload, Exception):
            raise payload
        return SimpleNamespace(status_code=200, json=lambda: payload, raise_for_status=lambda: None)


@pytest.mark.parametrize("payload", [
    {"duration": "NaN", "fingerprint": "valid-text"},
    {"duration": 0, "fingerprint": "valid-text"},
    {"duration": 8, "fingerprint": ""},
    {"duration": 8, "fingerprint": 123},
])
def test_invalid_fingerprint_output_cannot_be_persisted(monkeypatch, payload):
    monkeypatch.setattr(identity_module, "find_fpcalc", lambda _configured: "fpcalc")
    monkeypatch.setattr(identity_module.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)))
    with pytest.raises(IdentificationError, match="Invalid fingerprint output"):
        identity_module.fingerprint_file("selected.wav")


def test_fingerprint_process_returns_valid_duration_with_bounded_execution(monkeypatch):
    monkeypatch.setattr(identity_module, "find_fpcalc", lambda _configured: "configured-fpcalc")
    process = Mock(return_value=SimpleNamespace(stdout='{"duration": 12.5, "fingerprint": "verified-fingerprint"}'))
    monkeypatch.setattr(identity_module.subprocess, "run", process)
    assert identity_module.fingerprint_file("selected.wav") == (12.5, "verified-fingerprint")
    command = process.call_args.args[0]
    assert command == ["configured-fpcalc", "-json", "-length", "120", "selected.wav"]
    assert process.call_args.kwargs["timeout"] == 150
    assert process.call_args.kwargs["check"] is True


def test_acoustid_can_identify_a_strong_recording_without_full_media_duration():
    provider = ProviderSession({"results": [{"score": 0.98, "id": "fingerprint-match", "recordings": [
        {"id": "recording-id", "title": "Recording"},
    ]}]})
    result = AcoustIDClient(api_key="test-key", session=provider).identify(12, "fingerprint", expected_duration=None)
    assert result.status == IdentityStatus.IDENTIFIED
    assert result.recording_mbid == "recording-id" and result.duration is None
    assert result.artist is None and result.album is None


def test_musicbrainz_failed_refresh_preserves_last_verified_recording(monkeypatch):
    provider = ProviderSession({"title": "Verified title"}, requests.Timeout("offline"), requests.Timeout("offline"))
    clock = Mock(return_value=10.0)
    sleeps = []
    monkeypatch.setattr(identity_module.time, "monotonic", clock)
    monkeypatch.setattr(identity_module.time, "sleep", sleeps.append)
    client = MusicBrainzClient(session=provider, retries=2, minimum_interval=1, backoff=0.25)
    first = client.recording("recording")
    assert client.recording("recording", refresh=True) == first
    assert first == {"title": "Verified title"}
    assert sleeps == [1.0, 0.25, 1.0]
    assert len(provider.calls) == 3


@pytest.mark.parametrize("payload", [None, []])
def test_musicbrainz_unavailable_or_nonobject_recording_is_not_cached(payload):
    provider = ProviderSession(payload, {"title": "Recovered"})
    client = MusicBrainzClient(session=provider, retries=1, minimum_interval=0)
    assert client.recording("recording") is None
    assert client.recording("recording") == {"title": "Recovered"}
    assert len(provider.calls) == 2


@pytest.mark.parametrize("query,limit", [("  ", 10), ("Album", 0)])
def test_empty_release_search_never_calls_provider(query, limit):
    provider = ProviderSession()
    assert MusicBrainzClient(session=provider).search_releases(query, limit=limit) == []
    assert provider.calls == []


@pytest.mark.parametrize("state,mbid", [(IdentityStatus.AMBIGUOUS, "recording"), (IdentityStatus.IDENTIFIED, None)])
def test_unconfirmed_identity_cannot_be_enriched_as_a_different_recording(state, mbid):
    provider = ProviderSession()
    original = TrackIdentity(state, recording_mbid=mbid, title="Known title")
    assert MusicBrainzClient(session=provider).enrich(original) is original
    assert provider.calls == [] and original.title == "Known title"


def test_metadata_enrichment_keeps_existing_values_and_provenance_on_partial_or_missing_response():
    provider = ProviderSession(None, {"title": "", "artist-credit": [], "releases": [], "relations": []})
    client = MusicBrainzClient(session=provider, minimum_interval=0)
    original = TrackIdentity(IdentityStatus.IDENTIFIED, recording_mbid="recording", title="Known title",
                             artist="Known artist", album="Known album", provenance=["musicbrainz"])
    assert client.enrich(original) is original
    assert client.enrich(original) is original
    assert (original.title, original.artist, original.album) == ("Known title", "Known artist", "Known album")
    assert original.provenance == ["musicbrainz"]


@pytest.mark.parametrize("tags,expected_plain,expected_synced", [
    ({}, None, None),
    ({"USLT": "Plain words"}, "Plain words", None),
    ({"USLT": 123, "album": "Not lyrics"}, None, None),
    ({"SYLT": SimpleNamespace(text=None)}, None, None),
    ({"SYLT": SimpleNamespace(text=[None, ("invalid",), (123, 100), ("Untimed", -1), ("Timed", 1500)], format=2)},
     "Untimed\nTimed", "[00:01.500]Timed"),
    ({"SYLT": SimpleNamespace(text=[("Frame-unit lyric", 12)], format=1)}, "Frame-unit lyric", None),
    ({"SYLT": SimpleNamespace(text=[("Unknown units", 1500)])}, "Unknown units", None),
])
def test_embedded_lyrics_ignore_malformed_entries_without_inventing_timestamps(tmp_path, monkeypatch, tags, expected_plain, expected_synced):
    path = tmp_path / "recording.mp3"
    monkeypatch.setattr(identity_module, "MutagenFile", lambda _path: SimpleNamespace(tags=tags))
    result = local_lyrics(MediaRef(MediaSource.LOCAL, str(path)))
    if expected_plain is None:
        assert result is None
    else:
        assert result is not None
        assert result.plain == expected_plain and result.synced == expected_synced
        assert result.provider == "embedded"


def test_lyric_search_skips_unusable_candidates_before_returning_real_words():
    provider = ProviderSession({}, [{"id": 1, "plainLyrics": ""}, {"id": 2, "plainLyrics": "Real words"}])
    track = TrackIdentity(IdentityStatus.IDENTIFIED, title="Recording", artist="Artist")
    result = LRCLIBClient(session=provider).find(track)
    assert result.plain == "Real words" and result.provider_id == "2"


@pytest.fixture
def identification(tmp_path):
    with MarianaDatabase(tmp_path / "identity.db") as database:
        acoustid = Mock(spec=AcoustIDClient)
        acoustid.identify.return_value = TrackIdentity(IdentityStatus.NO_MATCH)
        metadata = Mock(spec=MusicBrainzClient)
        metadata.enrich.side_effect = lambda value: value
        lyrics = Mock(spec=LRCLIBClient)
        yield IdentificationService(database, acoustid=acoustid, musicbrainz=metadata, lrclib=lyrics)


def test_live_media_never_reuses_a_whole_recording_fingerprint(identification):
    media = MediaRef(MediaSource.URL, "https://example.test/live", capabilities=MediaCapabilities(live=True))
    assert identification.saved_fingerprint(media) is None
    identification.acoustid.identify.assert_not_called()


def test_mutation_during_fingerprinting_cannot_publish_an_identity(tmp_path, monkeypatch, identification):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"original")
    media = MediaRef(MediaSource.LOCAL, str(path), capabilities=MediaCapabilities(finite=True, fingerprintable=True))

    def fingerprint(*_args):
        path.write_bytes(b"different recording")
        return 12.0, "fingerprint"

    monkeypatch.setattr(identity_module, "fingerprint_file", fingerprint)
    with pytest.raises(IdentificationError, match="file changed"):
        identification.calculate_fingerprint(media)
    assert identification.saved_fingerprint(media) is None
    identification.acoustid.identify.assert_not_called()


def test_stale_fingerprint_only_record_is_recalculated_before_recognition(tmp_path, monkeypatch, identification):
    path = tmp_path / "recording.wav"
    path.write_bytes(b"original")
    media = MediaRef(MediaSource.LOCAL, str(path), capabilities=MediaCapabilities(finite=True, fingerprintable=True))
    fingerprint = Mock(side_effect=[(12.0, "original-fingerprint"), (13.0, "replacement-fingerprint")])
    monkeypatch.setattr(identity_module, "fingerprint_file", fingerprint)
    identification.calculate_fingerprint(media)
    path.write_bytes(b"replacement recording")
    assert identification.identify(media).status == IdentityStatus.NO_MATCH
    assert fingerprint.call_count == 2
    identification.acoustid.identify.assert_called_once_with(13.0, "replacement-fingerprint", None)


def test_online_identification_requires_audio_and_uses_the_provided_window(monkeypatch, identification):
    media = MediaRef(MediaSource.URL, "https://example.test/recording.mp3")
    assert identification.identify(media).status == IdentityStatus.INSUFFICIENT_AUDIO
    pcm_fingerprint = Mock(return_value=(12.0, "window-fingerprint"))
    monkeypatch.setattr(identity_module, "fingerprint_pcm", pcm_fingerprint)
    assert identification.identify(media, pcm=b"selected audio").status == IdentityStatus.NO_MATCH
    pcm_fingerprint.assert_called_once_with(b"selected audio", None)
    identification.acoustid.identify.assert_called_once_with(12.0, "window-fingerprint", None)


def test_online_fingerprint_calculation_requires_an_available_audio_window(identification):
    media = MediaRef(MediaSource.URL, "https://example.test/recording.mp3",
                     capabilities=MediaCapabilities(finite=True, fingerprintable=True))
    with pytest.raises(IdentificationError, match="Play this online item"):
        identification.calculate_fingerprint(media)
    assert identification.saved_fingerprint(media) is None
    identification.acoustid.identify.assert_not_called()


def test_explicit_identification_refresh_bypasses_a_persisted_result(monkeypatch, identification):
    media = MediaRef(MediaSource.URL, "https://example.test/recording.mp3")
    fingerprint = Mock(side_effect=[(12.0, "first"), (12.0, "refreshed")])
    monkeypatch.setattr(identity_module, "fingerprint_pcm", fingerprint)
    identification.identify(media, pcm=b"audio")
    identification.identify(media, pcm=b"audio", refresh=True)
    assert fingerprint.call_count == 2
    assert identification.acoustid.identify.call_count == 2
    identification.acoustid.identify.assert_called_with(12.0, "refreshed", None)


def test_explicit_lyrics_refresh_replaces_cache_without_reidentifying(identification):
    media = MediaRef(MediaSource.URL, "https://example.test/recording.mp3")
    track = TrackIdentity(IdentityStatus.IDENTIFIED, title="Recording", artist="Artist", recording_mbid="recording")
    identification.lrclib.find.side_effect = [
        LyricsResult(IdentityStatus.IDENTIFIED, plain="Original words", provider="LRCLIB"),
        LyricsResult(IdentityStatus.IDENTIFIED, plain="Corrected words", provider="LRCLIB"),
    ]
    assert identification.lyrics(media, track).plain == "Original words"
    assert identification.lyrics(media, track, refresh=True).plain == "Corrected words"
    assert identification.lyrics(media, track).plain == "Corrected words"
    assert identification.lrclib.find.call_count == 2
    identification.acoustid.identify.assert_not_called()


@pytest.mark.parametrize("timestamp_format", [1, 2])
def test_real_embedded_sylt_timestamp_units_are_respected(monkeypatch, timestamp_format):
    from io import BytesIO

    from mutagen.id3 import ID3, SYLT

    tags = ID3()
    tags.add(SYLT(encoding=3, lang="eng", format=timestamp_format, type=1,
                  text=[("First", 1250), ("Second", 2500)]))
    encoded = BytesIO()
    tags.save(encoded, v2_version=3)
    encoded.seek(0)
    restored = ID3(encoded)
    monkeypatch.setattr(identity_module, "MutagenFile", lambda _path: SimpleNamespace(tags=restored))
    result = local_lyrics(MediaRef(MediaSource.LOCAL, "song.mp3"))
    assert result is not None
    assert result.plain == "First\nSecond"
    assert result.synced == ("[00:01.250]First\n[00:02.500]Second" if timestamp_format == 2 else None)
