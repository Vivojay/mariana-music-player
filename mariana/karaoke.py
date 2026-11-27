"""Content-bound, whole-recording word timing for duet and group practice."""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
import unicodedata
from bisect import bisect_right
from pathlib import Path

SCHEMA = "mariana.karaoke.v1"
THRESHOLD = 0.9
MAX_BYTES = 2 * 1024 * 1024
MAX_MS = 86_400_000
USAGE = ("karaoke status | demo | start | stop | current | singers | part NAME|all | "
         "previous | next | import FILE | export FILE | compare SCORE.ttml ALIGNMENT.ttml | clear | vocals on|off | invite FILE [SINGER] | open FILE | accept")


def _label(value, limit):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)):
        raise ValueError("The sheet contains missing, oversized or non-printable text.")
    return value.strip()


def _time(value):
    if type(value) is not int or not 0 <= value <= MAX_MS:
        raise ValueError("Karaoke timestamps must be whole milliseconds within one day.")
    return value


def _confidence(value):
    if type(value) not in (float, int) or not 0 <= value <= 1:
        raise ValueError("The sheet needs numeric whole-recording and per-word confidence from 0 to 1.")
    return value


def _entries(value, maximum, minimum=0):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError("Karaoke sheet has an invalid number of segments, voices or words.")
    return value


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid karaoke sheet object.")
    return value


class Score:
    def __init__(self, value):
        data = _object(value)
        if data.get("schema") != SCHEMA:
            raise ValueError("A mariana.karaoke.v1 word-timed sheet is required.")
        if not isinstance(data.get("media_sha256"), str) or not re.fullmatch("[a-f0-9]{64}", data["media_sha256"]):
            raise ValueError("The sheet has no valid recording SHA-256.")
        self.digest = data["media_sha256"]
        self.duration = _time(data.get("duration_ms"))
        self.source = _label(data.get("source"), 180)
        self.score = _confidence(data.get("confidence"))
        self.data = {key: data[key] for key in ("schema", "media_sha256", "duration_ms", "confidence")}
        self.data.update(source=self.source, segments=[])
        self.starts = []
        self.sung_starts = []
        self.singers = []
        previous = 0
        for entry in _entries(data.get("segments"), 10000, 1):
            segment = _object(entry)
            start, end = _time(segment.get("start_ms")), _time(segment.get("end_ms"))
            if start != previous or end <= start or end > self.duration:
                raise ValueError("Every millisecond must be covered once. Mark interludes with empty voices.")
            previous = end
            self.starts.append(start)
            voices = []
            seen = set()
            for item in _entries(segment.get("voices"), 16):
                voice = _object(item)
                singer = _label(voice.get("singer"), 80)
                if singer in seen:
                    raise ValueError("A singer may appear only once in each segment.")
                seen.add(singer)
                words = []
                latest = start
                for item_word in _entries(voice.get("words"), 512, 1):
                    word = _object(item_word)
                    on, off = _time(word.get("start_ms")), _time(word.get("end_ms"))
                    if not latest <= on < off <= end:
                        raise ValueError("Overlapping or out-of-range word times in one singer's part.")
                    latest = off
                    number = _confidence(word.get("confidence"))
                    self.score = min(self.score, number)
                    words.append(dict(start_ms=on, end_ms=off, text=_label(word.get("text"), 128), confidence=number))
                if singer not in self.singers:
                    self.singers.append(singer)
                voices.append({"singer": singer, "words": words})
            if voices:
                self.sung_starts.append(start)
            self.data["segments"].append({"start_ms": start, "end_ms": end, "voices": voices})
        if previous != self.duration or not self.sung_starts:
            raise ValueError("The sheet must cover the complete recording and contain timed words.")

    def reason(self, digest, duration_ms):
        if self.digest != digest:
            return "This timing sheet belongs to a different recording (SHA-256 mismatch)."
        if duration_ms is None:
            return "Waiting for a finite playback duration to check whole-recording coverage."
        if abs(self.duration - duration_ms) > 250:
            return "The sheet duration differs from the loaded recording by more than 250 ms."
        if self.score < THRESHOLD:
            return f"Whole-recording confidence {math.floor(self.score * 10000) / 100:.2f}% is below the required 90%."
        return ""

    def segment(self, position):
        index = bisect_right(self.starts, position) - 1
        return self.data["segments"][index] if index >= 0 and position < self.duration else None

    def seek_line(self, position, next_line):
        if next_line:
            index = bisect_right(self.sung_starts, position)
        else:
            index = bisect_right(self.sung_starts, position - 1) - 1
        if not 0 <= index < len(self.sung_starts):
            raise ValueError("There are no more lyric lines in this direction.")
        return self.sung_starts[index]


def read_score(path):
    try:
        if not path.is_file():
            raise ValueError("Choose an existing karaoke sheet file.")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("The karaoke sheet exceeds the 2 MiB limit.")
        return Score(json.loads(raw.decode("utf-8-sig")))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError(f"Could not read the karaoke sheet: {error}") from error


