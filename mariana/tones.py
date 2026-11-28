"""Render oscillator previews for Mariana's ordinary local playback transport."""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import tone_procedures

RATE = 48_000
WAVES = ("sine", "triangle", "square", "sawtooth")
CHORDS = {
    "major": (0, 4, 7), "minor": (0, 3, 7), "fifth": (0, 7), "octave": (0, 12),
    "sus4": (0, 5, 7), "major7": (0, 4, 7, 11), "minor7": (0, 3, 7, 10),
}
TONE_HELP = """Generate a tone with the current output device and player volume.
  tone sine|triangle|square|sawtooth [Hz]     (default 440 Hz)
  tone harmony <Hz> <Hz> ...                  (2 to 8 simultaneous notes)
  tone harmony <root Hz> --chord major|minor|fifth|octave|sus4|major7|minor7
  tone sweep <start Hz> <end Hz>              (ascending or descending)
  --seconds 0.05..60    duration in seconds, default 2
  --level 0..100        generator level in percent, default 15
  --wave sine|triangle|square|sawtooth        waveform for harmony or sweep
  --curve linear|log                          sweep curve, default linear
Examples: tone square 110 --seconds 3
          tone harmony 220 277.18 329.63 --wave triangle
          tone sweep 880 110 --curve log --seconds 5
Use pause, stop, or seek during playback. Enter another tone to change frequency.""" + "\n" + tone_procedures.HELP + "\ntone keys [voice] opens a playable keyboard."


class _ToneParser(argparse.ArgumentParser):
    def error(self, message: str):
        raise ValueError(f"Tone: {message}. Use 'tone help' for examples.")


@dataclass(frozen=True)
class Tone:
    mode: str
    waveform: str
    frequencies: tuple[float, ...]
    seconds: float
    level: float
    curve: str

    @property
    def title(self) -> str:
        separator = " → " if self.mode == "sweep" else " + "
        notes = separator.join(f"{hz:g}" for hz in self.frequencies)
        return f"{self.waveform.capitalize()} {self.mode} · {notes} Hz"


def parse_tone(arguments: list[str]) -> Tone:
    parser = _ToneParser(prog="tone", add_help=False, allow_abbrev=False)
    parser.add_argument("mode", type=str.lower, choices=(*WAVES, "harmony", "sweep"))
    parser.add_argument("frequencies", nargs="*", type=float)
    parser.add_argument("--seconds", "--duration", type=float, default=2.0)
    parser.add_argument("--level", type=float, default=15.0)
    parser.add_argument("--wave", type=str.lower, choices=WAVES)
    parser.add_argument("--chord", type=str.lower, choices=tuple(CHORDS))
    parser.add_argument("--curve", type=str.lower, choices=("linear", "log"))
    args = parser.parse_intermixed_args(arguments)

    freqs = tuple(args.frequencies)
    if args.chord:
        if args.mode != "harmony" or len(freqs) != 1:
            raise ValueError("--chord needs a harmony with exactly one root frequency")
        freqs = tuple(freqs[0] * 2 ** (semitones / 12) for semitones in CHORDS[args.chord])
    if args.mode in WAVES:
        if args.wave or len(freqs) > 1:
            raise ValueError("A single tone takes one waveform and one optional frequency")
        freqs = freqs or (440.0,)
    elif args.mode == "sweep" and len(freqs) != 2:
        raise ValueError("A sweep needs a start and an end frequency")
    elif args.mode == "harmony" and not 2 <= len(freqs) <= 8:
        raise ValueError("A harmony needs 2 to 8 frequencies")
    if args.curve and args.mode != "sweep":
        raise ValueError("--curve applies to a sweep")
    if not all(1 <= hz <= 20_000 for hz in freqs):
        raise ValueError("Frequencies must be between 1 and 20000 Hz")
    if not 0.05 <= args.seconds <= 60 or not 0 <= args.level <= 100:
        raise ValueError("Choose a duration of 0.05 to 60 seconds and a level of 0 to 100 percent")
    return Tone(
        args.mode if args.mode not in WAVES else "tone",
        args.mode if args.mode in WAVES else args.wave or "sine",
        freqs,
        args.seconds,
        args.level,
        args.curve or "linear",
    )


def _step_correction(phase, phase_step):
    """PolyBLEP correction around a waveform discontinuity."""
    left = np.maximum(1 - phase / phase_step, 0)
    right = np.maximum(1 - (1 - phase) / phase_step, 0)
    return right * right - left * left


def _oscillator(waveform, cycles, step):
    phase = cycles % 1.0
    if waveform == "sine":
        return np.sin(2 * np.pi * phase)
    if waveform == "triangle":
        return 1 - 4 * np.abs(phase - 0.5)
    correction = _step_correction(phase, step)
    if waveform == "square":
        return np.where(phase < 0.5, 1.0, -1.0) + correction - _step_correction((phase + 0.5) % 1, step)
    return 2 * phase - 1 - correction


def _sweep_phase(tone: Tone, time):
    start, end = tone.frequencies
    if tone.curve == "log" and start != end:
        rate = math.log(end / start) / tone.seconds
        return start * np.expm1(rate * time) / rate, start * np.exp(rate * time) / RATE
    slope = (end - start) / tone.seconds
    return (start + 0.5 * slope * time) * time, (start + slope * time) / RATE


def _write_wav(path: Path, tone: Tone) -> None:
    frames = round(tone.seconds * RATE)
    fade = min(round(0.008 * RATE), frames // 2)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, RATE, frames, "NONE", "not compressed"))
        for first in range(0, frames, 8192):
            indexes = np.arange(first, min(first + 8192, frames))
            time = indexes / RATE
            if tone.mode == "sweep":
                phase, step = _sweep_phase(tone, time)
                samples = _oscillator(tone.waveform, phase, step)
            else:
                samples = sum(_oscillator(tone.waveform, time * hz, hz / RATE) for hz in tone.frequencies)
                samples /= len(tone.frequencies)
            envelope = np.minimum(np.minimum(indexes, frames - 1 - indexes) / fade, 1.0)
            pcm = np.rint(np.clip(samples, -1, 1) * envelope * (32767 * tone.level / 100))
            output.writeframesraw(pcm.astype("<i2").tobytes())


def render_tone(tone: Tone | tone_procedures.Procedure, directory: Path) -> Path:
    """Publish only complete previews and reuse an identical request within a session."""
    digest = hashlib.sha256(repr(tone).encode()).hexdigest()[:24]
    path = directory / f"tone-{digest}.wav"
    if path.is_file():
        return path
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".wav", delete=False) as handle:
        pending = Path(handle.name)
    try:
        if isinstance(tone, tone_procedures.Procedure):
            tone_procedures.write_procedure(pending, tone)
        else:
            _write_wav(pending, tone)
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)
    return path
