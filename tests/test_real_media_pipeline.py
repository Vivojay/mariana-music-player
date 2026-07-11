"""Real-process acceptance for the installed FFmpeg and Chromaprint toolchain."""

from pathlib import Path
import shutil
import subprocess

import pytest

from mariana.identity import find_fpcalc, fingerprint_file
from mariana.models import MediaRef, MediaSource
from mariana.playback import DecoderSession, probe_media


CONFIGURED_FFMPEG = Path(
    r"C:\Users\Vivan.Jaiswal\Documents\ffmpeg-2025-12-18-git-78c75d546a-essentials_build\bin"
)


def tool(name: str) -> str | None:
    candidate = CONFIGURED_FFMPEG / f"{name}.exe"
    return str(candidate) if candidate.is_file() else shutil.which(name)


@pytest.fixture(scope="module")
def media_fixtures(tmp_path_factory):
    ffmpeg = tool("ffmpeg")
    if not ffmpeg:
        pytest.skip("FFmpeg is not installed")
    directory = tmp_path_factory.mktemp("real-media")
    formats = {
        "wav": ["-c:a", "pcm_s16le"],
        "mp3": ["-c:a", "libmp3lame"],
        "flac": ["-c:a", "flac"],
        "ogg": ["-c:a", "libvorbis"],
        "aac": ["-c:a", "aac", "-f", "adts"],
        "webm": ["-c:a", "libopus"],
    }
    result = {}
    for extension, options in formats.items():
        path = directory / f"tone.{extension}"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=1.25",
                "-metadata",
                "title=Generated Tone",
                "-metadata",
                "artist=Mariana Tests",
                "-y",
                *options,
                str(path),
            ],
            check=True,
            timeout=30,
        )
        result[extension] = path
    return result


@pytest.mark.parametrize("extension", ["wav", "mp3", "flac", "ogg", "aac", "webm"])
def test_real_ffprobe_and_decode_all_required_formats(media_fixtures, extension):
    path = media_fixtures[extension]
    media = probe_media(MediaRef(MediaSource.LOCAL, str(path)), ffprobe_bin=tool("ffprobe"))
    assert media.duration == pytest.approx(1.25, abs=0.2)
    assert media.capabilities.finite and media.capabilities.seekable
    session = DecoderSession(media, ffmpeg_bin=tool("ffmpeg"), max_buffer_seconds=0.25)
    session.start()
    assert session.wait_for_buffer(0.05, timeout=5)
    assert len(session.read(1024)) > 0
    process = session.process
    session.stop()
    assert process.poll() is not None
    assert session.process is None


def test_real_seek_decoder_starts_at_requested_position(media_fixtures):
    media = probe_media(MediaRef(MediaSource.LOCAL, str(media_fixtures["flac"])), ffprobe_bin=tool("ffprobe"))
    session = DecoderSession(media, ffmpeg_bin=tool("ffmpeg"), start_at=0.75)
    session.start()
    assert session.wait_for_buffer(0.05, timeout=5)
    session.read(4800)
    assert session.position == pytest.approx(0.85, abs=0.01)
    session.stop()


def test_real_chromaprint_binary_fingerprints_generated_audio(tmp_path):
    try:
        fpcalc = find_fpcalc()
    except Exception:
        pytest.skip("fpcalc is not installed")
    ffmpeg = tool("ffmpeg")
    path = tmp_path / "fingerprint.wav"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=523.25:sample_rate=44100:duration=10",
            "-y",
            str(path),
        ],
        check=True,
        timeout=30,
    )
    duration, fingerprint = fingerprint_file(path, fpcalc)
    assert duration == pytest.approx(10, abs=1)
    assert len(fingerprint) > 20