def _stamp(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _sidecar(path):
    sidecar = path.with_name(path.name + ".karaoke.json")
    return sidecar if sidecar.is_file() else None


class KaraokeSession:
    def __init__(self, database):
        self.database = database
        self._lock = threading.RLock()
        self.binding = self.sheet_stamp = self.sheet = self.part = None
        self.digest = ""
        self.load_error = ""
        self._performance = None
        self._invitation = None

    def begin_stage(self):
        with self._lock:
            if self._performance is not None:
                raise ValueError("The karaoke stage is already open.")
            self._performance = threading.Event()
            return self._performance

    def end_stage(self, performance):
        with self._lock:
            if self._performance is performance:
                self._performance = None

    def stop(self):
        with self._lock:
            if self._performance is None:
                return False
            self._performance.set()
            return True

    def _bind(self, snapshot):
        media = snapshot.media
        if media is None:
            raise ValueError("Load a recording first.")
        if media.source != "local" or media.capabilities.live:
            raise ValueError("Karaoke needs a finite local recording to verify the exact audio.")
        path = Path(media.original_uri)
        if not path.is_file():
            raise ValueError("The local recording is unavailable.")
        stamp = _stamp(path)
        binding = (media.stable_id, str(path), stamp)
        if self.binding != binding:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if stamp != _stamp(path):
                raise ValueError("The recording changed during verification. Reload it and try again.")
            self.binding, self.digest = binding, digest
            self.sheet_stamp = self.sheet = self.part = None
        adjacent = _sidecar(path)
        sheet_stamp = (self.digest, _stamp(adjacent) if adjacent else None)
        if sheet_stamp != self.sheet_stamp:
            self.sheet = None
            self.load_error = ""
            data = self.database.get_state("karaoke.score." + self.digest)
            try:
                if isinstance(data, dict):
                    self.sheet = Score(data)
                elif data is None and adjacent:
                    self.sheet = read_score(adjacent)
            except ValueError as error:
                self.load_error = str(error)
            self.sheet_stamp = sheet_stamp
        duration = snapshot.duration or media.duration
        duration_ms = round(duration * 1000) if duration and math.isfinite(duration) and duration > 0 else None
        return duration_ms

    def stage(self, snapshot, *, include_sheet=False):
        position = snapshot.position
        state = dict(media_id=snapshot.media.stable_id if snapshot.media else None, available=False,
                     score=None, source="", reason="", threshold=THRESHOLD, sheet=None, state=str(snapshot.state),
                     position_ms=int(max(0, position) * 1000 + 0.5) if position and math.isfinite(position) else 0)
        with self._lock:
            try:
                duration = self._bind(snapshot)
                if self.sheet is None:
                    raise ValueError(self.load_error or
                                     "No word-timed sheet with whole-recording confidence. Use karaoke import or karaoke demo.")
                reason = self.sheet.reason(self.digest, duration)
                state["score"] = self.sheet.score
                state["source"] = self.sheet.source
                if reason:
                    raise ValueError(reason)
                state["available"] = True
                if include_sheet:
                    state["sheet"] = self.sheet.data
            except (OSError, ValueError) as error:
                state["reason"] = str(error)
        return state

    def install(self, snapshot, score):
        with self._lock:
            duration = self._bind(snapshot)
            if self.digest != score.digest:
                raise ValueError("Cannot import a sheet for a different recording.")
            if duration is not None and abs(duration - score.duration) > 250:
                raise ValueError("Cannot import a sheet with a mismatched duration.")
            self.database.set_state("karaoke.score." + self.digest, score.data)
            self.sheet_stamp = self.sheet = self.part = None

    def lyrics(self, snapshot, imported=None):
        with self._lock:
            duration = self._bind(snapshot)
            key = "karaoke.lyrics." + self.digest
            if imported is not None:
                self.database.set_state(key, imported)
            rows = self.database.get_state(key)
            if rows:
                return rows
            if self.sheet and self.sheet.digest == self.digest and duration is not None and abs(self.sheet.duration - duration) <= 250:
                return [(voice["singer"], " ".join(word["text"] for word in voice["words"]))
                        for segment in self.sheet.data["segments"] for voice in segment["voices"]]
            raise ValueError("Use lyrics voices FILE.ttml to load vocalist-labelled text.")

    def recording(self, snapshot):
        with self._lock:
            duration = self._bind(snapshot)
            return self.digest, duration

    def forget(self, snapshot):
        with self._lock:
            self._bind(snapshot)
            self.database.set_state("karaoke.score." + self.digest, False)
            self.sheet_stamp = self.sheet = self.part = None

    def active(self, snapshot):
        with self._lock:
            stage = self.stage(snapshot)
            if not stage["available"]:
                raise ValueError(stage["reason"])
            return self.sheet, stage["position_ms"]

    def export_invite(self, snapshot, path, name=None):
        from .karaoke_invite import practice_invite
        with self._lock:
            score, position = self.active(snapshot)
            part = self.part if name is None else (None if name.casefold() == "all" else name)
            invitation = practice_invite(score, part, position)
            with path.open("x", encoding="utf-8") as stream:
                json.dump(invitation, stream, ensure_ascii=False, indent=2)
            return invitation

    def open_invite(self, snapshot, path):
        from .karaoke_invite import read_invite, verify_invite
        with self._lock:
            self._invitation = None
            invite = read_invite(path)
            score, _ = self.active(snapshot)
            verify_invite(invite, score)
            self._invitation = invite
            return dict(invite)

    def accept_invite(self, snapshot, seek):
        from .karaoke_invite import verify_invite
        with self._lock:
            if self._invitation is None:
                raise ValueError("Preview a matching duet invitation with karaoke open FILE first.")
            score, _ = self.active(snapshot)
            invite = self._invitation
            verify_invite(invite, score)
            seek(invite["start_ms"] / 1000)
            self.part = invite["part"]
            self._invitation = None
            return dict(invite)

    def select(self, snapshot, name):
        with self._lock:
            score, _ = self.active(snapshot)
            if name.casefold() == "all":
                self.part = None
            elif name in score.singers:
                self.part = name
            else:
                raise ValueError("Choose a part from karaoke singers.")
            return self.part
