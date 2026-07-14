import subprocess
from pathlib import Path

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


@pytest.mark.parametrize(
    "media_url",
    [
        "https://soundcloud.com/francis-karel-1/like-all-my-friends",
        "https://www.dailymotion.com/video/x9abc",
    ],
)
def test_download_uses_installed_extractor_for_media_pages(tmp_path: Path, monkeypatch, media_url):
    captured = {}

    class FakeDownloader:
        def __init__(self, options):
            captured["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, url, *, download):
            captured["url"] = url
            captured["download"] = download
            staging = Path(captured["options"]["outtmpl"]).parent
            (staging / "media.mp3").write_bytes(b"audio")
            return {}

    monkeypatch.setattr("mariana.download.YoutubeDL", FakeDownloader)
    monkeypatch.setattr("mariana.download.subprocess.run", lambda *_args, **_kwargs: pytest.fail("FFmpeg input path used"))
    result = download_media(
        media_url,
        tmp_path / "song.mp3",
    )

    assert result == tmp_path / "song.mp3"
    assert result.read_bytes() == b"audio"
    assert captured["url"] == media_url
    assert captured["download"] is True
    assert captured["options"]["format"] == "bestaudio/best"


def test_extractor_download_honors_ffmpeg_location_and_rejects_missing_output(tmp_path: Path, monkeypatch):
    captured = {}

    class FakeDownloader:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, *, download):
            assert download is True

    monkeypatch.setattr("mariana.download.YoutubeDL", FakeDownloader)

    with pytest.raises(DownloadError, match="without producing a media file"):
        download_media(
            "https://soundcloud.com/artist/track",
            tmp_path / "song.mp3",
            ffmpeg_bin=str(tmp_path / "ffmpeg-bin"),
        )

    assert captured["ffmpeg_location"] == str(tmp_path / "ffmpeg-bin")


def test_extractor_download_wraps_library_failure_and_cleans_staging(tmp_path: Path, monkeypatch):
    class BrokenDownloader:
        def __init__(self, _options):
            pass

        def __enter__(self):
            raise OSError("extractor unavailable")

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr("mariana.download.YoutubeDL", BrokenDownloader)

    with pytest.raises(DownloadError, match="Media-page download failed: extractor unavailable"):
        download_media("https://soundcloud.com/artist/track", tmp_path / "song.mp3")

    assert list(tmp_path.glob(".mariana-download-*")) == []


def test_download_cleans_partial_on_timeout(tmp_path: Path, monkeypatch):
    def timeout(command, **_kwargs):
        Path(command[-1]).write_bytes(b"partial")
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr("mariana.download.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.download.subprocess.run", timeout)
    with pytest.raises(DownloadError, match="exceeded"):
        download_media("https://example.test/audio", tmp_path / "song.mp3", timeout=1)
    assert not list(tmp_path.glob("*.partial*"))


@pytest.mark.parametrize("failure", ["empty", "process", "process_text"])
def test_download_rejects_empty_output_and_reports_process_errors(tmp_path: Path, monkeypatch, failure):
    def run(command, **_kwargs):
        if failure.startswith("process"):
            detail = "server rejected media" if failure == "process_text" else b"server rejected media"
            raise subprocess.CalledProcessError(1, command, stderr=detail)
        Path(command[-1]).write_bytes(b"")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("mariana.download.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.download.subprocess.run", run)
    expected = "without producing" if failure == "empty" else "server rejected"
    with pytest.raises(DownloadError, match=expected):
        download_media("https://example.test/audio", tmp_path / "song.mp3")
