"""Bounded invocation-time PCM capture for ad-hoc track identification."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from .models import MediaRef

SAMPLE_RATE = 48_000
CHANNELS = 2
SAMPLE_WIDTH = 4
BYTES_PER_FRAME = CHANNELS * SAMPLE_WIDTH
DEFAULT_CAPTURE_SECONDS = 20.0
MIN_CAPTURE_SECONDS = 8.0
MAX_CAPTURE_SECONDS = 120.0
POSITION_TOLERANCE_SECONDS = 0.5


class AdHocIdentificationError(ValueError):
    """Raised when an ad-hoc capture command is not valid."""


class CapturePhase(StrEnum):
    IDLE = "idle"
    CAPTURING = "capturing"
    IDENTIFYING = "identifying"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class CaptureStatus:
    capture_id: str | None
    phase: CapturePhase
    media_id: str | None = None
    media_title: str | None = None
    playback_session_id: str | None = None
    decoder_token: str | None = None
    requested_start_seconds: float | None = None
    captured_start_seconds: float | None = None
    captured_end_seconds: float | None = None
    captured_seconds: float = 0.0
    target_seconds: float = 0.0
    reason: str | None = None
    result: object | None = None


@dataclass(frozen=True, slots=True)
class _Packet:
    generation: int
    pcm: bytes
    final: bool = False


class AdHocIdentificationService:
    """Capture fresh programme PCM without blocking the playback callback.

    The audio callback only validates continuity, copies a bounded chunk and
    calls ``put_nowait``. Fingerprinting and provider lookup run on a worker.
    """

    def __init__(
        self,
        identify: Callable[[MediaRef, bytes], object],
        *,
        on_update: Callable[[CaptureStatus], None] | None = None,
        queue_capacity: int = 256,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if queue_capacity < 1:
            raise ValueError("Capture queue capacity must be positive")
        self._identify = identify
        self._clock = clock
        self._deadline = 0.0
        self._closed = threading.Event()
        self._on_update = on_update
        self._queue: queue.Queue[_Packet | None] = queue.Queue(maxsize=queue_capacity)
        self._lock = threading.RLock()
        self._generation = 0
        self._contended_generation: int | None = None
        self._media: MediaRef | None = None
        self._status = CaptureStatus(None, CapturePhase.IDLE)
        self._accepted_frames = 0
        self._target_frames = 0
        self._worker = threading.Thread(
            target=self._work,
            name="mariana-identification-capture",
            daemon=True,
        )
        self._worker.start()

    def status(self) -> CaptureStatus:
        with self._lock:
            return self._status

    def start(
        self,
        media: MediaRef,
        playback_session_id: str,
        decoder_token: str,
        position_seconds: float,
        duration_seconds: float = DEFAULT_CAPTURE_SECONDS,
    ) -> CaptureStatus:
        try:
            duration = float(duration_seconds)
        except (TypeError, ValueError, OverflowError):
            duration = float("nan")
        if not np.isfinite(duration) or not MIN_CAPTURE_SECONDS <= duration <= MAX_CAPTURE_SECONDS:
            raise AdHocIdentificationError(
                f"Capture duration must be between {MIN_CAPTURE_SECONDS:g} and "
                f"{MAX_CAPTURE_SECONDS:g} seconds"
            )
        with self._lock:
            if self._closed.is_set():
                raise AdHocIdentificationError("Identification service is closed")
            if self._status.phase in {CapturePhase.CAPTURING, CapturePhase.IDENTIFYING}:
                raise AdHocIdentificationError("A time-specific identification is already active")
            self._contended_generation = None
            self._generation += 1
            self._media = MediaRef.from_dict(media.to_dict())
            self._accepted_frames = 0
            self._target_frames = round(duration * SAMPLE_RATE)
            # Paused/buffering output cannot leave a forgotten capture active forever.
            self._deadline = self._clock() + max(60.0, duration + 30.0)
            self._status = CaptureStatus(
                uuid.uuid4().hex,
                CapturePhase.CAPTURING,
                media_id=media.stable_id,
                media_title=media.title,
                playback_session_id=playback_session_id,
                decoder_token=decoder_token,
                requested_start_seconds=max(0.0, float(position_seconds)),
                target_seconds=duration,
            )
            status = self._status
        self._emit(status)
        return status

    def offer(
        self,
        samples: object,
        frames: int,
        *,
        media_id: str,
        playback_session_id: str,
        decoder_token: str,
        start_position_seconds: float,
        mixed: bool = False,
    ) -> None:
        """Offer one audible programme block from the real-time callback."""
        if frames <= 0:
            return
        if not self._lock.acquire(blocking=False):
            # Missing a block invalidates this capture, never the playback stream.
            if self._status.phase == CapturePhase.CAPTURING:
                self._contended_generation = self._generation
            return
        try:
            status = self._status
            if status.phase != CapturePhase.CAPTURING:
                return
            if self._contended_generation == self._generation:
                self._fail_locked("Identification capture could not keep up with playback; try again")
                return
            if media_id != status.media_id or playback_session_id != status.playback_session_id:
                self._fail_locked("Playback changed before identification capture completed")
                return
            if decoder_token != status.decoder_token:
                self._fail_locked("Playback was seeked or restarted during identification capture; try again")
                return
            if mixed:
                self._fail_locked("Identification capture crossed a mixed transition; try again")
                return
            expected = (
                status.captured_end_seconds
                if status.captured_end_seconds is not None
                else float(status.requested_start_seconds or 0.0)
            )
            if abs(float(start_position_seconds) - expected) > POSITION_TOLERANCE_SECONDS:
                self._fail_locked("Playback position changed during identification capture; try again")
                return
            remaining = self._target_frames - self._accepted_frames
            accepted = min(int(frames), remaining)
            if accepted <= 0:
                return
            pcm = self._pcm_bytes(samples, accepted)
            actual_frames = len(pcm) // BYTES_PER_FRAME
            if actual_frames <= 0:
                return
            final = self._accepted_frames + actual_frames >= self._target_frames
            try:
                self._queue.put_nowait(_Packet(self._generation, pcm, final))
            except queue.Full:
                self._fail_locked("Identification capture could not keep up with playback; try again")
                return
            captured_start = status.captured_start_seconds
            if captured_start is None:
                captured_start = max(0.0, float(start_position_seconds))
            self._accepted_frames += actual_frames
            captured_end = captured_start + self._accepted_frames / SAMPLE_RATE
            phase = CapturePhase.IDENTIFYING if final else CapturePhase.CAPTURING
            self._status = CaptureStatus(
                status.capture_id,
                phase,
                media_id=status.media_id,
                media_title=status.media_title,
                playback_session_id=status.playback_session_id,
                decoder_token=status.decoder_token,
                requested_start_seconds=status.requested_start_seconds,
                captured_start_seconds=captured_start,
                captured_end_seconds=captured_end,
                captured_seconds=self._accepted_frames / SAMPLE_RATE,
                target_seconds=status.target_seconds,
            )
        finally:
            self._lock.release()
        # The worker publishes terminal results. Never call output/UI hooks from
        # this playback callback, including the failure path.

    def stop(self) -> CaptureStatus:
        """Finish early after the minimum useful fingerprint duration."""
        with self._lock:
            status = self._status
            if status.phase != CapturePhase.CAPTURING:
                raise AdHocIdentificationError("No time-specific identification capture is active")
            if status.captured_seconds < MIN_CAPTURE_SECONDS:
                raise AdHocIdentificationError(
                    f"Capture needs at least {MIN_CAPTURE_SECONDS:g} seconds; "
                    f"{status.captured_seconds:.1f} seconds are available"
                )
            try:
                self._queue.put_nowait(_Packet(self._generation, b"", True))
            except queue.Full:
                self._fail_locked("Identification capture could not be finalized; try again")
                return self._status
            self._status = CaptureStatus(
                status.capture_id,
                CapturePhase.IDENTIFYING,
                media_id=status.media_id,
                media_title=status.media_title,
                playback_session_id=status.playback_session_id,
                decoder_token=status.decoder_token,
                requested_start_seconds=status.requested_start_seconds,
                captured_start_seconds=status.captured_start_seconds,
                captured_end_seconds=status.captured_end_seconds,
                captured_seconds=status.captured_seconds,
                target_seconds=status.target_seconds,
            )
            updated = self._status
        self._emit(updated)
        return updated

    def cancel(self, reason: str = "Identification capture cancelled") -> CaptureStatus:
        with self._lock:
            if self._status.phase not in {CapturePhase.CAPTURING, CapturePhase.IDENTIFYING}:
                raise AdHocIdentificationError("No time-specific identification is active")
            self._generation += 1
            self._status = self._terminal_status(CapturePhase.CANCELLED, reason=reason)
            self._media = None
            status = self._status
        self._emit(status)
        return status

    def active_media_changed(self, media: MediaRef | None, _resolved: object = None) -> None:
        with self._lock:
            if (
                self._status.phase == CapturePhase.CAPTURING
                and (media is None or media.stable_id != self._status.media_id)
            ):
                self._fail_locked("Playback changed before identification capture completed")

    def close(self, timeout: float = 1.0) -> None:
        try:
            timeout = float(timeout)
        except (TypeError, ValueError, OverflowError):
            timeout = 0.0
        timeout = min(2.0, max(0.0, timeout)) if np.isfinite(timeout) else 0.0
        self._closed.set()
        with self._lock:
            if self._status.phase in {CapturePhase.CAPTURING, CapturePhase.IDENTIFYING}:
                self._generation += 1
                self._status = self._terminal_status(
                    CapturePhase.CANCELLED,
                    reason="Application shutdown cancelled identification",
                )
                self._media = None
        self._worker.join(timeout)

    @staticmethod
    def _pcm_bytes(samples: object, frames: int) -> bytes:
        if isinstance(samples, (bytes, bytearray, memoryview)):
            return bytes(samples[: frames * BYTES_PER_FRAME])
        values = np.asarray(samples, dtype=np.float32).reshape(-1, CHANNELS)
        return values[:frames].tobytes()

    def _work(self) -> None:
        buffer = bytearray()
        buffer_generation = -1
        reported_failure = -1
        while not self._closed.is_set():
            with self._lock:
                if (self._status.phase == CapturePhase.CAPTURING
                        and self._contended_generation == self._generation):
                    self._fail_locked("Identification capture could not keep up with playback; try again")
                if self._status.phase == CapturePhase.CAPTURING and self._clock() >= self._deadline:
                    self._fail_locked("Identification capture timed out while playback was paused or buffering")
                current_generation = self._generation
                status = self._status
            if buffer_generation != current_generation:
                buffer = bytearray()
                buffer_generation = current_generation
            if status.phase == CapturePhase.FAILED and reported_failure != current_generation:
                reported_failure = current_generation
                self._emit(status)
            try:
                packet = self._queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if packet is None:
                return
            with self._lock:
                # A new capture may start while queue.get() is waiting. Validate
                # against live state, not the generation from before that wait.
                if self._closed.is_set() or packet.generation != self._generation or self._media is None:
                    continue
            if buffer_generation != packet.generation:
                buffer = bytearray()
                buffer_generation = packet.generation
            buffer.extend(packet.pcm)
            if not packet.final:
                continue
            pcm = bytes(buffer)
            buffer = bytearray()
            with self._lock:
                if self._closed.is_set() or packet.generation != self._generation or self._media is None:
                    continue
                media = self._media
            try:
                result = self._identify(media, pcm)
            except Exception:
                self._finish(packet.generation, None, "Identification failed; check the identification service and try again")
            else:
                self._finish(packet.generation, result, None)
            with self._lock:
                if packet.generation == self._generation and self._status.phase == CapturePhase.FAILED:
                    reported_failure = self._generation

    def _finish(self, generation: int, result: object | None, reason: str | None) -> None:
        with self._lock:
            if self._closed.is_set() or generation != self._generation:
                return
            phase = CapturePhase.FAILED if reason else CapturePhase.COMPLETE
            self._status = self._terminal_status(phase, result=result, reason=reason)
            self._media = None
            status = self._status
        self._emit(status)

    def _terminal_status(
        self,
        phase: CapturePhase,
        *,
        result: object | None = None,
        reason: str | None = None,
    ) -> CaptureStatus:
        status = self._status
        return CaptureStatus(
            status.capture_id,
            phase,
            media_id=status.media_id,
            media_title=status.media_title,
            playback_session_id=status.playback_session_id,
            decoder_token=status.decoder_token,
            requested_start_seconds=status.requested_start_seconds,
            captured_start_seconds=status.captured_start_seconds,
            captured_end_seconds=status.captured_end_seconds,
            captured_seconds=status.captured_seconds,
            target_seconds=status.target_seconds,
            reason=reason,
            result=result,
        )

    def _fail_locked(self, reason: str) -> None:
        self._generation += 1
        self._status = self._terminal_status(CapturePhase.FAILED, reason=reason)
        self._media = None

    def _emit(self, status: CaptureStatus) -> None:
        if self._on_update is not None:
            try:
                self._on_update(status)
            except Exception:
                return
