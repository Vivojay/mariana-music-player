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
import uuid
from array import array
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
import sounddevice

from .equalizer import EqualizerProcessor
from .media_details import normalized_provider_metadata
from .models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState, PlayRegion, canonical_uri
from .output_devices import OutputDeviceInfo, default_output_device
from .playback_diagnostics import operation, record
from .recipe_mix import CommittedOverlap, CommittedProgramEvent, PreparedRecipeMix, RecipeMixRuntime, RecipeMixSpec
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


class StemResourceLease(Protocol):
    """Backend ownership only; releasing can touch storage and is never callback work."""

    paths: tuple[Path, ...]

    def retain(self) -> StemResourceLease: ...
    def release(self) -> None: ...


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
        input_sources: Sequence[Path | str] | None = None,
        resource_lease: StemResourceLease | None = None,
    ):
        self.media = media
        self.resolved = resolved
        self.ffmpeg = find_executable("ffmpeg", ffmpeg_bin)
        self.start_at = max(0.0, start_at)
        self.max_buffer_bytes = int(max_buffer_seconds * SAMPLE_RATE * BYTES_PER_FRAME)
        self.audio_filter = audio_filter
        self.program_gain_db = float(program_gain_db)
        self.program_gain = 10.0 ** (self.program_gain_db / 20.0)
        self.input_sources = tuple(str(Path(value).resolve()) for value in (input_sources or ()))
        self.resource_lease = resource_lease
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
        source = "" if self.input_sources else (
            self.resolved.playback_uri if self.resolved else resolve_input(self.media)
        )
        if not self.input_sources and self.resolved and self.resolved.metadata.get("credential_ref"):
            from .credentials import ListenerAuthTunnel

            self._auth_tunnel = ListenerAuthTunnel(
                source,
                str(self.resolved.metadata.get("credential_username") or "source"),
                str(self.resolved.metadata["credential_ref"]),
            )
            source = self._auth_tunnel.start()
        log_level = "info" if self.media.capabilities.live else "warning"
        command = [self.ffmpeg, "-hide_banner", "-loglevel", log_level, "-nostdin"]
        if self.input_sources:
            for stem_source in self.input_sources:
                if self.start_at:
                    command += ["-ss", f"{self.start_at:.3f}"]
                command += ["-i", stem_source]
            if len(self.input_sources) == 1:
                command += ["-map", "0:a:0"]
            else:
                inputs = "".join(f"[{index}:a:0]" for index in range(len(self.input_sources)))
                command += [
                    "-filter_complex",
                    f"{inputs}amix=inputs={len(self.input_sources)}:duration=longest:dropout_transition=0:normalize=0[stem]",
                    "-map",
                    "[stem]",
                ]
        else:
            if self.start_at and self.media.capabilities.seekable:
                command += ["-ss", f"{self.start_at:.3f}"]
        if not self.input_sources and source.startswith(("http://", "https://")):
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
        if not self.input_sources:
            command += ["-i", source, "-map", "0:a:0"]
        command += [
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
        lease, self.resource_lease = self.resource_lease, None
        if lease is not None:
            lease.release()


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


MAX_CROSSFADE_SECONDS = 30.0


def _validated_crossfade_seconds(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("Crossfade duration must be a number from 0 to 30 seconds")
    seconds = float(value)
    if not math.isfinite(seconds) or not 0 <= seconds <= MAX_CROSSFADE_SECONDS:
        raise ValueError("Crossfade duration must be a number from 0 to 30 seconds")
    return seconds


def _equal_power_crossfade_gains(fraction: float) -> tuple[float, float]:
    """Return cosine/sine gains for a perceptually even two-source transition."""
    progress = min(1.0, max(0.0, float(fraction)))
    angle = progress * math.pi / 2.0
    return math.cos(angle), math.sin(angle)


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
        play_region_provider: Callable[[MediaRef], PlayRegion | None] | None = None,
        playback_event_sink: Callable[..., bool] | None = None,
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.crossfade_seconds = _validated_crossfade_seconds(crossfade_seconds)
        self.output_factory = output_factory or sounddevice.OutputStream
        self._native_output = output_factory is None and output_device_provider is None
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
        self.play_region_provider = play_region_provider
        self._playback_event_sink = playback_event_sink
        self._lock = threading.RLock()
        self._output_switch_lock = threading.Lock()
        self._active_media_publish_lock = threading.RLock()
        self._active: DecoderSession | None = None
        self._next: DecoderSession | None = None
        self._active_region: PlayRegion | None = None
        self._next_region: PlayRegion | None = None
        self._stream: OutputStream | None = None
        self._output_device: OutputDeviceInfo | None = None
        self._output_interrupted = False
        self._state = PlaybackState.IDLE
        self._volume = 1.0
        self.equalizer = EqualizerProcessor(SAMPLE_RATE)
        self._automation_gain = 1.0
        self._muted = False
        self._error: str | None = None
        self._prepared: MediaRef | None = None
        self._resolved: ResolvedMedia | None = None
        self._request_generation = 0
        self._completed_media: MediaRef | None = None
        self._completed_position = 0.0
        self._completed_duration: float | None = None
        self._completed_region: PlayRegion | None = None
        self.on_complete: Callable[[MediaRef], None] | None = None
        self.on_failure: Callable[[MediaRef, MediaFailure], None] | None = None
        self._watch_stop = threading.Event()
        self._identity_generation = 0
        self._program_sinks: list[Callable[[object, int], None]] = []
        self._identification_sinks: list[
            Callable[[object, int, str, str, str, float, bool], None]
        ] = []
        self._metadata_sinks: list[Callable[[str | None], None]] = []
        self._active_media_sinks: list[
            Callable[[MediaRef | None, ResolvedMedia | None], None]
        ] = []
        self._stream_metadata: dict[str, object] = {}
        self._playback_session_id: str | None = None
        self._stem_session: DecoderSession | None = None
        self._stem_previous: DecoderSession | None = None
        self._stem_media_id: str | None = None
        self._stem_sources: tuple[str, ...] = ()
        self._stem_transition_frames = 0
        self._stem_transition_total = max(1, round(SAMPLE_RATE * 0.05))
        self._audio_block_lock = threading.Lock()
        self._prepared_recipe_mix: PreparedRecipeMix | None = None
        self._pending_recipe_mix: PreparedRecipeMix | None = None
        self._recipe_mix: RecipeMixRuntime | None = None
        self._recipe_mix_worker: threading.Thread | None = None
        self._recipe_mix_worker_stop = threading.Event()
        self._recipe_capture_sink: Callable[[CommittedProgramEvent], bool] | None = None
        self._captured_transition: tuple[DecoderSession, DecoderSession] | None = None

    def _program_snapshot_locked(self, *, action: str = "snapshot", origin: str = "system",
                                 play_kind: str | None = None) -> CommittedProgramEvent:
        active, incoming = self._active, self._next
        overlap = None
        if active is not None and incoming is not None and active.media.duration is not None:
            remaining = active.media.duration - active.position
            window = min(self.crossfade_seconds, active.media.duration - active.start_at,
                         max(0, (incoming.media.duration or 0) - incoming.start_at))
            if window > 0 and 0 < remaining <= window:
                total = max(1, round(window * SAMPLE_RATE))
                overlap = CommittedOverlap(
                    incoming.media.stable_id, incoming.position, total,
                    min(total - 1, max(0, round((window - remaining) * SAMPLE_RATE))),
                    active.program_gain_db, incoming.program_gain_db,
                )
        return CommittedProgramEvent(
            action, active.media.stable_id if active is not None else None, self._playback_session_id,
            active.position if active is not None else 0,
            active.program_gain_db if active is not None else None,
            self._state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}, origin, play_kind, overlap,
        )

    def recipe_capture_snapshot(self) -> CommittedProgramEvent:
        with self._lock:
            return self._program_snapshot_locked()

    def _safe_program_snapshot_locked(
        self, *, action: str, origin: str, play_kind: str | None = None,
    ) -> CommittedProgramEvent:
        try:
            return self._program_snapshot_locked(action=action, origin=origin, play_kind=play_kind)
        except Exception:
            # Bad optional capture metadata must neither interrupt output nor
            # leave a recording falsely claiming to represent the operation.
            return CommittedProgramEvent('unsupported', None, None, 0, None, False)

    def begin_recipe_capture(
        self, sink: Callable[[CommittedProgramEvent], bool], initialize: Callable[[CommittedProgramEvent], None],
    ) -> None:
        """Queue the initial state before any later committed action can follow it."""
        with self._lock:
            snapshot = self._program_snapshot_locked()
            initialize(snapshot)
            self._recipe_capture_sink = sink
            self._captured_transition = (self._active, self._next) if snapshot.overlap is not None \
                and self._active is not None and self._next is not None else None

    def _capture_program_event(self, event: CommittedProgramEvent) -> None:
        sink = self._recipe_capture_sink
        if sink is not None:
            with suppress(Exception):
                sink(event)

    def prepare_recipe_mix(
        self, spec: RecipeMixSpec, *, cancelled: Callable[[], bool] = lambda: False, timeout: float = 10,
    ) -> PreparedRecipeMix:
        """Prepare a verified pair off the callback without replacing audible media."""
        spec.validate(SAMPLE_RATE)
        if not math.isfinite(timeout) or not 0 < timeout <= 30:
            raise ValueError("Preparation timeout must be between zero and 30 seconds")
        for source in (spec.outgoing, spec.incoming):
            if source is not None and self._play_region(source.media) is not None:
                raise UnsupportedAction("Recipe mixes do not support preferred regions")
        with self._lock:
            if self._pending_recipe_mix is not None:
                raise UnsupportedAction("A recipe mix is already awaiting commitment")
            if self._stem_session is not None or self._stem_previous is not None:
                raise UnsupportedAction("Restore the original mix before recipe replay")
            old = self._prepared_recipe_mix
            self._prepared_recipe_mix = None
            generation = self._begin_media_request()
        if old is not None:
            self.discard_recipe_mix(old)
        deadline = time.monotonic() + timeout
        sessions: list[DecoderSession] = []
        try:
            for source in (spec.outgoing, spec.incoming):
                if source is None:
                    continue
                self._check_recipe_preparation(generation, cancelled, deadline)
                session = DecoderSession(
                    source.media, resolved=source.resolved, ffmpeg_bin=self.ffmpeg_bin,
                    start_at=source.position_seconds, program_gain_db=source.program_gain_db,
                )
                sessions.append(session)
                session.start()
                minimum = min(.15, max(1 / SAMPLE_RATE, (source.media.duration or 0) - source.position_seconds))
                while session.buffered_seconds + 1 / SAMPLE_RATE < minimum and not session.eof:
                    self._check_recipe_preparation(generation, cancelled, deadline)
                    session.wait_for_buffer(minimum_seconds=minimum, timeout=.05)
                if session.failed or session.buffered_seconds <= 0:
                    raise PlaybackError("Recipe source produced no verified playable audio")
            self._check_recipe_preparation(generation, cancelled, deadline)
            prepared = PreparedRecipeMix(
                self, generation, sessions[0], sessions[1] if len(sessions) == 2 else None,
                spec, uuid.uuid4().hex, uuid.uuid4().hex if len(sessions) == 2 else None,
            )
            with self._lock:
                if generation != self._request_generation:
                    raise PlaybackError("Recipe preparation was replaced")
                self._prepared_recipe_mix = prepared
            return prepared
        except Exception:
            for session in sessions:
                session.stop()
            raise

    def _check_recipe_preparation(
        self, generation: int, cancelled: Callable[[], bool], deadline: float,
    ) -> None:
        if cancelled() or time.monotonic() >= deadline:
            raise PlaybackError("Recipe preparation was cancelled or timed out")
        with self._lock:
            if generation != self._request_generation:
                raise PlaybackError("Recipe preparation was replaced")

    def discard_recipe_mix(self, prepared: PreparedRecipeMix) -> None:
        """Retire only an uncommitted single-use preparation, outside the callback."""
        if prepared.owner is not self:
            raise UnsupportedAction("Recipe preparation belongs to another player")
        with self._lock:
            if prepared.status in {"committed", "discarded"}:
                return
            if self._pending_recipe_mix is prepared:
                self._pending_recipe_mix = None
            if self._prepared_recipe_mix is prepared:
                self._prepared_recipe_mix = None
            prepared.status = "discarded"
            prepared.acknowledged.set()
        for session in (prepared.outgoing, prepared.incoming):
            if session is not None:
                session.stop()

    def commit_recipe_mix(
        self, prepared: PreparedRecipeMix, *, cancelled: Callable[[], bool] = lambda: False, timeout: float = 2,
    ) -> None:
        """Wait outside the callback for a single complete audio-block handoff."""
        if prepared.owner is not self or not math.isfinite(timeout) or not 0 < timeout <= 10:
            raise UnsupportedAction("Invalid recipe preparation or commit deadline")
        deadline = time.monotonic() + timeout
        try:
            self._check_recipe_preparation(prepared.generation, cancelled, deadline)
            prepared.spec.validate(SAMPLE_RATE)
            self._ensure_output(expected_generation=prepared.generation)
            with self._lock:
                if (self._prepared_recipe_mix is not prepared or prepared.status != "prepared"
                        or prepared.generation != self._request_generation):
                    raise PlaybackError("Recipe preparation is stale or already consumed")
                if self._recipe_mix_worker is None:
                    worker = threading.Thread(target=self._watch_recipe_mix, name="mariana-recipe-mix", daemon=True)
                    worker.start()
                    self._recipe_mix_worker = worker
                prepared.status = "submitted"
                self._pending_recipe_mix = prepared
            while not prepared.acknowledged.wait(.01):
                self._check_recipe_preparation(prepared.generation, cancelled, deadline)
            self._check_recipe_preparation(prepared.generation, cancelled, deadline)
            with self._lock:
                if prepared.status != "committed" or prepared.generation != self._request_generation:
                    raise PlaybackError("Recipe mix did not commit")
            self._publish_active_media_for_session(prepared.outgoing, prepared.outgoing.media, prepared.outgoing.resolved)
            self._publish_metadata(prepared.outgoing.media.title, session=prepared.outgoing)
        except Exception:
            self.discard_recipe_mix(prepared)
            raise
        finally:
            # A stop/replacement after callback acknowledgement must not strand
            # the old pair which the callback already detached.
            with self._lock:
                retired, prepared.retired = prepared.retired, ()
            for session in retired:
                session.stop()

    def _install_recipe_mix(self) -> None:
        """Called only at the start of a serialized audio block; no external work."""
        with self._lock:
            prepared = self._pending_recipe_mix
            if prepared is None:
                return
            self._pending_recipe_mix = None
            if prepared.generation != self._request_generation or prepared.status != "submitted":
                prepared.status = "rejected"
                prepared.acknowledged.set()
                return
            old_mix = self._recipe_mix
            retired = (self._active, self._next, old_mix.promoted if old_mix is not None else None)
            prepared.retired = tuple(dict.fromkeys(session for session in retired if session is not None))
            self._active, self._next = prepared.outgoing, prepared.incoming
            self._prepared, self._resolved = prepared.outgoing.media, prepared.outgoing.resolved
            self._active_region = self._next_region = None
            self._completed_media = None
            self._completed_position = 0
            self._completed_duration = None
            self._completed_region = None
            self._playback_session_id = prepared.playback_session_id
            self._recipe_mix = RecipeMixRuntime(
                prepared.outgoing, prepared.incoming, prepared.spec.duration_frames,
                prepared.spec.elapsed_frames, prepared.playback_session_id, prepared.incoming_session_id,
            )
            self._state = PlaybackState.PAUSED if prepared.spec.paused else (
                PlaybackState.CROSSFADING if prepared.incoming is not None else PlaybackState.PLAYING
            )
            self._error = None
            self._prepared_recipe_mix = None
            prepared.status = "committed"
            prepared.acknowledged.set()

    def _watch_recipe_mix(self) -> None:
        """Retire promotion resources and publish identity away from audio callbacks."""
        while not self._recipe_mix_worker_stop.wait(.01):
            with self._lock:
                mix = self._recipe_mix
                retired = mix.promoted if mix is not None else None
                if mix is not None:
                    mix.promoted = None
                active = self._active
            if retired is not None:
                retired.stop()
                if mix is not None and active is not None and active is mix.outgoing:
                    self._publish_active_media_for_session(active, active.media, active.resolved)
                    self._publish_metadata(active.media.title, session=active)

    def set_recipe_program_gain(self, gain_db: float) -> None:
        """Apply a recorded effective source gain without changing local volume."""
        if isinstance(gain_db, bool) or not math.isfinite(gain_db) or not -120 <= gain_db <= 60:
            raise ValueError("Invalid recipe program gain")
        with self._lock:
            if self._recipe_mix is None or self._recipe_mix.incoming is not None:
                raise UnsupportedAction("Effective gain requires a single restored recipe source")
            self._recipe_mix.outgoing.program_gain_db = gain_db
            self._recipe_mix.outgoing.program_gain = 10 ** (gain_db / 20)

    def _capture_playback_event(
        self,
        action: str,
        *,
        origin: str,
        position_seconds: float,
        media: MediaRef | None = None,
        session_id: str | None = None,
        play_kind: str | None = None,
        seek_from_seconds: float | None = None,
        seek_to_seconds: float | None = None,
    ) -> None:
        """Submit a best-effort event without allowing capture to affect playback."""
        sink = self._playback_event_sink
        if sink is None and self._recipe_capture_sink is None:
            return
        with self._lock:
            current_media = media or (self._active.media if self._active else None)
            current_session_id = session_id or self._playback_session_id
            program_event = self._safe_program_snapshot_locked(action=action, origin=origin, play_kind=play_kind) \
                if self._recipe_capture_sink is not None else None
        if current_media is None or current_session_id is None:
            return
        if (program_event is not None and program_event.stable_id == current_media.stable_id
                and program_event.session_id == current_session_id):
            self._capture_program_event(program_event)
        elif self._recipe_capture_sink is not None:
            self._capture_program_event(CommittedProgramEvent('unsupported', None, None, 0, None, False))
        if sink is None:
            return
        try:
            sink(
                stable_id=current_media.stable_id,
                session_id=current_session_id,
                action=action,
                origin=origin,
                position_seconds=position_seconds,
                play_kind=play_kind,
                seek_from_seconds=seek_from_seconds,
                seek_to_seconds=seek_to_seconds,
            )
        except Exception:
            # Personal interaction capture is deliberately non-critical.
            return

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

    def stem_analysis_source(self, media_id: str) -> tuple[str, dict[str, str]]:
        """Return the current private decoder input to a trusted backend worker."""
        with self._lock:
            active = self._active
            resolved = self._resolved
            if active is None or active.media.stable_id != media_id:
                raise UnsupportedAction("Current media changed; prepare stems again")
            if active.media.capabilities.live or not active.media.capabilities.finite:
                raise UnsupportedAction("Stem preparation requires finite media")
            if active.media.source == MediaSource.LOCAL:
                return active.media.original_uri, {}
            if resolved is None:
                raise UnsupportedAction("The current online source cannot be prepared for stems")
            return resolved.playback_uri, dict(resolved.headers)

    def stem_monitor_status(self) -> dict[str, object]:
        with self._lock:
            return {
                "active": self._stem_session is not None,
                "transitioning": self._stem_previous is not None,
                "media_id": self._stem_media_id,
                "source_count": len(self._stem_sources),
            }

    @operation("stems.monitor")
    def configure_stem_monitor(
        self, media_id: str, sources: Sequence[Path | str], *, lease: StemResourceLease | None = None,
    ) -> None:
        """Consume a lease, retaining it until its prepared decoder has stopped."""
        transferred: list[DecoderSession] = []
        try:
            self._configure_stem_monitor(media_id, sources, lease=lease, transferred=transferred)
        finally:
            if lease is not None and not transferred:
                lease.release()
            elif transferred:
                candidate = transferred[0]
                with self._lock:
                    owned = candidate is self._stem_session or candidate is self._stem_previous
                if not owned:
                    candidate.stop()

    def _configure_stem_monitor(
        self, media_id: str, sources: Sequence[Path | str], *,
        lease: StemResourceLease | None, transferred: list[DecoderSession],
    ) -> None:
        """Monitor prepared local stems while the original remains playback authority."""
        normalized = tuple(str(Path(value).expanduser().resolve(strict=True)) for value in sources)
        if lease is not None and normalized != tuple(str(path.resolve(strict=True)) for path in lease.paths):
            raise UnsupportedAction("Prepared stem lease does not match its selected files")
        if len(set(normalized)) != len(normalized) or any(not Path(value).is_file() for value in normalized):
            raise UnsupportedAction("Prepared stem files are invalid")
        with self._lock:
            active = self._active
            if active is None or active.media.stable_id != media_id:
                raise UnsupportedAction("Current media changed; select stems for the active item")
            if self._state not in {PlaybackState.PLAYING, PlaybackState.PAUSED}:
                raise UnsupportedAction("Stem monitoring requires playing or paused finite media")
            if active.media.capabilities.live or not active.media.capabilities.finite:
                raise UnsupportedAction("Live media cannot use prepared stem monitoring")
            if normalized == self._stem_sources and self._stem_media_id == media_id:
                return
            retired_transition = self._stem_previous
            if not normalized:
                previous = self._stem_session
                self._stem_session = None
                self._stem_media_id = None
                self._stem_sources = ()
                if self._state == PlaybackState.PAUSED:
                    self._stem_previous = None
                    self._stem_transition_frames = 0
                    self._stop_stem_sessions_async(previous, retired_transition)
                else:
                    self._stem_previous = previous
                    self._stem_transition_frames = self._stem_transition_total if previous else 0
                    if retired_transition and retired_transition is not previous:
                        self._stop_stem_sessions_async(retired_transition)
                return
            media = active.media
            start_at = active.position
            program_gain_db = active.program_gain_db

        replacement = DecoderSession(
            media,
            ffmpeg_bin=self.ffmpeg_bin,
            start_at=start_at,
            program_gain_db=program_gain_db,
            input_sources=normalized,
            resource_lease=lease,
        )
        transferred.append(replacement)
        try:
            replacement.start()
        except Exception:
            replacement.stop()
            raise
        if not replacement.wait_for_buffer(minimum_seconds=0.35, timeout=10):
            replacement.stop()
            raise PlaybackError(replacement.error or "Prepared stems produced no playable audio")

        deadline = time.monotonic() + 5
        while True:
            media_changed = False
            with self._lock:
                if self._active is not active or active.media.stable_id != media_id:
                    media_changed = True
                else:
                    frames_to_skip = max(0, round((active.position - replacement.position) * SAMPLE_RATE))
                    buffered_frames = round(replacement.buffered_seconds * SAMPLE_RATE)
                    if buffered_frames >= frames_to_skip + 1024:
                        replacement.read(frames_to_skip)
                        previous = self._stem_session
                        stale_previous = self._stem_previous
                        self._stem_previous = previous
                        self._stem_session = replacement
                        self._stem_media_id = media_id
                        self._stem_sources = normalized
                        self._stem_transition_frames = self._stem_transition_total
                        break
            if media_changed:
                replacement.stop()
                raise UnsupportedAction("Current media changed while stem monitoring was prepared")
            if time.monotonic() >= deadline:
                replacement.stop()
                raise PlaybackError("Prepared stems could not synchronize with current playback")
            time.sleep(0.01)
        if stale_previous and stale_previous is not previous:
            threading.Thread(
                target=stale_previous.stop,
                name="mariana-stem-cleanup",
                daemon=True,
            ).start()

    def _play_region(self, media: MediaRef) -> PlayRegion | None:
        if self.play_region_provider is None:
            return None
        region = self.play_region_provider(media)
        if region is None or not region.active:
            return None
        duration = media.duration
        if media.capabilities.live or not media.capabilities.finite or duration is None:
            raise UnsupportedAction("Preferred playback bounds require finite media with a known duration")
        try:
            duration = float(duration)
        except (TypeError, ValueError, OverflowError) as error:
            raise UnsupportedAction("Preferred playback bounds require a valid media duration") from error
        start = region.start_seconds
        end = region.end_seconds
        if not math.isfinite(duration) or duration <= 0:
            raise UnsupportedAction("Preferred playback bounds require a valid media duration")
        if start is not None and (not math.isfinite(start) or start < 0 or start >= duration):
            raise UnsupportedAction("Saved preferred playback start is invalid for this media")
        if end is not None and (not math.isfinite(end) or end <= 0 or end > duration):
            raise UnsupportedAction("Saved preferred playback end is invalid for this media")
        if start is not None and end is not None and end <= start:
            raise UnsupportedAction("Saved preferred playback bounds are invalid for this media")
        return region

    @staticmethod
    def _validate_resolved_input(media: MediaRef, resolved: ResolvedMedia) -> None:
        """Private backend handoff; never accepts a renderer-provided transport."""
        if resolved.media is not media:
            raise UnsupportedAction("Resolved input does not belong to the selected media")
        if resolved.expired:
            raise UnsupportedAction("Resolved input expired; resolve the source again")

    @operation("prepare", priority=4)
    def prepare(self, media: MediaRef, *, probe: bool = True, resolved: ResolvedMedia | None = None) -> MediaRef:
        generation = self._begin_media_request()
        return self._prepare_media(media, probe=probe, resolved=resolved, generation=generation)

    def _begin_media_request(self) -> int:
        with self._lock:
            self._request_generation += 1
            return self._request_generation

    def reserve_media_request(self) -> int:
        """Reserve backend ownership before an outer supervisor starts provider work."""
        return self._begin_media_request()

    def reserve_media_request_if_current(self, expected: int) -> int | None:
        if type(expected) is not int:
            return None
        with self._lock:
            if expected != self._request_generation:
                return None
            return self._begin_media_request()

    def media_request_is_current(self, request: int) -> bool:
        if type(request) is not int:
            return False
        with self._lock:
            return request == self._request_generation

    def stop_reserved_media_request(self, request: int) -> bool:
        """Stop only the admitted supervisor generation, never a newer request."""
        if type(request) is not int:
            raise ValueError("Playback request generation must be an integer")
        return self._stop_playback(expected_generation=request)

    def _prepare_media(
        self, media: MediaRef, *, probe: bool, resolved: ResolvedMedia | None, generation: int,
    ) -> MediaRef:
        if resolved is not None:
            self._validate_resolved_input(media, resolved)
        with self._lock:
            if generation != self._request_generation:
                raise PlaybackError("Playback attempt was replaced")
            self._state = PlaybackState.RESOLVING
            self._error = None
            self._completed_media = None
            self._completed_position = 0.0
            self._completed_duration = None
            self._completed_region = None
        try:
            resolved = resolved if resolved is not None else self.resolvers.resolve(media)
            with self._lock:
                if generation != self._request_generation:
                    raise PlaybackError("Playback attempt was replaced")
            media.capabilities = resolved.capabilities
            if probe and media.source != MediaSource.YOUTUBE:
                media = probe_media(
                    media,
                    source=resolved.playback_uri,
                    headers=resolved.headers,
                    ffprobe_bin=self.ffprobe_bin,
                )
            with self._lock:
                if generation != self._request_generation:
                    raise PlaybackError("Playback attempt was replaced")
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
            provider_metadata = normalized_provider_metadata(resolved.metadata.get("provider_metadata"))
            if provider_metadata:
                # Engagement counts are inspection facts, not durable identity.
                # Keep them with this resolved playback without persisting any
                # extractor response, headers, or temporary stream references.
                media.resolver_data["provider_metadata"] = provider_metadata
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
            with self._lock:
                if generation != self._request_generation:
                    raise PlaybackError("Playback attempt was replaced")
                self._stream_metadata = dict(resolved.metadata.get("icy") or {})
                self._prepared = media
                self._resolved = resolved
            return media
        except Exception as error:
            with self._lock:
                if generation == self._request_generation:
                    self._state = PlaybackState.FAILED
                    self._error = str(error)
            raise

    @operation("play")
    def play(
        self,
        media: MediaRef | None = None,
        *,
        start_at: float = 0,
        probe: bool = True,
        origin: str = "system",
        start_paused: bool = False,
        resolved: ResolvedMedia | None = None,
        request_generation: int | None = None,
    ) -> MediaRef:
        if type(start_paused) is not bool:
            raise ValueError("Paused start must be true or false")
        if resolved is not None and media is None:
            raise UnsupportedAction("Resolved input requires selected media")
        if request_generation is not None:
            if type(request_generation) is not int or not self.media_request_is_current(request_generation):
                raise PlaybackError("Playback attempt was replaced")
            generation = request_generation
        else:
            generation = self._begin_media_request()
        if media is not None:
            self._prepare_media(media, probe=probe, resolved=resolved, generation=generation)
        with self._lock:
            if generation != self._request_generation:
                raise PlaybackError("Playback attempt was replaced")
            if self._prepared is None:
                raise PlaybackError("No media has been prepared")
            prepared, resolved = self._prepared, self._resolved
        region = self._play_region(prepared)
        if region is not None:
            start_at = max(float(start_at), region.start_seconds or 0.0)
            if region.end_seconds is not None:
                start_at = min(start_at, region.end_seconds)
        if not self._stop_playback(expected_generation=generation):
            raise PlaybackError("Playback attempt was replaced")
        media = prepared
        session = None
        try:
            with self._lock:
                if generation != self._request_generation:
                    raise PlaybackError("Playback attempt was replaced")
                self._prepared, self._resolved = prepared, resolved
                # Preserve paused intent before an output callback can consume
                # the replacement decoder.
                self._state = PlaybackState.PAUSED if start_paused else PlaybackState.BUFFERING
                playback_session_id = uuid.uuid4().hex
                self._playback_session_id = playback_session_id
                session = self._new_session(media, start_at=start_at)
                session.on_metadata = lambda title, source=session: self._handle_stream_metadata(source, title)
                self._active = session
                self._active_region = region
                session.start()
        except Exception as error:
            if session is not None:
                session.stop()
            with self._lock:
                if generation == self._request_generation:
                    self._active = None
                    self._active_region = None
                    self._playback_session_id = None
                    self._state = PlaybackState.FAILED
                    self._error = str(error)
            raise
        # Presentation consumers may resolve artwork independently of whether
        # the decoder ultimately produces audio. The session is now the
        # authoritative current-media attempt, and stale observers were already
        # cleared by stop().
        self._publish_active_media_for_session(session, media, resolved)
        if not session.wait_for_buffer():
            error = session.error or "FFmpeg produced no playable audio"
            session.stop()
            with self._lock:
                if self._active is session and generation == self._request_generation:
                    self._state = PlaybackState.FAILED
                    self._error = error
                    self._playback_session_id = None
            raise PlaybackError(error)
        with self._lock:
            current_attempt = self._active is session and generation == self._request_generation
        if not current_attempt:
            session.stop()
            raise PlaybackError("Playback attempt was replaced")
        try:
            self._ensure_output(expected_generation=generation)
        except Exception as error:
            # A decoder that buffered successfully is not a bad media file.
            # Retire this attempt instead of leaving a live decoder in BUFFERING.
            session.stop()
            with self._lock:
                current_attempt = self._active is session and generation == self._request_generation
                if current_attempt:
                    self._active = None
                    self._active_region = None
                    self._playback_session_id = None
                    self._state = PlaybackState.FAILED
                    self._error = "Audio output is unavailable; select an output device and retry"
            if not current_attempt:
                raise PlaybackError("Playback attempt was replaced") from None
            raise MediaFailure(
                FailureCode.OUTPUT_DEVICE, media.source,
                "Audio output is unavailable; select an output device and retry", cause=error,
            ) from None
        with self._lock:
            current_attempt = self._active is session and generation == self._request_generation
            if current_attempt:
                self._state = PlaybackState.PAUSED if start_paused else PlaybackState.PLAYING
                self._capture_playback_event(
                    "play", origin=origin, position_seconds=float(start_at), media=media,
                    session_id=playback_session_id, play_kind="start",
                )
                if start_paused:
                    self._capture_playback_event(
                        "pause", origin=origin, position_seconds=float(start_at),
                        media=media, session_id=playback_session_id,
                    )
                self._watch_stop.clear()
                threading.Thread(target=self._watch_completion, name="mariana-playback-watch", daemon=True).start()
        if not current_attempt:
            session.stop()
            raise PlaybackError("Playback attempt was replaced")
        self._publish_metadata(
            " - ".join(value for value in (media.artist, media.title) if value) or media.title,
            session=session,
        )
        return media

    @operation("prefetch", priority=4)
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
        region = self._play_region(media)
        session = DecoderSession(
            media,
            resolved=resolved,
            ffmpeg_bin=self.ffmpeg_bin,
            start_at=region.start_seconds if region and region.start_seconds is not None else 0.0,
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
            self._next_region = region
        return media

    def clear_prefetch(self) -> None:
        """Discard a queued decoder without disturbing the active item."""
        with self._lock:
            session = self._next
            self._next = None
            self._next_region = None
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
        try:
            return bool(stream is not None and getattr(stream, "active", True))
        except Exception:
            # An invalidated native stream can reject even its status query.
            return False

    def _replace_output(
        self, device: OutputDeviceInfo, *, force: bool = False, expected_generation: int | None = None,
    ) -> None:
        with self._output_switch_lock:
            with self._lock:
                if expected_generation is not None and expected_generation != self._request_generation:
                    raise PlaybackError("Playback attempt was replaced")
                if self.output_stream_active and self._output_device == device and not force:
                    return
                previous = self._stream
                self._stream = None
                self._output_interrupted = True
                self._error = "Audio output is reconnecting"
            try:
                self._close_output_stream(previous)
            except Exception:
                # An invalidated device can reject stop/close. Do not let the
                # obsolete stream prevent opening its replacement.
                record(2, "output_previous.close_failed")
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
                with self._lock:
                    if expected_generation is not None and expected_generation != self._request_generation:
                        raise PlaybackError("Playback attempt was replaced")
                    self._stream = stream
                    self._output_device = device
                    self._output_interrupted = False
                    self._error = None
            except Exception:
                if stream is not None:
                    try:
                        self._close_output_stream(stream)
                    except Exception:
                        record(2, "output_replacement.close_failed")
                raise
    def _ensure_output(self, *, expected_generation: int | None = None) -> None:
        self._open_output(self.default_output_device(), force=False, expected_generation=expected_generation)

    def _open_output(
        self, device: OutputDeviceInfo, *, force: bool, expected_generation: int | None = None,
    ) -> None:
        try:
            self._replace_output(device, force=force, expected_generation=expected_generation)
        except Exception:
            if not self._native_output or device.endpoint_id is None:
                raise
            # Windows' mapper resolves the live default when opened, unlike a
            # stale explicit PortAudio route. Never reinitialize global audio.
            fallback = default_output_device(prefer_system_mapper=True)
            if fallback.index == device.index:
                raise
            self._replace_output(fallback, force=True, expected_generation=expected_generation)

    @staticmethod
    def _stem_samples(session: DecoderSession | None, frames: int) -> np.ndarray | None:
        if session is None:
            return None
        payload = session.read(frames)
        if len(payload) != frames * BYTES_PER_FRAME:
            return None
        samples = np.frombuffer(payload, dtype=np.float32).reshape(-1, CHANNELS)
        return samples * session.program_gain

    def _stop_stem_sessions_async(self, *sessions: DecoderSession | None) -> None:
        unique = tuple({id(session): session for session in sessions if session is not None}.values())
        for session in unique:
            threading.Thread(target=session.stop, name="mariana-stem-cleanup", daemon=True).start()

    def _clear_stem_monitor(self) -> tuple[DecoderSession | None, DecoderSession | None]:
        with self._lock:
            active, previous = self._stem_session, self._stem_previous
            self._stem_session = None
            self._stem_previous = None
            self._stem_media_id = None
            self._stem_sources = ()
            self._stem_transition_frames = 0
        return active, previous

    def _apply_stem_monitor(
        self,
        original: np.ndarray,
        frames: int,
        stem: DecoderSession | None,
        previous: DecoderSession | None,
        remaining: int,
    ) -> np.ndarray:
        """Mix ready local stem PCM without blocking or changing the program feed."""
        if stem is None:
            target = original
        else:
            target = self._stem_samples(stem, frames)
            if target is None:
                with self._lock:
                    # A slow/empty read from a retired selection must not clear
                    # a newer monitor installed while this block was processing.
                    if self._stem_session is stem and self._stem_previous is previous:
                        active, stale = self._clear_stem_monitor()
                    else:
                        active = stale = None
                self._stop_stem_sessions_async(active, stale)
                return original
        if remaining <= 0:
            return target
        prior = self._stem_samples(previous, frames) if previous is not None else original
        if prior is None:
            prior = original
        elapsed = self._stem_transition_total - remaining
        positions = np.arange(frames, dtype=np.float32) + float(elapsed)
        fractions = np.clip(positions / float(self._stem_transition_total), 0.0, 1.0)
        angles = fractions * (math.pi / 2.0)
        mixed = prior * np.cos(angles)[:, None] + target * np.sin(angles)[:, None]
        retire = None
        with self._lock:
            if self._stem_session is stem and self._stem_previous is previous:
                self._stem_transition_frames = max(0, remaining - frames)
                if self._stem_transition_frames == 0:
                    retire = self._stem_previous
                    self._stem_previous = None
        if retire is not None:
            self._stop_stem_sessions_async(retire)
        return mixed

    def _audio_callback(self, outdata, frames, _time_info, _status) -> None:
        if not self._audio_block_lock.acquire(blocking=False):
            if isinstance(outdata, np.ndarray):
                outdata.fill(0)
            else:
                outdata[:] = b"\0" * (frames * BYTES_PER_FRAME)
            return
        try:
            if not self._lock.acquire(blocking=False):
                if isinstance(outdata, np.ndarray):
                    outdata.fill(0)
                else:
                    outdata[:] = b"\0" * (frames * BYTES_PER_FRAME)
                return
            try:
                self._install_recipe_mix()
                handled = self._render_recipe_mix(outdata, frames)
            finally:
                self._lock.release()
            if handled:
                return
            self._render_ordinary_audio(outdata, frames, _time_info, _status)
        finally:
            self._audio_block_lock.release()

    def _render_recipe_mix(self, outdata, frames: int) -> bool:
        with self._lock:
            mix = self._recipe_mix
            if mix is None:
                return False
            if self._state == PlaybackState.PAUSED or self._output_interrupted:
                samples = np.zeros((frames, CHANNELS), dtype=np.float32)
            else:
                samples = mix.render(frames, SAMPLE_RATE, CHANNELS)
                if mix.failed:
                    self._state = PlaybackState.FAILED
                    self._error = "A recipe source ended before its verified boundary"
                elif mix.buffering:
                    self._state = PlaybackState.BUFFERING
                else:
                    self._active, self._next = mix.outgoing, mix.incoming
                    self._playback_session_id = mix.session_id
                    self._prepared, self._resolved = mix.outgoing.media, mix.outgoing.resolved
                    self._state = PlaybackState.CROSSFADING if mix.incoming else PlaybackState.PLAYING
            local_gain = 0 if self._muted else self._volume * self._automation_gain
        self._publish_program(samples, frames)
        processed = self.equalizer.process(samples)
        processed = np.clip(processed * local_gain, -1, 1)
        if isinstance(outdata, np.ndarray):
            outdata[:] = processed
        else:
            outdata[:] = processed.astype(np.float32).tobytes()
        return True

    def _render_ordinary_audio(self, outdata, frames, _time_info, _status) -> None:
        size = frames * BYTES_PER_FRAME
        with self._lock:
            active = self._active
            next_session = self._next
            state = self._state
            active_region = self._active_region
            next_region = self._next_region
            crossfade_seconds = self.crossfade_seconds
            local_gain = 0.0 if self._muted else self._volume * self._automation_gain
            output_interrupted = self._output_interrupted
            stem_session = self._stem_session
            stem_previous = self._stem_previous
            stem_transition_frames = self._stem_transition_frames
            playback_session_id = self._playback_session_id
        if _status:
            with self._lock:
                self._error = f"Audio output reported: {_status}"
        numpy_output = isinstance(outdata, np.ndarray)
        if not active or state == PlaybackState.PAUSED or output_interrupted:
            if numpy_output:
                outdata.fill(0)
            else:
                outdata[:] = b"\0" * size
            self._publish_program(outdata, frames)
            return
        crossfade = False
        fraction = 0.0
        region_end = active_region.end_seconds if active_region else None
        effective_end = region_end if region_end is not None else active.media.duration
        read_frames = frames
        if region_end is not None:
            remaining_frames = max(0, math.ceil((region_end - active.position) * SAMPLE_RATE))
            read_frames = min(frames, remaining_frames)
            if read_frames == 0:
                if numpy_output:
                    outdata.fill(0)
                else:
                    outdata[:] = b"\0" * size
                self._publish_program(outdata, frames)
                self._finish_active(active)
                return
        crossfade_window = crossfade_seconds
        if crossfade_window > 0 and effective_end is not None:
            crossfade_window = min(
                crossfade_window,
                max(0.0, effective_end - float(getattr(active, "start_at", 0.0))),
            )
        if crossfade_window > 0 and next_session and next_session.media.duration is not None:
            next_end = next_region.end_seconds if next_region and next_region.end_seconds is not None \
                else next_session.media.duration
            crossfade_window = min(
                crossfade_window,
                max(0.0, next_end - float(getattr(next_session, "start_at", 0.0))),
            )
        if (
            next_session
            and crossfade_window > 0
            and effective_end is not None
            and active.media.capabilities.finite
            and not active.media.capabilities.live
            and next_session.media.capabilities.finite
            and not next_session.media.capabilities.live
            and effective_end - active.position <= crossfade_window
        ):
            crossfade = True
            fraction = min(1.0, max(0.0, 1 - (effective_end - active.position) / crossfade_window))
        outgoing_gain, incoming_gain = _equal_power_crossfade_gains(fraction) if crossfade else (1.0, 0.0)
        capture_start_position = active.position
        incoming_start_position = next_session.position if crossfade and next_session is not None else 0.0
        transition_event = None
        if crossfade and next_session is not None and self._recipe_capture_sink is not None \
                and self._captured_transition != (active, next_session):
            with self._lock:
                if self._active is active and self._next is next_session:
                    transition_event = self._safe_program_snapshot_locked(action='transition', origin='automatic')
        first = active.read(read_frames)
        decoded_frames = len(first) // BYTES_PER_FRAME
        if numpy_output:
            outdata.fill(0)
            first_samples = np.frombuffer(first, dtype=np.float32).reshape(-1, CHANNELS)
            count = min(frames, first_samples.shape[0])
            if count:
                np.multiply(
                    first_samples[:count],
                    getattr(active, "program_gain", 1.0) * outgoing_gain,
                    out=outdata[:count],
                )
            if crossfade and next_session:
                second = next_session.read(frames)
                second_samples = np.frombuffer(second, dtype=np.float32).reshape(-1, CHANNELS)
                second_count = min(frames, second_samples.shape[0])
                if second_count:
                    outdata[:second_count] += (
                        second_samples[:second_count]
                        * getattr(next_session, "program_gain", 1.0)
                        * incoming_gain
                    )
                np.clip(outdata, -1.0, 1.0, out=outdata)
        elif crossfade and next_session:
            second = next_session.read(frames)
            payload = _mix_pcm(
                first,
                second,
                getattr(active, "program_gain", 1.0) * outgoing_gain,
                getattr(next_session, "program_gain", 1.0) * incoming_gain,
                size,
            )
            with self._lock:
                self._state = PlaybackState.CROSSFADING
        else:
            payload = _scale_pcm(first, getattr(active, "program_gain", 1.0)).ljust(size, b"\0")
        if crossfade:
            with self._lock:
                self._state = PlaybackState.CROSSFADING
            expected_outgoing = min(read_frames, max(0, round(
                ((effective_end or capture_start_position) - capture_start_position) * SAMPLE_RATE,
            )))
            expected_incoming = min(frames, max(0, round(
                (((next_session.media.duration or incoming_start_position) if next_session else incoming_start_position)
                 - incoming_start_position) * SAMPLE_RATE,
            )))
            if (self._recipe_capture_sink is not None
                    and (decoded_frames < expected_outgoing or len(second) // BYTES_PER_FRAME < expected_incoming)):
                # Ordinary mixing may consume unequal buffers. That policy is
                # unchanged, but such a passage cannot claim faithful replay.
                self._capture_program_event(CommittedProgramEvent('unsupported', None, None, 0, None, False))
            elif transition_event is not None:
                if (next_session is not None and transition_event.overlap is not None
                        and decoded_frames > 0 and len(second) > 0):
                    self._captured_transition = (active, next_session)
                    self._capture_program_event(transition_event)
                else:
                    self._capture_program_event(CommittedProgramEvent('unsupported', None, None, 0, None, False))
        elif state == PlaybackState.CROSSFADING:
            with self._lock:
                if self._active is active and self._state == PlaybackState.CROSSFADING:
                    self._state = PlaybackState.PLAYING
        program = outdata if numpy_output else np.frombuffer(payload, dtype=np.float32).reshape(-1, CHANNELS)
        if decoded_frames and playback_session_id:
            self._publish_identification_pcm(
                program,
                decoded_frames,
                active.media.stable_id,
                playback_session_id,
                f"decoder-{id(active):x}",
                capture_start_position,
                crossfade,
            )
        self._publish_program(outdata if numpy_output else payload, frames)
        if crossfade and (stem_session is not None or stem_previous is not None):
            active_stem, previous_stem = self._clear_stem_monitor()
            self._stop_stem_sessions_async(active_stem, previous_stem)
            stem_session = stem_previous = None
            stem_transition_frames = 0
        local_samples = self._apply_stem_monitor(
            program,
            frames,
            stem_session,
            stem_previous,
            stem_transition_frames,
        )
        if numpy_output:
            if local_samples is not outdata:
                outdata[:] = local_samples
            outdata[:] = self.equalizer.process(outdata)
            np.multiply(outdata, local_gain, out=outdata)
            np.clip(outdata, -1.0, 1.0, out=outdata)
        else:
            processed = self.equalizer.process(local_samples)
            payload = processed.astype(np.float32).tobytes()
            payload = _scale_pcm(payload, local_gain)
            outdata[:] = payload[:size]
        if (region_end is not None and active.position >= region_end) or (
            active.eof and active.buffered_seconds == 0
        ):
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
                failure.request_generation = self._request_generation
                stem_active, stem_previous = self._stem_session, self._stem_previous
                self._stem_session = None
                self._stem_previous = None
                self._stem_media_id = None
                self._stem_sources = ()
                self._stem_transition_frames = 0
                self._active = None
                self._active_region = None
                self._playback_session_id = None
                self._state = PlaybackState.FAILED
                self._error = str(failure)
            threading.Thread(target=active.stop, name="mariana-decoder-cleanup", daemon=True).start()
            self._stop_stem_sessions_async(stem_active, stem_previous)
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
        promoted: DecoderSession | None = None
        promoted_session_id: str | None = None
        with self._lock:
            if self._active is not expected:
                return
            completed = expected
            completed_region = self._active_region
            stem_active, stem_previous = self._stem_session, self._stem_previous
            self._stem_session = None
            self._stem_previous = None
            self._stem_media_id = None
            self._stem_sources = ()
            self._stem_transition_frames = 0
            if self._next:
                self._active = self._next
                promoted = self._active
                self._next = None
                self._active_region = self._next_region
                self._next_region = None
                self._state = PlaybackState.PLAYING
                promoted_session_id = uuid.uuid4().hex
                self._playback_session_id = promoted_session_id
                self._completed_media = None
                self._completed_position = 0.0
                self._completed_duration = None
                self._completed_region = None
                self._capture_playback_event(
                    "play",
                    origin="automatic",
                    position_seconds=promoted.position,
                    media=promoted.media,
                    session_id=promoted_session_id,
                    play_kind="start",
                )
            else:
                self._completed_media = completed.media
                self._completed_duration = completed.media.duration
                self._completed_position = (
                    completed_region.end_seconds
                    if completed_region and completed_region.end_seconds is not None
                    else completed.media.duration
                    if completed.media.duration is not None
                    else completed.position
                )
                self._completed_region = completed_region
                self._active = None
                self._active_region = None
                self._playback_session_id = None
                self._state = PlaybackState.IDLE
        threading.Thread(target=completed.stop, name="mariana-decoder-cleanup", daemon=True).start()
        self._stop_stem_sessions_async(stem_active, stem_previous)
        if promoted is not None or self.on_complete:
            threading.Thread(
                target=self._publish_completion,
                args=(completed.media, promoted),
                name="mariana-playback-complete",
                daemon=True,
            ).start()

    def _publish_completion(self, completed: MediaRef, promoted: DecoderSession | None) -> None:
        """Notify presentation and queue consumers on the completion worker."""
        if promoted is not None:
            self._publish_active_media_for_session(
                promoted,
                promoted.media,
                getattr(promoted, "resolved", None),
            )
        if self.on_complete:
            self.on_complete(completed)

    def _watch_completion(self) -> None:
        while not self._watch_stop.wait(0.1):
            with self._lock:
                active = self._active
                region = self._active_region
                if self._recipe_mix is not None:
                    continue
            if active is None:
                return
            if (region and region.end_seconds is not None and active.position >= region.end_seconds) or (
                active.eof and active.buffered_seconds == 0
            ):
                self._finish_active(active)
                return

    @operation("pause")
    def pause(self, *, origin: str = "system") -> None:
        with self._lock:
            if self._state not in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}:
                raise UnsupportedAction("Nothing is currently playing")
            self._state = PlaybackState.PAUSED
            media = self._active.media if self._active else None
            position = self._active.position if self._active else 0.0
            session_id = self._playback_session_id
        self._capture_playback_event(
            "pause", origin=origin, position_seconds=position, media=media, session_id=session_id
        )

    @operation("resume")
    def resume(self, *, origin: str = "system") -> None:
        with self._lock:
            if self._state != PlaybackState.PAUSED:
                raise UnsupportedAction("Playback is not paused")
            self._state = PlaybackState.PLAYING
            media = self._active.media if self._active else None
            position = self._active.position if self._active else 0.0
            session_id = self._playback_session_id
        self._capture_playback_event(
            "play",
            origin=origin,
            position_seconds=position,
            media=media,
            session_id=session_id,
            play_kind="resume",
        )

    def toggle_pause(self, *, origin: str = "system") -> None:
        if self.snapshot().state == PlaybackState.PAUSED:
            self.resume(origin=origin)
        else:
            self.pause(origin=origin)

    @operation("seek")
    def seek(self, seconds: float, *, origin: str = "system", resolved: ResolvedMedia | None = None) -> None:
        retained: list[StemResourceLease] = []
        try:
            self._seek(seconds, origin=origin, resolved=resolved, retained_stem_leases=retained)
        finally:
            for lease in retained:
                lease.release()

    def _seek(
        self, seconds: float, *, origin: str, resolved: ResolvedMedia | None,
        retained_stem_leases: list[StemResourceLease],
    ) -> None:
        record(4, "seek.target", seconds=seconds)
        stem_sources: tuple[str, ...] = ()
        stem_active: DecoderSession | None = None
        stem_previous: DecoderSession | None = None
        stem_lease: StemResourceLease | None = None
        with self._lock:
            if self._recipe_mix is not None:
                raise UnsupportedAction("Seek the recipe timeline to restore its verified mix")
            active = self._active
            completed = self._completed_media if active is None and self._state == PlaybackState.IDLE else None
            if not active and not completed:
                raise UnsupportedAction("Nothing is loaded")
            media = active.media if active else completed
            assert media is not None
            if resolved is not None:
                self._validate_resolved_input(resolved.media, resolved)
                if (resolved.media.source != media.source or resolved.media.stable_id != media.stable_id
                        or canonical_uri(resolved.media.source, resolved.media.original_uri)
                        != canonical_uri(media.source, media.original_uri)):
                    raise UnsupportedAction("Resolved input does not match current media")
                media = resolved.media
            if not media.capabilities.seekable:
                raise UnsupportedAction("This live or nonseekable source cannot be seeked")
            seek_from = active.position if active else self._completed_position
            session_id = self._playback_session_id or uuid.uuid4().hex
            target = max(0.0, float(seconds))
            if media.duration is not None:
                target = min(target, media.duration)
            region = self._active_region if active else self._completed_region
            if region and region.start_seconds is not None:
                target = max(target, region.start_seconds)
            if region and region.end_seconds is not None and target >= region.end_seconds:
                if active:
                    self._finish_active(active)
                else:
                    self._completed_position = region.end_seconds
                self._capture_playback_event(
                    "seek",
                    origin=origin,
                    position_seconds=target,
                    media=media,
                    session_id=session_id,
                    seek_from_seconds=seek_from,
                    seek_to_seconds=target,
                )
                return
            was_paused = active is None or self._state == PlaybackState.PAUSED
            generation = self._begin_media_request()
            if active is not None and self._stem_media_id == media.stable_id:
                stem_sources = self._stem_sources
                stem_active, stem_previous = self._stem_session, self._stem_previous
                current_lease = getattr(stem_active, "resource_lease", None)
                if current_lease is not None:
                    stem_lease = current_lease.retain()
                    assert stem_lease is not None
                    retained_stem_leases.append(stem_lease)
                self._stem_session = None
                self._stem_previous = None
                self._stem_media_id = None
                self._stem_sources = ()
                self._stem_transition_frames = 0
            self.equalizer.reset()
            if resolved is not None:
                self._prepared, self._resolved = media, resolved
            self._state = PlaybackState.SEEKING
            if active:
                active.stop()
            replacement = self._new_session(media, start_at=target)
            replacement.on_metadata = lambda title, source=replacement: self._handle_stream_metadata(source, title)
            self._active = replacement
            self._active_region = region
            self._playback_session_id = session_id
            self._completed_media = None
            self._completed_position = 0.0
            self._completed_duration = None
            self._completed_region = None
            replacement.start()
        self._stop_stem_sessions_async(stem_active, stem_previous)
        try:
            buffered = replacement.wait_for_buffer()
            with self._lock:
                if self._active is not replacement or generation != self._request_generation:
                    raise PlaybackError("Seek attempt was replaced")
                if not buffered:
                    if self._seek_reached_clean_end(replacement, target):
                        self._finish_active(replacement)
                        self._capture_playback_event(
                            "seek",
                            origin=origin,
                            position_seconds=target,
                            media=media,
                            session_id=session_id,
                            seek_from_seconds=seek_from,
                            seek_to_seconds=target,
                        )
                        return
                    raise PlaybackError(replacement.error or "Seek produced no audio")
                self._state = PlaybackState.PAUSED if was_paused else PlaybackState.PLAYING
        except Exception:
            replacement.stop()
            raise
        if stem_sources:
            try:
                retained_stem_leases.clear()  # configure consumes the independently retained wrapper.
                self.configure_stem_monitor(media.stable_id, stem_sources, lease=stem_lease)
            except PlaybackError:
                record(2, "stems.monitor_seek_restore_failed")
        self._capture_playback_event(
            "seek",
            origin=origin,
            position_seconds=target,
            media=media,
            session_id=session_id,
            seek_from_seconds=seek_from,
            seek_to_seconds=target,
        )

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

    @operation("restart_live")
    def restart_live(self) -> None:
        with self._lock:
            active = self._active
            if not active or not active.media.capabilities.live:
                raise UnsupportedAction("Only live streams can be resynchronized")
            media = active.media
        self.play(media, probe=False, origin="recovery")

    @property
    def resolved_uri(self) -> str | None:
        with self._lock:
            return self._resolved.playback_uri if self._resolved else None

    @operation("volume")
    def set_volume(self, value: float) -> None:
        value = float(value)
        if value > 1:
            value /= 100
        if not 0 <= value <= 2:
            raise ValueError("Volume must be between 0 and 200 percent")
        with self._lock:
            self._volume = value

    def set_automation_gain(self, value: float) -> None:
        """Apply transient automation without changing the user's base volume."""
        value = float(value)
        if not 0 <= value <= 1:
            raise ValueError("Automation gain must be between 0 and 1")
        with self._lock:
            self._automation_gain = value

    @operation("crossfade")
    def set_crossfade_seconds(self, value: float) -> float:
        """Update automatic finite-media overlap without replacing either decoder."""
        seconds = _validated_crossfade_seconds(value)
        with self._lock:
            self.crossfade_seconds = seconds
            if seconds == 0 and self._state == PlaybackState.CROSSFADING:
                self._state = PlaybackState.PLAYING
        return seconds

    @operation("replaygain")
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
                if session and self._recipe_mix is None:
                    session.program_gain_db = self._program_gain_db(session.media)
                    session.program_gain = 10.0 ** (session.program_gain_db / 20.0)

    @operation("live_leveling")
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

    def add_identification_sink(
        self,
        callback: Callable[[object, int, str, str, str, float, bool], None],
    ) -> Callable[[], None]:
        """Observe newly decoded programme PCM for time-specific identification."""
        with self._lock:
            self._identification_sinks.append(callback)

        def remove() -> None:
            with self._lock:
                if callback in self._identification_sinks:
                    self._identification_sinks.remove(callback)

        return remove

    def add_metadata_sink(self, callback: Callable[[str | None], None]) -> Callable[[], None]:
        with self._lock:
            self._metadata_sinks.append(callback)

        def remove() -> None:
            with self._lock:
                if callback in self._metadata_sinks:
                    self._metadata_sinks.remove(callback)

        return remove

    def add_active_media_sink(
        self,
        callback: Callable[[MediaRef | None, ResolvedMedia | None], None],
    ) -> Callable[[], None]:
        """Observe authoritative active-media changes without affecting playback."""
        with self._lock:
            self._active_media_sinks.append(callback)

        def remove() -> None:
            with self._lock:
                if callback in self._active_media_sinks:
                    self._active_media_sinks.remove(callback)

        return remove

    def _publish_active_media(self, media: MediaRef | None, resolved: ResolvedMedia | None) -> None:
        with self._active_media_publish_lock:
            with self._lock:
                generation = self._request_generation
            self._dispatch_active_media(media, resolved, generation=generation)

    def _publish_active_media_for_session(
        self,
        session: DecoderSession,
        media: MediaRef,
        resolved: ResolvedMedia | None,
    ) -> None:
        """Publish only while the bound session is still authoritative."""

        with self._active_media_publish_lock:
            with self._lock:
                if self._active is not session:
                    return
                generation = self._request_generation
            self._dispatch_active_media(media, resolved, generation=generation, session=session)

    def _dispatch_active_media(
        self,
        media: MediaRef | None,
        resolved: ResolvedMedia | None,
        *,
        generation: int,
        session: DecoderSession | None = None,
    ) -> None:
        with self._lock:
            sinks = tuple(self._active_media_sinks)
        for sink in sinks:
            with self._lock:
                # An earlier observer may have selected or stopped media while
                # publishing reentrantly. Later observers must not undo it.
                if generation != self._request_generation or (session is not None and self._active is not session):
                    return
            try:
                sink(media, resolved)
            except Exception:
                # Artwork and other presentation consumers must never break playback.
                continue

    def _publish_metadata(self, title: str | None, *, session: DecoderSession | None = None) -> None:
        with self._active_media_publish_lock:
            with self._lock:
                sinks = tuple(self._metadata_sinks)
            for sink in sinks:
                with self._lock:
                    if session is not None and self._active is not session:
                        return
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

    def _publish_identification_pcm(
        self,
        samples: object,
        frames: int,
        media_id: str,
        session_id: str,
        decoder_token: str,
        start_position: float,
        mixed: bool,
    ) -> None:
        with self._lock:
            sinks = tuple(self._identification_sinks)
        for sink in sinks:
            try:
                sink(samples, frames, media_id, session_id, decoder_token, start_position, mixed)
            except Exception:
                # Identification is optional and must never affect playback.
                continue

    def identification_capture_context(self) -> tuple[MediaRef, str, str, float]:
        """Return the authoritative current source and invocation position."""
        with self._lock:
            if self._active is None or self._playback_session_id is None:
                raise UnsupportedAction("Nothing is currently playing")
            if self._state != PlaybackState.PLAYING:
                raise UnsupportedAction("Start time-specific identification while media is playing")
            if not self._active.media.capabilities.fingerprintable:
                raise UnsupportedAction("The current source cannot be fingerprinted")
            return (
                self._active.media,
                self._playback_session_id,
                f"decoder-{id(self._active):x}",
                self._active.position,
            )

    @property
    def automation_gain(self) -> float:
        with self._lock:
            return self._automation_gain

    @operation("mute")
    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self._muted = bool(muted)

    def fingerprint_pcm(self, *, media_id: str | None = None) -> bytes:
        with self._lock:
            if media_id is not None and (self._active is None or self._active.media.stable_id != media_id):
                raise UnsupportedAction("Active media changed before fingerprint capture; retry the command")
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
        self._publish_metadata(title, session=session)

    @operation("stop")
    def stop(self) -> None:
        self._stop_playback()

    def _stop_playback(self, *, expected_generation: int | None = None) -> bool:
        """Detach one request, retiring its resources without clearing a newer one."""
        with self._lock:
            if expected_generation is None:
                self._request_generation += 1
            elif expected_generation != self._request_generation:
                return False
            generation = self._request_generation
            self._watch_stop.set()
            self.equalizer.reset()
            active, next_session = self._active, self._next
            recipe_mix, self._recipe_mix = self._recipe_mix, None
            preparation = self._prepared_recipe_mix
            self._prepared_recipe_mix = None
            pending = self._pending_recipe_mix
            self._pending_recipe_mix = None
            stem_active, stem_previous = self._stem_session, self._stem_previous
            self._active = None
            self._next = None
            self._stem_session = None
            self._stem_previous = None
            self._stem_media_id = None
            self._stem_sources = ()
            self._stem_transition_frames = 0
            self._active_region = None
            self._next_region = None
            self._playback_session_id = None
            self._captured_transition = None
            self._resolved = None
            self._stream_metadata = {}
            self._completed_media = None
            self._completed_position = 0.0
            self._completed_duration = None
            self._completed_region = None
            if active or next_session:
                self._state = PlaybackState.STOPPING
        for prepared in (preparation, pending):
            if prepared is not None:
                self.discard_recipe_mix(prepared)
        for session in (active, next_session, stem_active, stem_previous,
                        recipe_mix.promoted if recipe_mix is not None else None):
            if session:
                session.stop()
        with self._lock:
            current = generation == self._request_generation
            if current:
                self._state = PlaybackState.IDLE
        with self._active_media_publish_lock:
            with self._lock:
                current = generation == self._request_generation
            if current:
                self._dispatch_active_media(None, None, generation=generation)
                with self._lock:
                    current = generation == self._request_generation
        return current

    @operation("close")
    def close(self) -> None:
        self.stop()
        self._recipe_mix_worker_stop.set()
        if self._recipe_mix_worker is not None:
            self._recipe_mix_worker.join(timeout=2)
        with self._output_switch_lock:
            with self._lock:
                stream = self._stream
                self._stream = None
                self._output_device = None
            self._close_output_stream(stream)

    @operation("output_recovery")
    def recover_output(self, device: OutputDeviceInfo | None = None) -> None:
        """Recreate the stream on the current operating-system default output."""
        with self._lock:
            generation = self._request_generation
        self._open_output(device or self.default_output_device(), force=True, expected_generation=generation)

    def report_output_error(self, message: str) -> None:
        record(2, "output_monitor.failed")
        with self._lock:
            self._error = message
            if not self.output_stream_active:
                self._output_interrupted = True

    def snapshot(self) -> PlaybackSnapshot:
        with self._lock:
            active = self._active
            completed = self._completed_media if active is None else None
            region = self._active_region if active else self._completed_region
            media = active.media if active else completed or self._prepared
            position = active.position if active else self._completed_position
            return PlaybackSnapshot(
                # Preserve play/pause intent internally while output is absent.
                # Recovery resumes the same decoder and PCM position.
                state=PlaybackState.BUFFERING if (
                    active and self._output_interrupted
                    and self._state in {PlaybackState.PLAYING, PlaybackState.CROSSFADING}
                ) else self._state,
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
                region_start_seconds=region.start_seconds if region else None,
                region_end_seconds=region.end_seconds if region else None,
                session_id=self._playback_session_id,
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
