"""Online inspection, exact stream recovery, and offline fingerprint regressions."""

import json
import threading
from copy import deepcopy
from types import SimpleNamespace
from typing import cast

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.identity import AcoustIDClient, IdentificationError, IdentificationService, MusicBrainzClient
from mariana.media_details import display_media_uri, flattened_details
from mariana.models import (
    IdentityStatus,
    MediaCapabilities,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    TrackIdentity,
)
from mariana.playback import BYTES_PER_FRAME, SAMPLE_RATE, PlaybackController, PlaybackError, UnsupportedAction
from mariana.sources import ResolvedMedia, ResolverRegistry, SourceResolver

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

    registry._resolvers[MediaSource.YOUTUBE] = cast(SourceResolver, SimpleNamespace(resolve=resolve))
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


@pytest.mark.parametrize("value", [STREAM, "https://person:password@cdn.test/audio?unusual=secret#private"])
def test_inspection_never_prints_signed_query_or_credentials(value):
    info = {"canonical_path": value, "metadata": {"title": "Known recording"}}
    rendered = str(flattened_details(info))
    for private in ("secret", "private", "password", "person", "signature", "9999999999"):
        assert private not in rendered
    assert "query omitted" in rendered
    assert info["canonical_path"] == value  # Display sanitization must not corrupt playback transport.
    assert display_media_uri(PAGE + "&token=secret") == PAGE
    assert display_media_uri("C:/Music/Track.flac") == "C:/Music/Track.flac"


@pytest.fixture
def fingerprint_service(tmp_path):
    database = MarianaDatabase(tmp_path / "fingerprints.db")
    def unexpected(*_args, **_kwargs):
        pytest.fail("Fingerprint calculation must not contact a recognition provider")
    service = IdentificationService(database, acoustid=cast(AcoustIDClient, SimpleNamespace(identify=unexpected)),
                                    musicbrainz=cast(MusicBrainzClient, SimpleNamespace(enrich=unexpected)))
    yield service
    database.close()


def test_online_fingerprint_persists_and_can_later_be_identified(monkeypatch, fingerprint_service):
    service = fingerprint_service
    media = MediaRef(MediaSource.YOUTUBE, PAGE)
    calls = []
    monkeypatch.setattr("mariana.identity.fingerprint_pcm", lambda pcm, _bin: calls.append(pcm) or (12.0, "audio-fingerprint"))
    assert service.calculate_fingerprint(media, pcm=b"decoded-audio") == (12.0, "audio-fingerprint")
    reloaded = IdentificationService(service.database)
    assert reloaded.saved_fingerprint(deepcopy(media)) == (12.0, "audio-fingerprint")
    reloaded.acoustid = cast(AcoustIDClient, SimpleNamespace(identify=lambda *_args: TrackIdentity(IdentityStatus.IDENTIFIED, title="Recognized")))
    reloaded.musicbrainz = cast(MusicBrainzClient, SimpleNamespace(enrich=lambda identity: identity))
    assert reloaded.identify(media).title == "Recognized"
    assert calls == [b"decoded-audio"]
    assert reloaded.saved_fingerprint(media) == (12.0, "audio-fingerprint")


def test_local_fingerprint_invalidates_on_file_change(monkeypatch, tmp_path, fingerprint_service):
    path = tmp_path / "track.wav"
    path.write_bytes(b"original")
    media = MediaRef(MediaSource.LOCAL, str(path))
    monkeypatch.setattr("mariana.identity.fingerprint_file", lambda *_args: (12.0, "local-fingerprint"))
    fingerprint_service.calculate_fingerprint(media)
    assert fingerprint_service.saved_fingerprint(media) == (12.0, "local-fingerprint")
    monkeypatch.setattr(main, "IDENTITY", fingerprint_service)
    info = {"fingerprint": None}
    assert main._media_info_with_fingerprint(media, info)[1]["fingerprint"] == "local-fingerprint"
    path.write_bytes(b"different recording")
    assert fingerprint_service.saved_fingerprint(media) is None


def test_local_source_change_during_calculation_is_not_saved(monkeypatch, tmp_path, fingerprint_service):
    path = tmp_path / "track.wav"
    path.write_bytes(b"before")
    media = MediaRef(MediaSource.LOCAL, str(path))
    def calculate(*_args):
        path.write_bytes(b"after replacement")
        return (12.0, "wrong-recording")
    monkeypatch.setattr("mariana.identity.fingerprint_file", calculate)
    with pytest.raises(IdentificationError, match="changed during"):
        fingerprint_service.calculate_fingerprint(media)
    assert fingerprint_service.saved_fingerprint(media) is None


def test_live_source_is_not_given_a_whole_media_fingerprint(fingerprint_service):
    media = MediaRef(MediaSource.RADIO, "https://radio.test/stream", capabilities=MediaCapabilities(live=True, finite=False))
    with pytest.raises(IdentificationError, match="live segment"):
        fingerprint_service.calculate_fingerprint(media, pcm=b"audio")


