"""Homepage cards and current discovery choices for the paired player."""

from __future__ import annotations

import re

from .homepage import (
    _IMAGE_CACHE_NAME,
    HOMEPAGE_IMAGE_MIME,
    _official_bandcamp_link,
    _official_musicbrainz_link,
    _plain_text,
    catalogue_sections,
    official_destination_sections,
)

CARD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
STATES = {"offline", "loading", "ready", "stale", "partial", "error"}
PICKER_STATES = {"loading", "tracks", "choices", "working", "complete", "error"}
OFFICIAL_DESTINATIONS = frozenset(
    item["link"] for section in (*catalogue_sections(), *official_destination_sections())
    for item in section["items"] if item["link"]
)


def _public_link(link):
    if not isinstance(link, str):
        return None
    if link.startswith("https://") and link in OFFICIAL_DESTINATIONS:
        return link
    return _official_bandcamp_link(link) or _official_musicbrainz_link(link)


def _picker_projection(picker, published, share_library):
    if picker is None:
        return None
    state = picker.snapshot()
    item_id, revision = state.get("item_id"), state.get("revision")
    phase = state.get("state")
    if item_id not in published or phase not in PICKER_STATES or type(revision) is not int or revision < 1:
        return None
    mode = "tracks" if phase == "tracks" else "candidates"
    rows = []
    for number, item in enumerate(state.get(mode, [])[:30], 1):
        if mode == "candidates" and not share_library and item.get("source") == "local":
            continue
        rows.append({
            "number": number,
            "title": _plain_text(item.get("title"), maximum=240) or "Version",
            "artist": _plain_text(item.get("artist"), maximum=160),
            "source": _plain_text(item.get("source"), maximum=60),
            "playable": item.get("playable") is True,
        })
    return {
        "itemId": item_id, "revision": revision, "state": phase, "rows": rows,
        "title": _plain_text(state.get("title"), maximum=240) or "Discovery selection",
        "message": _plain_text(state.get("message"), maximum=240),
        "page": state.get("page") if type(state.get("page")) is int and 0 <= state["page"] < 8 else None,
        "hasMore": state.get("has_more") is True,
    }


def browser_homepage(home, share_library=False, picker=None):
    """Provide display text, official links and public cache handles for the paired tab."""
    current = home.snapshot(include_local=share_library)
    sections = []
    published = set()
    enabled = current["online_enabled"] is True
    for section in current["sections"][:16]:
        if section["key"] == "local" and not share_library:
            continue
        items = []
        for card in section["items"][:30]:
            card_id = card.get("id")
            title = _plain_text(card.get("title"), maximum=240)
            if not title or not isinstance(card_id, str) or not CARD_ID.fullmatch(card_id):
                continue
            selectable = bool(enabled and card_id.startswith(("release:", "catalogue:"))
                              and home.release_target(card_id) is not None)
            if selectable:
                published.add(card_id)
            image = card.get("image_key")
            artwork = (isinstance(image, str) and _IMAGE_CACHE_NAME.fullmatch(image)
                       and HOMEPAGE_IMAGE_MIME.get(image.rsplit(".", 1)[-1]) == card.get("image_mime"))
            items.append({
                "id": card_id,
                "title": title,
                "summary": _plain_text(card.get("summary"), maximum=500),
                "source": _plain_text(card.get("source"), maximum=80) or "Mariana",
                "published": _plain_text(card.get("published_at"), maximum=64),
                "link": _public_link(card.get("link")),
                "selectable": selectable,
                "kind": "station" if (card.get("catalogue") or {}).get("kind") == "station" else None,
                **({"artwork": image} if artwork and section["key"] in {"culture", "releases", "artist-spotlight"} else {}),
            })
        sections.append({"key": section["key"], "title": section["title"], "items": items})
    return {
        "onlineEnabled": enabled,
        "state": current["state"] if current["state"] in STATES else "offline",
        "message": _plain_text(current.get("safe_message"), maximum=240),
        "sections": sections,
        "discovery": _picker_projection(picker, published, share_library),
    }
