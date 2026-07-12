import sys
from types import SimpleNamespace

import pytest

import beta.ffmpeg_player as media_player
import logger
from mariana.models import MediaSource, PlaybackSnapshot, PlaybackState
import runtime_check
import terminal_colors


class Controller:
    def __init__(self):
        self.prepared = None
        self.actions = []
        self.state = PlaybackState.IDLE

    def prepare(self, media):
        media.resolver_data["resolved_uri"] = f"resolved:{media.original_uri}"
        self.prepared = media
        return media

    def play(self):
        self.actions.append("play")
        self.state = PlaybackState.PLAYING

    def toggle_pause(self):
        self.actions.append("pause")

    def stop(self):
        self.actions.append("stop")

    def restart_live(self):
        self.actions.append("resync")

    def snapshot(self):
        return PlaybackSnapshot(self.state)


class Supervisor:
    def __init__(self, controller):
        self.controller = controller

    def play(self, media):
        self.controller.prepared = media
        self.controller.play()

    def stop(self):
        self.controller.stop()


def test_ffmpeg_facade_supports_local_url_and_actions(monkeypatch, tmp_path):
    controller = Controller()
    monkeypatch.setattr(media_player, "controller", controller)
    monkeypatch.setattr(media_player, "supervisor", Supervisor(controller))
    local = tmp_path / "track.mp3"
    local.write_bytes(b"audio")
    assert media_player.set_media(_type="local", localpath=str(local)) == str(local.resolve())
    assert media_player.current_media.source == MediaSource.LOCAL
    media_player.set_media(_type="audio", audurl="https://example.test/audio")
    assert media_player.current_media.source == MediaSource.URL
    for action in ("play", "pausetoggle", "stop", "resync"):
        media_player.media_player(action=action)
    assert controller.actions == ["play", "pause", "stop", "resync"]


def test_wait_until_playing_succeeds(monkeypatch):
    controller = Controller()
    controller.state = PlaybackState.PLAYING
    monkeypatch.setattr(media_player, "controller", controller)
    assert media_player.wait_until_playing(timeout=0.1, poll_interval=0) is True


def test_audio_output_detection_handles_devices_and_driver_errors(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(query_devices=lambda: [{"max_output_channels": 0}, {"max_output_channels": 2}]),
    )
    assert runtime_check.has_audio_output() is True
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(query_devices=lambda: (_ for _ in ()).throw(OSError())),
    )
    assert runtime_check.has_audio_output() is False


def test_runtime_report_can_be_fully_supported(monkeypatch):
    monkeypatch.setattr(runtime_check.sys, "version_info", (3, 12, 1))
    monkeypatch.setattr(runtime_check.sys, "platform", "win32")
    monkeypatch.setattr(runtime_check.ctypes, "sizeof", lambda _value: 8)
    monkeypatch.setattr(runtime_check, "_configured_executable", lambda name, _path=None: f"C:/{name}.exe")
    monkeypatch.setattr(runtime_check, "inspect_ffmpeg", lambda _path: "ffmpeg version test")
    monkeypatch.setattr(runtime_check.shutil, "which", lambda _name: "available")
    monkeypatch.setattr(runtime_check, "has_audio_output", lambda: True)
    report = runtime_check.check_runtime()
    assert report.supported is True
    assert report.errors == ()
    assert report.warnings == ()


@pytest.mark.parametrize("style", [0, 1, 2])
def test_logger_supports_all_formats(tmp_path, style):
    output = tmp_path / f"style-{style}.log"
    logger.SAY(False, 3, log_message="message", out_file=str(output), format_style=style)
    assert "message" in output.read_text(encoding="utf-8")


def test_terminal_color_unknown_values_are_safe():
    assert terminal_colors.fg("definitely_missing") == ""
    assert terminal_colors.back("navy_blue") == terminal_colors.bg("navy_blue")
