"""Select and render a bounded portion of the loaded recording without changing playback."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from .extractor_urls import youtube_recording_id
from .models import MediaSource, PlaybackSnapshot
from .output_targets import OutputTargetError, bind_output_target
from .play_regions import format_region_time, parse_region_time
from .toolchain import find_tool_executable

FORMATS = ("auto", "m4a", "wav", "mp3", "mp4", "story")
HELP = """Clip the current recording, even when playback is paused.
  clip status | clear | social          Public music link composer
  clip link                             YouTube link at the start mark or playhead
  clip start [TIME] · clip end [TIME]   Omit TIME to mark the playhead
  clip range START END                 Seconds or clock times, e.g. 0:15.250 0:30
  clip export [PATH] [--format auto|m4a|wav|mp3|mp4|story]
  clip share [--format auto|m4a|wav|mp3|mp4|story]
Auto preserves video as MP4 or exports audio as M4A. Story produces a vertical MP4.
Share opens a private file handoff in your browser. Select an app there.
Exports use a new file in Mariana's clips folder unless you supply a filename."""


@dataclass(frozen=True)
class ClipSource:
    media_id: str
    uri: str
    title: str
    duration: float
    local_stamp: tuple[int, int, int, int] | None


def _stamp(path: Path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("Choose a finite time in seconds.")
    return float(value)


def _youtube_id(media):
    if media is None or media.source not in {MediaSource.YOUTUBE, MediaSource.URL, MediaSource.RECOMMENDATION}:
        return None
    return youtube_recording_id(media.original_uri, media.resolver_data.get("youtube_id"))


def source_for(snapshot: PlaybackSnapshot, *, link_marks=False) -> ClipSource:
    media = snapshot.media
    if media is None:
        raise ValueError("Load a recording to select a clip.")
    duration = snapshot.duration or media.duration
    if (media.capabilities.live or not media.capabilities.finite or not media.capabilities.seekable
            or not duration or not math.isfinite(duration) or duration <= 0):
        raise ValueError("Clipping needs a seekable recording with a known duration. Live streams have no fixed end.")
    if _youtube_id(media):
        if link_marks:
            return ClipSource(media.stable_id, media.original_uri, media.title or "YouTube", duration, None)
        raise ValueError("Use clip link to share this YouTube moment. File export requires a local copy.")
    underlying = media.resolver_data.get("underlying_source") if media.source == MediaSource.RECOMMENDATION else None
    if (media.source == MediaSource.LOCAL or underlying == MediaSource.LOCAL
            or (media.source == MediaSource.RECOMMENDATION and not media.original_uri.lower().startswith(("http://", "https://"))
                and Path(media.original_uri).is_file())):
        path = Path(media.original_uri).expanduser().resolve()
        if not path.is_file():
            raise ValueError("The loaded recording is no longer available on disk.")
        return ClipSource(media.stable_id, str(path), media.title or path.stem, duration, _stamp(path))
    uri = media.original_uri
    parsed = urlsplit(uri)
    direct = media.source in {MediaSource.PODCAST, MediaSource.URL} or underlying in (MediaSource.URL, MediaSource.PODCAST)
    if (not direct
            or not media.capabilities.downloadable
            or parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password
            or media.resolver_data.get("youtube") or media.resolver_data.get("drm")):
        raise ValueError("Clipping supports local files and downloadable, direct media URLs. "
                         "For this provider, load a saved media file you can share.")
    return ClipSource(media.stable_id, uri, media.title or "Mariana clip", duration, None)


def _bounds(start, end, duration):
    start, end = _number(start), _number(end)
    if start < 0 or start >= end or end > duration + 0.0005:
        raise ValueError("Set a start before the end, within the recording's duration.")
    return start, min(duration, end)


def _run(command, timeout, failure):
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout, check=False,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as error:
        raise ValueError(f"{failure} The media tool timed out.") from error
    if result.returncode:
        # FFmpeg error logs may include signed source URLs or headers.
        raise ValueError(failure)
    return result.stdout


def _input_options(source):
    if source.local_stamp is None:
        return ["-protocol_whitelist", "http,https,tcp,tls", "-rw_timeout", "15000000",
                "-format_whitelist", "aac,ac3,aiff,asf,avi,flac,flv,matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,mp3,mpeg,mpegts,ogg,wav"]
    return ["-protocol_whitelist", "file,pipe"]


def _probe(source, ffprobe):
    output = _run([ffprobe, "-v", "error", *_input_options(source), "-show_entries",
                   "format=duration:stream=codec_type:stream_disposition=attached_pic",
                   "-of", "json", "-i", source.uri], 35, "Could not inspect the media. For a protected or expired URL, load a local copy.")
    try:
        data = json.loads(output)
        streams = data["streams"]
        audio = any(s.get("codec_type") == "audio" for s in streams)
        video = any(s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic") for s in streams)
        duration = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("The media tool could not read a finite duration for this recording.") from error
    if not math.isfinite(duration) or duration <= 0 or not (audio or video):
        raise ValueError("No finite audio or video recording was found.")
    return audio, video, duration


def _output_options(fmt, audio, video):
    if fmt in {"wav", "m4a", "mp3"}:
        if not audio:
            raise ValueError("This video has no audio stream. Choose MP4 or Story.")
        codec = {"wav": ["-c:a", "pcm_s16le"], "m4a": ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
                 "mp3": ["-c:a", "libmp3lame", "-q:a", "2"]}[fmt]
        return ["-map", "0:a:0", "-vn", *codec]
    if video:
        vf = ("scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,"
              "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1" if fmt == "story"
              else "pad=ceil(iw/2)*2:ceil(ih/2)*2")
        mapping = ["-map", "0:V:0", "-map", "0:a:0?", "-vf", vf]
    else:
        mapping = ["-filter_complex", "[0:a:0]showwaves=s=720x1280:mode=cline:rate=30:colors=0x79ded1[wave]",
                   "-map", "[wave]", "-map", "0:a:0"]
    return [*mapping, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]


def render_clip(source, start, end, fmt, folder, configured=None, destination=None):
    if fmt not in FORMATS:
        raise ValueError("Choose auto, wav, mp3, m4a, mp4 or story.")
    start, end = _bounds(start, end, source.duration)
    ffprobe = find_tool_executable("ffprobe", configured)
    ffmpeg = find_tool_executable("ffmpeg", configured)
    if not ffprobe or not ffmpeg:
        raise ValueError("FFmpeg and FFprobe are required. Run tools setup first.")
    if source.local_stamp is not None and source.local_stamp != _stamp(Path(source.uri)):
        raise ValueError("The source file changed. Set the clip range again.")
    audio, video, actual_duration = _probe(source, ffprobe)
    # Container and player may differ by one frame at the end.
    if end > actual_duration + 0.075 or start >= actual_duration:
        raise ValueError("The selected range exceeds the file on disk or at the source URL.")
    end = min(actual_duration, end)
    path = Path(destination).expanduser() if destination is not None else None
    if fmt == "auto" and path:
        fmt = path.suffix.lower().removeprefix(".")
        if fmt not in FORMATS or fmt in {"auto", "story"}:
            raise ValueError("Choose a .wav, .mp3, .m4a or .mp4 filename.")
    if fmt == "auto":
        fmt = "mp4" if video else "m4a"
    extension = "mp4" if fmt == "story" else fmt
    if path and path.suffix.casefold() != "." + extension:
        raise ValueError(f"The selected format requires a .{extension} filename.")
    if path is None:
        title = re.sub(r"[^\w -]", "", source.title, flags=re.UNICODE).strip()[:64] or "Recording"
        path = folder / f"Mariana - {title} - {round(start * 1000)}-{round(end * 1000)}-{uuid4().hex[:8]}.{extension}"
    options = _output_options(fmt, audio, video)
    try:
        target = bind_output_target(path)
        if target.existed:
            raise ValueError("That destination already exists. Choose a new filename.")
        seconds = f"{end - start:.6f}"
        with tempfile.TemporaryDirectory(dir=target.path.parent, prefix=".mariana-clip-") as work:
            partial = Path(work) / f"clip.{extension}"
            _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", *_input_options(source),
                  "-ss", f"{start:.6f}", "-i", source.uri, "-t", seconds, "-map_metadata", "-1",
                  "-map_chapters", "-1", "-dn", "-sn", *options, str(partial)],
                 max(120.0, (end - start) * 8), "Clip encoding failed. Check the source, disk space and FFmpeg codecs.")
            if not partial.is_file() or partial.stat().st_size == 0:
                raise ValueError("The media tool produced an empty clip.")
            if source.local_stamp is not None and source.local_stamp != _stamp(Path(source.uri)):
                raise ValueError("The media file changed while the clip was rendering.")
            return target.activate(partial)
    except OutputTargetError as error:
        raise ValueError(str(error)) from error


