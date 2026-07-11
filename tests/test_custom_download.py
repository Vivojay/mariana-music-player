from pathlib import Path
import subprocess

import pytest

from mariana.download import DownloadError, download_media


def test_download_validates_url_and_format(tmp_path: Path):
    with pytest.raises(DownloadError, match="valid HTTP"):
        download_media("file:///secret", tmp_path / "song.mp3")
    with pytest.raises(DownloadError, match="Unsupported"):
        download_media("https://example.test/audio", tmp_path / "song.exe", output_format="exe")


def test_download_is_atomic_and_uses_explicit_codec(tmp_path: Path, monkeypatch):
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        Path(command[-1]).write_bytes(b"audio")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("mariana.download.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.download.subprocess.run", run)
    result = download_media("https://example.test/audio", tmp_path / "song", output_format="flac", timeout=3)
    assert result == tmp_path / "song.flac"
    assert result.read_bytes() == b"audio"
    assert "flac" in captured["command"]
    assert captured["kwargs"]["timeout"] == 3


def test_download_cleans_partial_on_timeout(tmp_path: Path, monkeypatch):
    def timeout(command, **_kwargs):
        Path(command[-1]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr("mariana.download.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.download.subprocess.run", timeout)
    with pytest.raises(DownloadError, match="exceeded"):
        download_media("https://example.test/audio", tmp_path / "song.mp3", timeout=1)
    assert not list(tmp_path.glob("*.partial*"))


@pytest.mark.parametrize("failure", ["empty", "process"])
def test_download_rejects_empty_output_and_reports_process_errors(tmp_path: Path, monkeypatch, failure):
    def run(command, **_kwargs):
        if failure == "process":
            raise subprocess.CalledProcessError(1, command, stderr=b"server rejected media")
        Path(command[-1]).write_bytes(b"")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("mariana.download.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.download.subprocess.run", run)
    expected = "without producing" if failure == "empty" else "server rejected"
    with pytest.raises(DownloadError, match=expected):
        download_media("https://example.test/audio", tmp_path / "song.mp3")
