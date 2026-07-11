from pathlib import Path

from ruamel.yaml import YAML

from config_manager import deep_merge_defaults, load_user_settings


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
