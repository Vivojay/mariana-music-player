from pathlib import Path
from types import SimpleNamespace

import pytest
from ruamel.yaml import YAML

import main
from mariana.integrations.discord_presence import (
    DiscordConnectionState,
    DiscordPresenceFailureCode,
    DiscordPresenceStatus,
)
from mariana.presence import PresencePrivacyMode


class Coordinator:
    def __init__(self, mode="off"):
        self.mode = PresencePrivacyMode(mode)
        self.calls = []

    def start(self):
        self.calls.append("start")

    def set_mode(self, mode):
        self.mode = PresencePrivacyMode(mode)
        self.calls.append(("mode", self.mode))

    def refresh(self):
        self.calls.append("refresh")


class Publisher:
    def __init__(self, status=None):
        self._status = status or DiscordPresenceStatus(DiscordConnectionState.DISCONNECTED)

    def status(self):
        return self._status


def configure(monkeypatch, mode="off"):
    settings = {"integrations": {"discord": {"presence": {"mode": mode}}}}
    coordinator = Coordinator(mode)
    saved = []
    printed = []
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "PRESENCE", coordinator)
    monkeypatch.setattr(main, "DISCORD_PRESENCE", Publisher())
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=Path("settings.yml")))
    monkeypatch.setattr(main, "save_user_settings", lambda value, path: saved.append((value, path)))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(
        main,
        "SAY",
        lambda **values: printed.append(str(values.get("display_message") or values.get("log_message") or "")),
    )
    return settings, coordinator, saved, printed


@pytest.mark.parametrize("mode", ["off", "app", "track", "session"])
def test_discord_presence_modes_persist_and_route(monkeypatch, mode):
    settings, coordinator, saved, printed = configure(monkeypatch)
    assert main.process(f"discord presence {mode}") is None
    assert settings["integrations"]["discord"]["presence"]["mode"] == mode
    assert len(saved) == 1
    assert coordinator.mode == PresencePrivacyMode(mode)
    assert ("start" in coordinator.calls) is (mode != "off")
    assert printed[-1] == f"Discord presence mode set to {mode}."


def test_discord_presence_status_refresh_and_usage(monkeypatch):
    _settings, coordinator, saved, printed = configure(monkeypatch, "track")
    main.process("discord presence status")
    assert "mode=track" in printed[-1] and "local RPC=disconnected" in printed[-1]
    main.process("discord presence refresh")
    assert coordinator.calls[-2:] == ["start", "refresh"]
    assert saved == []
    main.process("discord presence unknown")
    assert any("Usage: discord presence" in value for value in printed)


def test_discord_presence_off_refresh_does_not_start_rpc(monkeypatch):
    _settings, coordinator, _saved, printed = configure(monkeypatch)
    main.process("discord presence refresh")
    assert coordinator.calls == []
    assert "is off" in printed[-1]


def test_discord_presence_settings_rollback_on_atomic_write_failure(monkeypatch):
    settings, coordinator, _saved, printed = configure(monkeypatch, "app")

    def fail(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(main, "save_user_settings", fail)
    main.process("discord presence session")
    assert settings["integrations"]["discord"]["presence"]["mode"] == "app"
    assert coordinator.mode == PresencePrivacyMode.APP
    assert any("disk full" in value for value in printed)


def test_discord_presence_factory_default_is_off():
    defaults = YAML(typ="safe").load((Path(__file__).parents[1] / "settings" / "settings.yml.default").read_text())
    assert defaults["integrations"]["discord"]["presence"]["mode"] == "off"


def test_discord_presence_invalid_persisted_mode_falls_back_to_off():
    settings = {"integrations": {"discord": {"presence": {"mode": "private-everything"}}}}
    assert main._configured_presence_mode(settings) == PresencePrivacyMode.OFF
    invalid = {"integrations": {"discord": {"presence": {"mode": None}}}}
    assert main._configured_presence_mode(invalid) == PresencePrivacyMode.OFF


def test_discord_application_id_prefers_developer_environment_override(monkeypatch):
    monkeypatch.setenv("MARIANA_DISCORD_APPLICATION_ID", "123456789012345678")
    settings = {"system_settings": {"discord_application_id": "987654321098765432"}}
    assert main._configured_discord_application_id(settings) == "123456789012345678"
    monkeypatch.delenv("MARIANA_DISCORD_APPLICATION_ID")
    assert main._configured_discord_application_id(settings) == "987654321098765432"


def test_discord_presence_enablement_reports_invalid_build_configuration(monkeypatch):
    _settings, _coordinator, _saved, printed = configure(monkeypatch)
    monkeypatch.setattr(
        main,
        "DISCORD_PRESENCE",
        Publisher(
            DiscordPresenceStatus(
                DiscordConnectionState.DISCONNECTED,
                DiscordPresenceFailureCode.NOT_CONFIGURED,
                "Mariana's public Discord application ID is not configured correctly in this build.",
            )
        ),
    )

    main.process("discord presence track")

    assert "not configured correctly" in printed[-1]