def test_fingerprint_capture_is_identity_bound_and_read_only():
    media = MediaRef(MediaSource.YOUTUBE, PAGE)
    controller = SimpleNamespace(_lock=threading.Lock(), _active=SimpleNamespace(media=media, fingerprint_pcm=b"pcm"))
    assert PlaybackController.fingerprint_pcm(cast(PlaybackController, controller), media_id=media.stable_id) == b"pcm"
    with pytest.raises(UnsupportedAction, match="Active media changed"):
        PlaybackController.fingerprint_pcm(cast(PlaybackController, controller), media_id="previous")
    assert controller._active.media is media


@pytest.fixture
def command_scene(monkeypatch, fingerprint_service):
    media = MediaRef(MediaSource.URL, STREAM, title="Known track")
    pcm = b"\0" * (8 * SAMPLE_RATE * BYTES_PER_FRAME)
    output = []
    monkeypatch.setattr(main, "IDENTITY", fingerprint_service)
    monkeypatch.setattr(main, "IPrint", lambda text, **_kwargs: output.append(str(text)))
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media, duration=163),
        fingerprint_pcm=lambda *, media_id: pcm if media_id == media.stable_id else pytest.fail("Wrong media"),
    ))
    monkeypatch.setattr(main, "_prepare_fingerprint_tool", lambda: True)
    return media, output


def test_online_command_calculates_once_then_inspects_saved_data(monkeypatch, command_scene):
    media, output = command_scene
    calls = []
    monkeypatch.setattr("mariana.identity.fingerprint_pcm", lambda *_args: calls.append(True) or (8, "fingerprint-value"))
    assert main.media_command(["fingerprint"]) == "fingerprint-value"
    assert "17 characters" in output[-1]
    monkeypatch.setattr(main, "_prepare_fingerprint_tool", lambda: pytest.fail("Cached results need no executable"))
    assert main.media_command(["fingerprint", "--full"]) == "fingerprint-value"
    info = main.media_command(["probe", "--full"])
    assert isinstance(info, dict)
    assert info["metadata"]["title"] == "Known track"
    assert "secret" not in output[-1] and "query omitted" in output[-1]
    assert info["fingerprint"] == "fingerprint-value" and calls == [True]
    assert main.vas.controller.snapshot().media is media


def test_unknown_stream_explains_missing_metadata_and_insufficient_audio(monkeypatch, command_scene):
    media, output = command_scene
    media.title = None
    info = main.media_command(["info"])
    assert isinstance(info, dict)
    assert "No trusted title" in info["metadata"]["metadata_note"]
    monkeypatch.setattr(main.vas.controller, "fingerprint_pcm", lambda **_kwargs: b"short")
    monkeypatch.setattr(main, "_prepare_fingerprint_tool", lambda: pytest.fail("No setup before enough audio"))
    assert main.media_command(["fingerprint"]) is None
    assert "At least 8 seconds" in output[-1]
    assert "library scan" not in output[-1] and "fpcalc" not in output[-1]


@pytest.mark.parametrize("consent", [False, True])
def test_missing_tool_requires_consent_and_never_restarts_playback(monkeypatch, consent):
    calls, output = [], []
    location: list[str | None] = [None]
    def find(_configured=None):
        if location[0] is None:
            raise PlaybackError("missing")
        return location[0]
    monkeypatch.setattr(main, "find_fpcalc", find)
    monkeypatch.setattr(main, "executable_version", lambda *_args: "fpcalc 1.6.0")
    monkeypatch.setattr(main, "_confirm_action", lambda _message: consent)
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "IDENTITY", SimpleNamespace())
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace())
    def setup(args):
        calls.append(args)
        location[0] = "verified/fpcalc"
    monkeypatch.setattr(main, "tools_command", setup)
    monkeypatch.setattr(main, "refresh_runtime_configuration", lambda **_kwargs: pytest.fail("Must preserve controller"))
    assert main._prepare_fingerprint_tool() is consent
    assert calls == ([["setup"]] if consent else [])
    if consent:
        assert main.IDENTITY.fpcalc_bin == main.LIBRARY.fpcalc_bin == "verified/fpcalc"
    else:
        assert "cancelled" in output[-1]


def test_installed_tool_does_not_prompt_or_download(monkeypatch):
    monkeypatch.setattr(main, "find_fpcalc", lambda _configured: "existing/fpcalc")
    monkeypatch.setattr(main, "executable_version", lambda *_args: "fpcalc 1.6.0")
    monkeypatch.setattr(main, "_confirm_action", lambda _message: pytest.fail("Already installed"))
    monkeypatch.setattr(main, "IDENTITY", SimpleNamespace())
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace())
    assert main._prepare_fingerprint_tool()


