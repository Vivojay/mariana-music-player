"""URL classification backed by yt-dlp's installed extractor registry."""

from __future__ import annotations

import re
from functools import lru_cache
from urllib.parse import parse_qs, urlparse, urlsplit


@lru_cache(maxsize=1)
def _dedicated_extractors() -> tuple[type, ...]:
    """Load extractor classes once without retaining user URLs or query tokens."""
    from yt_dlp.extractor import gen_extractor_classes

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


def youtube_recording_id(value: str, hint: object = None) -> str | None:
    """Identify a canonical YouTube recording conservatively from its original URL."""
    if not isinstance(value, str) or len(value) > 4096 or any(ord(character) < 33 for character in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or parsed.username or parsed.password or parsed.port:
            return None
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=64)
        candidate = None
        if parsed.hostname in {'youtu.be', 'www.youtu.be'}:
            match = re.fullmatch(r'/([A-Za-z0-9_-]{11})/?', parsed.path)
            candidate = match.group(1) if match and 'v' not in query else None
        elif parsed.hostname in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'}:
            if parsed.path == '/watch' and len(query.get('v', [])) == 1:
                candidate = query['v'][0]
            elif 'v' not in query:
                match = re.fullmatch(r'/(?:shorts|live|embed)/([A-Za-z0-9_-]{11})/?', parsed.path)
                candidate = match.group(1) if match else None
        if candidate is None or not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
            return None
        return candidate if hint is None or hint == candidate else None
    except ValueError:
        return None
