from __future__ import annotations

import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

import beta.ffmpeg_player as facade
import lyrics_provider.detect_song as detect_song
import lyrics_provider.get_lyrics as lyrics
import mariana.platform as platform_adapter
from mariana.models import (
    IdentityStatus,
    LyricsResult,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    TrackIdentity,
)
from mariana.playback import PlaybackError, UnsupportedAction


@pytest.mark.parametrize(
    ("host", "expected"),
    [("win32", ["explorer", "/select,"]), ("darwin", ["open", "-R"])],
)
def test_reveal_path_native_hosts(monkeypatch, tmp_path, host, expected):
    calls = []
    target = tmp_path / "track.mp3"
    target.write_bytes(b"audio")
    monkeypatch.setattr(platform_adapter.sys, "platform", host)
    monkeypatch.setattr(platform_adapter.subprocess, "Popen", lambda command: calls.append(command))
    platform_adapter.reveal_path(target)
    assert calls[0][:2] == expected
    assert calls[0][-1] == str(target.resolve())


def test_linux_open_and_reveal_use_xdg_open(monkeypatch, tmp_path):
    calls = []
    directory = tmp_path / "music"
    directory.mkdir()
    target = directory / "track.mp3"
    target.write_bytes(b"audio")
    monkeypatch.setattr(platform_adapter.sys, "platform", "linux")
    monkeypatch.setattr(platform_adapter.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(platform_adapter.subprocess, "Popen", lambda command: calls.append(command))
    platform_adapter.reveal_path(target)
    platform_adapter.reveal_path(directory)
    platform_adapter.open_path(target)
    assert calls == [
        ["/usr/bin/xdg-open", str(directory.resolve())],
        ["/usr/bin/xdg-open", str(directory.resolve())],
        ["/usr/bin/xdg-open", str(target.resolve())],
    ]


@pytest.mark.parametrize("operation", [platform_adapter.open_path, platform_adapter.reveal_path])
def test_linux_openers_fail_with_typed_error(monkeypatch, tmp_path, operation):
    monkeypatch.setattr(platform_adapter.sys, "platform", "linux")
    monkeypatch.setattr(platform_adapter.shutil, "which", lambda _name: None)
    with pytest.raises(platform_adapter.PlatformCapabilityError, match="xdg-open"):
        operation(tmp_path)


def test_native_open_path_and_command_errors(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(platform_adapter.sys, "platform", "win32")
    monkeypatch.setattr(platform_adapter.os, "startfile", lambda target: calls.append(target), raising=False)
    platform_adapter.open_path(tmp_path)
    assert calls == [tmp_path.resolve()]
    monkeypatch.setattr(platform_adapter.sys, "platform", "darwin")
    monkeypatch.setattr(platform_adapter.subprocess, "Popen", lambda command: calls.append(command))
    platform_adapter.open_path(tmp_path)
    assert calls[-1] == ["open", str(tmp_path.resolve())]

    monkeypatch.setattr(
        platform_adapter.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("tool", 5)),
    )
    with pytest.raises(platform_adapter.PlatformCapabilityError):
        platform_adapter._run_text(["tool"])


def test_linux_volume_backends_and_clamping(monkeypatch):
    calls = []
    monkeypatch.setattr(platform_adapter.sys, "platform", "linux")
    monkeypatch.setattr(
        platform_adapter,
        "_run_text",
        lambda command: calls.append(command) or ("Volume: 0.42 [MUTED]" if "get-volume" in command else ""),
    )
    monkeypatch.setattr(platform_adapter.shutil, "which", lambda name: "/bin/wpctl" if name == "wpctl" else None)
    assert platform_adapter.get_master_volume() == 42
    platform_adapter.set_master_volume(140)
    assert calls[-1][-1] == "100%"

    monkeypatch.setattr(platform_adapter.shutil, "which", lambda name: "/bin/pactl" if name == "pactl" else None)
    monkeypatch.setattr(
        platform_adapter,
        "_run_text",
        lambda command: calls.append(command) or ("front-left: 1 / 67% / 0.00 dB" if "get-sink-volume" in command else ""),
    )
    assert platform_adapter.get_master_volume() == 67
    platform_adapter.set_master_volume(-3)
    assert calls[-1][-1] == "0%"


def test_windows_volume_backend_and_missing_endpoint(monkeypatch):
    endpoint = SimpleNamespace(
        GetMasterVolumeLevelScalar=lambda: 0.375,
        SetMasterVolumeLevelScalar=lambda value, context: setattr(endpoint, "set_to", (value, context)),
    )
    audio_utilities = SimpleNamespace(GetSpeakers=lambda: SimpleNamespace(EndpointVolume=endpoint))
    package = ModuleType("pycaw")
    module = ModuleType("pycaw.pycaw")
    module.AudioUtilities = audio_utilities
    monkeypatch.setitem(sys.modules, "pycaw", package)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", module)
    monkeypatch.setattr(platform_adapter.sys, "platform", "win32")
    assert platform_adapter.get_master_volume() == 38
    platform_adapter.set_master_volume(25.4)
    assert endpoint.set_to == (0.25, None)
    module.AudioUtilities = SimpleNamespace(GetSpeakers=lambda: None)
    with pytest.raises(platform_adapter.PlatformCapabilityError, match="default audio endpoint"):
        platform_adapter.get_master_volume()
    with pytest.raises(platform_adapter.PlatformCapabilityError, match="default audio endpoint"):
        platform_adapter.set_master_volume(20)


def test_detect_song_contracts(monkeypatch, tmp_path, capsys):
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")
    with pytest.raises(OSError, match="does not exist"):
        detect_song.get_song_info(tmp_path / "missing.mp3")

    class Service:
        def __init__(self, identity):
            self.identity = identity

        def identify(self, media):
            assert media.source == MediaSource.LOCAL
            return self.identity

    monkeypatch.setattr(
        detect_song,
        "_service",
        Service(TrackIdentity(IdentityStatus.NO_MATCH, confidence=0.1)),
    )
    assert detect_song.get_song_info(song) == {}
    assert detect_song.get_song_info(song, get_title_only=True) is None

    identity = TrackIdentity(
        IdentityStatus.IDENTIFIED,
        title="Title",
        artist="Artist",
        recording_mbid="recording",
        work_mbid="work",
        confidence=0.94,
        provenance=("fpcalc",),
        metadata={"musicbrainz": {"tags": ["rock"]}},
    )
    monkeypatch.setattr(detect_song, "_service", Service(identity))
    assert detect_song.get_song_info(song, get_title_only=True) == "Artist — Title"
    result = detect_song.get_song_info(song, display_id=True, get_related=True)
    assert result["genres"] == ["rock"]
    assert result["lyrics"] == []
    assert "recording" in capsys.readouterr().out


def test_detect_song_lazily_builds_service(monkeypatch):
    database = object()
    service = object()
    monkeypatch.setattr(detect_song, "_database", None)
    monkeypatch.setattr(detect_song, "_service", None)
    monkeypatch.setattr(detect_song, "MarianaDatabase", lambda: database)
    monkeypatch.setattr(detect_song, "IdentificationService", lambda value: service if value is database else None)
    assert detect_song._get_service() is service
    assert detect_song._get_service() is service


class FacadeController:
    def __init__(self, snapshots=None):
        self.snapshots = list(snapshots or [PlaybackSnapshot(PlaybackState.IDLE)])
        self.calls = []

    def snapshot(self):
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]

    def seek(self, value):
        self.calls.append(("seek", value))

    def set_volume(self, value):
        self.calls.append(("volume", value))

    def set_muted(self, value):
        self.calls.append(("mute", value))

    def toggle_pause(self):
        self.calls.append(("pause",))

    def restart_live(self):
        self.calls.append(("resync",))


