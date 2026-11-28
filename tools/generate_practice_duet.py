"""Rebuild Mariana's original, sample-scheduled two-part vocal exercise."""
import hashlib
import json
import math
import struct
import wave
from pathlib import Path

RATE = 12000
DEST = Path(__file__).resolve().parents[1] / "res" / "karaoke"
# Each word starts at an exact sample and is silent after its end. Singers
# overlap in the third phrase. Segment boundaries also label instrumental gaps.
SCORE = [
    (0, 400, {}),
    (400, 1900, {"Alto": [("Ah", 400, 1100, 220), ("Ooh", 1175, 1875, 261.63)]}),
    (1900, 3400, {"Tenor": [("Oh", 1900, 2600, 174.61), ("Ah", 2675, 3375, 196)]}),
    (3400, 5650, {"Alto": [("Ah", 3400, 4100, 261.63), ("Oh", 4150, 4850, 293.66),
                          ("Ooh", 4900, 5600, 261.63)],
                  "Tenor": [("Ooh", 3400, 4100, 164.81), ("Ah", 4150, 4850, 196),
                            ("Oh", 4900, 5600, 174.61)]}),
    (5650, 6000, {}),
]
FORMANTS = {"Ah": (730, 1120, 2410), "Ooh": (300, 870, 2240), "Oh": (500, 900, 2470)}


def render():
    duration = SCORE[-1][1]
    samples = [0.0] * (duration * RATE // 1000)
    segments = []
    for start, end, lanes in SCORE:
        voices = []
        for singer, notes in lanes.items():
            words = []
            for vowel, begin, finish, hz in notes:
                words.append({"text": vowel, "start_ms": begin, "end_ms": finish, "confidence": 1.0})
                offset = begin * RATE // 1000
                count = finish * RATE // 1000 - offset
                gains = [
                    (0.10 + sum(math.exp(-((n * hz - f) / 145) ** 2) for f in FORMANTS[vowel])) / n
                    for n in range(1, int(5000 / hz))
                ]
                gain = 0.43 / sum(gains)
                for j in range(count):
                    t = j / RATE
                    phase = 2 * math.pi * hz * t + .09 * math.sin(2 * math.pi * 5 * t)
                    envelope = min(1.0, t / .025, (count - j) / (RATE * .065))
                    samples[offset + j] += envelope * gain * sum(
                        value * math.sin(n * phase) for n, value in enumerate(gains, 1)
                    )
            voices.append({"singer": singer, "words": words})
        segments.append({"start_ms": start, "end_ms": end, "voices": voices})
    DEST.mkdir(parents=True, exist_ok=True)
    audio = DEST / "practice-duet.wav"
    with wave.open(str(audio), "wb") as out:
        out.setparams((1, 2, RATE, len(samples), "NONE", "not compressed"))
        out.writeframes(b"".join(struct.pack("<h", round(sample * 32767)) for sample in samples))
    sheet = {
        "schema": "mariana.karaoke.v1", "media_sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
        "duration_ms": duration, "source": "Mariana · original sample-scheduled practice duet",
        "confidence": 1.0, "segments": segments,
    }
    (DEST / "practice-duet.json").write_text(json.dumps(sheet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    render()
