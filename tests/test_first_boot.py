import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import BadZipFile

import pytest

import beta.mediadl as mediadl
import first_boot_setup
from mariana.setup import SetupAlreadyRunning, SetupState, SetupStateError, SetupStateStore


def setup_store(tmp_path: Path) -> SetupStateStore:
    store = SetupStateStore(
        SimpleNamespace(setup_state=tmp_path / "setup-state.json", setup_lock=tmp_path / ".setup.lock")
    )
    store.reset()
    return store


def test_first_boot_can_decline_samples_and_exit(monkeypatch, tmp_path: Path):
    about = {"ver": {"maj": 0, "min": 6, "rel": 2}}
    store = setup_store(tmp_path)
    responses = iter(["n", "n", "n"])
    monkeypatch.setattr(
        first_boot_setup, "runtime_paths", lambda: SimpleNamespace(library_file=tmp_path / "lib.lib")
    )
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        first_boot_setup,
        "download_cloud_mariana_samples",
        lambda _about: pytest.fail("sample download must not run when declined"),
    )

    assert first_boot_setup.fbs(about, store) is True
    assert store.load().status == "complete"


def test_setup_state_detects_corruption_and_repairs(monkeypatch, tmp_path: Path):
    store = setup_store(tmp_path)
    store.path.write_text("not json", encoding="utf-8")
    with pytest.raises(SetupStateError, match="unreadable"):
        store.load()
    backup = store.repair()
    assert backup and backup.read_text(encoding="utf-8") == "not json"
    assert store.load().status == "pending"


def test_setup_lock_rejects_live_owner_and_recovers_stale(tmp_path: Path):
    store = setup_store(tmp_path)
    with store.lock(), pytest.raises(SetupAlreadyRunning), store.lock():
        pass
    store.lock_path.write_text(json.dumps({"pid": -1, "created_at": 0}), encoding="utf-8")
    with store.lock():
        assert store.lock_path.exists()
    assert not store.lock_path.exists()


def test_setup_steps_are_idempotent_and_resume(monkeypatch, tmp_path: Path):
    store = setup_store(tmp_path)
    library = tmp_path / "lib.lib"
    music = tmp_path / "Music"
    music.mkdir()
    monkeypatch.setattr(first_boot_setup, "runtime_paths", lambda: SimpleNamespace(library_file=library))
    answers = iter(["y", str(music), str(music), "xxx", "n", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    assert first_boot_setup.fbs({"ver": {"maj": 0, "min": 7, "rel": 0}}, store) is False
    assert library.read_text(encoding="utf-8").count(str(music)) == 1
    assert first_boot_setup.fbs({"ver": {"maj": 0, "min": 7, "rel": 0}}, store) is False


class InvalidArchiveResponse:
    headers = {"content-length": "12"}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        assert chunk_size == 1024
        yield b"not-a-zip"


def test_first_boot_rejects_invalid_sample_archive(monkeypatch, tmp_path: Path):
    settings_directory = tmp_path / "settings"
    settings_directory.mkdir()
    (settings_directory / "settings.yml").write_text("download: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mediadl, "setup_dl_dir", lambda *_args: str(tmp_path))
    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: InvalidArchiveResponse())

    with pytest.raises(BadZipFile, match="valid zip archive"):
        first_boot_setup.download_cloud_mariana_samples({})


def test_selected_sample_failure_is_not_marked_complete(monkeypatch, tmp_path: Path):
    store = setup_store(tmp_path)
    monkeypatch.setattr(first_boot_setup, "runtime_paths", lambda: SimpleNamespace(library_file=tmp_path / "lib.lib"))
    responses = iter(["n", "y"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(first_boot_setup, "download_cloud_mariana_samples", lambda _about: 2)

    with pytest.raises(first_boot_setup.SampleSetupError, match="not downloaded"):
        first_boot_setup.fbs({"ver": {"maj": 0, "min": 7, "rel": 0}}, store)

    state = store.load()
    assert state.status == "failed"
    assert state.current_step == "samples"
    assert "samples" not in state.completed_steps


def test_failed_optional_samples_can_be_explicitly_skipped(monkeypatch, tmp_path: Path):
    store = setup_store(tmp_path)
    store.save(
        SetupState(
            status="failed",
            current_step="samples",
            completed_steps=["library"],
            error={"type": "SampleSetupError", "message": "offline"},
        )
    )
    monkeypatch.setattr(first_boot_setup, "runtime_paths", lambda: SimpleNamespace(library_file=tmp_path / "lib.lib"))
    responses = iter(["skip", "n"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        first_boot_setup,
        "download_cloud_mariana_samples",
        lambda _about: pytest.fail("skipped optional samples must not be retried"),
    )

    assert first_boot_setup.fbs({"ver": {"maj": 0, "min": 7, "rel": 0}}, store) is True
    state = store.load()
    assert state.status == "complete"
    assert state.completed_steps == ["library", "samples", "launch"]


@pytest.mark.parametrize("interrupt_at", ["library", "samples", "launch"])
def test_each_interrupted_step_remains_resumable(monkeypatch, tmp_path: Path, interrupt_at: str):
    store = setup_store(tmp_path)
    store.begin(interrupt_at)
    if interrupt_at != "library":
        store.complete_step("library")
        store.begin(interrupt_at)
    if interrupt_at == "launch":
        store.complete_step("samples")
        store.begin("launch")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "q")

    assert first_boot_setup._recover(store) is False
    state = store.load()
    assert state.status == "in_progress"
    assert state.current_step == interrupt_at


def test_setup_atomic_replace_failure_retains_previous_state(monkeypatch, tmp_path: Path):
    store = setup_store(tmp_path)
    previous = store.path.read_bytes()
    monkeypatch.setattr("mariana.setup.os.replace", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        store.begin("library")

    assert store.path.read_bytes() == previous
    assert not list(tmp_path.glob(".setup-state.json.*.tmp"))
