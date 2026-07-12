import json

from mariana.paths import RuntimePaths, initialize_runtime_paths


def test_runtime_paths_copy_legacy_state_without_removing_source(tmp_path):
    resources = tmp_path / "resources"
    data = tmp_path / "state"
    (resources / "settings").mkdir(parents=True)
    (resources / "user").mkdir()
    (resources / "data").mkdir()
    (resources / "settings" / "settings.yml.default").write_text("visible: true\n")
    (resources / "settings" / "settings.yml").write_text("visible: false\n")
    (resources / "lib.lib").write_text("C:/Music\n")
    (resources / "user" / "user_data.yml").write_text("default_user_data: {}\n")
    paths = initialize_runtime_paths(RuntimePaths(resources, data))

    assert paths.settings.read_text() == "visible: false\n"
    assert paths.library_file.read_text() == "C:/Music\n"
    assert (resources / "lib.lib").exists()
    marker = json.loads((data / ".migration.json").read_text())
    assert marker["migration_version"] == 1
    assert "lib.lib" in marker["copied"]


def test_runtime_path_initialization_is_additive(tmp_path):
    resources = tmp_path / "resources"
    data = tmp_path / "state"
    (resources / "settings").mkdir(parents=True)
    (resources / "settings" / "settings.yml.default").write_text("visible: true\n")
    data.mkdir()
    (data / "lib.lib").write_text("user choice\n")
    initialize_runtime_paths(RuntimePaths(resources, data))
    assert (data / "lib.lib").read_text() == "user choice\n"
    assert (data / "settings" / "settings.yml").read_text() == "visible: true\n"