def test_player_adapter_and_action_errors(monkeypatch):
    snapshot = PlaybackSnapshot(PlaybackState.CROSSFADING, position=2.5, duration=4.25)
    controller = FacadeController([snapshot])
    supervisor = SimpleNamespace(
        play=lambda media: controller.calls.append(("play", media)),
        stop=lambda: controller.calls.append(("stop",)),
        close=lambda: controller.calls.append(("close",)),
    )
    monkeypatch.setattr(facade, "controller", controller)
    monkeypatch.setattr(facade, "supervisor", supervisor)
    assert facade.player.get_length() == 4250
    assert facade.player.get_time() == 2500
    assert facade.player.is_playing()
    facade.player.set_time(1250)
    facade.player.audio_set_volume(35)
    facade.player.audio_set_mute(1)
    facade.current_media = None
    with pytest.raises(PlaybackError, match="No media"):
        facade.media_player(action="play")
    facade.current_media = MediaRef(MediaSource.URL, "https://example.test/audio")
    for action in ("play", "pausetoggle", "stop", "resync"):
        facade.media_player(action=action)
    with pytest.raises(UnsupportedAction):
        facade.media_player(action="unknown")
    facade.close()
    assert ("seek", 1.25) in controller.calls
    assert ("close",) in controller.calls


