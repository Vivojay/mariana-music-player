from pathlib import Path
from types import SimpleNamespace

import pytest

import main
import mariana.platform as platform_adapter
from mariana.paths import RuntimePaths
from mariana.sleep_timer import SleepAction, SleepStatus


class Timer:
    def __init__(self):
        self.current = SleepStatus(False)
        self.started = []

    def status(self): return self.current
    def cancel(self):
        active = self.current.active
        self.current = SleepStatus(False)
        return active

    def start(self, duration, *, action, fade_seconds=None):
        self.started.append((duration, action, fade_seconds))
        self.current = SleepStatus(True, duration, duration, min(duration, fade_seconds or 600), action, 1)
        return self.current


def test_sleep_cli_parses_default_and_explicit_behavior(monkeypatch):
    timer = Timer()
    monkeypatch.setattr(main, "SLEEP_TIMER", timer)
    main.sleep_command(["30m"])
    assert timer.started[-1] == (1800, SleepAction.PAUSE, None)
    main.sleep_command(["1h30m", "stop", "fade", "5m"])
    assert timer.started[-1] == (5400, SleepAction.STOP, 300)
    assert main.sleep_command(["status"]).active
    assert main.sleep_command(["cancel"]).active is False


@pytest.mark.parametrize("arguments", [["nope"], ["10m", "later"], ["10m", "pause", "fade"]])
def test_sleep_cli_rejects_invalid_syntax(arguments, monkeypatch):
    monkeypatch.setattr(main, "SLEEP_TIMER", Timer())
    with pytest.raises(ValueError):
        main.sleep_command(arguments)


def test_update_prepare_backs_up_database_and_mutable_state(tmp_path, monkeypatch):
    resources = tmp_path / "resources"
    state = tmp_path / "state"
    paths = RuntimePaths(resources, state)
    paths.settings.parent.mkdir(parents=True)
    paths.user_data.parent.mkdir(parents=True)
    paths.settings.write_text("visible: true\n")
    paths.library_file.write_text("music\n")
    paths.user_data.write_text("default_user_data: {}\n")

    class Database:
        def backup(self, destination):
            Path(destination).write_bytes(b"sqlite")
            return Path(destination)

    events = []
    monkeypatch.setattr(main, "RUNTIME_PATHS", paths)
    monkeypatch.setattr(main, "DATABASE", Database())
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=lambda *value: events.append(value)))
    backup = main.prepare_update()
    assert (backup / "mariana.db").read_bytes() == b"sqlite"
    assert (backup / "settings.yml").is_file()
    assert events[-1][0] == "update-prepared"


def test_platform_volume_adapters_are_typed(monkeypatch):
    monkeypatch.setattr(platform_adapter.sys, "platform", "darwin")
    monkeypatch.setattr(platform_adapter, "_run_text", lambda arguments: "42" if "output volume" in arguments[-1] else "")
    assert platform_adapter.get_master_volume() == 42
    platform_adapter.set_master_volume(20)

    monkeypatch.setattr(platform_adapter.sys, "platform", "linux")
    monkeypatch.setattr(platform_adapter.shutil, "which", lambda _name: None)
    with pytest.raises(platform_adapter.PlatformCapabilityError, match="wpctl or pactl"):
        platform_adapter.get_master_volume()


def test_playback_automation_gain_does_not_replace_user_volume():
    from mariana.playback import PlaybackController

    controller = PlaybackController(output_factory=lambda **_kwargs: None)
    controller.set_volume(25)
    controller.set_automation_gain(0.5)
    assert controller.snapshot().volume == 0.25
    assert controller.automation_gain == 0.5
    with pytest.raises(ValueError):
        controller.set_automation_gain(1.1)
