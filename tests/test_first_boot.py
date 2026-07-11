from pathlib import Path
from zipfile import BadZipFile

import pytest
import toml

import beta.mediadl as mediadl
import first_boot_setup


def test_first_boot_can_decline_samples_and_exit(monkeypatch, tmp_path: Path):
    settings_directory = tmp_path / "settings"
    settings_directory.mkdir()
    system_path = settings_directory / "system.toml"
    about = {
        "first_boot": True,
        "ver": {"maj": 0, "min": 6, "rel": 2},
    }
    system_path.write_text(toml.dumps(about), encoding="utf-8")
    responses = iter(["n", "n", "n"])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(
        first_boot_setup,
        "download_cloud_mariana_samples",
        lambda _about: pytest.fail("sample download must not run when declined"),
    )

    assert first_boot_setup.fbs(about) is True
    assert toml.load(system_path)["first_boot"] is False


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
