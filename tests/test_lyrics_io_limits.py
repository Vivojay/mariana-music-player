import json
from types import SimpleNamespace

import pytest
import requests

from mariana.identity import LRCLIBClient, local_lyrics
from mariana.models import IdentityStatus, MediaRef, MediaSource, TrackIdentity


@pytest.mark.parametrize("extra", [0, 1])
def test_sidecar_byte_limit_is_inclusive_and_oversize_falls_back_to_tags(tmp_path, monkeypatch, extra):
    monkeypatch.setattr("mariana.identity.MAX_LYRICS_FILE_BYTES", 64)
    monkeypatch.setattr("mariana.identity.MutagenFile", lambda _path: SimpleNamespace(tags={"LYRICS": ["Embedded"]}))
    path = tmp_path / "song.mp3"
    text = "[00:01]" + "x" * (64 - len("[00:01]") + extra)
    path.with_suffix(".lrc").write_bytes(text.encode("utf-8"))
    result = local_lyrics(MediaRef(MediaSource.LOCAL, str(path)))
    assert result is not None
    if extra:
        assert result.provider == "embedded"
        assert result.plain == "Embedded"
    else:
        assert result.provider == "local-sidecar"
        assert result.synced == text


def test_invalid_utf8_sidecar_falls_back_to_embedded_lyrics(tmp_path, monkeypatch):
    monkeypatch.setattr("mariana.identity.MutagenFile", lambda _path: SimpleNamespace(tags={"LYRICS": ["Embedded"]}))
    path = tmp_path / "song.mp3"
    path.with_suffix(".lrc").write_bytes(b"[00:01]\xff")
    assert local_lyrics(MediaRef(MediaSource.LOCAL, str(path))).plain == "Embedded"


def test_extra_byte_read_detects_sidecar_growth_after_stat(monkeypatch):
    class GrowingSidecar:
        def is_file(self):
            return True

        def stat(self):
            return SimpleNamespace(st_size=64)

        def open(self, mode):
            import io
            assert mode == "rb"

            class BoundedRead(io.BytesIO):
                def read(self, size=-1):
                    assert size == 65
                    return super().read(size)

            return BoundedRead(b"x" * 65)

    monkeypatch.setattr("mariana.identity.MAX_LYRICS_FILE_BYTES", 64)
    monkeypatch.setattr("mariana.identity.Path", lambda _uri: SimpleNamespace(with_suffix=lambda _suffix: GrowingSidecar()))
    monkeypatch.setattr("mariana.identity.MutagenFile", lambda _path: SimpleNamespace(tags={"LYRICS": ["Embedded"]}))
    assert local_lyrics(MediaRef(MediaSource.LOCAL, "song.mp3", stable_id="song")).plain == "Embedded"


class StreamResponse:
    def __init__(self, chunks, *, status=200, headers=None, error=None):
        self.chunks = chunks
        self.status_code = status
        self.headers = headers or {}
        self.error = error
        self.closed = False
        self.yielded = 0

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP failure")

    def iter_content(self, chunk_size):
        assert chunk_size == 16_384
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk
        if self.error:
            raise self.error

    def close(self):
        self.closed = True

    def json(self):
        raise AssertionError("Real streamed responses must not use unbounded response.json")


class Session:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, _url, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


def test_streamed_json_accepts_exact_byte_limit_and_closes_response(monkeypatch):
    payload = json.dumps({"id": 1, "plainLyrics": "Café"}, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr("mariana.identity.MAX_LYRICS_RESPONSE_BYTES", len(payload))
    response = StreamResponse([payload[:4], b"", payload[4:]], headers={"Content-Length": str(len(payload))})
    session = Session(response)
    result = LRCLIBClient(session=session, timeout=2).find(TrackIdentity(IdentityStatus.IDENTIFIED, title="Song", artist="Artist"))
    assert result.status == IdentityStatus.IDENTIFIED
    assert result.plain == "Café"
    assert response.closed
    assert session.calls[0]["stream"] is True
    assert session.calls[0]["timeout"] == 2


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "1"}, {"Content-Length": "unknown"}])
def test_streamed_size_limit_cannot_be_bypassed_by_missing_or_incorrect_length(monkeypatch, headers):
    monkeypatch.setattr("mariana.identity.MAX_LYRICS_RESPONSE_BYTES", 64)
    response = StreamResponse([b" " * 64, b"x", b"must-not-be-read"], headers=headers)
    client = LRCLIBClient(session=Session(response))
    with pytest.raises(ValueError, match="size"):
        client._get("get", {})
    assert response.yielded == 2
    assert response.closed


def test_declared_oversize_is_rejected_without_reading_body(monkeypatch):
    monkeypatch.setattr("mariana.identity.MAX_LYRICS_RESPONSE_BYTES", 64)
    response = StreamResponse([b"unread"], headers={"Content-Length": "65"})
    with pytest.raises(ValueError, match="size"):
        LRCLIBClient(session=Session(response))._get("get", {})
    assert response.yielded == 0
    assert response.closed


def test_404_still_falls_back_to_search_and_closes_both_streams():
    missing = StreamResponse([], status=404)
    found = StreamResponse([b'[{"id":2,"syncedLyrics":"[00:01]Words"}]'])
    result = LRCLIBClient(session=Session(missing, found)).find(
        TrackIdentity(IdentityStatus.IDENTIFIED, title="Song", artist="Artist"),
    )
    assert result.synced == "[00:01]Words"
    assert missing.closed and found.closed


@pytest.mark.parametrize("response", [
    StreamResponse([b"not JSON"]),
    StreamResponse([b"{"], error=requests.Timeout("private timeout details")),
    StreamResponse([], status=503),
], ids=["malformed-json", "read-timeout", "http-error"])
def test_stream_failures_remain_nonfatal_offline_results_and_close(response):
    result = LRCLIBClient(session=Session(response)).find(
        TrackIdentity(IdentityStatus.IDENTIFIED, title="Song", artist="Artist"),
    )
    assert result.status == IdentityStatus.OFFLINE
    assert response.closed


def test_stream_read_deadline_limits_slow_chunked_payloads(monkeypatch):
    times = iter([0.0, 0.5, 2.1])
    monkeypatch.setattr("mariana.identity.time.monotonic", lambda: next(times))
    response = StreamResponse([b"{", b"}"])
    with pytest.raises(requests.Timeout, match="time limit"):
        LRCLIBClient(session=Session(response), timeout=2)._get("get", {})
    assert response.closed


def test_legacy_in_memory_json_adapter_remains_compatible_and_size_checked(monkeypatch):
    response = SimpleNamespace(status_code=200, raise_for_status=lambda: None, json=lambda: {"plainLyrics": "x" * 64})
    monkeypatch.setattr("mariana.identity.MAX_LYRICS_RESPONSE_BYTES", 64)
    with pytest.raises(ValueError, match="size"):
        LRCLIBClient(session=Session(response))._get("get", {})


@pytest.mark.parametrize("chunks", [None, 17, b"{}", "{}", [None], [False], [123]])
def test_invalid_stream_or_nonbyte_chunks_are_rejected_and_response_closed(chunks):
    closed = []
    response = SimpleNamespace(status_code=200, raise_for_status=lambda: None,
                               iter_content=lambda **_kwargs: chunks, close=lambda: closed.append(True))
    with pytest.raises(ValueError, match="malformed"):
        LRCLIBClient(session=Session(response))._get("get", {})
    assert closed == [True]
