from ruamel.yaml import YAML
from mariana.paths import runtime_paths
yaml = YAML(typ='safe')  # Allows for safe YAML loading

APP_DIR = runtime_paths().data

with runtime_paths().settings_defaults.open('r', encoding='utf-8') as f:
    DEFAULT_SETTINGS = yaml.load(f)

def restore(changed_setting_location, SETTINGS):
    changed_setting_location = changed_setting_location.split('/')
    _ = DEFAULT_SETTINGS[changed_setting_location[0]]
    for i in changed_setting_location[1:]:
        _ = _[i]

    exec(f"""SETTINGS["{'"]["'.join(changed_setting_location)}"] = DEFAULT_SETTINGS["{'"]["'.join(changed_setting_location)}"]""")

    with (APP_DIR / 'settings' / 'settings.yml').open('w', encoding='utf-8') as f:
        yaml.dump(SETTINGS, f)
