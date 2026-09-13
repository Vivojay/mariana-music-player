"""Bounded, plain-text caption loading for the current video presentation."""

from __future__ import annotations

import bisect
import contextlib
import copy
import hashlib
import html
import json
import os
import re
import secrets
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from itertools import islice
from pathlib import Path

MAX_CAPTION_BYTES = 2 * 1024 * 1024
MAX_CAPTION_CUES = 20_000
MAX_CUE_TEXT = 1_000
MAX_CAPTION_TRACKS = 32
CAPTION_PROBE_BYTES = 128_000
CAPTION_TOOL_TIMEOUT = 15.0
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_DIRECT_SUFFIXES = frozenset({".srt", ".vtt"})
_CONVERTIBLE_SUFFIXES = frozenset({".ass", ".ssa", ".sub"})
_TEXT_CODECS = frozenset({"ass", "ssa", "subrip", "srt", "text", "webvtt", "mov_text"})
_TIMESTAMP = re.compile(r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})[,.](\d{1,3})")
_TAG = re.compile(r"<[^>]{1,200}>")


class CaptionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CaptionCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True, slots=True)
class CaptionTrack:
    label: str
    cues: tuple[CaptionCue, ...]
    starts: tuple[float, ...]
    source: str = "manual"

    def cue_at(self, seconds: float) -> str | None:
        index = bisect.bisect_right(self.starts, seconds) - 1
        if index < 0:
            return None
        cue = self.cues[index]
        return cue.text if cue.start <= seconds < cue.end else None


def _seconds(value: str) -> float:
    parts = value.strip().split()
    match = _TIMESTAMP.fullmatch(parts[0]) if parts else None
    if not match:
        raise CaptionError("Caption timing is invalid")
    hours, minutes, seconds, fraction = match.groups()
    if int(minutes) >= 60 or int(seconds) >= 60:
        raise CaptionError("Caption timing is invalid")
    milliseconds = int(fraction.ljust(3, "0")[:3])
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + milliseconds / 1000


def _plain_text(lines: list[str]) -> str:
    text = "\n".join(lines).strip()
    text = html.unescape(_TAG.sub("", text))
    text = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    text = "".join(character for character in text if character in "\n\t" or ord(character) >= 32)
    return text[:MAX_CUE_TEXT].strip()


def _safe_label(value: str) -> str:
    label = "".join(character for character in value if ord(character) >= 32)
    label = " ".join(label.replace("\\", " ").replace("/", " ").split())[:120]
    if re.search(r"(?i)https?:|[a-z]:", label):
        return "Captions"
    return label or "Captions"


def parse_captions(value: str, *, label: str = "Captions", source: str = "manual") -> CaptionTrack:
    """Parse SRT or WebVTT into sorted, bounded, immutable cues."""
    blocks = re.split(r"\r?\n\s*\r?\n", value.lstrip("\ufeff").strip())
    cues: list[CaptionCue] = []
    for block in blocks:
        lines = block.splitlines()
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        start_value, end_value = lines[timing_index].split("-->", 1)
        start, end = _seconds(start_value), _seconds(end_value)
        text = _plain_text(lines[timing_index + 1 :])
        if end <= start or not text:
            continue
        cues.append(CaptionCue(start, end, text))
        if len(cues) > MAX_CAPTION_CUES:
            raise CaptionError("Caption file contains too many cues")
    if not cues:
        raise CaptionError("Caption file contains no usable timed cues")
    cues.sort(key=lambda cue: (cue.start, cue.end))
    safe_label = _safe_label(label)
    result = tuple(cues)
    safe_source = source if source in {"manual", "sidecar", "embedded", "provider", "provider-generated"} else "manual"
    return CaptionTrack(safe_label, result, tuple(cue.start for cue in result), safe_source)


