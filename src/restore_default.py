from ruamel.yaml import YAML

yaml = YAML(typ="safe")  # Allows for safe YAML loading

with open("settings/settings.yml.default", "r", encoding="utf-8") as f:
    DEFAULT_SETTINGS = yaml.load(f)


def restore(changed_setting_location, SETTINGS):
    changed_setting_location = changed_setting_location.split("/")
    _ = DEFAULT_SETTINGS[changed_setting_location[0]]
    for i in changed_setting_location[1:]:
        _ = _[i]

    exec(
        f"""SETTINGS["{'"]["'.join(changed_setting_location)}"] = DEFAULT_SETTINGS["{'"]["'.join(changed_setting_location)}"]"""
    )

    with open("settings/settings.yml", "w", encoding="utf-8") as f:
        yaml.dump(SETTINGS, f)