class ClipSession:
    def __init__(self):
        self.lock = threading.RLock()
        self.binding = None
        self.start = self.end = None
        self.job: dict[str, Any] = {}

    def _sync(self, source):
        key = (source.media_id, source.uri, source.local_stamp)
        if self.binding != key:
            self.binding = key
            self.start = self.end = None

    def project(self, snapshot):
        with self.lock:
            can_link = bool(_youtube_id(snapshot.media))
            try:
                source = source_for(snapshot, link_marks=can_link)
            except (ValueError, OSError) as error:
                self.binding = None
                self.start = self.end = None
                return {"media_id": snapshot.media.stable_id if snapshot.media else None, "available": False,
                        "link_available": can_link, "reason": str(error), "duration_seconds": None, "start_seconds": None, "end_seconds": None}
            self._sync(source)
            return {"media_id": source.media_id, "available": not can_link, "link_available": can_link,
                    "reason": "Use clip link to share this YouTube moment. File export requires a local copy." if can_link else "",
                    "duration_seconds": source.duration,
                    "start_seconds": self.start, "end_seconds": self.end}

    def link(self, snapshot):
        video = _youtube_id(snapshot.media)
        if not video:
            raise ValueError("A timestamp link requires a loaded YouTube or YouTube Music recording.")
        with self.lock:
            status = self.project(snapshot)
            base = f"https://www.youtube.com/watch?v={video}"
            if not status["duration_seconds"]:
                return base
            position = self.start if self.start is not None else _number(snapshot.position)
            return f"{base}&t={int(max(0, min(position, status['duration_seconds'])))}s"

    def command(self, args, snapshot, folder, configured=None):
        from .clip_share import open_share

        operation, *values = args or ["status"]
        operation = operation.casefold()
        if operation in {"help", "?"} and not values:
            return HELP
        if operation == "link" and not values:
            return self.link(snapshot)
        status = self.project(snapshot)
        link_marks = status["link_available"] and operation in {"clear", "range", "start", "end", "status"}
        if not status["available"] and not (link_marks and status["duration_seconds"]):
            return status["reason"]
        source = source_for(snapshot, link_marks=link_marks)
        with self.lock:
            self._sync(source)
            if operation == "clear" and not values:
                self.start = self.end = None
            elif operation == "range" and len(values) == 2:
                self.start, self.end = _bounds(*(parse_region_time(v) for v in values), source.duration)
            elif operation in {"start", "end"} and len(values) <= 1:
                mark = parse_region_time(values[0]) if values else _number(snapshot.position)
                if not 0 <= mark <= source.duration or (operation == "start" and mark >= source.duration):
                    raise ValueError("The mark must be within the recording.")
                if operation == "start":
                    if self.end is not None:
                        _bounds(mark, self.end, source.duration)
                    self.start = mark
                else:
                    _bounds(self.start or 0, mark, source.duration)
                    self.end = mark
            elif operation in {"export", "share"}:
                fmt = "auto"
                if "--format" in values:
                    index = values.index("--format")
                    if index + 1 >= len(values):
                        raise ValueError("Provide a format after --format.")
                    fmt = values[index + 1].casefold()
                    del values[index:index + 2]
                if len(values) > (1 if operation == "export" else 0):
                    raise ValueError(HELP)
                if self.start is None or self.end is None:
                    raise ValueError("Set both clip marks first. Use clip range START END.")
                start, end = self.start, self.end
                destination = values[0] if values else None
            elif operation != "status" or values:
                raise ValueError(HELP)
            if operation not in {"export", "share"}:
                def label(mark):
                    return "unset" if mark is None else format_region_time(mark)
                return (f"{source.title} · clip {label(self.start)} → {label(self.end)} · "
                        f"playhead {format_region_time(snapshot.position)} / {format_region_time(source.duration)}"
                        + (" · clip link shares this moment" if link_marks else ""))
        path = render_clip(source, start, end, fmt, folder, configured, destination)
        return open_share(path) if operation == "share" else f"Exported clip: {path}"

    def desktop(self, action, payload, snapshot, folder, configured=None):
        from .clip_share import open_share

        if action == "clip.status" and not payload:
            return {"ok": True, **self.project(snapshot)}
        if action == "clip.link" and set(payload) == {"media_id"}:
            if not snapshot.media or payload["media_id"] != snapshot.media.stable_id:
                raise ValueError("The loaded recording changed. Select the link again.")
            return {"ok": True, "url": self.link(snapshot)}
        with self.lock:
            if action == "clip.job" and set(payload) == {"job_id"}:
                if self.job and self.job["job_id"] == payload["job_id"]:
                    return {"ok": True, **self.job}
                raise ValueError("This clip job is no longer current.")
            keys = {"media_id", "start_seconds", "end_seconds"}
            supported = {"clip.range": keys, "clip.export": keys | {"format", "path"}, "clip.share": keys | {"format"}}
            if action not in supported or not keys <= payload.keys() <= supported[action]:
                raise ValueError("Invalid clip request.")
            source = source_for(snapshot, link_marks=action == "clip.range")
            if payload["media_id"] != source.media_id:
                raise ValueError("The loaded recording changed. Select the range again.")
            start, end = _bounds(payload["start_seconds"], payload["end_seconds"], source.duration)
            self._sync(source)
            if action == "clip.range":
                self.start, self.end = start, end
                return {"ok": True, **self.project(snapshot)}
            fmt = payload.get("format", "auto")
            if fmt not in FORMATS:
                raise ValueError("Unknown clip format.")
            destination = payload.get("path")
            if destination is not None and (not isinstance(destination, str) or not Path(destination).is_absolute()):
                raise ValueError("Choose an absolute destination filename.")
            if self.job.get("phase") == "rendering":
                raise ValueError("A clip is already being prepared.")
            self.start, self.end = start, end
            job_id = uuid4().hex
            self.job = {"job_id": job_id, "phase": "rendering", "message": "Preparing your clip…"}

        def worker():
            try:
                path = render_clip(source, start, end, fmt, folder, configured, destination)
                message = open_share(path) if action == "clip.share" else f"Exported clip: {path}"
                result = {"phase": "ready", "path": str(path), "message": message}
            except (OSError, ValueError, RuntimeError) as error:
                result = {"phase": "error", "message": str(error)}
            with self.lock:
                self.job.update(result)
        threading.Thread(target=worker, name="mariana-clip", daemon=True).start()
        return {"ok": True, "job_id": job_id}
