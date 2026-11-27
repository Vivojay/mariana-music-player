"""Portable practice cues. The shared file carries no recording, lyric text, or path."""
from __future__ import annotations

import hashlib
import json
import re

from .karaoke import _label, _time

SCHEMA = "mariana.duet-invite.v1"
KEYS = {"schema", "media_sha256", "timing_sha256", "duration_ms", "part", "start_ms"}


def _timing_digest(score):
    sequence = [score.duration, [
        [seg["start_ms"], seg["end_ms"], [
            [voice["singer"], [[word["text"], word["start_ms"], word["end_ms"]] for word in voice["words"]]]
            for voice in seg["voices"]]]
        for seg in score.data["segments"]]]
    canonical = json.dumps(sequence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def practice_invite(score, part, start_ms):
    if part is not None and part not in score.singers:
        raise ValueError("Choose a singer from karaoke singers.")
    if not 0 <= _time(start_ms) < score.duration:
        raise ValueError("Seek to a position before the end to invite someone.")
    return dict(schema=SCHEMA, media_sha256=score.digest, timing_sha256=_timing_digest(score),
                duration_ms=score.duration, part=part, start_ms=start_ms)


def read_invite(path):
    if not path.is_file():
        raise ValueError("Choose an existing duet invitation.")
    with path.open("rb") as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError("A duet invitation must be at most 4 KiB.")
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as error:
        raise ValueError("The duet invitation is not valid UTF-8 JSON.") from error
    if not isinstance(value, dict) or set(value) != KEYS or value.get("schema") != SCHEMA:
        raise ValueError("Unrecognized duet invitation fields.")
    for key in ("media_sha256", "timing_sha256"):
        if not isinstance(value[key], str) or not re.fullmatch("[a-f0-9]{64}", value[key]):
            raise ValueError("Invalid recording or timing fingerprint in the invitation.")
    if _time(value["start_ms"]) >= _time(value["duration_ms"]):
        raise ValueError("The practice cue falls outside the recording.")
    if value["part"] is not None and _label(value["part"], 80) != value["part"]:
        raise ValueError("Invalid singer name in the practice invitation.")
    return value


def verify_invite(invite, score):
    if invite["media_sha256"] != score.digest or invite["duration_ms"] != score.duration:
        raise ValueError("The invitation belongs to a different recording.")
    if invite["timing_sha256"] != _timing_digest(score):
        raise ValueError("The recording matches, but its karaoke timing or singer assignments differ.")
    if invite["part"] is not None and invite["part"] not in score.singers:
        raise ValueError("The requested singer does not exist in this score.")
