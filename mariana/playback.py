"""FFmpeg decoding and callback-driven PCM playback."""

from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import threading
import time
from array import array
from collections import deque
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Protocol, cast

import numpy as np
import sounddevice

from .models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from .output_devices import OutputDeviceInfo, default_output_device
from .seek import END_MARGIN_SECONDS
from .sources import FailureCode, MediaFailure, ResolvedMedia, ResolverRegistry, redacted_uri

SAMPLE_RATE = 48_000
CHANNELS = 2
SAMPLE_WIDTH = 4
BYTES_PER_FRAME = CHANNELS * SAMPLE_WIDTH
DEFAULT_BUFFER_SECONDS = 8.0
FINGERPRINT_SECONDS = 120
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PlaybackError(RuntimeError):
    pass


class UnsupportedAction(PlaybackError):
    pass


class OutputStream(Protocol):
    def start(self): ...
    def stop(self): ...
    def close(self): ...


def find_executable(name: str, configured_bin: str | None = None) -> str:
    from .toolchain import find_tool_executable

    if executable := find_tool_executable(name, configured_bin):
        return executable
    raise PlaybackError(
        f"{name} was not found; run 'tools setup' or configure its executable/directory in settings"
    )


@lru_cache(maxsize=8)
def _ffmpeg_http_options(executable: str) -> frozenset[str]:
    optional = {"reconnect_max_retries", "reconnect_delay_total_max", "respect_retry_after"}
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-h", "protocol=http"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    output = f"{result.stdout}\n{result.stderr}"
    return frozenset(option for option in optional if option in output)


def resolve_input(media: MediaRef) -> str:
    if media.source in {MediaSource.YOUTUBE, MediaSource.RECOMMENDATION} or media.resolver_data.get("youtube"):
        from beta.youtube_media import stream_url

        return stream_url(media.original_uri, audio_only=True)
    return str(media.resolver_data.get("resolved_uri") or media.original_uri)


def probe_media(
    media: MediaRef,
    *,
    source: str | None = None,
    headers: dict[str, str] | None = None,
    ffprobe_bin: str | None = None,
    timeout: float = 20,
) -> MediaRef:
    ffprobe = find_executable("ffprobe", ffprobe_bin)
    source = source or resolve_input(media)
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name,tags:stream=codec_type,codec_name,duration,tags",
        "-of",
        "json",
    ]
    if headers:
        command.extend(["-headers", "".join(f"{key}: {value}\r\n" for key, value in headers.items())])
    command.append(source)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            creationflags=CREATE_NO_WINDOW,
        )
        payload = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        stderr = getattr(error, "stderr", None)
        detail = str(stderr).strip()[-1000:] if stderr else str(error)
        raise PlaybackError(f"FFprobe could not inspect {redacted_uri(media.original_uri)}: {detail}") from error

    format_info = payload.get("format") or {}
    streams = payload.get("streams") or []
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    duration_value = format_info.get("duration") or audio_stream.get("duration")
    try:
        duration = float(duration_value) if duration_value not in (None, "N/A") else None
    except (TypeError, ValueError):
        duration = None
    tags = {str(key).lower(): value for key, value in (format_info.get("tags") or {}).items()}
    tags.update({str(key).lower(): value for key, value in (audio_stream.get("tags") or {}).items()})
    is_live = media.capabilities.live or media.source == MediaSource.RADIO
    media.duration = duration
    media.title = media.title or tags.get("title")
    media.artist = media.artist or tags.get("artist")
    media.album = media.album or tags.get("album")
    media.resolver_data.update(
        {
            "codec": audio_stream.get("codec_name"),
            "format": format_info.get("format_name"),
            "tags": tags,
        }
    )
    media.capabilities = MediaCapabilities(
        finite=not is_live,
        live=is_live,
        seekable=media.capabilities.seekable and not is_live,
        fingerprintable=True,
        downloadable=media.source != MediaSource.RADIO,
        metadata_available=bool(tags),
    )
    return media


def _is_windows() -> bool:
    return os.name == "nt"