def load_captions(path: str | Path, *, label: str | None = None, source: str = "manual") -> CaptionTrack:
    try:
        caption_path = Path(path).expanduser().resolve(strict=True)
    except OSError:
        raise CaptionError("Choose an existing .srt or .vtt caption file") from None
    if not caption_path.is_file() or caption_path.suffix.casefold() not in {".srt", ".vtt"}:
        raise CaptionError("Choose an existing .srt or .vtt caption file")
    size = caption_path.stat().st_size
    if not 0 < size <= MAX_CAPTION_BYTES:
        raise CaptionError("Caption file must be between 1 byte and 2 MiB")
    try:
        with caption_path.open("rb") as stream:
            data = stream.read(MAX_CAPTION_BYTES + 1)
        if len(data) > MAX_CAPTION_BYTES:
            raise CaptionError("Caption file exceeds 2 MiB")
        value = data.decode("utf-8-sig")
    except (OSError, UnicodeError):
        raise CaptionError("Caption file must be readable UTF-8 text") from None
    return parse_captions(value, label=label or caption_path.name, source=source)


def matching_sidecars(media_path: str | Path) -> tuple[Path, ...]:
    """Return bounded same-basename text sidecars, with exact matches first."""
    media = Path(media_path).resolve(strict=True)
    if not media.is_file():
        return ()
    supported = _DIRECT_SUFFIXES | _CONVERTIBLE_SUFFIXES
    candidates: list[Path] = []
    try:
        entries = list(islice(media.parent.iterdir(), 1_024))
    except OSError:
        return ()
    for entry in entries:
        suffix = entry.suffix.casefold()
        stem = entry.stem.casefold()
        if (suffix not in supported or not entry.is_file()
                or (stem != media.stem.casefold() and not stem.startswith(media.stem.casefold() + "."))):
            continue
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        if 0 < size <= MAX_CAPTION_BYTES:
            resolved = entry.resolve()
            if resolved.parent != media.parent.resolve() or entry.is_symlink():
                continue
            candidates.append(resolved)
    candidates.sort(key=lambda path: (
        path.stem.casefold() != media.stem.casefold(),
        0 if path.suffix.casefold() == ".srt" else 1,
        path.name.casefold(),
    ))
    return tuple(candidates[:MAX_CAPTION_TRACKS])


def _run_caption_tool(command: list[str], output: Path, cancel: threading.Event) -> bool:
    process = subprocess.Popen(
        command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=CREATE_NO_WINDOW,
    )
    deadline = time.monotonic() + CAPTION_TOOL_TIMEOUT
    try:
        while process.poll() is None:
            if cancel.wait(0.05) or time.monotonic() > deadline:
                return False
        return process.returncode == 0 and output.is_file() and 0 < output.stat().st_size <= MAX_CAPTION_BYTES
    except OSError:
        return False
    finally:
        if process.poll() is None:
            with contextlib.suppress(OSError):
                process.terminate()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=1)
            if process.poll() is None:
                with contextlib.suppress(OSError):
                    process.kill()
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    process.wait(timeout=1)


def _caption_probe(command: list[str], cancel: threading.Event) -> bytes | None:
    """Bound stdout while receiving it; cancellation never waits for the probe timeout."""
    if cancel.is_set():
        return None
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
    assert process.stdout is not None
    stream = process.stdout
    done = threading.Event()
    received = bytearray()
    errors: list[OSError] = []

    def read() -> None:
        try:
            while len(received) <= CAPTION_PROBE_BYTES:
                chunk = stream.read(min(8192, CAPTION_PROBE_BYTES + 1 - len(received)))
                if not chunk:
                    break
                received.extend(chunk)
        except OSError as error:
            errors.append(error)
        finally:
            done.set()

    reader = threading.Thread(target=read, name="mariana-caption-probe-output", daemon=True)
    deadline = time.monotonic() + CAPTION_TOOL_TIMEOUT
    try:
        reader.start()
        while not done.wait(0.025):
            if cancel.is_set() or time.monotonic() >= deadline:
                return None
        if cancel.is_set() or errors or len(received) > CAPTION_PROBE_BYTES:
            return None
        while process.poll() is None:
            if cancel.wait(0.025) or time.monotonic() >= deadline:
                return None
        return bytes(received) if process.returncode == 0 and not cancel.is_set() else None
    finally:
        if process.poll() is None:
            with contextlib.suppress(OSError):
                process.terminate()
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                process.wait(timeout=1)
            if process.poll() is None:
                with contextlib.suppress(OSError):
                    process.kill()
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    process.wait(timeout=1)
        if reader.ident is not None:
            reader.join(timeout=1)
        if not reader.is_alive():
            stream.close()


