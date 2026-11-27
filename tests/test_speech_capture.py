import json
import threading
import time
import wave

import pytest

from mariana.speech_capture import RATE, SpeechCapture, local_recognizer


class Stream:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def start(self):
        pass

    def read(self, frames):
        self.entered.set()
        self.release.wait(timeout=2)
        time.sleep(.005)
        return b"\x01\x00" * frames, False

    def close(self):
        self.closed = True


class Recognizer:
    def AcceptWaveform(self, data):
        return False

    def PartialResult(self):
        return '{"partial":"hel"}'

    def FinalResult(self):
        return json.dumps({"text": "hello <everyone>", "result": [{"start": 0, "end": .1}]})


def test_record_stop_export_and_share_real_wav_and_labeled_captions(tmp_path, monkeypatch):
    stream = Stream()
    capture = SpeechCapture(tmp_path / "takes", input_factory=lambda: stream, model_factory=lambda _: Recognizer())
    capture.command(["start", "my-model"])
    assert stream.entered.wait(1)
    capture.command(["speaker", "Jay", "&", "friends"])
    with pytest.raises(ValueError, match="already in use"):
        capture.command(["record"])
    with pytest.raises(ValueError, match="before exporting"):
        capture.command(["export", str(tmp_path / "early.wav")])
    stream.release.set()
    for _ in range(100):
        if "hel" in capture.command(["text"]):
            break
        time.sleep(.01)
    assert "hel" in capture.command(["text"])
    assert "Stopped" in capture.command(["stop"])
    capture.close()
    assert stream.closed
    assert capture.command(["text"]) == "Jay & friends: hello <everyone>"
    for ext in ("wav", "vtt", "txt"):
        capture.command(["export", str(tmp_path / ("take." + ext))])
    with wave.open(str(tmp_path / "take.wav"), "rb") as output:
        assert (output.getframerate(), output.getnchannels(), output.getsampwidth()) == (RATE, 1, 2)
        assert output.getnframes() >= 1600
        assert output.readframes(1600) == b"\x01\x00" * 1600
    assert "00:00:00.000 --> 00:00:00.100\n<v Jay &amp; friends>hello &lt;everyone&gt;</v>" in (tmp_path / "take.vtt").read_text()
    assert (tmp_path / "take.txt").read_text() == "Jay & friends: hello <everyone>\n"
    assert capture.take.path.with_suffix(".vtt").is_file()
    with pytest.raises(ValueError, match="already exists"):
        capture.command(["export", str(tmp_path / "take.wav")])
    monkeypatch.setattr("mariana.clip_share.open_share", lambda path, recording: path if recording else None)
    assert capture.command(["share"]) == capture.take.path
    assert capture.command(["share", "txt"]).read_text() == "Jay & friends: hello <everyone>\n"


def test_unavailable_model_does_not_open_microphone(tmp_path):
    capture = SpeechCapture(tmp_path, input_factory=lambda: pytest.fail("opened microphone"))
    with pytest.raises(ValueError, match="extracted Vosk model directory"):
        capture.command(["start", str(tmp_path / "missing")])
    assert not list(tmp_path.iterdir())
    assert "Microphone off" in capture.command(["status"])


def test_device_failure_closes_stream_and_preserves_diagnostic(tmp_path):
    stream = Stream()
    stream.read = lambda n: (b"", True)
    capture = SpeechCapture(tmp_path, input_factory=lambda: stream)
    capture.command(["record"])
    assert capture.take.done.wait(2)
    assert stream.closed
    assert "overflow" in capture.command(["status"])
    with pytest.raises(ValueError, match="no audio or captions"):
        capture.command(["export", str(tmp_path / "empty.wav")])


def test_missing_model_and_permission_denial_have_actionable_errors(tmp_path, monkeypatch):
    monkeypatch.delenv("MARIANA_VOSK_MODEL", raising=False)
    with pytest.raises(ValueError, match="extracted Vosk"):
        local_recognizer(None)
    stream = Stream()

    def deny():
        raise OSError("microphone permission denied")

    stream.start = deny
    capture = SpeechCapture(tmp_path, input_factory=lambda: stream)
    with pytest.raises(ValueError, match="permission denied"):
        capture.command(["record"])
    assert capture.take is None and stream.closed


def test_private_transcript_handoff_uses_plain_text_and_serves_exact_content(tmp_path):
    from urllib.request import ProxyHandler, build_opener

    from mariana.clip_share import start_handoff

    path = tmp_path / "Mariana.vtt"
    path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v Jay>Hello</v>\n", encoding="utf-8")
    handoff = start_handoff(path, lifetime=1, recording=True)
    client = build_opener(ProxyHandler({}))
    with client.open(handoff, timeout=2) as response:
        page = response.read()
        assert b"Share your transcript" in page and b"<audio controls" not in page
    with client.open(handoff + "file", timeout=2) as response:
        assert response.headers["Content-Type"] == "text/vtt"
        assert response.read() == path.read_bytes()
