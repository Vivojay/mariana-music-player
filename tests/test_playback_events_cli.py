from copy import deepcopy
from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource


class PlaybackEventsStub:
    def __init__(self):
        self.enabled = False
        self.retention_days = 90
        self.forward_to_log = False
        self.clear_calls = 0
        self.aggregate_calls = []

    def configure(self, *, enabled=None, retention_days=None, forward_to_log=None):
        if enabled is not None:
            self.enabled = enabled
        if retention_days is not None:
            self.retention_days = retention_days
        if forward_to_log is not None:
            self.forward_to_log = forward_to_log

    def status(self):
        return {
            "enabled": self.enabled,
            "retention_days": self.retention_days,
            "forward_to_log": self.forward_to_log,
            "stored": 2,
            "pending": 0,
            "capacity": 512,
            "dropped": 0,
        }

    def clear(self):
        self.clear_calls += 1
        return True

    def aggregate(self, stable_id, *, bin_seconds, scaling):
        self.aggregate_calls.append((stable_id, bin_seconds, scaling))
        return [
            {
                "start_seconds": 10.0,
                "end_seconds": 15.0,
                "play_starts": 1,
                "play_resumes": 0,
                "pauses": 1,
                "seek_destinations": 2,
                "total": 4,
                "intensity": 1.0,
                "scaling": scaling,
            }
        ]


@pytest.fixture
def cli(monkeypatch, tmp_path):
    service = PlaybackEventsStub()
    settings = deepcopy(main.SETTINGS)
    saved = []
    printed = []
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "track.flac"), stable_id="media-1")
    monkeypatch.setattr(main, "PLAYBACK_EVENTS", service)
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    monkeypatch.setattr(main, "save_user_settings", lambda value, _path: saved.append(deepcopy(value)))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(
        main,
        "vas",
        SimpleNamespace(controller=SimpleNamespace(snapshot=lambda: SimpleNamespace(media=media))),
    )
    return service, settings, saved, printed


def test_hotspot_settings_persist_and_current_aggregation_is_explicit(cli):
    service, settings, saved, printed = cli
    assert main.hotspots_command([])["enabled"] is False
    main.hotspots_command(["enable"])
    main.hotspots_command(["retention", "30"])
    main.hotspots_command(["logging", "on"])
    rows = main.hotspots_command(["current", "5", "log1p"])

    assert settings["playback events"] == {
        "enabled": True,
        "retention days": 30,
        "forward to log": True,
    }
    assert saved[-1]["playback events"] == settings["playback events"]
    assert service.aggregate_calls == [("media-1", 5.0, "log1p")]
    assert rows[0]["seek_destinations"] == 2
    assert "Personal interaction hotspots" in "\n".join(printed)


def test_hotspot_clear_is_confirmed_and_settings_reject_invalid_values(cli):
    service, settings, _saved, _printed = cli
    with pytest.raises(ValueError, match="requires"):
        main.hotspots_command(["clear"])
    assert service.clear_calls == 0
    main.hotspots_command(["clear", "--yes"])
    assert service.clear_calls == 1
    with pytest.raises(ValueError, match="between 1 and 3650"):
        main.hotspots_command(["retention", "0"])
    with pytest.raises(ValueError, match="linear or log1p"):
        main.hotspots_command(["current", "10", "zscore"])
    assert main._configured_playback_events({"playback events": {"enabled": "yes"}}) == {
        "enabled": False,
        "retention_days": 90,
        "forward_to_log": False,
    }
    assert "playback events" not in settings or settings["playback events"].get("retention days") != 0
