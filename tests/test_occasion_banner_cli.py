from pathlib import Path
from types import SimpleNamespace

import pytest

import main


def test_banner_country_and_occasion_preferences_persist_independently(monkeypatch):
    settings = {"show banner": True, "banner": {"country": "auto", "occasion greetings": True}}
    saved = []
    output = []
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "save_user_settings", lambda value, _path: saved.append(value.copy()))
    monkeypatch.setattr(main, "configured_country", lambda value, **_kwargs: None if value == "auto" else value.upper())
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))

    main.banner_command(["occasions", "off"])
    main.banner_command(["country", "in"])

    assert settings["show banner"] is True
    assert settings["banner"] == {"country": "IN", "occasion greetings": False, "subdivision": None}
    assert len(saved) == 2
    assert any("country: IN" in value for value in output)


def test_showbanner_adds_current_greeting_without_location_lookup(monkeypatch):
    banner = Path(__file__)
    output = []
    gradients = []
    monkeypatch.setattr(main, "SETTINGS", {"banner": {"country": "IN", "occasion greetings": True}})
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(resource=lambda *_parts: banner))
    monkeypatch.setattr(main, "blue_gradient_print", lambda value, _colors: gradients.append(value))
    monkeypatch.setattr(
        main,
        "occasion_greeting",
        lambda **_kwargs: ("World Music Day: Wishing everyone a day filled with music", (), "IN"),
    )
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "showversion", lambda: None)
    monkeypatch.setattr(main, "visible", True)

    main.showbanner()

    assert gradients
    assert output == ["♫ World Music Day: Wishing everyone a day filled with music ♫"]


def test_country_lookup_requires_approval_and_preserves_settings_on_refusal(monkeypatch):
    settings = {"banner": {"country": "IN", "subdivision": "MH", "occasion greetings": False}}
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(main, "detect_country", lambda: pytest.fail("lookup before consent"))
    main.banner_command(["country", "detect"])
    assert settings["banner"]["subdivision"] == "MH"
    monkeypatch.setattr(main, "_confirm_action", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(main, "detect_country", lambda: "JP")
    monkeypatch.setattr(main, "save_user_settings", lambda *_: None)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    main.banner_command(["country", "detect"])
    assert settings["banner"] == {"country": "JP", "subdivision": None, "occasion greetings": False}


def test_banner_setting_disk_failure_rolls_back_and_preview_does_not_persist(monkeypatch):
    from datetime import date

    original = {"country": "IN", "occasion greetings": False}
    settings = {"banner": original}
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "save_user_settings", lambda *_: (_ for _ in ()).throw(OSError("disk error")))
    with pytest.raises(OSError):
        main.banner_command(["occasions", "on"])
    assert settings["banner"] is original
    previews = []
    monkeypatch.setattr(main, "showbanner", lambda *, current: previews.append(current))
    main.banner_command(["preview", "2026-11-08"])
    assert previews == [date(2026, 11, 8)]
    assert settings["banner"] is original
