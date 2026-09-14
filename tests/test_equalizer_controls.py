from copy import deepcopy
from types import SimpleNamespace

import pytest

import main
from mariana.equalizer import EqualizerProcessor, EqualizerService


@pytest.fixture
def service(monkeypatch, tmp_path):
    engine = EqualizerProcessor()
    settings = deepcopy(main.SETTINGS)
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    result = EqualizerService(lambda: engine, persist=main._persist_equalizer_configuration)
    monkeypatch.setattr(main, "EQUALIZER", result)
    monkeypatch.setattr(main, "IPrint", lambda *a, **kw: None)
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=lambda *a: None))
    return result


def test_cli_and_desktop_share_persistent_revision_bound_settings(service):
    import yaml

    main.eq_command(["on"])
    main.eq_command(["band", "1khz", "3"])
    state = main.eq_command(["status"])
    assert state["enabled"] and state["bands"][5] == 3
    assert main._desktop_control_request("equalizer.configure", {
        "revision": state["revision"], "operation": "preamp", "gain": -9,
    }) == {"ok": True}
    assert main.eq_command([])["preamp"] == -9
    persisted = yaml.safe_load(main.RUNTIME_PATHS.settings.read_text(encoding="utf-8"))
    assert persisted["equalizer"]["preamp"] == -9
    assert persisted["equalizer"]["enabled"] is True
    assert main._desktop_control_request("equalizer.status", {}) == {"ok": True}
    invalid_payloads: tuple[dict[str, object], ...] = (
        {"operation": "reset"}, {"revision": 0, "operation": "reset"},
        {"revision": service.revision, "operation": "preamp", "gain": float("nan")},
    )
    for payload in invalid_payloads:
        assert not main._desktop_control_request("equalizer.configure", payload)["ok"]
    assert service.settings.preamp == -9


def test_failed_save_does_not_change_settings_or_emit_private_error(service, monkeypatch):
    before = deepcopy(main.SETTINGS)
    monkeypatch.setattr(main, "save_user_settings", lambda *a: (_ for _ in ()).throw(OSError("private/path")))
    result = main._desktop_control_request("equalizer.configure", {
        "revision": service.revision, "operation": "enabled", "enabled": True,
    })
    assert result == {"ok": False, "error": "Could not update equalizer settings"}
    assert before == main.SETTINGS
    assert not service.settings.enabled
    with pytest.raises(ValueError, match="Could not save equalizer settings"):
        main.eq_command(["on"])


def test_status_cli_presets_warnings_and_invalid_read_request(service):
    main.process('eq preset save "Quiet listening"')
    assert "Quiet listening" in service.presets
    assert main.eq_command(["preset", "list"])["presets"][-1]["name"] == "Quiet listening"
    service.warning = "Saved equalizer settings were invalid"
    assert main.eq_command(["status"])["warning"]
    assert not main._desktop_control_request("equalizer.status", {"unexpected": True})["ok"]