def _converted_track(
    source_path: Path | str,
    output_directory: Path,
    ffmpeg_bin: str,
    cancel: threading.Event,
    *,
    stream_index: int | None = None,
    label: str,
    origin: str,
) -> CaptionTrack | None:
    output_directory.mkdir(parents=True, exist_ok=True)
    output = output_directory / f"caption-{secrets.token_hex(12)}.srt"
    command = [
        ffmpeg_bin, "-nostdin", "-hide_banner", "-loglevel", "error",
        "-protocol_whitelist", "file,pipe,http,tcp", "-i", str(source_path),
    ]
    command += ["-map", f"0:{stream_index}" if stream_index is not None else "0:s:0"]
    command += ["-c:s", "srt", "-fs", str(MAX_CAPTION_BYTES), "-f", "srt", "-n", str(output)]
    try:
        if not _run_caption_tool(command, output, cancel):
            return None
        return load_captions(output, label=label, source=origin)
    except (CaptionError, OSError):
        return None
    finally:
        with contextlib.suppress(OSError):
            output.unlink(missing_ok=True)


def _embedded_tracks(media: Path | str, ffprobe_bin: str, cancel: threading.Event) -> list[dict[str, object]]:
    if cancel.is_set():
        return []
    try:
        result = _caption_probe(
            [ffprobe_bin, "-v", "error", "-protocol_whitelist", "file,pipe,http,tcp",
             "-select_streams", "s", "-show_entries",
             "stream=index,codec_name:stream_tags=language,title:stream_disposition=default,forced",
             "-of", "json", str(media)],
            cancel,
        )
        if cancel.is_set() or result is None:
            return []
        payload = json.loads(result)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return []
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        return []
    usable = [row for row in streams if isinstance(row, dict)
              and row.get("codec_name") in _TEXT_CODECS and type(row.get("index")) is int]
    usable.sort(key=lambda row: (
        not bool((row.get("disposition") or {}).get("default")) if isinstance(row.get("disposition"), dict) else True,
        not bool((row.get("disposition") or {}).get("forced")) if isinstance(row.get("disposition"), dict) else True,
        int(row["index"]),
    ))
    return usable[:MAX_CAPTION_TRACKS]


def autodetect_local_captions(
    media_path: str | Path,
    output_directory: str | Path,
    *,
    ffprobe_bin: str,
    ffmpeg_bin: str,
    cancel: threading.Event,
) -> CaptionTrack | None:
    """Load a matching sidecar or preferred embedded text track without blocking playback."""
    try:
        media = Path(media_path).resolve(strict=True)
    except OSError:
        return None
    for sidecar in matching_sidecars(media):
        if cancel.is_set():
            return None
        if sidecar.suffix.casefold() in _DIRECT_SUFFIXES:
            try:
                return load_captions(sidecar, source="sidecar")
            except CaptionError:
                continue
        converted = _converted_track(
            sidecar, Path(output_directory), ffmpeg_bin, cancel,
            label=sidecar.name, origin="sidecar",
        )
        if converted is not None:
            return converted
    return autodetect_embedded_captions(
        media, output_directory, ffprobe_bin=ffprobe_bin, ffmpeg_bin=ffmpeg_bin, cancel=cancel,
    )


