"""Explainable local-library similarity with a bounded, opt-in acoustic index."""

from __future__ import annotations

import json
import math
import re
import stat
import subprocess
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from recommendation_engine.engine import cosine

from .database import MarianaDatabase

MODES = ("hybrid", "audio", "tags", "fingerprint")
RATE = 12_000
FRAME_SIZE = 1024
HOP = 256
EXCERPT_SECONDS = 12
MAX_SCAN_ITEMS = 50
SCAN_SECONDS = 12
DECODE_TIMEOUT = 4
ANALYSIS_VERSION = 1
BAND_EDGES = (35, 70, 140, 280, 560, 1120, 2240, 4480, 6001)
FREQUENCIES = np.fft.rfftfreq(FRAME_SIZE, 1 / RATE)
WINDOW = np.hanning(FRAME_SIZE)
PULSE_RATES = (60, 72, 86, 103, 124, 149, 179)
_SQL_ROWS = (
    "SELECT f.library_id,f.canonical_path,f.size,f.mtime_ns,f.metadata_json,"
    "f.fingerprint,f.content_signature,i.features_json AS acoustic_json "
    "FROM library_files f "
    "LEFT JOIN library_similarity i ON i.library_id=f.library_id "
    "AND i.analysis_version=? AND i.size=f.size AND i.mtime_ns=f.mtime_ns "
    "LEFT JOIN blocked_media b ON b.stable_id=f.library_id "
    "WHERE f.state='available' AND b.stable_id IS NULL "
)


@dataclass(frozen=True)
class Track:
    library_id: str
    path: Path
    stamp: tuple[int, int]
    metadata: dict
    tags: frozenset[str]
    fingerprint: str | None
    content_signature: str | None
    audio: tuple | None

    @property
    def title(self):
        return self.metadata.get("title") or self.path.stem


@dataclass(frozen=True)
class Match:
    track: Track
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ScanResult:
    analyzed: int
    unavailable: int
    stopped: bool


def _key(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().split())


def _words(value):
    return frozenset(re.findall(r"[^\W_]+", _key(value)))


def _overlap(left, right):
    combined = left | right
    return len(left & right) / len(combined) if combined else 0.0


def _metadata_score(left, right):
    total = 0.0
    reasons = []
    for field, weight, reason in (("artist", .35, "same artist"), ("album", .25, "same album")):
        first = _key(left.metadata.get(field))
        if first and first == _key(right.metadata.get(field)):
            total += weight
            reasons.append(reason)
    for overlap, weight, reason in (
        (_overlap(_words(left.metadata.get("genre")), _words(right.metadata.get("genre"))), .18, "overlapping genre"),
        (_overlap(left.tags, right.tags), .12, "shared library tags"),
        (_overlap(_words(left.title), _words(right.title)), .06, "similar title"),
    ):
        if overlap:
            total += overlap * weight
            reasons.append(reason)
    if total > 0:
        first_year, second_year = (_key(track.metadata.get("date"))[:4] for track in (left, right))
        if len(first_year) == 4 and first_year.isdecimal() and first_year == second_year:
            total += .01
        try:
            one, two = (float(track.metadata.get("duration")) for track in (left, right))
        except (TypeError, ValueError):
            pass
        else:
            if math.isfinite(one) and math.isfinite(two) and min(one, two) > 0:
                total += .03 * min(one, two) / max(one, two)
    return total, tuple(reasons)


def _recording_match(left, right):
    if left.fingerprint and left.fingerprint == right.fingerprint:
        return ("matching Chromaprint fingerprint",)
    if left.content_signature and left.content_signature == right.content_signature:
        return ("matching sampled file signature",)
    return ()


