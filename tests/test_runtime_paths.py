import json

import pytest

from mariana.paths import RuntimePaths, _copy_atomic, initialize_runtime_paths
from mariana.setup import SetupStateStore


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
    assert SetupStateStore(paths).load().status == "pending"


def test_runtime_path_initialization_is_additive(tmp_path):
    resources = tmp_path / "resources"
    data = tmp_path / "state"
    (resources / "settings").mkdir(parents=True)
    (resources / "settings" / "settings.yml.default").write_text("visible: true\n")
    data.mkdir()
    (data / "lib.lib").write_text("user choice\n")
    initialize_runtime_paths(RuntimePaths(resources, data))
    assert SetupStateStore(RuntimePaths(resources, data)).load().status == "complete"
    assert (data / "lib.lib").read_text() == "user choice\n"
    assert (data / "settings" / "settings.yml").read_text() == "visible: true\n"
    initialize_runtime_paths(RuntimePaths(resources, data))


def test_existing_install_is_not_forced_through_setup_again(tmp_path):
    resources = tmp_path / "resources"
    data = tmp_path / "state"
    (resources / "settings").mkdir(parents=True)
    (resources / "settings" / "settings.yml.default").write_text("visible: true\n")
    data.mkdir()
    (data / ".migration.json").write_text('{"migration_version": 1}', encoding="utf-8")
    paths = initialize_runtime_paths(RuntimePaths(resources, data))
    assert SetupStateStore(paths).load().status == "complete"


def test_pre_migration_install_without_marker_is_not_forced_through_setup(tmp_path):
    resources = tmp_path / "resources"
    data = tmp_path / "state"
    (resources / "settings").mkdir(parents=True)
    (resources / "settings" / "settings.yml.default").write_text("visible: true\n")
    (data / "settings").mkdir(parents=True)
    (data / "settings" / "settings.yml").write_text("visible: false\n")

    paths = initialize_runtime_paths(RuntimePaths(resources, data))

    state = SetupStateStore(paths).load()
    assert state.status == "complete"
    assert state.migrated_existing_install is True


def test_runtime_path_initialization_creates_empty_library_and_user_state(tmp_path):
    resources = tmp_path / "resources"
    (resources / "settings").mkdir(parents=True)
    (resources / "settings" / "settings.yml.default").write_text("visible: true\n")
    paths = initialize_runtime_paths(RuntimePaths(resources, tmp_path / "state"))
    assert paths.library_file.read_text().startswith("# Add one")
    assert paths.user_data.read_text() == "default_user_data: {}\n"


def test_atomic_copy_rejects_verification_mismatch(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_text("content")
    digests = iter(("source", "different"))
    monkeypatch.setattr("mariana.paths._digest", lambda _path: next(digests))
    with pytest.raises(OSError, match="Verification failed"):
        _copy_atomic(source, destination)
    assert not destination.exists()
