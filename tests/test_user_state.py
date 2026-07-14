import os
import subprocess
import sys
from pathlib import Path

import pytest

from mariana.user_state import load_user_data, normalize_user_data, write_user_data_atomic

ROOT = Path(__file__).resolve().parents[1]


def test_empty_user_data_is_backed_up_and_recovered(tmp_path: Path):
    path = tmp_path / "user" / "user_data.yml"
    path.parent.mkdir()
    path.write_bytes(b"")

    payload, backup = load_user_data(path)

    assert backup is not None
    assert backup.read_bytes() == b""
    assert payload["default_user_data"]["stats"]["play_count"]["local"] == 0
    assert path.stat().st_size > 0
    reloaded, second_backup = load_user_data(path)
    assert reloaded == payload
    assert second_backup is None


@pytest.mark.parametrize("content", ["null\n", "[]\n", "{broken\n", "\udcff"])
def test_invalid_user_data_recovers_without_discarding_evidence(tmp_path: Path, content: str):
    path = tmp_path / "user_data.yml"
    path.write_bytes(content.encode("utf-8", errors="surrogatepass"))

    payload, backup = load_user_data(path)

    assert backup is not None
    assert backup.exists()
    assert payload["default_user_data"]["stats"]["times_spent"] == []


def test_partial_user_data_is_completed_and_custom_fields_are_retained(tmp_path: Path):
    path = tmp_path / "user_data.yml"
    path.write_text(
        "default_user_data:\n  name: Vivan\n  stats:\n    play_count:\n      local: 7\ncustom: retained\n",
        encoding="utf-8",
    )

    payload, backup = load_user_data(path)

    assert backup is None
    assert payload["default_user_data"]["name"] == "Vivan"
    assert payload["default_user_data"]["stats"]["play_count"]["local"] == 7
    assert payload["default_user_data"]["stats"]["play_count"]["youtube"] == 0
    assert payload["custom"] == "retained"


def test_packaged_template_is_merged_with_embedded_defaults(tmp_path: Path):
    template = tmp_path / "template.yml"
    template.write_text("default_user_data:\n  name: packaged\n", encoding="utf-8")

    payload = normalize_user_data(None, template)

    assert payload["default_user_data"]["name"] == "packaged"
    assert payload["default_user_data"]["stats"]["log_ins"] == 0


def test_missing_user_data_is_created_without_a_backup(tmp_path: Path):
    path = tmp_path / "missing" / "user_data.yml"

    payload, backup = load_user_data(path)

    assert backup is None
    assert path.is_file()
    assert payload["default_user_data"]["name"] == "guest_001"


def test_backup_failure_does_not_prevent_recovery(monkeypatch, tmp_path: Path):
    path = tmp_path / "user_data.yml"
    path.write_bytes(b"")

    def fail_copy(*_args):
        raise OSError("denied")

    monkeypatch.setattr("mariana.user_state.shutil.copy2", fail_copy)

    payload, backup = load_user_data(path)

    assert backup is None
    assert payload["default_user_data"]["stats"]["log_ins"] == 0
    assert path.stat().st_size > 0


def test_atomic_write_failure_preserves_previous_file(monkeypatch, tmp_path: Path):
    path = tmp_path / "user_data.yml"
    path.write_text("previous: true\n", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("mariana.user_state.os.replace", fail_replace)

    with pytest.raises(OSError, match="simulated"):
        write_user_data_atomic(path, {"new": True})

    assert path.read_text(encoding="utf-8") == "previous: true\n"
    assert not list(tmp_path.glob(".user_data.yml.*"))


def test_atomic_write_retries_a_transient_windows_file_lock(monkeypatch, tmp_path: Path):
    path = tmp_path / "user_data.yml"
    path.write_text("previous: true\n", encoding="utf-8")
    real_replace = os.replace
    attempts = 0

    def transient_lock(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise PermissionError("simulated scanner lock")
        real_replace(source, destination)

    monkeypatch.setattr("mariana.user_state.os.replace", transient_lock)
    monkeypatch.setattr("mariana.user_state.time.sleep", lambda _delay: None)

    write_user_data_atomic(path, {"new": True})

    assert attempts == 3
    assert "new: true" in path.read_text(encoding="utf-8")


def test_atomic_write_reports_a_persistent_windows_file_lock(monkeypatch, tmp_path: Path):
    path = tmp_path / "user_data.yml"
    path.write_text("previous: true\n", encoding="utf-8")
    attempts = 0

    def persistent_lock(_source, _destination):
        nonlocal attempts
        attempts += 1
        raise PermissionError("persistent scanner lock")

    monkeypatch.setattr("mariana.user_state.os.replace", persistent_lock)
    monkeypatch.setattr("mariana.user_state.time.sleep", lambda _delay: None)

    with pytest.raises(PermissionError, match="persistent"):
        write_user_data_atomic(path, {"new": True})

    assert attempts == 6
    assert path.read_text(encoding="utf-8") == "previous: true\n"
    assert not list(tmp_path.glob(".user_data.yml.*"))


def test_real_main_import_recovers_zero_byte_runtime_user_data(tmp_path: Path):
    data = tmp_path / "runtime"
    user_data = data / "user" / "user_data.yml"
    user_data.parent.mkdir(parents=True)
    user_data.write_bytes(b"")
    environment = os.environ.copy()
    environment.update(
        MARIANA_DATA_DIR=str(data),
        MARIANA_RESOURCE_DIR=str(ROOT),
        MARIANA_E2E="1",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import main; "
                "assert main.USER_DATA['default_user_data']['stats']['play_count']['local'] == 0"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Recovered empty or invalid user statistics" in result.stdout
    assert user_data.stat().st_size > 0
    assert len(list(user_data.parent.glob("user_data.yml.invalid-*.bak"))) == 1
