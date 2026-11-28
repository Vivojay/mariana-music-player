"""Original morphing wavetables for Mariana and interchangeable cycle-based synths."""
from __future__ import annotations

import io
import math
import struct
import wave
import zipfile
from functools import lru_cache
from pathlib import Path

FRAME = 2048
FRAMES = 8
PARTIALS = 32
RATE = 44100
FAMILIES = ("reed", "organ", "vowel", "brass", "glass", "string", "pulse", "bass")
COLORS = ("velvet", "amber", "hollow", "silver", "dust", "opal", "neon", "ice")
HELP = ("soundbank list [family] · soundbank play <table> [Hz] · "
        "soundbank export <table> <new.wav> · soundbank export-all <new.zip>")


def names(family=""):
    if family and family not in FAMILIES:
        raise ValueError("Choose a family: " + ", ".join(FAMILIES))
    return [f"{f}-{c}" for f in FAMILIES if not family or f == family for c in COLORS]


def spectrum(name):
    if name not in names():
        raise ValueError("Unknown wavetable. Enter soundbank list.")
    fam, color = name.split("-")
    color = COLORS.index(color)
    result = []
    for frame in range(FRAMES):
        t = frame / (FRAMES - 1)
        row = []
        for h in range(1, PARTIALS + 1):
            weight = h ** (-1.35 + color * .07 + t * .28)
            if fam == "reed":
                weight *= 1 if h % 2 else .07 + t * .22
            elif fam == "organ":
                weight *= (1 if h in (1, 2, 3, 4, 6, 8) else .035) * (.25 + .75 * abs(math.cos(h * (.2 + t * .4))))
            elif fam == "vowel":
                peak = 3 + t * 5 + color * .4
                weight *= .12 + 2.2 * math.exp(-((h-peak)/2)**2) + math.exp(-((h-2*peak)/2.7)**2)
            elif fam == "brass":
                weight *= .24 + min(h / (2 + color * .45), 1.6) * math.exp(-h / (4 + 19*t))
            elif fam == "glass":
                weight *= 1 if h in (1, 3, 7, 11, 17, 23, 29) else .025
                weight *= .4 + .6 * abs(math.cos(h * (.1 + .09*t)))
            elif fam == "string":
                weight *= abs(math.sin(h * math.pi * (.15 + .32*t + .012*color)))
            elif fam == "pulse":
                weight *= math.sin(h * math.pi * (.08 + t * .29 + color * .009))
            else:
                weight *= (1 if h <= 3 else .16 + .72*t) * math.exp(-h/(4 + color + 6*t))
            if h == 1:
                weight += .5
            row.append(round(weight, 6))
        result.append(row)
    return result


@lru_cache(maxsize=1)
def _basis():
    return [[math.sin(2 * math.pi * h * n / FRAME) for n in range(FRAME)]
            for h in range(1, PARTIALS+1)]


def frames(name, harmonics=PARTIALS):
    basis = _basis()
    waves = []
    for row in spectrum(name):
        samples = [0.0] * FRAME
        for harmonic, weight in enumerate(row[:harmonics]):
            samples = [s + weight*v for s, v in zip(samples, basis[harmonic], strict=True)]
        waves.append(samples)
    peak = max(abs(s) for samples in waves for s in samples)
    return [[v / peak for v in samples] for samples in waves]


def _wav(samples):
    with io.BytesIO() as out:
        with wave.open(out, "wb") as writer:
            writer.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            writer.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        return out.getvalue()


def table_wav(name):
    return _wav([round(32000*v) for row in frames(name) for v in row])


def preview_wav(name, hz=220.0):
    if not math.isfinite(hz) or not 20 <= hz <= 4000:
        raise ValueError("Choose a frequency between 20 and 4000 Hz.")
    waves = frames(name, min(PARTIALS, int(RATE * .46 / hz)))
    length = RATE * 2
    samples = []
    for i in range(length):
        pos = (i * hz * FRAME / RATE) % FRAME
        index, frac = int(pos), pos % 1
        next_index = (index + 1) % FRAME
        morph = (FRAMES-1)*i/(length-1)
        a = waves[int(morph)]
        b = waves[min(FRAMES-1, int(morph)+1)]
        v = a[index] * (1-frac) + a[next_index]*frac
        w = b[index] * (1-frac) + b[next_index]*frac
        envelope = min(1, i/(RATE*.012), (length-1-i)/(RATE*.08))
        samples.append(round((v + (w-v)*(morph%1)) * envelope * 7500))
    return _wav(samples)


def export_bank(path):
    # Assemble before opening the requested output, preserving existing files.
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name in names():
                z.writestr(f"{name.split('-')[0]}/{name}.wav", table_wav(name))
            z.writestr("README.txt", "Mariana original morphing wavetables. 8 frames of 2048 samples, mono 16-bit PCM WAV, 44100 Hz. Import as a wavetable, choose a frame length of 2048 and scan the table position. You may use, adapt and redistribute these generated waveforms, including in commercial music. No third-party audio is included.\n")
        with Path(path).open("xb") as f:
            f.write(buffer.getvalue())
