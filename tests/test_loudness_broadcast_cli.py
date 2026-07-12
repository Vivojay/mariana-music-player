from types import SimpleNamespace

import pytest

import main
from mariana.broadcast import BroadcastProfile, BroadcastSnapshot, BroadcastState
from mariana.models import PlaybackSnapshot, PlaybackState


class StateDatabase:
    def __init__(self):
        self.values = {}

    def set_state(self, key, value):
        self.values[key] = dict(value)


def test_replaygain_cli_persists_runtime_policy_and_schedules_scans(monkeypatch):
    configured = []
    controller = SimpleNamespace(
        replaygain_enabled=False,
        replaygain_mode="track",
        replaygain_preamp_db=0,
        configure_replaygain=lambda **value: configured.append(value),
        snapshot=lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )
    database = StateDatabase()
    catalog = SimpleNamespace(
        loudness=SimpleNamespace(get=lambda _stable_id: None, delete=lambda _stable_id: True),
        schedule_loudness=lambda mode, *args: 4,
        info=lambda _value: {"library_id": "track", "canonical_path": "C:/track.flac"},
    )
    service = SimpleNamespace(enable_loudness=lambda: configured.append({"worker": True}))
    monkeypatch.setattr(main.vas, "controller", controller)
    monkeypatch.setattr(main, "DATABASE", database)
    monkeypatch.setattr(main, "LIBRARY", catalog)
    monkeypatch.setattr(main, "LIBRARY_SERVICE", service)
    monkeypatch.setattr(main, "REPLAYGAIN_SETTINGS", {"enabled": False, "mode": "track"})
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)

    main.replaygain_command(["on", "auto"])
    main.replaygain_command(["preamp", "-2.5"])
    main.replaygain_command(["scan", "full"])
    main.replaygain_command(["rescan", "1"])
    main.replaygain_command(["off"])
    assert {"enabled": True, "mode": "auto"} in configured
    assert {"preamp_db": -2.5} in configured
    assert database.values["replaygain"]["enabled"] is False
    with pytest.raises(ValueError):
        main.replaygain_command(["unknown"])


class Credentials:
    def __init__(self):
        self.calls = []

    def set(self, reference, password):
        self.calls.append(("set", reference, password))

    def delete(self, reference):
        self.calls.append(("delete", reference))
        return True

    def status(self, reference):
        self.calls.append(("status", reference))
        return {"available": True, "source": "keyring", "environment": "MARIANA_ICECAST_PASSWORD_HOME"}


class Broadcaster:
    def __init__(self):
        self.profiles = {"home": BroadcastProfile("home", "https://example.test", "/stream")}
        self.credentials = Credentials()
        self.calls = []

    def start(self, name): self.calls.append(("start", name))
    def stop(self): self.calls.append(("stop",))
    def test(self, name):
        self.calls.append(("test", name))
        return True
    def metadata(self, title): self.calls.append(("metadata", title))
    def snapshot(self): return BroadcastSnapshot(BroadcastState.IDLE)


def test_broadcast_cli_uses_keychain_and_supervisor_contract(monkeypatch):
    broadcaster = Broadcaster()
    monkeypatch.setattr(main, "BROADCASTER", broadcaster)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "getpass", lambda _prompt: "not-persisted")
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.IDLE))
    main.broadcast_command(["profiles"])
    main.broadcast_command(["credentials", "set", "home"])
    main.broadcast_command(["credentials", "status", "home"])
    main.broadcast_command(["start", "home"])
    main.broadcast_command(["test", "home"])
    main.broadcast_command(["stop"])
    assert ("set", "home", "not-persisted") in broadcaster.credentials.calls
    assert ("start", "home") in broadcaster.calls
    assert ("test", "home") in broadcaster.calls
