"""Mariana 0.7 media platform.

The package intentionally keeps decoding, persistence, identification, radio,
and recommendations behind small interfaces so the legacy CLI does not own
their lifecycle.
"""

from .models import (
    IdentityStatus,
    MediaCapabilities,
    LyricsResult,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    TrackIdentity,
)
from .sources import FailureCode, MediaFailure, ResolvedMedia, ResolverRegistry

__all__ = [
    "IdentityStatus",
    "MediaCapabilities",
    "LyricsResult",
    "MediaRef",
    "MediaSource",
    "PlaybackSnapshot",
    "PlaybackState",
    "TrackIdentity",
    "FailureCode",
    "MediaFailure",
    "ResolvedMedia",
    "ResolverRegistry",
]
