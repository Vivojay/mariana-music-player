from pathlib import Path

from ruamel.yaml import YAML

from config_manager import deep_merge_defaults, load_user_settings, save_user_settings


def test_deep_merge_adds_defaults_without_overwriting_user_values():
    merged, changed = deep_merge_defaults(
        {"audio": {"volume": 25}},
        {"audio": {"volume": 80, "muted": False}, "visible": True},
    )
    assert changed is True
    assert merged == {"audio": {"volume": 25, "muted": False}, "visible": True}


def test_load_user_settings_persists_only_missing_keys(tmp_path: Path):
    yaml = YAML()
    defaults_path = tmp_path / "settings.yml.default"
    settings_path = tmp_path / "settings.yml"
    with defaults_path.open("w", encoding="utf-8") as stream:
        yaml.dump({"visible": True, "nested": {"new": 2}}, stream)
    with settings_path.open("w", encoding="utf-8") as stream:
        yaml.dump({"visible": False, "nested": {"existing": 1}}, stream)

    loaded = load_user_settings(settings_path, defaults_path)

    assert loaded == {"visible": False, "nested": {"existing": 1, "new": 2}}
    assert load_user_settings(settings_path, defaults_path, persist_migration=False) == loaded


def test_save_user_settings_replaces_file_atomically(tmp_path: Path):
    settings_path = tmp_path / "settings.yml"
    settings_path.write_text("original: true\n", encoding="utf-8")

    assert save_user_settings({"sources": {"youtube": {"browser profile": "firefox"}}}, settings_path) == settings_path
    assert load_user_settings(settings_path, settings_path, persist_migration=False) == {
        "sources": {"youtube": {"browser profile": "firefox"}}
    }
    assert not list(tmp_path.glob(".settings.yml.*.tmp"))


def test_save_user_settings_preserves_original_when_replace_fails(monkeypatch, tmp_path: Path):
    settings_path = tmp_path / "settings.yml"
    settings_path.write_text("original: true\n", encoding="utf-8")
    monkeypatch.setattr("config_manager.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    try:
        save_user_settings({"original": False}, settings_path)
    except OSError as error:
        assert str(error) == "disk full"
    else:
        raise AssertionError("atomic replace failure must be reported")

    assert settings_path.read_text(encoding="utf-8") == "original: true\n"
    assert not list(tmp_path.glob(".settings.yml.*.tmp"))