def describe_audio(samples):
    """Measure a normalized octave spectrum, temporal flux and onset periodicity."""
    if len(samples) < RATE or not np.isfinite(samples).all():
        return None
    frames = np.lib.stride_tricks.sliding_window_view(samples, FRAME_SIZE)[::HOP]
    power = np.abs(np.fft.rfft(frames * WINDOW)) ** 2
    bands = np.stack([power[:, (FREQUENCIES >= low) & (FREQUENCIES < high)].sum(axis=1)
                      for low, high in zip(BAND_EDGES[:-1], BAND_EDGES[1:], strict=True)], axis=-1)
    energy = bands.sum(axis=1)
    if float(energy.max()) < 1e-5:
        return None
    audible = energy > max(1e-5, float(energy.max()) * 1e-5)
    mean_spectrum = (bands[audible] / energy[audible, None]).mean(axis=0)
    timbre = np.sqrt(mean_spectrum)
    # Restrict flux to rises so note attacks contribute more than release tails.
    levels = np.log1p(10 * bands / max(float(energy.max()), 1e-5))
    flux = np.maximum(0, np.diff(levels, axis=0)).sum(axis=1)
    pulses = np.zeros(len(PULSE_RATES))
    if len(flux) > RATE // HOP and float(flux.std()) > 1e-5:
        centered = flux - flux.mean()
        strength = float(np.dot(centered, centered))
        for index, bpm in enumerate(PULSE_RATES):
            lag = round(60 * RATE / (HOP * bpm))
            if lag < len(centered):
                pulses[index] = max(0.0, float(np.dot(centered[:-lag], centered[lag:])) / strength)
    return timbre.tolist(), pulses.tolist()


def _audio_score(left, right):
    if left.audio is None or right.audio is None:
        return None, ()
    left_timbre, left_pulses = left.audio
    right_timbre, right_pulses = right.audio
    timbre = min(1.0, cosine(left_timbre, right_timbre))
    if max(left_pulses) >= .08 and max(right_pulses) >= .08:
        pulse = min(1.0, cosine(left_pulses, right_pulses))
        reasons = ("similar audio spectrum",) if timbre >= .55 else ()
        if pulse >= .65:
            reasons += ("similar rhythmic pulse",)
        return .8 * timbre + .2 * pulse, reasons
    return timbre, ("similar audio spectrum",) if timbre >= .55 else ()


def _file_stamp(path):
    try:
        info = path.stat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return info.st_size, info.st_mtime_ns


def _decode(path, duration, ffmpeg, timeout, cancelled):
    try:
        duration = float(duration)
    except (TypeError, ValueError):
        duration = 0.0
    position = min(90.0, duration / 4) if math.isfinite(duration) and duration > EXCERPT_SECONDS * 2 else 0.0
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-threads", "1",
        "-protocol_whitelist", "file,pipe", "-ss", str(position), "-i", str(path),
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", str(EXCERPT_SECONDS),
        "-ac", "1", "-ar", str(RATE), "-f", "f32le", "pipe:1",
    ]
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ) as process:
        deadline = time.monotonic() + timeout
        while not cancelled():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                pcm, _ = process.communicate(timeout=min(remaining, .2))
            except subprocess.TimeoutExpired:
                continue
            if process.returncode == 0 and len(pcm) % 4 == 0 and len(pcm) <= RATE * EXCERPT_SECONDS * 4:
                return describe_audio(np.frombuffer(pcm, dtype="<f4"))
            return None
        process.kill()
        process.communicate()
        return None


def _metadata(raw):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _audio_features(raw):
    if not raw:
        return None
    try:
        timbre, pulses = json.loads(raw)
        valid = (len(timbre) == len(BAND_EDGES) - 1 and len(pulses) == len(PULSE_RATES)
                 and all(isinstance(item, (float, int)) and 0.0 <= item <= 1.0 for item in (*timbre, *pulses)))
        if valid:
            return timbre, pulses
    except (TypeError, ValueError):
        pass
    return None


