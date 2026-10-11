"""Canonical played-media reconciliation for search and favorites.

When a title query matches something already streamed (online) or played
(local), the remembered canonical identity wins over a fresh provider result.
This keeps one stable identity per song so replays, ratings, favorites, and
history all attach to the same item instead of scattering across reuploads.

Matching is intentionally conservative: normalized titles must agree exactly
after case, accent, punctuation, and parenthetical suffixes
("(Lyrics)", "(Clip Officiel)", "[Official Video]", ...) are removed.
"""

from __future__ import annotations

import re
import unicodedata

_PARENTHETICAL = re.compile(r"\s*(?:\([^()]*\)|\[[^\[\]]*\])")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_TRAILING_TAG = re.compile(
    r"\s+[\-\u2013\u2014|:]\s*(lyrics|lyric|official video|official audio|official music video|"
    r"music video|clip officiel|clip|audio|video|visualizer|visualiser|topic|vevo)\s*$"
)

_MIN_QUERY_CHARS = 3
_MAX_QUERY_CHARS = 200


def normalize_media_title(value: object) -> str:
    """Reduce a title to its canonical comparable form."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.casefold()
    text = _PARENTHETICAL.sub(" ", text)
    previous = None
    while previous != text:
        previous = text
        text = _TRAILING_TAG.sub("", text)
    text = _NON_ALNUM.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _candidate_forms(title: object, artist: object) -> set[str]:
    forms = set()
    normalized_title = normalize_media_title(title)
    if normalized_title:
        forms.add(normalized_title)
    normalized_artist = normalize_media_title(artist)
    if normalized_artist and normalized_title:
        forms.add(f"{normalized_artist} {normalized_title}")
        forms.add(f"{normalized_title} {normalized_artist}")
    return forms


def find_canonical_media(database, query: str) -> dict | None:
    """Return the most recently played row whose title matches the query.

    Only remembered media (played at least once, online or local) is
    considered. Returns the database row mapping or None when nothing
    matches. Callers decide playback; this function never plays anything.
    """
    normalized_query = normalize_media_title(query)
    if not _MIN_QUERY_CHARS <= len(normalized_query) <= _MAX_QUERY_CHARS:
        return None
    rows = database.fetchall(
        "SELECT stable_id, source, original_uri, title, artist, capabilities_json, "
        "resolver_json, chapters_json, updated_at FROM media_items ORDER BY updated_at DESC"
    )
    for row in rows or []:
        title = row["title"] if isinstance(row, dict) else row[3]
        artist = row["artist"] if isinstance(row, dict) else row[4]
        if normalized_query in _candidate_forms(title, artist):
            return row
    return None


def find_duplicate_favorites(preferences, media, *, exclude_stable_id: str | None = None) -> list[tuple[int, str, str]]:
    """List (index, title, source) favorites whose title matches the media.

    Used to warn when a "new" favorite is really a reupload of an already
    favorited song. Never mutates anything.
    """
    from mariana.preferences import PreferenceState

    entries = preferences.list(PreferenceState.FAVORITE)
    normalized = normalize_media_title(getattr(media, "title", None))
    if not normalized:
        return []
    duplicates = []
    for position, entry in enumerate(entries, start=1):
        if entry.stable_id == (exclude_stable_id or getattr(media, "stable_id", None)):
            continue
        stored = preferences.media(entry.stable_id)
        candidate = stored.title if stored else None
        if candidate and normalize_media_title(candidate) == normalized:
            duplicates.append((position, candidate, entry.source or "?"))
    return duplicates
