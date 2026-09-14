"""Fresh, exact online preflight for the existing session replay authority.

Only a public YouTube identity currently has enough portable information in the
recipe format. Transient transport data lives in this worker-owned handoff, not
in the recipe, queue, public projection, or media resolver hints.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable
from dataclasses import dataclass

from .models import MediaRef, MediaSource, canonical_uri
from .session_recipes import ReplayBlocked, _matching_reference, canonical_media_reference
from .sources import ResolvedMedia, ResolverRegistry


@dataclass(frozen=True, slots=True)
class PreparedRecipeSource:
    media: MediaRef
    resolved: ResolvedMedia


def prepare_online_recipe_source(
    media: MediaRef,
    expected: dict,
    resolvers: ResolverRegistry,
    *,
    cancelled: Callable[[], bool],
    deadline: float | None = None,
) -> tuple[PreparedRecipeSource, dict]:
    """Verify provider facts freshly and retain exactly the verified transport.

    The resolver retains its own bounded network timeouts. Cancellation is
    checked before and after resolution, so late responses cannot start audio;
    a blocked provider call is not forcibly terminated by this adapter.
    """
    if cancelled():
        raise ReplayBlocked("replay_cancelled")
    if deadline is not None and time.monotonic() >= deadline:
        raise ReplayBlocked("source_preflight_timeout")
    if media.source != MediaSource.YOUTUBE or expected["source"] != "youtube":
        raise ReplayBlocked("online_recipe_preflight_unavailable")
    if not expected["duration_ms"] or not expected["provider_id"]:
        raise ReplayBlocked("unverified_online_source")
    selected = copy.deepcopy(media)
    # Check catalog identity before requesting anything from the provider.
    catalog_reference = canonical_media_reference(selected)
    if any(expected[key] != catalog_reference[key] for key in ("source", "stable_id", "provider_id")):
        raise ReplayBlocked("changed_source")
    selected.original_uri = canonical_uri(selected.source, selected.original_uri)
    resolved = resolvers.resolve(selected, force=True)
    if cancelled():
        raise ReplayBlocked("replay_cancelled")
    if deadline is not None and time.monotonic() >= deadline:
        raise ReplayBlocked("source_preflight_timeout")
    if resolved.media is not selected or resolved.canonical_uri != selected.original_uri:
        raise ReplayBlocked("changed_source")
    if resolved.expired:
        raise ReplayBlocked("expired_source")
    capabilities = resolved.capabilities
    if capabilities.live or not capabilities.finite or not capabilities.seekable:
        raise ReplayBlocked("live_source_requires_archive")
    facts = resolved.metadata.get("provider_metadata")
    if not isinstance(facts, dict) or facts.get("provider_media_id") != expected["provider_id"]:
        raise ReplayBlocked("changed_source")
    # Stale catalog duration must never stand in for missing provider evidence.
    selected.duration = resolved.metadata.get("duration")
    selected.capabilities = copy.deepcopy(capabilities)
    try:
        actual = canonical_media_reference(selected)
    except (TypeError, ValueError, OverflowError) as error:
        raise ReplayBlocked("unverified_online_source") from error
    if not actual["duration_ms"]:
        raise ReplayBlocked("unverified_online_source")
    _matching_reference(expected, actual)
    for name in ("title", "artist", "album"):
        if resolved.metadata.get(name) is not None:
            setattr(selected, name, resolved.metadata[name])
    return PreparedRecipeSource(selected, resolved), actual
