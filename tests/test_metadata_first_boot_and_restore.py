import io
import zipfile

import pytest
from ruamel.yaml import YAML

import beta.mediadl as mediadl
import first_boot_setup
import restore_default


class ArchiveResponse:
    def __init__(self, content: bytes):
        self.content = content
        self.headers = {"content-length": str(len(content))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        assert chunk_size == 1024
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset : offset + chunk_size]


def zip_bytes(name: str, content: bytes = b"audio") -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(name, content)
    return output.getvalue()


def prepare_first_boot_download(monkeypatch, tmp_path, archive: bytes):
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / "settings.yml").write_text("download: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mediadl, "setup_dl_dir", lambda *_args: str(tmp_path))
    monkeypatch.setattr("requests.get", lambda *_a, **_k: ArchiveResponse(archive))


def test_sample_download_extracts_valid_archive_and_removes_zip(monkeypatch, tmp_path):
    prepare_first_boot_download(monkeypatch, tmp_path, zip_bytes("album/song.mp3"))
    first_boot_setup.download_cloud_mariana_samples({})
    assert (tmp_path / "mariana_music_samples" / "album" / "song.mp3").read_bytes() == b"audio"
    assert not (tmp_path / "mariana_samples.zip").exists()


@pytest.mark.parametrize("member", ["../escape.txt", "album/../../escape.txt"])
def test_sample_download_rejects_archive_path_traversal(monkeypatch, tmp_path, member):
    prepare_first_boot_download(monkeypatch, tmp_path, zip_bytes(member))
    with pytest.raises(zipfile.BadZipFile, match="Unsafe path"):
        first_boot_setup.download_cloud_mariana_samples({})
    assert not (tmp_path / "escape.txt").exists()


def test_first_boot_validates_answers_saves_library_and_runs_download(monkeypatch, tmp_path):
    settings = tmp_path / "settings"
    settings.mkdir()
    system = settings / "system.toml"
    responses = iter(["maybe", "yes", str(tmp_path), "xxx", "maybe", "yes", "maybe", "no"])
    downloads = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(first_boot_setup, "download_cloud_mariana_samples", lambda about: downloads.append(about))
    about = {"first_boot": True, "ver": {"maj": 0, "min": 6, "rel": 2}}

    assert first_boot_setup.fbs(about) is True
    assert downloads == [about]
    assert str(tmp_path).lower() in (tmp_path / "lib.lib").read_text(encoding="utf-8")
    assert about["first_boot"] is False
    assert system.is_file()


def test_restore_default_updates_nested_setting_and_persists(monkeypatch, tmp_path):
    yaml = YAML(typ="safe")
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir()
    monkeypatch.setattr(restore_default, "APP_DIR", tmp_path)
    monkeypatch.setattr(restore_default, "DEFAULT_SETTINGS", {"audio": {"volume": 80}})
    current = {"audio": {"volume": 10, "muted": False}}

    restore_default.restore("audio/volume", current)

    assert current["audio"]["volume"] == 80
    with (settings_dir / "settings.yml").open(encoding="utf-8") as stream:
        assert yaml.load(stream)["audio"] == {"volume": 80, "muted": False}