def test_media_link_recovery_keeps_canonical_identity_in_playback_and_recents(monkeypatch, stream_registry):
    registry, calls = stream_registry
    original = MediaRef(MediaSource.YOUTUBE, PAGE)
    registry.resolve(original)
    for name in ("current_media_type", "currentsong", "songindex", "isplaying", "currentsong_length"):
        monkeypatch.setattr(main, name, getattr(main, name))
    recents, played, checked = [], [], []
    state = {"media": None}
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        resolvers=registry, snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=state["media"]),
    ))
    monkeypatch.setattr(main.vas, "current_media", None)
    def set_media(**kwargs):
        state["media"] = main.vas.current_media = kwargs["media"]
    def play(**_kwargs):
        resolved = registry.resolve(state["media"])
        played.append((resolved.media, resolved.playback_uri))
    monkeypatch.setattr(main.vas, "set_media", set_media)
    monkeypatch.setattr(main.vas, "media_player", play)
    monkeypatch.setattr(main.vas, "player", SimpleNamespace(audio_set_volume=lambda _v: None, get_length=lambda: 163_000))
    monkeypatch.setattr(main.vas, "wait_until_playing", lambda _timeout: None)
    monkeypatch.setattr(main, "stopsong", lambda: None)
    monkeypatch.setattr(main, "_ensure_media_playable", lambda media: checked.append(media))
    monkeypatch.setattr(main, "recents_queue_save", recents.append)
    monkeypatch.setattr(main, "_record_queue_history", lambda _media: None)
    monkeypatch.setattr(main, "_record_successful_start", lambda _media: None)
    monkeypatch.setattr(main, "_show_local_copy_hint", lambda _media: None)
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "USER_DATA", {"default_user_data": {"stats": {"play_count": {"general": 0}}}})
    main.play_vas_media(STREAM, media_type="general")
    assert len(calls) == 1 and played[0][1] == STREAM
    assert played[0][0].title == "Known recording"
    assert checked[0].stable_id == original.stable_id
    assert checked[0].source == MediaSource.YOUTUBE
    assert main.current_media_type == 0
    assert recents == [("Known recording", PAGE, PAGE)]


def test_auth_change_while_resolving_cannot_restore_old_stream_bindings(stream_registry):
    registry, _ = stream_registry
    def resolve(media, **_kwargs):
        registry.set_youtube_browser_profile(None)
        return ResolvedMedia(media, STREAM, PAGE, MediaCapabilities())
    registry._resolvers[MediaSource.YOUTUBE] = SimpleNamespace(resolve=resolve)
    registry.resolve(MediaRef(MediaSource.YOUTUBE, PAGE))
    assert registry.recover_stream_identity(STREAM) is None


def test_provider_error_redacts_signed_urls_in_output_and_logs(monkeypatch):
    messages = []
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    monkeypatch.setattr(main, "youtube_browser_profile", lambda: None)
    main.report_youtube_error(RuntimeError(f"HTTP 403 for {STREAM}"))
    assert len(messages) == 1
    for key in ("display_message", "log_message"):
        assert "403" in messages[0][key]
        assert "secret" not in messages[0][key]
        assert "private" not in messages[0][key]


@pytest.mark.parametrize("duration,fingerprint", [(float("nan"), "fp"), (0, "fp"), (10, ""), (10, None)])
def test_invalid_tool_output_is_not_a_successful_fingerprint(monkeypatch, duration, fingerprint):
    from mariana.identity import fingerprint_file
    monkeypatch.setattr("mariana.identity.find_fpcalc", lambda *_args: "tool")
    monkeypatch.setattr("mariana.identity.subprocess.run", lambda *_args, **_kwargs: SimpleNamespace(
        stdout=json.dumps({"duration": duration, "fingerprint": fingerprint}),
    ))
    with pytest.raises(IdentificationError, match="could not fingerprint"):
        fingerprint_file("local-file")


def test_native_online_pcm_fingerprint_can_be_read_after_database_reload(tmp_path):
    import math
    from array import array

    from mariana.identity import find_fpcalc
    try:
        executable = find_fpcalc()
    except PlaybackError:
        pytest.skip("Native fpcalc is required")
    # Generated stereo audio exercises the same float-PCM conversion as playback.
    pcm = array("f", (0.2 * math.sin(2 * math.pi * 523.25 * (sample // 2) / SAMPLE_RATE)
                      for sample in range(10 * SAMPLE_RATE * 2))).tobytes()
    media = MediaRef(MediaSource.YOUTUBE, PAGE)
    database_path = tmp_path / "reload.db"
    with MarianaDatabase(database_path) as database:
        service = IdentificationService(database, fpcalc_bin=executable)
        duration, fingerprint = service.calculate_fingerprint(media, pcm=pcm)
        assert duration == pytest.approx(10, abs=0.1)
        assert fingerprint
    with MarianaDatabase(database_path) as database:
        assert IdentificationService(database).saved_fingerprint(media) == (duration, fingerprint)
