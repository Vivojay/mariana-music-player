"""Backend-only prepared recipe mixes and bounded, atomic PCM consumption.

There is no resolver, file access, decoder construction, or worker scheduling in
the rendering operation. Preparation/retirement belong to PlaybackController.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from .models import MediaRef
from .sources import ResolvedMedia

if TYPE_CHECKING:
    from .playback import DecoderSession, PlaybackController


@dataclass(frozen=True, slots=True)
class CommittedOverlap:
    incoming_id: str
    incoming_position_seconds: float
    duration_frames: int
    elapsed_frames: int
    outgoing_gain_db: float
    incoming_gain_db: float


@dataclass(frozen=True, slots=True)
class CommittedProgramEvent:
    """Allowlisted private-free state captured at the successful backend action."""

    action: str
    stable_id: str | None
    session_id: str | None
    position_seconds: float
    program_gain_db: float | None
    playing: bool
    origin: str = "system"
    play_kind: str | None = None
    overlap: CommittedOverlap | None = None


@dataclass(frozen=True, slots=True)
class RecipeMixSource:
    media: MediaRef
    resolved: ResolvedMedia
    position_seconds: float
    program_gain_db: float


@dataclass(frozen=True, slots=True)
class RecipeMixSpec:
    outgoing: RecipeMixSource
    incoming: RecipeMixSource | None = None
    duration_frames: int = 0
    elapsed_frames: int = 0
    paused: bool = False

    def validate(self, sample_rate: int) -> None:
        if type(self.paused) is not bool:
            raise ValueError("Paused intent must be boolean")
        if type(self.duration_frames) is not int or type(self.elapsed_frames) is not int:
            raise ValueError("Overlap timing must use integer frames")
        if self.incoming is None:
            if self.duration_frames or self.elapsed_frames:
                raise ValueError("Single-source mix cannot carry overlap timing")
        elif not 0 <= self.elapsed_frames < self.duration_frames <= sample_rate * 30:
            raise ValueError("Invalid overlap envelope")
        remaining = (self.duration_frames - self.elapsed_frames) / sample_rate
        for source in (self.outgoing, self.incoming):
            if source is None:
                continue
            media = source.media
            if source.resolved.media is not media or source.resolved.expired:
                raise ValueError("Resolved source is stale or belongs to different media")
            caps = source.resolved.capabilities
            if caps.live or not caps.finite or not caps.seekable:
                raise ValueError("Recipe mix requires finite seekable media")
            if (isinstance(source.position_seconds, bool) or not math.isfinite(source.position_seconds)
                    or isinstance(source.program_gain_db, bool) or not math.isfinite(source.program_gain_db)
                    or not -120 <= source.program_gain_db <= 60):
                raise ValueError("Invalid source position or program gain")
            if (media.duration is None or not math.isfinite(media.duration)
                    or not 0 <= source.position_seconds < media.duration):
                raise ValueError("Recipe source has no valid remaining duration")
            if self.incoming is not None and media.duration - source.position_seconds + 1 / sample_rate < remaining:
                raise ValueError("Recipe overlap exceeds a source's remaining duration")


@dataclass(eq=False, slots=True)
class PreparedRecipeMix:
    owner: PlaybackController
    generation: int
    outgoing: DecoderSession
    incoming: DecoderSession | None
    spec: RecipeMixSpec
    playback_session_id: str
    incoming_session_id: str | None = None
    status: str = "prepared"
    acknowledged: threading.Event = field(default_factory=threading.Event)
    retired: tuple[DecoderSession, ...] = ()


@dataclass(slots=True)
class RecipeMixRuntime:
    outgoing: DecoderSession
    incoming: DecoderSession | None
    duration_frames: int
    elapsed_frames: int
    session_id: str
    incoming_session_id: str | None = None
    promoted: DecoderSession | None = None
    failed: bool = False
    buffering: bool = False

    def render(self, frames: int, sample_rate: int, channels: int) -> np.ndarray:
        """Consume the full paired requirement or neither source; never wait.

        Producer locks are acquired nonblocking and in stable object order. The
        source buffers only grow outside this operation. A block crossing the
        envelope endpoint consumes outgoing only to that endpoint, then incoming
        alone. Output duration is bounded by the host's audio block size.
        """
        output = np.zeros((frames, channels), dtype=np.float32)
        self.buffering = False
        if self.failed:
            return output
        outgoing, incoming = self.outgoing, self.incoming
        overlap_frames = min(frames, self.duration_frames - self.elapsed_frames) if incoming is not None else 0
        incoming_count = frames if incoming is not None else 0
        if incoming is not None and incoming.media.duration is not None:
            incoming_count = min(frames, max(0, round((incoming.media.duration - incoming.position) * sample_rate)))
        outgoing_count = overlap_frames if incoming is not None else frames
        if incoming is None and outgoing.media.duration is not None:
            outgoing_count = min(frames, max(0, round((outgoing.media.duration - outgoing.position) * sample_rate)))
        sessions = sorted((source for source in (outgoing, incoming) if source is not None), key=id)
        acquired = []
        try:
            for session in sessions:
                if not session._condition.acquire(blocking=False):
                    self.buffering = True
                    return output
                acquired.append(session)
            width = channels * 4
            for session, count in ((outgoing, outgoing_count), (incoming, incoming_count)):
                if session is not None and len(session._buffer) < count * width:
                    if session.eof:
                        self.failed = True
                    else:
                        self.buffering = True
                    return output
            first = outgoing.read(outgoing_count)
            second = incoming.read(incoming_count) if incoming is not None else None
        finally:
            for session in reversed(acquired):
                session._condition.release()
        if incoming is None:
            if outgoing_count:
                output[:outgoing_count] = np.frombuffer(first, dtype=np.float32).reshape(-1, channels) * outgoing.program_gain
            return output
        assert second is not None
        incoming_samples = np.frombuffer(second, dtype=np.float32).reshape(-1, channels)
        positions = (np.arange(overlap_frames, dtype=np.float64) + self.elapsed_frames) / self.duration_frames
        angle = positions * (math.pi / 2)
        output[:overlap_frames] = (
            np.frombuffer(first, dtype=np.float32).reshape(-1, channels)
            * (np.cos(angle) * outgoing.program_gain)[:, None]
            + incoming_samples[:overlap_frames] * (np.sin(angle) * incoming.program_gain)[:, None]
        )
        if overlap_frames < incoming_count:
            output[overlap_frames:incoming_count] = incoming_samples[overlap_frames:] * incoming.program_gain
        self.elapsed_frames += overlap_frames
        if self.elapsed_frames == self.duration_frames:
            self.promoted = outgoing
            self.outgoing, self.incoming = incoming, None
            if self.incoming_session_id is not None:
                self.session_id = self.incoming_session_id
                self.incoming_session_id = None
        return output
