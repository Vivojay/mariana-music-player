"""Restore individual settings from the packaged defaults."""

from pathlib import Path

from ruamel.yaml import YAML

from config_manager import save_user_settings
from mariana.paths import runtime_paths

yaml = YAML(typ="safe")

with runtime_paths().settings_defaults.open("r", encoding="utf-8") as stream:
    DEFAULT_SETTINGS = yaml.load(stream)


def restore(changed_setting_location, settings, settings_path: Path | None = None):
    """Restore one default value and persist the complete settings atomically."""
    keys = changed_setting_location.split("/")
    default_parent = DEFAULT_SETTINGS
    current_parent = settings
    for key in keys[:-1]:
        default_parent = default_parent[key]
        current_parent = current_parent[key]
    current_parent[keys[-1]] = default_parent[keys[-1]]
    save_user_settings(settings, settings_path or runtime_paths().settings)