def autodetect_embedded_captions(
    media_input: str | Path,
    output_directory: str | Path,
    *,
    ffprobe_bin: str,
    ffmpeg_bin: str,
    cancel: threading.Event,
) -> CaptionTrack | None:
    """Extract the preferred embedded text track from a bounded media input."""
    for row in _embedded_tracks(media_input, ffprobe_bin, cancel):
        raw_tags = row.get("tags")
        tags: dict[str, object] = raw_tags if isinstance(raw_tags, dict) else {}
        stream_index = row.get("index")
        if type(stream_index) is not int:
            continue
        title = " ".join(str(tags.get("title") or "").split())[:80]
        language = " ".join(str(tags.get("language") or "").split())[:24]
        label = title or "Embedded subtitles"
        if language and f"[{language.casefold()}]" not in label.casefold():
            label = f"{label} [{language}]"
        converted = _converted_track(
            media_input, Path(output_directory), ffmpeg_bin, cancel,
            stream_index=stream_index, label=label, origin="embedded",
        )
        if converted is not None:
            return converted
    return None


_LANGUAGE_ALIASES = {
    "en": "eng", "fr": "fra", "fre": "fra", "de": "deu", "ger": "deu",
    "es": "spa", "hi": "hin", "ar": "ara", "ja": "jpn", "ko": "kor",
    "zh": "zho", "chi": "zho", "pt": "por", "it": "ita", "ru": "rus",
    "ta": "tam", "te": "tel", "bn": "ben", "ur": "urd",
}


def caption_language(value: str) -> str:
    """Normalize common two/three-letter equivalents, retaining region subtags."""
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", value):
        raise CaptionError("Use language codes such as en, eng, hi or pt-BR")
    base, separator, region = value.partition("-")
    return _LANGUAGE_ALIASES.get(base, base) + (separator + region if separator else "")


def caption_languages(values: object) -> tuple[str, ...]:
    if not isinstance(values, (list, tuple)) or len(values) > 5 or any(not isinstance(v, str) for v in values):
        raise CaptionError("Choose at most five preferred caption languages")
    return tuple(dict.fromkeys(caption_language(value) for value in values))


