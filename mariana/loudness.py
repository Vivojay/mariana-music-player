"""ReplayGain-compatible metadata, storage, analysis, and playback gain policy."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import csv
import io
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Iterable

from .database import MarianaDatabase
from .toolchain import find_managed_executable


TARGET_LUFS = -18.0
DEFAULT_HEADROOM_DBTP = -1.0
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LoudnessError(RuntimeError):
    pass


class ReplayGainMode(StrEnum):
    OFF = "off"
    TRACK = "track"
    ALBUM = "album"
    AUTO = "auto"


@dataclass(frozen=True, slots=True)
class LoudnessProfile:
    stable_id: str
    content_signature: str | None = None
    album_key: str | None = None
    track_gain_db: float | None = None
    track_peak: float | None = None
    album_gain_db: float | None = None
    album_peak: float | None = None
    target_lufs: float = TARGET_LUFS
    algorithm: str = "itu-bs.1770"
    source: str = "tags"
    complete_album: bool = False
    scanned_at: float = 0.0
    error_text: str | None = None

    @property
    def has_track(self) -> bool:
        return self.track_gain_db is not None

    @property
    def has_album(self) -> bool:
        return self.album_gain_db is not None


def _tag_name(value: Any) -> str:
    name = str(value).casefold().replace("-", "_")
    for marker in ("replaygain_", "r128_"):
        index = name.find(marker)
        if index >= 0:
            return name[index:]
    return name


def _tag_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "text"):
        value = value.text
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if value is not None and not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip() if value is not None else ""
    return text or None


def parse_gain_db(value: Any) -> float | None:
    text = _tag_value(value)
    if not text:
        return None
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    if not match:
        return None
    result = float(match.group(0))
    return result if math.isfinite(result) and -60 <= result <= 60 else None


def parse_peak(value: Any) -> float | None:
    result = parse_gain_db(value)
    return result if result is not None and 0 < result <= 64 else None


def parse_r128_gain(value: Any) -> float | None:
    text = _tag_value(value)
    try:
        q78 = int(text) if text is not None else None
    except ValueError:
        return None
    if q78 is None or not -32768 <= q78 <= 32767:
        return None
    # RFC 7845 references -23 LUFS; Mariana's ReplayGain target is -18 LUFS.
    return q78 / 256.0 + 5.0


def album_identity(metadata: dict[str, Any]) -> str | None:
    release = metadata.get("release_mbid") or metadata.get("musicbrainz_releaseid")
    if release:
        return f"mbid:{str(release).strip().casefold()}"
    album = str(metadata.get("album") or "").strip().casefold()
    artist = str(metadata.get("album_artist") or metadata.get("albumartist") or "").strip().casefold()
    disc = str(metadata.get("disc") or metadata.get("discnumber") or "1").split("/", 1)[0].strip()
    if not album or not artist:
        return None
    return "tags:" + "\0".join((artist, album, disc))


def profile_from_tags(
    stable_id: str,
    tags: dict[str, Any],
    *,
    metadata: dict[str, Any] | None = None,
    content_signature: str | None = None,
) -> LoudnessProfile | None:
    normalized = {_tag_name(key): _tag_value(value) for key, value in tags.items()}
    track_gain = parse_gain_db(normalized.get("replaygain_track_gain"))
    album_gain = parse_gain_db(normalized.get("replaygain_album_gain"))
    if track_gain is None:
        track_gain = parse_r128_gain(normalized.get("r128_track_gain"))
    if album_gain is None:
        album_gain = parse_r128_gain(normalized.get("r128_album_gain"))
    if track_gain is None and album_gain is None:
        return None
    return LoudnessProfile(
        stable_id=stable_id,
        content_signature=content_signature,
        album_key=album_identity(metadata or {}),
        track_gain_db=track_gain,
        track_peak=parse_peak(normalized.get("replaygain_track_peak")),
        album_gain_db=album_gain,
        album_peak=parse_peak(normalized.get("replaygain_album_peak")),
        source="tags",
        complete_album=album_gain is not None,
        scanned_at=time.time(),
    )


def effective_gain_db(
    profile: LoudnessProfile | None,
    mode: ReplayGainMode | str,
    *,
    preamp_db: float = 0.0,
    prevent_clipping: bool = True,
    headroom_dbtp: float = DEFAULT_HEADROOM_DBTP,
    album_context: bool = False,
) -> float:
    mode = ReplayGainMode(mode)
    if mode == ReplayGainMode.OFF or profile is None:
        return 0.0
    use_album = mode == ReplayGainMode.ALBUM or (
        mode == ReplayGainMode.AUTO and album_context and profile.complete_album
    )
    gain = profile.album_gain_db if use_album and profile.album_gain_db is not None else profile.track_gain_db
    peak = profile.album_peak if use_album and profile.album_peak is not None else profile.track_peak
    if gain is None:
        return 0.0
    gain += min(15.0, max(-15.0, float(preamp_db)))
    if prevent_clipping:
        if peak is None and gain > 0:
            gain = 0.0
        elif peak:
            maximum = headroom_dbtp - 20.0 * math.log10(peak)
            gain = min(gain, maximum)
    return min(24.0, max(-60.0, gain))


def linear_gain(decibels: float) -> float:
    return 10.0 ** (float(decibels) / 20.0)


class LoudnessRepository:
    def __init__(self, database: MarianaDatabase):
        self.database = database

    def save(self, profile: LoudnessProfile) -> LoudnessProfile:
        values = asdict(profile)
        values["complete_album"] = int(profile.complete_album)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO loudness_profiles(stable_id, content_signature, album_key, track_gain_db, track_peak, "
                "album_gain_db, album_peak, target_lufs, algorithm, source, complete_album, scanned_at, error_text) "
                "VALUES(:stable_id, :content_signature, :album_key, :track_gain_db, :track_peak, :album_gain_db, "
                ":album_peak, :target_lufs, :algorithm, :source, :complete_album, :scanned_at, :error_text) "
                "ON CONFLICT(stable_id) DO UPDATE SET content_signature=excluded.content_signature, "
                "album_key=excluded.album_key, track_gain_db=excluded.track_gain_db, track_peak=excluded.track_peak, "
                "album_gain_db=excluded.album_gain_db, album_peak=excluded.album_peak, target_lufs=excluded.target_lufs, "
                "algorithm=excluded.algorithm, source=excluded.source, complete_album=excluded.complete_album, "
                "scanned_at=excluded.scanned_at, error_text=excluded.error_text",
                values,
            )
        return profile

    def get(self, stable_id: str) -> LoudnessProfile | None:
        row = self.database.fetchone("SELECT * FROM loudness_profiles WHERE stable_id=?", (stable_id,))
        return self._profile(row) if row else None

    def by_content(self, signature: str | None) -> LoudnessProfile | None:
        if not signature:
            return None
        row = self.database.fetchone(
            "SELECT * FROM loudness_profiles WHERE content_signature=? AND error_text IS NULL "
            "ORDER BY scanned_at DESC LIMIT 1",
            (signature,),
        )
        return self._profile(row) if row else None

    @staticmethod
    def _profile(row: Any) -> LoudnessProfile:
        values = dict(row)
        values["complete_album"] = bool(values["complete_album"])
        return LoudnessProfile(**values)


def parse_rsgain_output(output: str, paths: Iterable[Path]) -> dict[str, dict[str, float | None]]:
    """Parse pinned rsgain 3.7 TSV output with a conservative text fallback."""
    path_list = [Path(path) for path in paths]
    results: dict[str, dict[str, float | None]] = {}
    rows = list(csv.reader(io.StringIO(output), delimiter="\t"))
    if rows:
        headers = [re.sub(r"[^a-z0-9]+", "_", cell.casefold()).strip("_") for cell in rows[0]]
        if "filename" in headers or "file" in headers:
            file_key = "filename" if "filename" in headers else "file"
            for row in rows[1:]:
                if len(row) != len(headers):
                    continue
                values = dict(zip(headers, row, strict=True))
                name = values.get(file_key)
                if not name:
                    continue
                results[str(Path(name).resolve())] = {
                    "track_gain_db": parse_gain_db(values.get("track_gain") or values.get("track_gain_db")),
                    "track_peak": parse_peak(values.get("track_peak") or values.get("true_peak")),
                    "album_gain_db": parse_gain_db(values.get("album_gain") or values.get("album_gain_db")),
                    "album_peak": parse_peak(values.get("album_peak")),
                }
    if results:
        return results
    labels = {
        "track gain": "track_gain_db", "track peak": "track_peak",
        "album gain": "album_gain_db", "album peak": "album_peak",
    }
    values: dict[str, float | None] = {}
    for line in output.splitlines():
        for label, key in labels.items():
            if label in line.casefold():
                values[key] = parse_peak(line) if "peak" in key else parse_gain_db(line)
    if values and len(path_list) == 1:
        results[str(path_list[0].resolve())] = values
    return results


class RSGainAnalyzer:
    def __init__(self, executable: str | None = None, *, timeout: float = 3600):
        self.executable = executable
        self.timeout = timeout

    def analyze(self, paths: Iterable[Path], *, album: bool = False) -> dict[str, dict[str, float | None]]:
        files = [Path(path).resolve() for path in paths]
        if not files:
            return {}
        executable = self.executable or find_managed_executable("rsgain") or shutil.which("rsgain")
        if not executable:
            suffix = ".exe" if os.name == "nt" else ""
            raise LoudnessError(f"rsgain{suffix} was not found; install or repair Mariana's managed media tools")
        command = [executable, "custom", "-s", "s", "-t", "-l", "-18", "-O"]
        if album and len(files) > 1:
            command.append("-a")
        command.extend(str(path) for path in files)
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=True,
                creationflags=CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise LoudnessError(f"rsgain analysis failed: {error}") from error
        parsed = parse_rsgain_output(result.stdout or result.stderr, files)
        if not parsed:
            raise LoudnessError("rsgain returned no usable scan results")
        return parsed
