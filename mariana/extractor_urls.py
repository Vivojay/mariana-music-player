"""URL classification backed by yt-dlp's installed extractor registry."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from yt_dlp.extractor import gen_extractor_classes


@lru_cache(maxsize=1)
def _dedicated_extractors() -> tuple[type, ...]:
    """Load extractor classes once without retaining user URLs or query tokens."""
    return tuple(
        extractor
        for extractor in gen_extractor_classes()
        if getattr(extractor, "IE_NAME", "").casefold() != "generic"
    )


def extractor_key_for_url(value: str) -> str | None:
    """Return the dedicated yt-dlp extractor key for a safe HTTP(S) URL."""
    parsed = urlparse(value.strip())
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    for extractor in _dedicated_extractors():
        try:
            if extractor.suitable(value):
                return str(extractor.ie_key())
        except (AttributeError, TypeError, ValueError):
            continue
    return None


def has_dedicated_extractor(value: str) -> bool:
    """Return whether the installed yt-dlp supports *value* explicitly."""
    return extractor_key_for_url(value) is not None
