from pathlib import Path

from logger import SAY
from runtime_check import check_runtime, format_runtime_report
from terminal_colors import attr, bg, fg
from url_validate import id_if_url_is_of_yt_format


def test_url_parser_handles_common_youtube_shapes():
    assert id_if_url_is_of_yt_format("https://www.youtube.com/watch?v=abc12345678") == "abc12345678"
    assert id_if_url_is_of_yt_format("https://youtu.be/abc12345678") == "abc12345678"
    assert id_if_url_is_of_yt_format("https://www.youtube.com/embed/abc12345678") == "abc12345678"


def test_fatal_logging_writes_general_and_crash_logs(tmp_path: Path):
    general_log = tmp_path / "general.log"
    SAY(False, 1, log_message="fatal test", out_file=str(general_log))
    assert "fatal test" in general_log.read_text(encoding="utf-8")
    assert "fatal test" in (tmp_path / "appcrashes.log").read_text(encoding="utf-8")


def test_runtime_report_is_actionable(monkeypatch):
    monkeypatch.setattr("runtime_check.find_tool_executable", lambda *_args: None)
    monkeypatch.setattr("runtime_check.find_javascript_runtime", lambda: None)
    monkeypatch.setattr("runtime_check.has_audio_output", lambda: False)
    report = check_runtime()
    messages = format_runtime_report(report)
    assert any("ffmpeg" in message for message in messages)
    assert any("fpcalc" in message for message in messages)
    assert any("rsgain" in message for message in messages)
    assert any("JavaScript runtime" in message for message in messages)
    assert any("output device" in message for message in messages)


def test_terminal_color_compatibility_api():
    assert fg("magenta_3a")
    assert bg("navy_blue")
    assert attr("reset")
