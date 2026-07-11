"""FFmpeg decoding and callback-driven PCM playback."""

from __future__ import annotations

from array import array
from collections import deque
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from typing import Callable, Protocol

import sounddevice

from .models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


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
    if configured_bin:
        candidate = Path(configured_bin).expanduser()
        if candidate.is_dir():
            candidate /= f"{name}.exe" if os.name == "nt" else name
        if candidate.is_file():
            return str(candidate.resolve())
    executable = shutil.which(name)
    if executable:
        return executable
    raise PlaybackError(f"{name} was not found; configure the FFmpeg bin directory or add it to PATH")


def resolve_input(media: MediaRef) -> str:
    if media.source in {MediaSource.YOUTUBE, MediaSource.RECOMMENDATION} or media.resolver_data.get("youtube"):
        from beta.youtube_media import stream_url

        return stream_url(media.original_uri, audio_only=True)
    return str(media.resolver_data.get("resolved_uri") or media.original_uri)


def probe_media(media: MediaRef, *, ffprobe_bin: str | None = None, timeout: float = 20) -> MediaRef:
    ffprobe = find_executable("ffprobe", ffprobe_bin)
    source = resolve_input(media)
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,format_name,tags:stream=codec_type,codec_name,duration,tags",
        "-of",
        "json",
        source,
    ]
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
        raise PlaybackError(f"FFprobe could not inspect {media.original_uri}: {error}") from error

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
    is_live = media.source == MediaSource.RADIO or duration is None
    media.duration = duration
    media.title = media.title or tags.get("title")
    media.artist = media.artist or tags.get("artist")
    media.album = media.album or tags.get("album")
    media.resolver_data.update(
        {
            "resolved_uri": source,
            "codec": audio_stream.get("codec_name"),
            "format": format_info.get("format_name"),
            "tags": tags,
        }
    )
    media.capabilities = MediaCapabilities(
        finite=not is_live,
        live=is_live,
        seekable=not is_live,
        fingerprintable=True,
        downloadable=media.source != MediaSource.RADIO,
        metadata_available=bool(tags),
    )
    return media


