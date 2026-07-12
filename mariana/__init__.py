"""Mariana 0.7 media platform.

The package intentionally keeps decoding, persistence, identification, radio,
and recommendations behind small interfaces so the legacy CLI does not own
their lifecycle.
"""

from .models import (
    IdentityStatus,
    LyricsResult,
    MediaCapabilities,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
    TrackIdentity,
)
from .sources import FailureCode, MediaFailure, ResolvedMedia, ResolverRegistry

__all__ = [
    "FailureCode",
    "IdentityStatus",
    "LyricsResult",
    "MediaCapabilities",
    "MediaFailure",
    "MediaRef",
    "MediaSource",
    "PlaybackSnapshot",
    "PlaybackState",
    "ResolvedMedia",
    "ResolverRegistry",
    "TrackIdentity",
]
