import io
import zipfile
from types import SimpleNamespace

import pytest
from ruamel.yaml import YAML

import beta.mediadl as mediadl
import first_boot_setup
import restore_default
from mariana.setup import SetupStateStore


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


def test_atomic_setup_replace_retries_transient_permission_error(monkeypatch, tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_text("ready", encoding="utf-8")
    real_replace = first_boot_setup.os.replace
    calls = []

    def transient_replace(current, target):
        calls.append((current, target))
        if len(calls) == 1:
            raise PermissionError("temporarily locked")
        real_replace(current, target)

    monkeypatch.setattr(first_boot_setup.os, "replace", transient_replace)
    monkeypatch.setattr(first_boot_setup.time, "sleep", lambda _delay: None)
    first_boot_setup._replace_with_retry(source, destination)

    assert len(calls) == 2
    assert destination.read_text(encoding="utf-8") == "ready"


def test_atomic_setup_replace_propagates_persistent_permission_error(monkeypatch, tmp_path):
    source = tmp_path / "source"
    source.write_text("ready", encoding="utf-8")
    monkeypatch.setattr(
        first_boot_setup.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(PermissionError("locked")),
    )
    monkeypatch.setattr(first_boot_setup.time, "sleep", lambda _delay: None)

    with pytest.raises(PermissionError, match="locked"):
        first_boot_setup._replace_with_retry(source, tmp_path / "destination", attempts=2)


@pytest.mark.parametrize("member", ["../escape.txt", "album/../../escape.txt"])
def test_sample_download_rejects_archive_path_traversal(monkeypatch, tmp_path, member):
    prepare_first_boot_download(monkeypatch, tmp_path, zip_bytes(member))
    with pytest.raises(zipfile.BadZipFile, match="Unsafe path"):
        first_boot_setup.download_cloud_mariana_samples({})
    assert not (tmp_path / "escape.txt").exists()


def test_first_boot_validates_answers_saves_library_and_runs_download(monkeypatch, tmp_path):
    responses = iter(["maybe", "yes", str(tmp_path), "xxx", "maybe", "yes", "maybe", "no"])
    downloads = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(responses))
    monkeypatch.setattr(first_boot_setup, "download_cloud_mariana_samples", lambda about: downloads.append(about))
    monkeypatch.setattr(
        first_boot_setup,
        "runtime_paths",
        lambda: SimpleNamespace(library_file=tmp_path / "lib.lib"),
    )
    about = {"first_boot": True, "ver": {"maj": 0, "min": 6, "rel": 2}}
    store = SetupStateStore(
        SimpleNamespace(setup_state=tmp_path / "setup-state.json", setup_lock=tmp_path / ".setup.lock")
    )
    store.reset()

    assert first_boot_setup.fbs(about, store) is True
    assert downloads == [about]
    assert str(tmp_path).casefold() in (tmp_path / "lib.lib").read_text(encoding="utf-8").casefold()
    assert store.load().status == "complete"


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