class WindowsJob:
    """Best-effort kill-on-close Windows job for child process cleanup."""

    def __init__(self, process: subprocess.Popen):
        self.handle = None
        if not _is_windows():
            return
        try:
            import win32job

            handle = win32job.CreateJobObject(None, "")
            if handle is None:
                raise OSError("Windows could not create a playback job object")
            information = win32job.QueryInformationJobObject(
                handle, win32job.JobObjectExtendedLimitInformation
            )
            information["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation, information)
            process_handle = cast(Any, process)._handle
            win32job.AssignProcessToJobObject(handle, int(process_handle))
            self.handle = handle
        except Exception:
            self.handle = None

    def close(self) -> None:
        if self.handle is not None:
            try:
                import win32api

                win32api.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


def parse_icy_title(value: str | bytes) -> str | None:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError:
            value = value.decode("cp1252", errors="replace")
    value = " ".join(value.replace("\x00", " ").split())
    match = re.search(
        r"(?:StreamTitle|icy-title)\s*[:=]\s*(['\"]?)(.*?)(?:\1)?(?:;|$)",
        value,
        re.IGNORECASE,
    )
    if not match:
        return None
    title = match.group(2).strip(" '\";\x00")
    return title[:1000] or None


class DecoderSession:
    def __init__(
        self,
        media: MediaRef,
        *,
        resolved: ResolvedMedia | None = None,
        ffmpeg_bin: str | None = None,
        start_at: float = 0,
        max_buffer_seconds: float = DEFAULT_BUFFER_SECONDS,
        audio_filter: str | None = None,
        program_gain_db: float = 0.0,
    ):
        self.media = media
        self.resolved = resolved
        self.ffmpeg = find_executable("ffmpeg", ffmpeg_bin)
        self.start_at = max(0.0, start_at)
        self.max_buffer_bytes = int(max_buffer_seconds * SAMPLE_RATE * BYTES_PER_FRAME)
        self.audio_filter = audio_filter
        self.program_gain_db = float(program_gain_db)
        self.program_gain = 10.0 ** (self.program_gain_db / 20.0)
        self.process: subprocess.Popen | None = None
        self.job: WindowsJob | None = None
        self._buffer = bytearray()
        self._fingerprint = bytearray()
        self._fingerprint_limit = FINGERPRINT_SECONDS * SAMPLE_RATE * BYTES_PER_FRAME
        self._condition = threading.Condition()
        self._stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._stderr: deque[str] = deque(maxlen=30)
        self.eof = False
        self.frames_emitted = 0
        self.on_metadata: Callable[[str], None] | None = None
        self._last_stream_title: str | None = None
        self._auth_tunnel = None

    @property
    def position(self) -> float:
        return self.start_at + self.frames_emitted / SAMPLE_RATE

    @property
    def buffered_seconds(self) -> float:
        with self._condition:
            return len(self._buffer) / BYTES_PER_FRAME / SAMPLE_RATE

    @property
    def fingerprint_pcm(self) -> bytes:
        with self._condition:
            return bytes(self._fingerprint)

    @property
    def error(self) -> str | None:
        return "\n".join(self._stderr) or None

    @property
    def failed(self) -> bool:
        process = self.process
        return bool(self.eof and process is not None and process.poll() not in {None, 0})

    def reset_fingerprint(self) -> None:
        with self._condition:
            self._fingerprint.clear()

    def start(self) -> None:
        if self.process is not None:
            return
        source = self.resolved.playback_uri if self.resolved else resolve_input(self.media)
        if self.resolved and self.resolved.metadata.get("credential_ref"):
            from .credentials import ListenerAuthTunnel

            self._auth_tunnel = ListenerAuthTunnel(
                source,
                str(self.resolved.metadata.get("credential_username") or "source"),
                str(self.resolved.metadata["credential_ref"]),
            )
            source = self._auth_tunnel.start()
        log_level = "info" if self.media.capabilities.live else "warning"
        command = [self.ffmpeg, "-hide_banner", "-loglevel", log_level, "-nostdin"]
        if self.start_at and self.media.capabilities.seekable:
            command += ["-ss", f"{self.start_at:.3f}"]
        if source.startswith(("http://", "https://")):
            command += [
                "-rw_timeout",
                "30000000",
                "-reconnect",
                "1",
                "-reconnect_at_eof",
                "1" if self.media.capabilities.live else "0",
                "-reconnect_on_network_error",
                "1",
                "-reconnect_on_http_error",
                "429,5xx",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
            ]
            supported = _ffmpeg_http_options(self.ffmpeg)
            for option, value in (
                ("reconnect_max_retries", "3"),
                ("reconnect_delay_total_max", "30"),
                ("respect_retry_after", "1"),
            ):
                if option in supported:
                    command += [f"-{option}", value]
            if self.media.capabilities.live:
                command += ["-icy", "1"]
        if self.resolved and self.resolved.headers:
            command += ["-headers", "".join(f"{key}: {value}\r\n" for key, value in self.resolved.headers.items())]
        command += [
            "-i",
            source,
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
        ]
        if self.audio_filter:
            command += ["-af", self.audio_filter]
        command += [
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "f32le",
            "pipe:1",
        ]
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                creationflags=CREATE_NO_WINDOW,
                start_new_session=os.name != "nt",
            )
        except OSError as error:
            raise PlaybackError(f"FFmpeg could not start: {error}") from error
        self.job = WindowsJob(self.process)
        self._reader = threading.Thread(target=self._read_loop, name="mariana-ffmpeg-reader", daemon=True)
        self._reader.start()
        threading.Thread(target=self._stderr_loop, name="mariana-ffmpeg-stderr", daemon=True).start()

    def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        try:
            while not self._stop.is_set():
                chunk = self.process.stdout.read(65_536)
                if not chunk:
                    break
                with self._condition:
                    while len(self._buffer) >= self.max_buffer_bytes and not self._stop.is_set():
                        self._condition.wait(0.1)
                    if self._stop.is_set():
                        break
                    self._buffer.extend(chunk)
                    remaining = self._fingerprint_limit - len(self._fingerprint)
                    if remaining > 0:
                        self._fingerprint.extend(chunk[:remaining])
                    self._condition.notify_all()
        finally:
            with self._condition:
                self.eof = True
                self._condition.notify_all()

    def _stderr_loop(self) -> None:
        assert self.process and self.process.stderr
        for raw in iter(self.process.stderr.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()
            self._stderr.append(line)
            title = parse_icy_title(line)
            if title and title != self._last_stream_title:
                self._last_stream_title = title
                if self.on_metadata:
                    self.on_metadata(title)

    def wait_for_buffer(self, minimum_seconds: float = 0.15, timeout: float = 10) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self.buffered_seconds < minimum_seconds and not self.eof:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(remaining, 0.1))
        return self.buffered_seconds > 0

    def read(self, frames: int) -> bytes:
        requested = frames * BYTES_PER_FRAME
        with self._condition:
            size = min(requested, len(self._buffer))
            size -= size % BYTES_PER_FRAME
            data = bytes(self._buffer[:size])
            del self._buffer[:size]
            self.frames_emitted += size // BYTES_PER_FRAME
            self._condition.notify_all()
        return data

    def stop(self) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        process = self.process
        if process and process.poll() is None:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    process.terminate()
            else:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        process.kill()
                else:
                    process.kill()
                process.wait(timeout=2)
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=2)
        if self.job:
            self.job.close()
        if self._auth_tunnel:
            self._auth_tunnel.close()
            self._auth_tunnel = None
        self.process = None