def test_set_media_all_sources_and_catalog(monkeypatch, tmp_path):
    local = tmp_path / "song.mp3"
    local.write_bytes(b"audio")
    facade.set_media(_type="local", localpath=[str(local), str(local)])
    assert facade.current_media.resolver_data["legacy_playlist"] == [str(local), str(local)]
    facade.set_media(_type="yt_video", vidurl="https://youtube.test/watch?v=x")
    assert facade.current_media.source == MediaSource.YOUTUBE
    assert facade.current_media.resolver_data["youtube"] is True
    with pytest.raises(ValueError, match="Media type"):
        facade.set_media()
    with pytest.raises(ValueError, match="Unknown radio"):
        facade.radio_stream_url("missing")

    station = SimpleNamespace(station_id="id", name="Station")
    catalog = SimpleNamespace(get=lambda station_id: station, endpoints=lambda value: ["https://radio.test/live"])
    monkeypatch.setattr(facade, "radio_catalog", catalog)
    assert facade.set_media(_type="radio/coffee") == "https://radio.test/live"
    assert facade.current_media.title == "Station"
    assert facade.current_media.resolver_data["station_id"] == "id"


def test_wait_until_playing_failure_and_timeout(monkeypatch):
    failed = FacadeController([PlaybackSnapshot(PlaybackState.FAILED, error="decoder failed")])
    monkeypatch.setattr(facade, "controller", failed)
    with pytest.raises(PlaybackError, match="decoder failed"):
        facade.wait_until_playing(timeout=0.01, poll_interval=0)
    idle = FacadeController()
    monkeypatch.setattr(facade, "controller", idle)
    with pytest.raises(TimeoutError):
        facade.wait_until_playing(timeout=0, poll_interval=0)


def test_lyrics_fallback_and_active_pcm(monkeypatch, tmp_path):
    song = tmp_path / "song.wav"
    song.write_bytes(b"audio")
    unidentified = TrackIdentity(IdentityStatus.AMBIGUOUS, confidence=0.4, provenance=("fpcalc",))

    class Service:
        def __init__(self, result):
            self.result = result
            self.seen = []

        def identify(self, media, pcm=None):
            self.seen.append((media, pcm))
            return unidentified

        def lyrics(self, media, identity):
            assert identity.title == media.title
            return self.result

    service = Service(LyricsResult(IdentityStatus.NO_LYRICS))
    monkeypatch.setattr(lyrics, "IDENTIFICATION_SERVICE", service)
    monkeypatch.setattr(lyrics, "get_settings", lambda: ([".wav"], {}))
    assert lyrics.get_lyrics(1, False, songfile=str(song)) == ("(Lyrics not available)", "Lyrics N/A")
    assert lyrics.get_lyrics(1, False, songfile=str(song.with_suffix(".txt"))) == (
        "(Lyrics not available)",
        "Lyrics N/A",
    )
    assert lyrics.get_lyrics(1, False) == ("(Lyrics not available)", "Lyrics N/A")

    active = MediaRef(MediaSource.URL, "https://active.test/audio", title="Active", artist="Artist")
    service.result = LyricsResult(IdentityStatus.IDENTIFIED, synced="[00:01] words")
    monkeypatch.setattr(
        lyrics,
        "PLAYBACK_CONTROLLER",
        SimpleNamespace(snapshot=lambda: SimpleNamespace(media=active), fingerprint_pcm=lambda: b"pcm"),
    )
    assert lyrics.get_lyrics(1, False, weblink="https://requested.test/audio") == (
        "[00:01] words",
        "Artist — Active",
    )
    assert service.seen[-1] == (active, b"pcm")


def test_lyrics_service_absence_is_safe(monkeypatch):
    monkeypatch.setattr(lyrics, "IDENTIFICATION_SERVICE", None)
    assert lyrics.get_lyrics(1, False, weblink="https://example.test/audio") == (
        "(Lyrics not available)",
        "Lyrics N/A",
    )
