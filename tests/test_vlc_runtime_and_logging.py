import importlib
import sys
from types import SimpleNamespace

import pytest

import logger
import runtime_check
import terminal_colors


@pytest.fixture
def vlc_stream():
    return importlib.import_module("beta.vlc-async-stream")


class FakeMediaList:
    def __init__(self):
        self.items = []

    def add_media(self, media):
        self.items.append(media)


class FakeListPlayer:
    def __init__(self):
        self.media_list = None
        self.actions = []
        self.player = SimpleNamespace(is_playing=lambda: False)

    def set_media_list(self, media_list):
        self.media_list = media_list

    def get_media_player(self):
        return self.player

    def get_state(self):
        return 1

    def play(self):
        self.actions.append("play")

    def pause(self):
        self.actions.append("pause")

    def stop(self):
        self.actions.append("stop")


class FakeInstance:
    def __init__(self):
        self.media_list = FakeMediaList()
        self.list_player = FakeListPlayer()
        self.log_disabled = False

    def log_unset(self):
        self.log_disabled = True

    def media_list_new(self):
        return self.media_list

    def media_new(self, mrl):
        return f"media:{mrl}"

    def media_list_player_new(self):
        return self.list_player


def enable_fake_vlc(monkeypatch, vlc_stream):
    instances = []

    def create_instance():
        instance = FakeInstance()
        instances.append(instance)
        return instance

    monkeypatch.setattr(vlc_stream, "VLC_AVAILABLE", True)
    monkeypatch.setattr(vlc_stream, "vlc", SimpleNamespace(Instance=create_instance))
    monkeypatch.setattr(vlc_stream, "media_player", lambda **_kwargs: None)
    return instances


def test_vlc_load_media_object_preserves_order(vlc_stream):
    instance = FakeInstance()
    vlc_stream.load_media_object(instance, ["one", "two"])
    assert instance.media_list.items == ["media:one", "media:two"]
    assert vlc_stream.vlc_media_player is instance.list_player


def test_vlc_set_media_supports_radio_local_and_youtube(monkeypatch, vlc_stream):
    instances = enable_fake_vlc(monkeypatch, vlc_stream)
    monkeypatch.setattr(vlc_stream, "stream_url", lambda url, *, audio_only: f"direct:{url}:{audio_only}")

    vlc_stream.set_media(_type="radio/coffee")
    assert instances[-1].media_list.items[0].endswith("gsclassic.m3u")

    vlc_stream.set_media(_type="local", localpath="track.mp3")
    assert instances[-1].media_list.items == ["media:track.mp3"]

    assert vlc_stream.set_media(_type="yt_video", vidurl="video") == "direct:video:True"
    assert instances[-1].media_list.items == ["media:direct:video:True"]

    vlc_stream.set_media(_type="audio", audurl="https://youtu.be/abc12345678")
    assert "direct:https://www.youtube.com/watch?v=abc12345678:True" in instances[-1].media_list.items[0]


def test_vlc_set_media_rejects_missing_youtube_stream(monkeypatch, vlc_stream):
    enable_fake_vlc(monkeypatch, vlc_stream)
    with pytest.raises(ValueError, match="playable audio stream"):
        vlc_stream.set_media(_type="yt_video")


@pytest.mark.parametrize(
    ("action", "expected"),
    [("play", ["play"]), ("stop", ["stop"]), ("pausetoggle", ["pause"])],
)
def test_vlc_media_player_actions(monkeypatch, vlc_stream, action, expected):
    player = FakeListPlayer()
    monkeypatch.setattr(vlc_stream, "VLC_AVAILABLE", True)
    monkeypatch.setattr(vlc_stream, "vlc", object())
    monkeypatch.setattr(vlc_stream, "vlc_media_player", player)
    vlc_stream.media_player(action=action)
    assert player.actions == expected


def test_vlc_resync_restores_paused_state(monkeypatch, vlc_stream):
    player = FakeListPlayer()
    monkeypatch.setattr(vlc_stream, "VLC_AVAILABLE", True)
    monkeypatch.setattr(vlc_stream, "vlc", object())
    monkeypatch.setattr(vlc_stream, "vlc_media_player", player)
    vlc_stream.media_player(action="resync")
    assert player.actions == ["stop", "play", "pause"]


