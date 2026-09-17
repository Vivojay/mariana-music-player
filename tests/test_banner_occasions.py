from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main


@pytest.fixture
def banner_cli(monkeypatch):
    printed = []
    monkeypatch.setattr(main, "SETTINGS", {})
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "save_user_settings", Mock())
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings="settings.yml"))
    return printed


def test_banner_help_explains_offline_controls(banner_cli):
    assert main.banner_command(["help"]) is None
    assert any("ipapi.co only after confirmation" in line for line in banner_cli)


def test_banner_status_reports_defaults_without_network(banner_cli):
    result = main.banner_command([])
    assert result["enabled"] is True
    assert result["country_setting"] == "auto"
    assert any("operating-system region" in line for line in banner_cli)


def test_banner_occasions_toggle_preserves_other_settings(banner_cli, monkeypatch):
    monkeypatch.setattr(main, "SETTINGS", {"banner": {"country": "IN"}})
    assert main.banner_command(["occasions", "off"])["enabled"] is False
    assert main.SETTINGS == {"banner": {"country": "IN", "occasion greetings": False}}
    assert main.banner_command(["occasions", "on"])["enabled"] is True


def test_banner_country_detect_declined_makes_no_request(banner_cli, monkeypatch):
    monkeypatch.setattr(main, "_confirm_action", lambda _message, **_kwargs: False)
    monkeypatch.setattr(
        main, "detect_country", lambda: pytest.fail("Declined detection must not run"),
    )
    assert main.banner_command(["country", "detect"]) is None
    assert main.SETTINGS == {}


def test_banner_preview_rejects_invalid_dates(banner_cli):
    with pytest.raises(ValueError):
        main.banner_command(["preview", "not-a-date"])
    assert banner_cli == []