class WindowsJob:
    """Best-effort kill-on-close Windows job for child process cleanup."""

    def __init__(self, process: subprocess.Popen):
        self.handle = None
        if os.name != "nt":
            return
        try:
            import win32job

            handle = win32job.CreateJobObject(None, "")
            information = win32job.QueryInformationJobObject(
                handle, win32job.JobObjectExtendedLimitInformation
            )
            information["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            win32job.SetInformationJobObject(handle, win32job.JobObjectExtendedLimitInformation, information)
            win32job.AssignProcessToJobObject(handle, int(process._handle))
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


class DecoderSession:
    def __init__(
        self,
        media: MediaRef,
        *,
        ffmpeg_bin: str | None = None,
        start_at: float = 0,
        max_buffer_seconds: float = DEFAULT_BUFFER_SECONDS,
    ):
        self.media = media
        self.ffmpeg = find_executable("ffmpeg", ffmpeg_bin)
        self.start_at = max(0.0, start_at)
        self.max_buffer_bytes = int(max_buffer_seconds * SAMPLE_RATE * BYTES_PER_FRAME)
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

    def reset_fingerprint(self) -> None:
        with self._condition:
            self._fingerprint.clear()

    def start(self) -> None:
        if self.process is not None:
            return
        source = str(self.media.resolver_data.get("resolved_uri") or resolve_input(self.media))
        command = [self.ffmpeg, "-hide_banner", "-loglevel", "warning", "-nostdin"]
        if self.start_at and self.media.capabilities.seekable:
            command += ["-ss", f"{self.start_at:.3f}"]
        if source.startswith(("http://", "https://")):
            command += [
                "-rw_timeout",
                "30000000",
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "5",
            ]
        command += [
            "-i",
            source,
            "-map",
            "0:a:0",
            "-vn",
            "-sn",
            "-dn",
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
            self._stderr.append(raw.decode("utf-8", errors="replace").strip())

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
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=2)
        if self.job:
            self.job.close()
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
    ):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin
        self.crossfade_seconds = max(0.0, crossfade_seconds)
        self.output_factory = output_factory or sounddevice.RawOutputStream
        self._lock = threading.RLock()
        self._active: DecoderSession | None = None
        self._next: DecoderSession | None = None
        self._stream: OutputStream | None = None
        self._state = PlaybackState.IDLE
        self._volume = 1.0
        self._muted = False
        self._error: str | None = None
        self._prepared: MediaRef | None = None
        self.on_complete: Callable[[MediaRef], None] | None = None
        self._watch_stop = threading.Event()
        self._identity_generation = 0

    def prepare(self, media: MediaRef, *, probe: bool = True) -> MediaRef:
        with self._lock:
            self._state = PlaybackState.RESOLVING
            self._error = None
        try:
            if probe:
                media = probe_media(media, ffprobe_bin=self.ffprobe_bin)
            else:
                media.resolver_data["resolved_uri"] = resolve_input(media)
            self._prepared = media
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
        self.stop()
        media = self._prepared
        with self._lock:
            self._state = PlaybackState.BUFFERING
            session = DecoderSession(media, ffmpeg_bin=self.ffmpeg_bin, start_at=start_at)
            self._active = session
            session.start()
        if not session.wait_for_buffer():
            error = session.error or "FFmpeg produced no playable audio"
            session.stop()
            with self._lock:
                self._state = PlaybackState.FAILED
                self._error = error
            raise PlaybackError(error)
        with self._lock:
            self._ensure_output()
            self._state = PlaybackState.PLAYING
            self._watch_stop.clear()
            threading.Thread(target=self._watch_completion, name="mariana-playback-watch", daemon=True).start()
        return media

    def prefetch(self, media: MediaRef, *, probe: bool = True) -> MediaRef:
        media = probe_media(media, ffprobe_bin=self.ffprobe_bin) if probe else media
        session = DecoderSession(media, ffmpeg_bin=self.ffmpeg_bin)
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

    def _ensure_output(self) -> None:
        if self._stream is None:
            self._stream = self.output_factory(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
                callback=self._audio_callback,
                blocksize=1024,
            )
            self._stream.start()

    def _audio_callback(self, outdata, frames, _time_info, _status) -> None:
        size = frames * BYTES_PER_FRAME
        with self._lock:
            active = self._active
            next_session = self._next
            state = self._state
            gain = 0.0 if self._muted else self._volume
        if _status:
            with self._lock:
                self._error = f"Audio output reported: {_status}"
        if not active or state == PlaybackState.PAUSED:
            outdata[:] = b"\0" * size
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
        if crossfade and next_session:
            second = next_session.read(frames)
            payload = _mix_pcm(first, second, gain * (1 - fraction), gain * fraction, size)
            with self._lock:
                self._state = PlaybackState.CROSSFADING
        else:
            payload = _scale_pcm(first, gain).ljust(size, b"\0")
        outdata[:] = payload[:size]
        if active.eof and active.buffered_seconds == 0:
            self._promote_next(active)

    def _promote_next(self, expected: DecoderSession) -> None:
        with self._lock:
            if self._active is not expected:
                return
            completed = self._active
            if self._next:
                self._active = self._next
                self._next = None
                self._state = PlaybackState.PLAYING
            else:
                self._active = None
                self._state = PlaybackState.IDLE
        if completed:
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
                self._promote_next(active)
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
            replacement = DecoderSession(media, ffmpeg_bin=self.ffmpeg_bin, start_at=target)
            self._active = replacement
            replacement.start()
        if not replacement.wait_for_buffer():
            raise PlaybackError(replacement.error or "Seek produced no audio")
        with self._lock:
            self._state = PlaybackState.PAUSED if was_paused else PlaybackState.PLAYING

    def restart_live(self) -> None:
        with self._lock:
            active = self._active
            if not active or not active.media.capabilities.live:
                raise UnsupportedAction("Only live streams can be resynchronized")
            media = active.media
        self.play(media, probe=False)

    def set_volume(self, value: float) -> None:
        value = float(value)
        if value > 1:
            value /= 100
        if not 0 <= value <= 1:
            raise ValueError("Volume must be between 0 and 100 percent")
        with self._lock:
            self._volume = value

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

    def stop(self) -> None:
        with self._lock:
            self._watch_stop.set()
            active, next_session = self._active, self._next
            self._active = None
            self._next = None
            if active or next_session:
                self._state = PlaybackState.STOPPING
        for session in (active, next_session):
            if session:
                session.stop()
        with self._lock:
            self._state = PlaybackState.IDLE

    def close(self) -> None:
        self.stop()
        with self._lock:
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None

    def recover_output(self) -> None:
        """Recreate the device stream after a Windows output-device loss."""
        with self._lock:
            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                finally:
                    self._stream = None
            self._ensure_output()
            self._error = None

    def snapshot(self) -> PlaybackSnapshot:
        with self._lock:
            active = self._active
            return PlaybackSnapshot(
                state=self._state,
                position=active.position if active else 0.0,
                duration=active.media.duration if active else None,
                buffered_seconds=active.buffered_seconds if active else 0.0,
                volume=self._volume,
                muted=self._muted,
                error=self._error,
                media=active.media if active else self._prepared,
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
        )
    except OSError as error:
        raise PlaybackError(f"FFplay could not start: {error}") from error
