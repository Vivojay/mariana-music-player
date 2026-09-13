"""Exact transport recovery retains provider identity without storing secrets."""

import json
from types import SimpleNamespace

import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.sources import ResolvedMedia, ResolverRegistry

PAGE = "https://www.youtube.com/watch?v=abcdefghijk"
STREAM = "https://cdn.example.test/videoplayback?signature=secret&ip=private&expire=9999999999"


@pytest.fixture
def stream_registry():
    registry = ResolverRegistry()
    calls = []

    def resolve(media, *, force=False):
        calls.append((media.original_uri, force))
        return ResolvedMedia(
            media, STREAM, media.original_uri, MediaCapabilities(),
            headers={"Authorization": "private-header"},
            metadata={"title": "Known recording", "artist": "Artist", "duration": 163,
                      "provider_metadata": {"views": 42}},
        )

    registry._resolvers[MediaSource.YOUTUBE] = SimpleNamespace(resolve=resolve)
    return registry, calls


def test_exact_resolved_stream_recovers_identity_and_uses_transport_once(stream_registry):
    registry, calls = stream_registry
    original = MediaRef(MediaSource.YOUTUBE, PAGE)
    registry.resolve(original)  # Resolution can succeed even if decoder opening subsequently fails.
    selected = registry.recover_stream_identity(STREAM)
    assert selected is not None and selected is not original
    assert selected.source == MediaSource.YOUTUBE
    assert selected.original_uri == PAGE and selected.stable_id == original.stable_id
    assert selected.title == "Known recording" and selected.artist == "Artist"
    assert "secret" not in json.dumps(selected.to_dict())
    assert "private-header" not in json.dumps(selected.to_dict())
    recovered = registry.resolve(selected)
    assert recovered.media is selected
    assert recovered.playback_uri == STREAM
    assert recovered.headers == {"Authorization": "private-header"}
    assert recovered.metadata["provider_metadata"] == {"views": 42}
    assert len(calls) == 1
    registry.resolve(selected)
    assert len(calls) == 2  # A retry must resolve the canonical identity afresh.


def test_stream_recovery_never_guesses_or_reuses_another_search(stream_registry):
    registry, _ = stream_registry
    assert registry.recover_stream_identity(STREAM) is None
    original = MediaRef(MediaSource.YOUTUBE, PAGE)
    registry.resolve(original)
    assert registry.recover_stream_identity(STREAM.replace("secret", "different")) is None
    assert registry.recover_stream_identity("https://cdn.example.test/another") is None
    selected = registry.recover_stream_identity(STREAM)
    assert selected is not None
    selected.title = "Changed by caller"
    assert registry.recover_stream_identity(STREAM).title == "Known recording"
    assert registry.recover_stream_identity(PAGE) is None


def test_stream_recovery_expires_is_bounded_and_clears_on_auth_change(monkeypatch, stream_registry):
    registry, _ = stream_registry
    clock = [1000.0]
    monkeypatch.setattr("mariana.sources.time.time", lambda: clock[0])
    for index in range(20):
        media = MediaRef(MediaSource.YOUTUBE, f"https://www.youtube.com/watch?v=id{index:09d}")
        registry._remember_stream(ResolvedMedia(media, f"https://cdn.example.test/{index}", media.original_uri,
                                               MediaCapabilities()))
    assert len(registry._recent_streams) == 16
    assert registry.recover_stream_identity("https://cdn.example.test/0") is None
    assert registry.recover_stream_identity("https://cdn.example.test/19") is not None
    clock[0] += 601
    assert registry.recover_stream_identity("https://cdn.example.test/19") is None
    assert not registry._selected_streams
    registry.resolve(MediaRef(MediaSource.YOUTUBE, PAGE))
    registry.set_youtube_browser_profile(None)
    assert registry.recover_stream_identity(STREAM) is None


def test_expired_stream_and_forced_refresh_cannot_use_cached_transport(monkeypatch, stream_registry):
    registry, calls = stream_registry
    monkeypatch.setattr("mariana.sources.time.time", lambda: 1000)
    media = MediaRef(MediaSource.YOUTUBE, PAGE)
    registry._remember_stream(ResolvedMedia(media, STREAM, PAGE, MediaCapabilities(), expires_at=1005))
    assert registry.recover_stream_identity(STREAM) is None
    registry.resolve(media)
    selected = registry.recover_stream_identity(STREAM)
    registry.resolve(selected, force=True)
    assert calls[-1] == (PAGE, True) and len(calls) == 2


def test_auth_change_while_resolving_cannot_restore_old_stream_bindings(stream_registry):
    registry, _ = stream_registry
    def resolve(media, **_kwargs):
        registry.set_youtube_browser_profile(None)
        return ResolvedMedia(media, STREAM, PAGE, MediaCapabilities())
    registry._resolvers[MediaSource.YOUTUBE] = SimpleNamespace(resolve=resolve)
    registry.resolve(MediaRef(MediaSource.YOUTUBE, PAGE))
    assert registry.recover_stream_identity(STREAM) is None
