from copy import deepcopy
from pathlib import Path

import pytest
import toml
from hypothesis import given
from hypothesis import strategies as st

from config_manager import deep_merge_defaults, load_system_settings, load_user_settings


@given(
    current=st.dictionaries(st.text(min_size=1), st.integers(), max_size=10),
    defaults=st.dictionaries(st.text(min_size=1), st.integers(), max_size=10),
)
def test_deep_merge_is_additive_and_does_not_mutate_inputs(current, defaults):
    original_current = deepcopy(current)
    original_defaults = deepcopy(defaults)

    merged, changed = deep_merge_defaults(current, defaults)

    assert current == original_current
    assert defaults == original_defaults
    assert merged == {**defaults, **current}
    assert changed is any(key not in current for key in defaults)


def test_load_user_settings_creates_missing_parent_and_file(tmp_path: Path):
    defaults = tmp_path / "defaults.yml"
    defaults.write_text("nested:\n  enabled: true\n", encoding="utf-8")
    settings = tmp_path / "missing" / "settings.yml"

    assert load_user_settings(settings, defaults) == {"nested": {"enabled": True}}
    assert settings.is_file()


def test_load_user_settings_can_avoid_persisting_migration(tmp_path: Path):
    defaults = tmp_path / "defaults.yml"
    defaults.write_text("enabled: true\n", encoding="utf-8")
    settings = tmp_path / "settings.yml"

    assert load_user_settings(settings, defaults, persist_migration=False) == {"enabled": True}
    assert not settings.exists()


@pytest.mark.parametrize(
    ("defaults_text", "settings_text", "message"),
    [
        ("- invalid\n", "{}\n", "Default settings"),
        ("{}\n", "- invalid\n", "User settings"),
    ],
)
def test_load_user_settings_rejects_non_mapping_roots(tmp_path, defaults_text, settings_text, message):
    defaults = tmp_path / "defaults.yml"
    settings = tmp_path / "settings.yml"
    defaults.write_text(defaults_text, encoding="utf-8")
    settings.write_text(settings_text, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_user_settings(settings, defaults)


def test_load_system_settings_reads_requested_path(tmp_path: Path):
    path = tmp_path / "system.toml"
    path.write_text(toml.dumps({"about": {"first_boot": False}}), encoding="utf-8")
    assert load_system_settings(path)["about"]["first_boot"] is False
