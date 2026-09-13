import subprocess
import traceback
from pathlib import Path

import pytest

from mariana.download import DownloadError, download_media, prepare_download_target
from mariana.media_details import MediaDiagnosticLogger


def test_download_validates_url_and_format(tmp_path: Path):
    with pytest.raises(DownloadError, match="valid HTTP"):
        download_media("file:///secret", tmp_path / "song.mp3")
    with pytest.raises(DownloadError, match="Unsupported"):
        download_media("https://example.test/audio", tmp_path / "song.exe", output_format="exe")


@pytest.mark.parametrize("level", ["debug", "warning", "error"])
def test_provider_diagnostic_levels_share_the_same_url_privacy_boundary(caplog, level):
    logger = MediaDiagnosticLogger("mariana.download-test")
    with caplog.at_level("DEBUG", logger="mariana.download-test"):
        getattr(logger, level)("HTTP 403: https://person:password@media.test/track?unusual=secret#private")
    record = caplog.records[-1]
    assert record.levelname == level.upper()
    assert record.getMessage() == "HTTP 403: https://media.test/track [query omitted]"
    assert record.exc_info is None
    assert "secret" not in str(record.args)


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


def test_download_existing_destination_requires_bound_approval(tmp_path: Path, monkeypatch):
    destination = tmp_path / "song.mp3"
    destination.write_bytes(b"old")
    with pytest.raises(DownloadError, match="overwrite approval"):
        download_media("https://example.test/audio", destination)

    target = prepare_download_target(destination)

    def run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"new")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("mariana.download.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.download.subprocess.run", run)
    assert download_media(
        "https://example.test/audio", destination, output_target=target
    ).read_bytes() == b"new"


def test_download_refuses_destination_changed_after_approval(tmp_path: Path, monkeypatch):
    destination = tmp_path / "song.mp3"
    destination.write_bytes(b"old")
    target = prepare_download_target(destination)
    replacement = tmp_path / "replacement.mp3"
    replacement.write_bytes(b"changed")
    replacement.replace(destination)
    monkeypatch.setattr(
        "mariana.download.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("download ran for a stale output approval"),
    )

    with pytest.raises(DownloadError, match="changed after approval"):
        download_media("https://example.test/audio", destination, output_target=target)

    assert destination.read_bytes() == b"changed"


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


def test_video_download_uses_mp4_streams_and_forwards_real_progress(tmp_path: Path, monkeypatch):
    captured = {}
    updates = []

    class FakeDownloader:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def extract_info(self, _url, *, download):
            assert download is True
            captured["progress_hooks"][0]({
                "downloaded_bytes": 50,
                "total_bytes": 100,
                "speed": 25,
            })
            Path(captured["outtmpl"]).with_name("media.mp4").write_bytes(b"video")

    monkeypatch.setattr("mariana.download.YoutubeDL", FakeDownloader)
    result = download_media(
        "https://example.test/video",
        tmp_path / "clip.mp4",
        output_format="mp4",
        progress_hook=updates.append,
    )

    assert result.read_bytes() == b"video"
    assert captured["format"] == "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]"
    assert captured["merge_output_format"] == "mp4"
    assert captured["postprocessors"] == []
    assert updates == [{"downloaded_bytes": 50, "total_bytes": 100, "speed": 25}]


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


@pytest.mark.parametrize("stderr", [None, "text", "bytes"])
def test_ffmpeg_download_error_hides_private_transport_in_messages_and_tracebacks(tmp_path, monkeypatch, stderr):
    stream = "https://listener:secret-pass@media.test/audio.mp3?signature=private-token&unusual=private-value#fragment"
    def reject(command, **_kwargs):
        detail = f"HTTP 403 while opening {stream}"
        if stderr == "bytes":
            detail = detail.encode()
        elif stderr is None:
            detail = None
        raise subprocess.CalledProcessError(1, command, stderr=detail)

    monkeypatch.setattr("mariana.download.find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr("mariana.download._uses_extractor", lambda _url: False)
    monkeypatch.setattr("mariana.download.subprocess.run", reject)
    with pytest.raises(DownloadError) as error:
        download_media(stream, tmp_path / "song.mp3")

    rendered = "".join(traceback.format_exception(error.value))
    for private in ("listener", "secret-pass", "private-token", "private-value", "#fragment"):
        assert private not in str(error.value)
        assert private not in rendered
    assert "query omitted" in str(error.value)
    assert "media.test/audio.mp3" in str(error.value)
    assert not list(tmp_path.iterdir())


def test_extractor_download_redacts_both_its_logger_and_raised_error(tmp_path, monkeypatch, caplog):
    stream = "https://listener:secret-pass@media.test/audio?signature=private-token&unusual=private-value"
    class RejectedDownloader:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            assert download
            message = f"HTTP 403 for {stream}"
            self.options["logger"].error(message)
            raise OSError(message)

    monkeypatch.setattr("mariana.download.YoutubeDL", RejectedDownloader)
    monkeypatch.setattr("mariana.download._uses_extractor", lambda _url: True)
    with pytest.raises(DownloadError) as error:
        download_media("https://provider.test/recording", tmp_path / "song.mp3")

    rendered = str(error.value) + "".join(traceback.format_exception(error.value)) + caplog.text
    assert "403" in str(error.value) and "403" in caplog.text
    assert "query omitted" in str(error.value) and "query omitted" in caplog.text
    for private in ("listener", "secret-pass", "private-token", "private-value"):
        assert private not in rendered
    assert all(record.exc_info is None for record in caplog.records)
    assert not list(tmp_path.iterdir())
