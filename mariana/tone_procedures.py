"""Stored finite scores for Mariana's ordinary local audio transport."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

RATE = 32_000
TABLE_SIZE = 2048
MAX_SECONDS = 90
MAX_TRACKS = 4
HELP = """tone procedure play twinkle [--bpm 100] [--chorus 38] [--level 32]
tone procedure list | tone voices | tone sfx list
tone procedure save my-theme 96 @felt-keys C5 G5 E5:2 @choir C4+E4+G4:4 --chorus 32
tone synth glass C4+E4+G4:2 R A4 | tone sfx footstep
Durations are in beats. R is a rest. Start a simultaneous part with @voice."""
FAMILIES = ("procedure", "voices", "synth", "sfx")
BANK = json.loads(Path(__file__).with_name("tone_bank.json").read_text(encoding="utf-8"))
VOICES = BANK["voices"]
NOTE = re.compile(r"([A-Ga-g])([#b]?)([0-8])\Z")
LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def number(value, lower, upper, label):
    if not re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)", str(value)):
        raise ValueError(f"Choose {label} between {lower} and {upper}.")
    result = float(value)
    if not lower <= result <= upper:
        raise ValueError(f"Choose {label} between {lower} and {upper}.")
    return result


@dataclass(frozen=True)
class Note:
    start: int
    length: int
    pitches: tuple[int, ...]


@dataclass(frozen=True)
class Part:
    voice: str
    gain: float
    notes: tuple[Note, ...]


@dataclass(frozen=True)
class Procedure:
    title: str
    parts: tuple[Part, ...]
    frames: int
    chorus: float
    level: float

    @property
    def seconds(self):
        return self.frames / RATE


def compile_score(score, options):
    bpm = number(options.get("--bpm", score["bpm"]), 30, 300, "tempo")
    chorus = number(options.get("--chorus", score.get("chorus", 0)), 0, 100, "chorus")
    level = number(options.get("--level", 32), 0, 100, "level")
    tracks = score["tracks"]
    if not 1 <= len(tracks) <= MAX_TRACKS:
        raise ValueError("Use one to four @voice parts.")
    parts, frames = [], 0
    for track in tracks:
        name, tokens = track["voice"], track["score"].split()
        if name not in VOICES or not 1 <= len(tokens) <= 128:
            raise ValueError("Choose a voice from 'tone voices' and 1 to 128 steps per part.")
        notes, beat = [], 0.
        for token in tokens:
            chord, sep, duration = token.partition(":")
            length = number(duration if sep else 1, .0625, 16, "step length")
            pitches = []
            if chord.upper() != "R":
                for key in chord.split("+"):
                    match = NOTE.fullmatch(key)
                    if not match or len(pitches) >= 6:
                        raise ValueError(f"Invalid note or chord: {token}. Try C4+Eb4+G4:2 or R.")
                    letter, accidental, octave = match.groups()
                    pitches.append(12 * (int(octave) + 1) + LETTERS[letter.upper()] + {"": 0, "#": 1, "b": -1}[accidental])
            start = round(beat * 60 / bpm * RATE)
            beat += length
            end = round(beat * 60 / bpm * RATE)
            if end > MAX_SECONDS * RATE:
                raise ValueError("A procedure may last up to 90 seconds.")
            notes.append(Note(start, end-start, tuple(pitches)))
        parts.append(Part(name, float(track.get("gain", .7)), tuple(notes)))
        frames = max(frames, end)
    return Procedure(score["title"], tuple(parts), frames, chorus, level)


def _score(name, bpm, words):
    tracks = []
    for word in words:
        if word.startswith("@"):
            tracks.append({"voice": word[1:].lower(), "score": [], "gain": .72})
        else:
            if not tracks:
                tracks.append({"voice": "felt-keys", "score": [], "gain": .72})
            tracks[-1]["score"].append(word)
    for track in tracks:
        track["score"] = " ".join(track["score"])
    return {"title": name, "bpm": bpm, "tracks": tracks}


def _options(args):
    words, options = [], {}
    tokens = iter(args)
    for word in tokens:
        if not word.startswith("--"):
            words.append(word)
        else:
            key, equals, value = word.partition("=")
            if key not in {"--bpm", "--chorus", "--level"} or key in options:
                raise ValueError(f"Unsupported or repeated tone option: {key}")
            options[key] = value if equals else next(tokens, "")
    return words, options


def _library(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.execute("CREATE TABLE IF NOT EXISTS procedures (id TEXT PRIMARY KEY, score TEXT NOT NULL)")
    return connection


def _slug(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", value):
        raise ValueError("Use 1–40 lower-case letters, digits and hyphens for a procedure name.")
    return value


def procedure_names(library, prefix="", limit=None):
    builtins = [name for name in BANK["procedures"] if name.startswith(prefix)]
    if library is None or not library.is_file():
        return builtins
    # Completion is read-only and scoped to the current profile.
    if prefix and not re.fullmatch(r"[a-z0-9-]+", prefix):
        return []
    db = sqlite3.connect(library.resolve().as_uri() + "?mode=ro", uri=True, timeout=.15)
    try:
        return [*builtins, *(row[0] for row in db.execute(
            "SELECT id FROM procedures WHERE id LIKE ? ORDER BY id LIMIT ?", (prefix+"%", limit or -1)))]
    finally:
        db.close()


def command(args, library):
    words, options = _options(args)
    command_name = words.pop(0).lower()
    if command_name == "voices" and not words and not options:
        return ", ".join(VOICES)
    if command_name == "synth" and len(words) >= 2:
        return compile_score(_score(words[0], 100, ["@" + words[0], *words[1:]]), options)
    if command_name == "sfx":
        if words in ([], ["list"]) and not options:
            return ", ".join(BANK["sfx"])
        if len(words) == 1 and words[0] in BANK["sfx"]:
            name = words[0]
            return compile_score(_score(name, 100, ["@" + name, BANK["sfx"][name]]), options)
    if command_name != "procedure":
        raise ValueError(HELP)
    action = words.pop(0).lower() if words else "list"
    builtins = BANK["procedures"]
    if action == "list" and not words and not options:
        return ", ".join(procedure_names(library))
    if action == "play" and len(words) == 1:
        key = _slug(words[0])
        score = builtins.get(key)
        if score is None and library.is_file():
            db = _library(library)
            try:
                row = db.execute("SELECT score FROM procedures WHERE id=?", (key,)).fetchone()
            finally:
                db.close()
            if row:
                score = json.loads(row[0])
        if score is None:
            raise ValueError("Unknown procedure. Use 'tone procedure list'.")
        return compile_score(score, options)
    if action == "save" and len(words) >= 3:
        key = _slug(words[0])
        if key in builtins or "--level" in options or "--bpm" in options:
            raise ValueError("Use a new name, a positional tempo, and optional --chorus when saving.")
        score = _score(key, words[1], words[2:])
        score["chorus"] = number(options.get("--chorus", 0), 0, 100, "chorus")
        compile_score(score, {})
        db = _library(library)
        try:
            with db:
                db.execute("INSERT INTO procedures VALUES (?, ?)", (key, json.dumps(score)))
        except sqlite3.IntegrityError:
            raise ValueError("This procedure name already exists. Choose a new name.") from None
        finally:
            db.close()
        return f"Saved {key}. Play it with tone procedure play {key}."
    raise ValueError(HELP)


@lru_cache(maxsize=512)
def _table(voice, partial_count):
    partials = VOICES[voice]["partials"][:partial_count]
    phase = np.arange(TABLE_SIZE + 1) * (2 * np.pi / TABLE_SIZE)
    return sum(amp * np.sin((i+1) * phase) for i, amp in enumerate(partials)) / sum(partials)


def write_procedure(path, procedure):
    mix = np.zeros(procedure.frames, dtype=np.float32)
    for part in procedure.parts:
        voice = VOICES[part.voice]
        for step in part.notes:
            if not step.pitches:
                continue
            samples = np.arange(step.length)
            t = samples / RATE
            envelope = np.minimum(1, t/voice["attack"]) * (
                voice["sustain"] + (1-voice["sustain"]) * np.exp(-np.maximum(0, t-voice["attack"])/voice["decay"]))
            envelope *= np.clip((step.length-1-samples)/(RATE*min(voice["release"], step.length/RATE*.35)), 0, 1)
            signal = np.zeros(step.length)
            for midi in step.pitches:
                hz = 440 * 2**((midi-69)/12)
                bend = voice["bend"] * math.log(2) / (12 * step.length / RATE)
                phase = hz * (np.expm1(t * bend) / bend if bend else t)
                highest = hz * max(1, 2**(voice["bend"]/12))
                count = min(len(voice["partials"]), int(.48 * RATE / highest))
                if count:
                    table = _table(part.voice, count)
                    x = (phase % 1) * TABLE_SIZE
                    i = x.astype(np.int32)
                    signal += table[i] + (table[i+1]-table[i]) * (x-i)
            signal /= len(step.pitches)
            wet = voice["noise"]
            if wet:
                # Fixed seed makes saved foley cues reproducible on replay.
                rng = np.random.default_rng(step.start + step.pitches[0])
                signal = signal*(1-wet) + rng.uniform(-1,1,step.length)*wet
            mix[step.start:step.start + step.length] += signal * envelope * part.gain
    peaks = max(1., float(np.max(np.abs(mix))))
    mix *= procedure.level/(100*peaks)
    with wave.open(str(path), "wb") as target:
        target.setparams((2, 2, RATE, procedure.frames, "NONE", "not compressed"))
        for start in range(0, procedure.frames, 32768):
            indexes = np.arange(start, min(start+32768, procedure.frames))
            dry = mix[indexes]
            channels = []
            amount = procedure.chorus / 200
            for phase in (0., np.pi*.65):
                offset = RATE * (.016 + .003 * np.sin(2*np.pi*.8*indexes/RATE + phase))
                pos = indexes - offset
                lo = np.maximum(0, pos.astype(int))
                delayed = (mix[lo] + (mix[np.minimum(lo+1, procedure.frames-1)]-mix[lo])*(pos-lo)) * (pos >= 0)
                channels.append((1-amount)*dry + amount*delayed)
            target.writeframesraw(np.rint(np.column_stack(channels) * 32767).astype("<i2").tobytes())