def _scale_pcm(data: bytes, gain: float) -> bytes:
    if not data or gain == 1.0:
        return data
    samples = array("f")
    samples.frombytes(data)
    for index, sample in enumerate(samples):
        samples[index] = max(-1.0, min(1.0, sample * gain))
    return samples.tobytes()


def _mix_pcm(first: bytes, second: bytes, first_gain: float, second_gain: float, size: int) -> bytes:
    count = size // SAMPLE_WIDTH
    left = array("f")
    right = array("f")
    left.frombytes(first.ljust(size, b"\0"))
    right.frombytes(second.ljust(size, b"\0"))
    mixed = array("f", [0.0]) * count
    for index in range(count):
        mixed[index] = max(-1.0, min(1.0, left[index] * first_gain + right[index] * second_gain))
    return mixed.tobytes()


class PlaybackController:
    def __init__(
        self,
        *,
        ffmpeg_bin: str | None = None,
        ffprobe_bin: str | None = None,
        crossfade_seconds: float = 0.0,
        output_factory: Callable[..., OutputStream] | None = None,
        resolvers: ResolverRegistry | None = None,
        loudness_repository=None,
        replaygain_enabled: bool = False,
        replaygain_mode: str = "track",
        replaygain_preamp_db: float = 0.0,
        replaygain_prevent_clipping: bool = True,
        replaygain_headroom_dbtp: float = -1.0,
        live_leveling: bool = False,
        live_target_lufs: float = -18.0,
        live_true_peak_dbtp: float = -1.0,
        live_lra: float = 11.0,
        output_device_provider: Callable[[], OutputDeviceInfo] | None = None,
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.crossfade_seconds = max(0.0, crossfade_seconds)
        self.output_factory = output_factory or sounddevice.OutputStream
        self.resolvers = resolvers or ResolverRegistry()
        self.loudness_repository = loudness_repository
        self.replaygain_enabled = bool(replaygain_enabled)
        self.replaygain_mode = replaygain_mode
        self.replaygain_preamp_db = float(replaygain_preamp_db)
        self.replaygain_prevent_clipping = bool(replaygain_prevent_clipping)
        self.replaygain_headroom_dbtp = float(replaygain_headroom_dbtp)
        self.live_leveling = bool(live_leveling)
        self.live_target_lufs = float(live_target_lufs)
        self.live_true_peak_dbtp = float(live_true_peak_dbtp)
        self.live_lra = float(live_lra)
        self.output_device_provider = output_device_provider or (
            default_output_device
            if output_factory is None
            else lambda: OutputDeviceInfo("custom-output", "Custom output", None, "Custom output", "test")
        )
        self._lock = threading.RLock()
        self._output_switch_lock = threading.Lock()
        self._active: DecoderSession | None = None
        self._next: DecoderSession | None = None
        self._stream: OutputStream | None = None
        self._output_device: OutputDeviceInfo | None = None
        self._state = PlaybackState.IDLE
        self._volume = 1.0
        self._automation_gain = 1.0
        self._muted = False
        self._error: str | None = None
        self._prepared: MediaRef | None = None
        self._resolved: ResolvedMedia | None = None
        self._completed_media: MediaRef | None = None
        self._completed_position = 0.0
        self._completed_duration: float | None = None
        self.on_complete: Callable[[MediaRef], None] | None = None
        self.on_failure: Callable[[MediaRef, MediaFailure], None] | None = None
        self._watch_stop = threading.Event()
        self._identity_generation = 0
        self._program_sinks: list[Callable[[object, int], None]] = []
        self._metadata_sinks: list[Callable[[str | None], None]] = []
        self._stream_metadata: dict[str, object] = {}

    def _program_gain_db(self, media: MediaRef) -> float:
        if not self.replaygain_enabled or media.capabilities.live or self.loudness_repository is None:
            return 0.0
        from .loudness import ReplayGainMode, effective_gain_db

        profile = self.loudness_repository.get(media.stable_id)
        return effective_gain_db(
            profile,
            ReplayGainMode(self.replaygain_mode),
            preamp_db=self.replaygain_preamp_db,
            prevent_clipping=self.replaygain_prevent_clipping,
            headroom_dbtp=self.replaygain_headroom_dbtp,
            album_context=bool(media.resolver_data.get("album_context")),
        )

    def _live_filter(self, media: MediaRef) -> str | None:
        if not self.live_leveling or not media.capabilities.live:
            return None
        return (
            f"loudnorm=I={self.live_target_lufs:g}:TP={self.live_true_peak_dbtp:g}:"
            f"LRA={self.live_lra:g}"
        )

    def _new_session(self, media: MediaRef, *, start_at: float = 0) -> DecoderSession:
        return DecoderSession(
            media,
            resolved=self._resolved,
            ffmpeg_bin=self.ffmpeg_bin,
            start_at=start_at,
            audio_filter=self._live_filter(media),
            program_gain_db=self._program_gain_db(media),
        )

    def prepare(self, media: MediaRef, *, probe: bool = True) -> MediaRef:
        with self._lock:
            self._state = PlaybackState.RESOLVING
            self._error = None
            self._completed_media = None
            self._completed_position = 0.0
            self._completed_duration = None
        try:
            resolved = self.resolvers.resolve(media)
            media.capabilities = resolved.capabilities
            if probe and media.source != MediaSource.YOUTUBE:
                media = probe_media(
                    media,
                    source=resolved.playback_uri,
                    headers=resolved.headers,
                    ffprobe_bin=self.ffprobe_bin,
                )
            for field in ("title", "artist", "album", "duration"):
                if getattr(media, field) is None and resolved.metadata.get(field) is not None:
                    setattr(media, field, resolved.metadata[field])
            if not media.chapters:
                from .models import MediaChapter

                media.chapters = [
                    MediaChapter.from_dict(item)
                    for item in (resolved.metadata.get("chapters") or [])
                    if isinstance(item, dict)
                ]
            if media.source == MediaSource.YOUTUBE:
                categories = [str(item) for item in (resolved.metadata.get("categories") or [])]
                media.resolver_data.update(
                    {
                        "youtube": True,
                        "categories": categories,
                        "track": resolved.metadata.get("track"),
                        "is_music": bool(resolved.metadata.get("track") and resolved.metadata.get("artist"))
                        or any(item.casefold() == "music" for item in categories),
                    }
                )
            resolved.capabilities = media.capabilities
            self._stream_metadata = dict(resolved.metadata.get("icy") or {})
            self._prepared = media
            self._resolved = resolved
            return media
        except Exception as error:
            with self._lock:
                self._state = PlaybackState.FAILED
                self._error = str(error)
            raise

    def play(self, media: MediaRef | None = None, *, start_at: float = 0, probe: bool = True) -> MediaRef:
        if media is not None:
            self.prepare(media, probe=probe)
        if self._prepared is None:
            raise PlaybackError("No media has been prepared")
        prepared, resolved = self._prepared, self._resolved
        self.stop()
        self._prepared, self._resolved = prepared, resolved
        media = prepared
        with self._lock:
            self._state = PlaybackState.BUFFERING
            session = self._new_session(media, start_at=start_at)
            session.on_metadata = lambda title, source=session: self._handle_stream_metadata(source, title)
            self._active = session
            session.start()
        if not session.wait_for_buffer():
            error = session.error or "FFmpeg produced no playable audio"
            session.stop()
            with self._lock:
                self._state = PlaybackState.FAILED
                self._error = error
            raise PlaybackError(error)
        self._ensure_output()
        with self._lock:
            self._state = PlaybackState.PLAYING
            self._watch_stop.clear()
            threading.Thread(target=self._watch_completion, name="mariana-playback-watch", daemon=True).start()
        self._publish_metadata(" - ".join(value for value in (media.artist, media.title) if value) or media.title)
        return media

    def prefetch(self, media: MediaRef, *, probe: bool = True) -> MediaRef:
        resolved = self.resolvers.resolve(media)
        media.capabilities = resolved.capabilities
        media = (
            probe_media(
                media,
                source=resolved.playback_uri,
                headers=resolved.headers,
                ffprobe_bin=self.ffprobe_bin,
            )
            if probe
            else media
        )
        session = DecoderSession(
            media,
            resolved=resolved,
            ffmpeg_bin=self.ffmpeg_bin,
            audio_filter=self._live_filter(media),
            program_gain_db=self._program_gain_db(media),
        )
        session.on_metadata = lambda title, source=session: self._handle_stream_metadata(source, title)
        session.start()
        if not session.wait_for_buffer(timeout=10):
            error = session.error or "FFmpeg could not prefetch this media"
            session.stop()
            raise PlaybackError(error)
        with self._lock:
            if self._next:
                self._next.stop()
            self._next = session
        return media

    def clear_prefetch(self) -> None:
        """Discard a queued decoder without disturbing the active item."""
        with self._lock:
            session = self._next
            self._next = None
        if session:
            session.stop()

    @staticmethod
    def _close_output_stream(stream: OutputStream | None) -> None:
        if stream is None:
            return
        try:
            stream.stop()
        finally:
            stream.close()

    def default_output_device(self) -> OutputDeviceInfo:
        return self.output_device_provider()

    @property
    def active_output_device(self) -> OutputDeviceInfo | None:
        with self._lock:
            return self._output_device

    @property
    def output_stream_active(self) -> bool:
        with self._lock:
            stream = self._stream
        return bool(stream is not None and getattr(stream, "active", True))

    def _replace_output(self, device: OutputDeviceInfo, *, force: bool = False) -> None:
        with self._output_switch_lock:
            with self._lock:
                if self._stream is not None and self._output_device == device and not force:
                    return
                previous = self._stream
                self._stream = None
            self._close_output_stream(previous)
            stream = None
            try:
                stream = self.output_factory(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="float32",
                    callback=self._audio_callback,
                    blocksize=1024,
                    device=device.index,
                )
                stream.start()
            except Exception:
                if stream is not None:
                    self._close_output_stream(stream)
                raise
            with self._lock:
                self._stream = stream
                self._output_device = device
                self._error = None

    def _ensure_output(self) -> None:
        self._replace_output(self.default_output_device())

    def _audio_callback(self, outdata, frames, _time_info, _status) -> None:
        size = frames * BYTES_PER_FRAME
        with self._lock:
            active = self._active
            next_session = self._next
            state = self._state
            local_gain = 0.0 if self._muted else self._volume * self._automation_gain
        if _status:
            with self._lock:
                self._error = f"Audio output reported: {_status}"
        numpy_output = isinstance(outdata, np.ndarray)
        if not active or state == PlaybackState.PAUSED:
            if numpy_output:
                outdata.fill(0)
            else:
                outdata[:] = b"\0" * size
            self._publish_program(outdata, frames)
            return
        crossfade = False
        fraction = 0.0
        if (
            next_session
            and self.crossfade_seconds > 0
            and active.media.duration is not None
            and active.media.duration - active.position <= self.crossfade_seconds
        ):
            crossfade = True
            fraction = min(1.0, max(0.0, 1 - (active.media.duration - active.position) / self.crossfade_seconds))
        first = active.read(frames)
        if numpy_output:
            outdata.fill(0)
            first_samples = np.frombuffer(first, dtype=np.float32).reshape(-1, CHANNELS)
            count = min(frames, first_samples.shape[0])
            if count:
                np.multiply(
                    first_samples[:count],
                    getattr(active, "program_gain", 1.0) * (1 - fraction if crossfade else 1),
                    out=outdata[:count],
                )
            if crossfade and next_session:
                second = next_session.read(frames)
                second_samples = np.frombuffer(second, dtype=np.float32).reshape(-1, CHANNELS)
                second_count = min(frames, second_samples.shape[0])
                if second_count:
                    outdata[:second_count] += (
                        second_samples[:second_count] * getattr(next_session, "program_gain", 1.0) * fraction
                    )
                np.clip(outdata, -1.0, 1.0, out=outdata)
        elif crossfade and next_session:
            second = next_session.read(frames)
            payload = _mix_pcm(
                first,
                second,
                getattr(active, "program_gain", 1.0) * (1 - fraction),
                getattr(next_session, "program_gain", 1.0) * fraction,
                size,
            )
            with self._lock:
                self._state = PlaybackState.CROSSFADING
        else:
            payload = _scale_pcm(first, getattr(active, "program_gain", 1.0)).ljust(size, b"\0")
        if crossfade:
            with self._lock:
                self._state = PlaybackState.CROSSFADING
        self._publish_program(outdata if numpy_output else payload, frames)
        if numpy_output:
            np.multiply(outdata, local_gain, out=outdata)
            np.clip(outdata, -1.0, 1.0, out=outdata)
        else:
            payload = _scale_pcm(payload, local_gain)
            outdata[:] = payload[:size]
        if active.eof and active.buffered_seconds == 0:
            self._finish_active(active)

    def _finish_active(self, active: DecoderSession) -> None:
        if getattr(active, "failed", False):
            failure = MediaFailure(
                FailureCode.DECODE,
                active.media.source,
                active.error or "FFmpeg stopped before playback completed",
                retryable=active.media.source != MediaSource.LOCAL,
            )
            with self._lock:
                if self._active is not active:
                    return
                self._active = None
                self._state = PlaybackState.FAILED
                self._error = str(failure)
            threading.Thread(target=active.stop, name="mariana-decoder-cleanup", daemon=True).start()
            if self.on_failure:
                threading.Thread(
                    target=self.on_failure,
                    args=(active.media, failure),
                    name="mariana-playback-failure",
                    daemon=True,
                ).start()
            return
        self._promote_next(active)

    def _promote_next(self, expected: DecoderSession) -> None:
        with self._lock:
            if self._active is not expected:
                return
            completed = expected
            if self._next:
                self._active = self._next
                self._next = None
                self._state = PlaybackState.PLAYING
                self._completed_media = None
                self._completed_position = 0.0
                self._completed_duration = None
            else:
                self._completed_media = completed.media
                self._completed_duration = completed.media.duration
                self._completed_position = (
                    completed.media.duration
                    if completed.media.duration is not None
                    else completed.position
                )
                self._active = None
                self._state = PlaybackState.IDLE
        threading.Thread(target=completed.stop, name="mariana-decoder-cleanup", daemon=True).start()
        if self.on_complete:
            threading.Thread(
                target=self.on_complete,
                args=(completed.media,),
                name="mariana-playback-complete",
                daemon=True,
            ).start()

    def _watch_completion(self) -> None:
        while not self._watch_stop.wait(0.1):
            with self._lock:
                active = self._active
            if active is None:
                return
            if active.eof and active.buffered_seconds == 0:
                self._finish_active(active)
                return

    def pause(self) -> None:
        with self._lock:
            if self._state not in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}:
                raise UnsupportedAction("Nothing is currently playing")
            self._state = PlaybackState.PAUSED

    def resume(self) -> None:
        with self._lock:
            if self._state != PlaybackState.PAUSED:
                raise UnsupportedAction("Playback is not paused")
            self._state = PlaybackState.PLAYING

    def toggle_pause(self) -> None:
        if self.snapshot().state == PlaybackState.PAUSED:
            self.resume()
        else:
            self.pause()

    def seek(self, seconds: float) -> None:
        with self._lock:
            active = self._active
            if not active:
                raise UnsupportedAction("Nothing is loaded")
            if not active.media.capabilities.seekable:
                raise UnsupportedAction("This live or nonseekable source cannot be seeked")
            target = max(0.0, float(seconds))
            if active.media.duration is not None:
                target = min(target, active.media.duration)
            was_paused = self._state == PlaybackState.PAUSED
            self._state = PlaybackState.SEEKING
            media = active.media
            active.stop()
            replacement = self._new_session(media, start_at=target)
            replacement.on_metadata = lambda title, source=replacement: self._handle_stream_metadata(source, title)
            self._active = replacement
            replacement.start()
        if not replacement.wait_for_buffer():
            if self._seek_reached_clean_end(replacement, target):
                self._finish_active(replacement)
                return
            raise PlaybackError(replacement.error or "Seek produced no audio")
        with self._lock:
            self._state = PlaybackState.PAUSED if was_paused else PlaybackState.PLAYING

    @staticmethod
    def _seek_reached_clean_end(session: DecoderSession, target: float) -> bool:
        """Return whether an unbuffered seek completed normally at the finite endpoint."""
        duration = session.media.duration
        if duration is None or session.media.capabilities.live or not session.eof:
            return False
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(duration) or duration <= 0 or getattr(session, "failed", False):
            return False
        margin = min(END_MARGIN_SECONDS, duration / 2)
        return target >= duration - margin

    def restart_live(self) -> None:
        with self._lock:
            active = self._active
            if not active or not active.media.capabilities.live:
                raise UnsupportedAction("Only live streams can be resynchronized")
            media = active.media
        self.play(media, probe=False)

    @property
    def resolved_uri(self) -> str | None:
        with self._lock:
            return self._resolved.playback_uri if self._resolved else None

    def set_volume(self, value: float) -> None:
        value = float(value)
        if value > 1:
            value /= 100
        if not 0 <= value <= 1:
            raise ValueError("Volume must be between 0 and 100 percent")
        with self._lock:
            self._volume = value

    def set_automation_gain(self, value: float) -> None:
        """Apply transient automation without changing the user's base volume."""
        value = float(value)
        if not 0 <= value <= 1:
            raise ValueError("Automation gain must be between 0 and 1")
        with self._lock:
            self._automation_gain = value

    def configure_replaygain(
        self,
        *,
        enabled: bool | None = None,
        mode: str | None = None,
        preamp_db: float | None = None,
        prevent_clipping: bool | None = None,
    ) -> None:
        from .loudness import ReplayGainMode

        with self._lock:
            if enabled is not None:
                self.replaygain_enabled = bool(enabled)
            if mode is not None:
                self.replaygain_mode = ReplayGainMode(mode).value
            if preamp_db is not None:
                if not -15 <= float(preamp_db) <= 15:
                    raise ValueError("ReplayGain preamp must be between -15 and 15 dB")
                self.replaygain_preamp_db = float(preamp_db)
            if prevent_clipping is not None:
                self.replaygain_prevent_clipping = bool(prevent_clipping)
            for session in (self._active, self._next):
                if session:
                    session.program_gain_db = self._program_gain_db(session.media)
                    session.program_gain = 10.0 ** (session.program_gain_db / 20.0)

    def set_live_leveling(self, enabled: bool) -> None:
        with self._lock:
            changed = self.live_leveling != bool(enabled)
            self.live_leveling = bool(enabled)
            restart = changed and self._active is not None and self._active.media.capabilities.live
        if restart:
            self.restart_live()

    def add_program_sink(self, callback: Callable[[object, int], None]) -> Callable[[], None]:
        with self._lock:
            self._program_sinks.append(callback)

        def remove() -> None:
            with self._lock:
                if callback in self._program_sinks:
                    self._program_sinks.remove(callback)

        return remove

    def add_metadata_sink(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        with self._lock:
            self._metadata_sinks.append(callback)

        def remove() -> None:
            with self._lock:
                if callback in self._metadata_sinks:
                    self._metadata_sinks.remove(callback)

        return remove

    def _publish_metadata(self, title: str | None) -> None:
        with self._lock:
            sinks = tuple(self._metadata_sinks)
        for sink in sinks:
            try:
                sink(title)
            except Exception:
                continue

    def _publish_program(self, samples: object, frames: int) -> None:
        with self._lock:
            sinks = tuple(self._program_sinks)
        for sink in sinks:
            try:
                sink(samples, frames)
            except Exception:
                # A broadcast/telemetry consumer must never break playback.
                continue

    @property
    def automation_gain(self) -> float:
        with self._lock:
            return self._automation_gain

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self._muted = bool(muted)

    def fingerprint_pcm(self) -> bytes:
        with self._lock:
            return self._active.fingerprint_pcm if self._active else b""

    def notify_metadata_boundary(self, title: str | None = None) -> int:
        """Start a fresh live fingerprint window and invalidate stale identification work."""
        with self._lock:
            if not self._active or not self._active.media.capabilities.live:
                raise UnsupportedAction("Metadata boundaries apply only to live streams")
            if title:
                self._active.media.title = title
            self._active.reset_fingerprint()
            self._identity_generation += 1
            return self._identity_generation

    def _handle_stream_metadata(self, session: DecoderSession, title: str) -> None:
        with self._lock:
            if self._active is not session:
                return
            self._stream_metadata["title"] = title
        self.notify_metadata_boundary(title)
        self._publish_metadata(title)

    def stop(self) -> None:
        with self._lock:
            self._watch_stop.set()
            active, next_session = self._active, self._next
            self._active = None
            self._next = None
            self._resolved = None
            self._stream_metadata = {}
            self._completed_media = None
            self._completed_position = 0.0
            self._completed_duration = None
            if active or next_session:
                self._state = PlaybackState.STOPPING
        for session in (active, next_session):
            if session:
                session.stop()
        with self._lock:
            self._state = PlaybackState.IDLE

    def close(self) -> None:
        self.stop()
        with self._output_switch_lock:
            with self._lock:
                stream = self._stream
                self._stream = None
                self._output_device = None
            self._close_output_stream(stream)

    def recover_output(self, device: OutputDeviceInfo | None = None) -> None:
        """Recreate the stream on the current operating-system default output."""
        self._replace_output(device or self.default_output_device(), force=True)

    def report_output_error(self, message: str) -> None:
        with self._lock:
            self._error = message

    def snapshot(self) -> PlaybackSnapshot:
        with self._lock:
            active = self._active
            completed = self._completed_media if active is None else None
            media = active.media if active else completed or self._prepared
            position = active.position if active else self._completed_position
            return PlaybackSnapshot(
                state=self._state,
                position=position,
                duration=active.media.duration if active else self._completed_duration,
                buffered_seconds=active.buffered_seconds if active else 0.0,
                volume=self._volume,
                muted=self._muted,
                error=self._error,
                media=media,
                replaygain_db=getattr(active, "program_gain_db", 0.0) if active else 0.0,
                live_leveling=bool(active and active.media.capabilities.live and self.live_leveling),
                stream_title=str(self._stream_metadata.get("title")) if self._stream_metadata.get("title") else None,
                stream_metadata=dict(self._stream_metadata),
                output_device=self._output_device.name if self._output_device else None,
                output_backend=self._output_device.route if self._output_device else None,
                current_chapter=media.chapter_at(position) if media else None,
            )


def launch_ffplay(media: MediaRef, *, ffplay_bin: str | None = None) -> subprocess.Popen:
    """Launch FFplay as an explicitly external diagnostic/video fallback."""
    executable = find_executable("ffplay", ffplay_bin)
    source = resolve_input(media)
    try:
        return subprocess.Popen(
            [executable, "-hide_banner", "-autoexit", source],
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            start_new_session=os.name != "nt",
        )
    except OSError as error:
        raise PlaybackError(f"FFplay could not start: {error}") from error
