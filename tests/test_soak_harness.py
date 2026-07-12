from pathlib import Path

import pytest

from tools.soak_test import run

FFMPEG_BIN = Path(
    r"C:\Users\Vivan.Jaiswal\Documents\ffmpeg-2025-12-18-git-78c75d546a-essentials_build\bin"
)


def test_short_mixed_playback_and_library_soak_has_bounded_resources():
    if not (FFMPEG_BIN / "ffmpeg.exe").is_file():
        pytest.skip("configured FFmpeg build is unavailable")
    result = run(2, str(FFMPEG_BIN), live_radio=False, library_files=100)
    assert result["cycles"] >= 1
    assert result["library_files"] == 100
    assert result["growth"] < 64 * 1024 * 1024