def caption_source_signature(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha256(f"{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CaptionCandidate:
    key: str
    label: str
    language: str | None
    source: str
    default: bool
    forced: bool
    codec: str
    path: Path
    signature: str
    stream_index: int | None = None

    def projection(self) -> dict[str, object]:
        return {"id": self.key, "label": self.label, "language": self.language,
                "source": self.source, "default": self.default, "forced": self.forced, "codec": self.codec}


def discover_caption_tracks(media: Path, ffprobe_bin: str, cancel: threading.Event) -> tuple[CaptionCandidate, ...]:
    """Inspect alternatives without decoding every subtitle track or exposing paths."""
    signature = caption_source_signature(media)
    candidates: list[CaptionCandidate] = []
    for path in matching_sidecars(media):
        if cancel.is_set():
            return ()
        suffix = path.stem[len(media.stem):].lstrip(".").lower()
        language = None
        with contextlib.suppress(CaptionError):
            language = caption_language(suffix.split(".")[0])
        forced = "forced" in suffix.split(".")
        sidecar_signature = caption_source_signature(path)
        key = hashlib.sha256(f"sidecar:{suffix}:{path.suffix}:{sidecar_signature}".encode()).hexdigest()[:32]
        label = "Sidecar subtitles" + (f" [{language}]" if language else "")
        if forced:
            label += " (forced)"
        candidates.append(CaptionCandidate(key, label, language, "sidecar", not suffix, forced,
                                           path.suffix[1:].lower(), path, sidecar_signature))
    for row in _embedded_tracks(media, ffprobe_bin, cancel):
        tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
        assert isinstance(tags, dict)
        disposition = row.get("disposition") if isinstance(row.get("disposition"), dict) else {}
        assert isinstance(disposition, dict)
        language = None
        with contextlib.suppress(CaptionError):
            language = caption_language(str(tags.get("language", "")))
        label = _safe_label(str(tags.get("title") or "Embedded subtitles"))
        if language:
            label = _safe_label(f"{label[:90]} [{language}]")
        index = int(str(row["index"]))
        codec = str(row["codec_name"])
        key = hashlib.sha256(f"embedded:{index}:{codec}:{language}:{label}".encode()).hexdigest()[:32]
        candidates.append(CaptionCandidate(key, label, language, "embedded", bool(disposition.get("default")),
                                           bool(disposition.get("forced")), codec, media, signature, index))
    if cancel.is_set() or caption_source_signature(media) != signature:
        return ()
    return tuple(candidates[:MAX_CAPTION_TRACKS])


def rank_caption_tracks(tracks: tuple[CaptionCandidate, ...], languages: tuple[str, ...]) -> tuple[CaptionCandidate, ...]:
    def rank(track: CaptionCandidate) -> tuple[int, int, bool, bool]:
        language_rank = len(languages) * 2 + 1
        for index, language in enumerate(languages):
            if track.language == language:
                language_rank = index * 2
                break
            if track.language and track.language.split("-")[0] == language.split("-")[0]:
                language_rank = index * 2 + 1
                break
        return language_rank, 0 if track.source == "sidecar" else 1, not track.default, not track.forced
    return tuple(sorted(tracks, key=rank))


def load_caption_candidate(
    candidate: CaptionCandidate, output: Path, ffmpeg_bin: str, cancel: threading.Event,
) -> CaptionTrack | None:
    try:
        if cancel.is_set() or caption_source_signature(candidate.path) != candidate.signature:
            return None
        if candidate.source == "sidecar" and candidate.path.suffix.lower() in _DIRECT_SUFFIXES:
            track = load_captions(candidate.path, label=candidate.label, source="sidecar")
        else:
            track = _converted_track(candidate.path, output, ffmpeg_bin, cancel,
                                     stream_index=candidate.stream_index, label=candidate.label, origin=candidate.source)
        if cancel.is_set() or caption_source_signature(candidate.path) != candidate.signature:
            return None
        return track
    except (CaptionError, OSError):
        return None


class CaptionPreferences:
    """Bounded settings snapshot: only hashed media keys/selectors, no file paths."""

    def __init__(self, value: object = None, save: Callable[[dict], None] | None = None) -> None:
        self._lock = threading.RLock()
        self._save = save or (lambda _value: None)
        section = value if isinstance(value, Mapping) else {}
        try:
            self.languages = caption_languages(section.get("preferred languages", []))
        except CaptionError:
            self.languages = ()
        self._choices: dict[str, dict] = {}
        choices = section.get("media choices", {})
        if isinstance(choices, Mapping):
            for key, choice in list(choices.items())[-128:]:
                if (isinstance(key, str) and re.fullmatch(r"[a-f0-9]{64}", key) and isinstance(choice, dict)
                        and isinstance(choice.get("signature"), str) and re.fullmatch(r"[a-f0-9]{64}", choice["signature"])
                        and isinstance(choice.get("track"), str) and re.fullmatch(r"[a-f0-9]{32}", choice["track"])
                        and type(choice.get("enabled")) is bool and type(choice.get("offset_ms")) is int
                        and -60000 <= choice["offset_ms"] <= 60000):
                    self._choices[key] = {field: choice[field] for field in ("signature", "track", "enabled", "offset_ms")}

    @staticmethod
    def _key(media_id: str) -> str:
        return hashlib.sha256(media_id.encode()).hexdigest()

    def get(self, media_id: str) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._choices.get(self._key(media_id)))

    def _commit(self, languages: tuple[str, ...], choices: dict[str, dict]) -> None:
        try:
            self._save({"preferred languages": list(languages), "media choices": copy.deepcopy(choices)})
        except Exception:
            raise CaptionError("Caption preferences could not be saved") from None
        self.languages, self._choices = languages, choices

    def set_languages(self, values: object) -> None:
        languages = caption_languages(values)
        with self._lock:
            self._commit(languages, dict(self._choices))

    def remember(self, media_id: str, signature: str, track: str, enabled: bool, offset_ms: int) -> None:
        with self._lock:
            choices = dict(self._choices)
            key = self._key(media_id)
            choices.pop(key, None)
            choices[key] = {"signature": signature, "track": track, "enabled": enabled, "offset_ms": offset_ms}
            self._commit(self.languages, dict(list(choices.items())[-128:]))

    def forget(self, media_id: str) -> None:
        with self._lock:
            choices = dict(self._choices)
            choices.pop(self._key(media_id), None)
            self._commit(self.languages, choices)
