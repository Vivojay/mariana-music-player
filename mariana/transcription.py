"""Generate timed, explicitly unverified transcript drafts from local media."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
import wave

from .output_targets import OutputTargetError, bind_output_target
from .speech_capture import timestamp


RATE = 16_000
MAX_SECONDS = 1_800
MAX_RESPONSE = 8 * 1024 * 1024
MAX_CUES = 20_000
DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"
SCHEMA = "mariana.transcript-draft.v1"
LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[a-z0-9]{2,8}){0,3}", re.I | re.ASCII)
USAGE = (
    "speech transcribe NEW.json|NEW.vtt [--backend whisper|deepgram] "
    "[--language auto|LANGUAGE] [--send-audio]\n"
    "Transcribe the loaded local recording. See docs/LIVE_SPEECH.md for setup."
)


@dataclass(frozen=True)
class Request:
    destination: Path
    backend: str
    language: str
    send_audio: bool


def parse_request(arguments):
    if not arguments or arguments[0].startswith("--"):
        raise ValueError(USAGE)
    destination = Path(arguments[0]).expanduser()
    if destination.suffix.lower() not in {".json", ".vtt"}:
        raise ValueError("Choose a new .json or .vtt file.")
    options = {}
    index = 1
    while index < len(arguments):
        flag = arguments[index].casefold()
        if flag in options:
            raise ValueError(f"Option {flag} may appear only once.")
        if flag == "--send-audio":
            options[flag] = True
            index += 1
        elif flag in {"--backend", "--language"} and index + 1 < len(arguments):
            options[flag] = arguments[index + 1].casefold()
            index += 2
        else:
            raise ValueError(USAGE)
    backend = options.get("--backend", "whisper")
    language = options.get("--language", "auto")
    send_audio = options.get("--send-audio", False)
    if backend not in {"whisper", "deepgram"}:
        raise ValueError("Choose whisper or deepgram.")
    if backend == "whisper" and send_audio:
        raise ValueError("--send-audio is only for the Deepgram backend.")
    if language != "auto" and not LANGUAGE.fullmatch(language):
        raise ValueError("Choose auto or a language code such as en, hi or en-IN.")
    if backend == "deepgram" and not send_audio:
        raise ValueError("Deepgram receives the recording's audio. Confirm by adding --send-audio.")
    return Request(destination, backend, language, send_audio)


def _run(command, *, timeout, cancelled, description, cwd=None):
    if cancelled():
        raise ValueError("Transcription cancelled.")
    try:
        process = subprocess.Popen(
            command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise ValueError(f"Could not start {description}. Check its installation.") from error
    deadline = time.monotonic() + timeout
    try:
        while True:
            if cancelled():
                raise ValueError("Transcription cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(f"{description} timed out.")
            try:
                result = process.wait(timeout=min(0.2, remaining))
            except subprocess.TimeoutExpired:
                continue
            if result:
                raise ValueError(f"{description} failed. Check the input and installation.")
            return
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def _extract(source, audio, ffmpeg, cancelled):
    # A named local file and a strict protocol list keep extraction offline.
    command = [
        ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
        "-i", "file:" + str(source), "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-t", str(MAX_SECONDS + 1), "-ar", str(RATE), "-ac", "1", "-c:a",
        "pcm_s16le", "-f", "wav", str(audio),
    ]
    _run(command, timeout=120, cancelled=cancelled, description="FFmpeg audio extraction")
    try:
        with wave.open(str(audio), "rb") as stream:
            duration = stream.getnframes() / stream.getframerate()
    except (OSError, EOFError, wave.Error) as error:
        raise ValueError("FFmpeg did not generate readable mono audio.") from error
    if duration <= 0 or duration > MAX_SECONDS:
        raise ValueError("Choose a recording with an audio track no longer than 30 minutes.")
    return duration


def _text(value, limit):
    if not isinstance(value, str):
        return ""
    filtered = "".join(char for char in value if unicodedata.category(char) not in {"Cc", "Cs"}
                       or char in "\t\r\n")
    return " ".join(filtered.split())[:limit]


def _number(value):
    return type(value) in {int, float} and abs(value) <= 1e9


def _confidence(value):
    return value if _number(value) and 0 <= value <= 1 else None


def _language(value):
    return value if isinstance(value, str) and LANGUAGE.fullmatch(value) else None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _list(value):
    return value if isinstance(value, list) else []


def _times(start, end, duration, *, units=1):
    if _number(start) and _number(end) and 0 <= start < end:
        start = round(start / units, 3)
        end = round(min(end / units, duration), 3)
        if start < end:
            return start, end
    return None


def _draft(backend, duration, language_codes, segments, confidence=None):
    if not segments:
        raise ValueError("No timed words or phrases were returned. Try clearer, isolated vocals or speech.")
    return {
        "schema": SCHEMA, "backend": backend, "reviewRequired": True,
        "duration": duration, "languages": list(dict.fromkeys(filter(None, language_codes))),
        "transcriptConfidence": confidence, "segments": segments,
    }


def parse_whisper(data, duration):
    data = _mapping(data)
    language = _language(_mapping(data.get("result")).get("language"))
    rows = _list(data.get("transcription"))
    if len(rows) > MAX_CUES:
        raise ValueError("The local recognizer returned too many phrases.")
    segments = []
    for entry in rows:
        row = _mapping(entry)
        offsets = _mapping(row.get("offsets"))
        times = _times(offsets.get("from"), offsets.get("to"), duration, units=1000)
        body = _text(row.get("text"), 2400)
        if times and body:
            segments.append(dict(startTime=times[0], endTime=times[1], body=body, speaker=None,
                                 language=None))
    segments.sort(key=lambda item: (item["startTime"], item["endTime"]))
    return _draft("whisper.cpp", duration, [language], segments)


def parse_deepgram(data, duration):
    channels = _list(_mapping(_mapping(data).get("results")).get("channels"))
    channel = _mapping(channels[0]) if channels else {}
    alternatives = _list(channel.get("alternatives"))
    alternative = _mapping(alternatives[0]) if alternatives else {}
    rows = _list(alternative.get("words"))
    if len(rows) > MAX_CUES:
        raise ValueError("The speech service returned too many words.")
    words = []
    for entry in rows:
        row = _mapping(entry)
        times = _times(row.get("start"), row.get("end"), duration)
        body = _text(row.get("punctuated_word") or row.get("word"), 120)
        if not times or not body:
            continue
        speaker = row.get("speaker")
        words.append({
            "text": body, "startTime": times[0], "endTime": times[1],
            "language": _language(row.get("language")),
            "confidence": _confidence(row.get("confidence")),
            "speakerConfidence": _confidence(row.get("speaker_confidence")),
            "speaker": f"Speaker {speaker + 1}" if type(speaker) is int and 0 <= speaker <= 1000 else None,
        })
    words.sort(key=lambda word: (word["startTime"], word["endTime"]))
    segments = []
    for word in words:
        current = segments[-1] if segments else None
        if (current is None or current["speaker"] != word["speaker"] or
                current["language"] != word["language"] or word["startTime"] - current["endTime"] > 1 or
                word["endTime"] - current["startTime"] > 10 or len(current["words"]) >= 40):
            current = dict(startTime=word["startTime"], endTime=word["endTime"], speaker=word["speaker"],
                           language=word["language"], words=[])
            segments.append(current)
        current["words"].append(word)
        current["endTime"] = max(current["endTime"], word["endTime"])
    for entry in segments:
        entry["body"] = " ".join(word["text"] for word in entry["words"])
    reported = [*_list(alternative.get("languages")), *_list(channel.get("languages")),
                channel.get("detected_language")]
    language_codes = [_language(code) for code in reported]
    language_codes.extend(word["language"] for word in words)
    return _draft("deepgram-nova-3", duration, language_codes, segments, _confidence(alternative.get("confidence")))


def _json(data):
    try:
        return json.loads(data)
    except (UnicodeError, RecursionError, ValueError) as error:
        raise ValueError("The transcription backend returned invalid JSON.") from error


def _whisper_config():
    setting = os.environ.get("MARIANA_WHISPER_CLI", "whisper-cli")
    executable = shutil.which(str(Path(setting).expanduser()))
    model = Path(os.environ.get("MARIANA_WHISPER_MODEL", "")).expanduser()
    if not executable or not model.is_file():
        raise ValueError("Install whisper-cli and set MARIANA_WHISPER_MODEL. See docs/LIVE_SPEECH.md.")
    return str(Path(executable).resolve()), model.resolve()


def _whisper(audio, config, language, duration, cancelled):
    executable, model = config
    output = audio.parent / "draft"
    command = [executable, "-m", str(model), "-f", str(audio), "-l", language.split("-")[0],
               "-oj", "-of", str(output), "-np"]
    _run(command, timeout=900, cancelled=cancelled, description="whisper.cpp recognition", cwd=audio.parent)
    try:
        with output.with_suffix(".json").open("rb") as stream:
            encoded = stream.read(MAX_RESPONSE + 1)
    except OSError as error:
        raise ValueError("whisper.cpp did not create its JSON transcript. Use a current whisper-cli.") from error
    if len(encoded) > MAX_RESPONSE:
        raise ValueError("The local recognizer returned a transcript above 8 MiB.")
    return parse_whisper(_json(encoded), duration)


def _deepgram(audio, key, language, duration, cancelled):
    import requests

    params = {"model": "nova-3", "language": "multi", "diarize_model": "latest", "punctuate": "true"}
    if language != "auto":
        params["language_hint"] = language
    if cancelled():
        raise ValueError("Transcription cancelled.")
    try:
        with audio.open("rb") as stream, requests.post(
            DEEPGRAM_URL, params=params,
            headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
            data=stream, timeout=(8, 120), stream=True, allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ValueError(f"Deepgram returned HTTP {response.status_code}. Check the API key and service status.")
            encoded = bytearray()
            for block in response.iter_content(65536):
                if cancelled():
                    raise ValueError("Transcription cancelled.")
                encoded.extend(block)
                if len(encoded) > MAX_RESPONSE:
                    raise ValueError("The speech service returned a transcript above 8 MiB.")
    except requests.RequestException as error:
        raise ValueError("Could not finish the Deepgram request. Check connectivity and retry.") from error
    return parse_deepgram(_json(encoded), duration)


def _vtt(draft):
    lines = ["WEBVTT", "", f"NOTE Unverified machine transcript, {draft['backend']}.", ""]
    for entry in draft["segments"]:
        text = escape(entry["body"], quote=False)
        if entry["language"]:
            text = f"<lang {entry['language']}>{text}</lang>"
        if entry["speaker"]:
            text = f"<v {escape(entry['speaker'], quote=False)}>{text}</v>"
        lines.extend((f"{timestamp(entry['startTime'])} --> {timestamp(entry['endTime'])}", text, ""))
    return "\n".join(lines) + "\n"


def transcribe(source, request, *, ffmpeg, temporary, cancelled=lambda: False):
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError("The loaded local recording is unavailable.")
    ffmpeg = shutil.which(str(ffmpeg)) if ffmpeg else shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("Transcription needs FFmpeg. See tools setup.")
    ffmpeg = str(Path(ffmpeg).resolve())
    if request.backend == "whisper":
        config = _whisper_config()
    else:
        config = os.environ.get("DEEPGRAM_API_KEY", "").strip()
        if not config or len(config) > 512 or not config.isascii() or not config.isprintable() or any(c.isspace() for c in config):
            raise ValueError("Set DEEPGRAM_API_KEY outside Mariana. See docs/LIVE_SPEECH.md.")
    try:
        target = bind_output_target(request.destination)
        if target.existed:
            raise ValueError("The destination already exists. Choose a new filename.")
        temporary.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="transcript-", dir=temporary) as work:
            audio = Path(work) / "source.wav"
            duration = _extract(source, audio, ffmpeg, cancelled)
            recognize = _whisper if request.backend == "whisper" else _deepgram
            draft = recognize(audio, config, request.language, duration, cancelled)
        with tempfile.TemporaryDirectory(prefix="transcript-", dir=target.path.parent) as work:
            staged = Path(work) / target.path.name
            text = _vtt(draft) if target.path.suffix.lower() == ".vtt" else json.dumps(
                draft, ensure_ascii=False, indent=2, allow_nan=False,
            ) + "\n"
            staged.write_text(text, encoding="utf-8")
            if cancelled():
                raise ValueError("Transcription cancelled.")
            path = target.activate(staged)
    except (OSError, OutputTargetError) as error:
        raise ValueError(f"Could not save the transcript draft: {error}") from error
    return path, draft