def test_wait_until_playing_succeeds(monkeypatch, vlc_stream):
    states = iter([False, True])
    player = SimpleNamespace(is_playing=lambda: next(states))
    monkeypatch.setattr(vlc_stream, "VLC_AVAILABLE", True)
    monkeypatch.setattr(vlc_stream, "vlc", object())
    monkeypatch.setattr(vlc_stream, "vlc_media_player", SimpleNamespace(get_media_player=lambda: player))
    monkeypatch.setattr(vlc_stream.time, "sleep", lambda _seconds: None)
    assert vlc_stream.wait_until_playing(timeout=1) is True


def test_find_vlc_directory_honors_config_and_environment(monkeypatch, tmp_path):
    configured = tmp_path / "configured"
    configured.mkdir()
    (configured / "vlc.exe").touch()
    assert runtime_check.find_vlc_directory(str(configured)) == configured.resolve()

    monkeypatch.setenv("VLC_HOME", str(configured))
    assert runtime_check.find_vlc_directory() == configured.resolve()


def test_inspect_vlc_installation_reads_architecture_and_version(monkeypatch, tmp_path):
    directory = tmp_path / "vlc"
    directory.mkdir()
    (directory / "vlc.exe").touch()
    fake_file = SimpleNamespace(GetBinaryType=lambda _path: 6, SCS_32BIT_BINARY=0)
    fake_api = SimpleNamespace(
        GetFileVersionInfo=lambda *_a: {
            "FileVersionMS": (3 << 16) | 1,
            "FileVersionLS": (2 << 16) | 3,
        }
    )
    monkeypatch.setitem(sys.modules, "win32file", fake_file)
    monkeypatch.setitem(sys.modules, "win32api", fake_api)
    assert runtime_check.inspect_vlc_installation(directory) == (64, (3, 1, 2, 3))


def test_audio_output_detection_handles_devices_and_driver_errors(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(query_devices=lambda: [{"max_output_channels": 0}, {"max_output_channels": 2}]),
    )
    assert runtime_check.has_audio_output() is True
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(query_devices=lambda: (_ for _ in ()).throw(OSError())))
    assert runtime_check.has_audio_output() is False


def test_runtime_report_can_be_fully_supported(monkeypatch, tmp_path):
    vlc = tmp_path / "vlc"
    monkeypatch.setattr(runtime_check.sys, "version_info", SimpleNamespace(major=3, minor=12, micro=1, __getitem__=lambda *_a: None))
    # check_runtime slices version_info, so provide a tuple-compatible value after documenting the expected baseline.
    monkeypatch.setattr(runtime_check.sys, "version_info", (3, 12, 1))
    monkeypatch.setattr(runtime_check.sys, "platform", "win32")
    monkeypatch.setattr(runtime_check.ctypes, "sizeof", lambda _value: 8)
    monkeypatch.setattr(runtime_check.shutil, "which", lambda _name: "available")
    monkeypatch.setattr(runtime_check, "has_audio_output", lambda: True)
    monkeypatch.setattr(runtime_check, "find_vlc_directory", lambda _path=None: vlc)
    monkeypatch.setattr(runtime_check, "inspect_vlc_installation", lambda _path: (64, (3, 0, 21, 0)))
    report = runtime_check.check_runtime()
    assert report.supported is True
    assert report.errors == ()
    assert report.warnings == ()


@pytest.mark.parametrize("style", [0, 1, 2])
def test_logger_supports_all_formats(tmp_path, style):
    output = tmp_path / f"style-{style}.log"
    logger.SAY(False, 3, log_message="message", out_file=str(output), format_style=style)
    assert "message" in output.read_text(encoding="utf-8")


def test_logger_visibility_priority_zero_and_invalid_format(tmp_path, capsys):
    output = tmp_path / "log.txt"
    logger.SAY(True, 0, display_message="visible", out_file=str(output))
    assert "visible" in capsys.readouterr().out
    assert not output.exists()

    with pytest.raises(ValueError, match="InvalidLogformat"):
        logger.SAY(False, 2, log_message="bad", out_file=str(output), format_style=99)


def test_terminal_color_unknown_values_are_safe():
    assert terminal_colors.fg("definitely_missing") == ""
    assert terminal_colors.back("navy_blue") == terminal_colors.bg("navy_blue")