def scan_library(
    database: MarianaDatabase, ffmpeg: str, limit=12, *,
    library_id=None, retry=False, cancelled=lambda: False,
):
    """Consume a bounded number of unindexed items from the active profile."""
    if not 1 <= limit <= MAX_SCAN_ITEMS:
        raise ValueError(f"Scan limit must be 1–{MAX_SCAN_ITEMS}")
    pending = "i.features_json='null'" if retry else "i.library_id IS NULL"
    parameters = (ANALYSIS_VERSION,)
    if library_id is not None:
        pending += " AND f.library_id=?"
        parameters += (library_id,)
    rows = database.fetchall(_SQL_ROWS + f" AND {pending} ORDER BY f.path_key LIMIT ?", (*parameters, limit + 1))
    analyzed = unavailable = 0
    deadline = time.monotonic() + SCAN_SECONDS
    for row in rows[:limit]:
        if cancelled() or time.monotonic() >= deadline:
            return ScanResult(analyzed, unavailable, True)
        path = Path(row["canonical_path"])
        stamp = row["size"], row["mtime_ns"]
        analysis = None
        if _file_stamp(path) == stamp:
            analysis = _decode(
                path, _metadata(row["metadata_json"]).get("duration"), ffmpeg,
                min(DECODE_TIMEOUT, deadline - time.monotonic()), cancelled,
            )
        if cancelled() or time.monotonic() >= deadline:
            return ScanResult(analyzed, unavailable, True)
        if _file_stamp(path) != stamp:
            # Invalidate the old result immediately; library scan will give the
            # replacement a new stamp, making it eligible for another analysis.
            analysis = None
        with database.transaction() as connection:
            updated = connection.execute(
                "INSERT INTO library_similarity(library_id,analysis_version,size,mtime_ns,features_json) "
                "SELECT library_id,?,size,mtime_ns,? FROM library_files "
                "WHERE library_id=? AND size=? AND mtime_ns=? AND state='available' "
                "ON CONFLICT(library_id) DO UPDATE SET analysis_version=excluded.analysis_version,"
                "size=excluded.size,mtime_ns=excluded.mtime_ns,features_json=excluded.features_json "
                "WHERE excluded.features_json<>'null' OR library_similarity.features_json='null' "
                "OR library_similarity.analysis_version<>excluded.analysis_version "
                "OR library_similarity.size<>excluded.size "
                "OR library_similarity.mtime_ns<>excluded.mtime_ns",
                (ANALYSIS_VERSION, json.dumps(analysis), row["library_id"], *stamp),
            ).rowcount
        if updated and analysis is not None:
            analyzed += 1
        else:
            unavailable += 1
    return ScanResult(analyzed, unavailable, len(rows) > limit)


def find_similar(database: MarianaDatabase, library_id: str, mode="hybrid", limit=10):
    if mode not in MODES or not 1 <= limit <= MAX_SCAN_ITEMS:
        raise ValueError("Choose mode hybrid, audio, tags or fingerprint and a result limit of 1–50.")
    rows = database.fetchall(_SQL_ROWS + " ORDER BY f.path_key", (ANALYSIS_VERSION,))
    tags = defaultdict(set)
    if mode in ("hybrid", "tags"):
        for row in database.fetchall(
            "SELECT mt.stable_id,t.name_key FROM media_tags mt JOIN tags t ON t.tag_id=mt.tag_id "
            "JOIN library_files f ON f.library_id=mt.stable_id WHERE f.state='available'"
        ):
            tags[row["stable_id"]].add(row["name_key"])
    def as_track(row):
        return Track(
            row["library_id"], Path(row["canonical_path"]), (row["size"], row["mtime_ns"]),
            _metadata(row["metadata_json"]), frozenset(tags[row["library_id"]]),
            row["fingerprint"], row["content_signature"],
            _audio_features(row["acoustic_json"]) if mode in ("hybrid", "audio") else None,
        )

    reference = next((as_track(row) for row in rows if row["library_id"] == library_id), None)
    if reference is None:
        raise ValueError("Choose an available, unblocked item from this profile’s local library.")
    if _file_stamp(reference.path) != reference.stamp:
        raise ValueError("The reference file changed or is unavailable. Run library scan changed and retry.")
    if mode == "audio" and reference.audio is None:
        raise ValueError("This item needs an acoustic profile. Run similar scan, then try again.")
    results = []
    for row in rows:
        if row["library_id"] == library_id:
            continue
        candidate = as_track(row)
        score, reasons = 0.0, ()
        if mode in ("hybrid", "fingerprint") and (duplicate := _recording_match(reference, candidate)):
            score, reasons = 1.0, duplicate
        else:
            if mode in ("hybrid", "tags"):
                match, evidence = _metadata_score(reference, candidate)
                score += match * (.30 if mode == "hybrid" else 1.0)
                reasons += evidence
            if mode in ("hybrid", "audio"):
                acoustic, evidence = _audio_score(reference, candidate)
                if evidence:
                    score += acoustic * (.70 if mode == "hybrid" else 1.0)
                    reasons += evidence
        if reasons:
            results.append(Match(candidate, min(1.0, score), reasons))
    results.sort(key=lambda match: (-match.score, _key(match.track.title), match.track.library_id))
    available = []
    for match in results:
        if _file_stamp(match.track.path) == match.track.stamp:
            available.append(match)
            if len(available) == limit:
                break
    return reference, available
