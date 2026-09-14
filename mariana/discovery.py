"""Bounded, explicit release selection through existing album/playback services."""

from __future__ import annotations

import copy
import math
import re
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from .albums import AlbumCatalog, PlaybackCandidate
from .homepage import _plain_text
from .models import AlbumRef, AlbumTrack, MediaRef

HANDLE = re.compile(r"^[0-9a-f]{32}$")
STALE = "Selection changed or expired; find versions again"


def _text(value: object, fallback: str, maximum: int = 240) -> str:
    text = _plain_text(value, maximum=maximum)
    if not text or re.search(r"\b(?:bearer|credential|private[_ -]?id|resolver)\b", text, re.I):
        return fallback
    return text


def _duration(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 < value <= 604800 and math.isfinite(value) else None


class DiscoverySelection:
    """One worker, one current session, and at most one pending lookup.

    Provider operations never run on the control listener. Selection handles
    expire and bind to the current source card; neither URLs nor CLI ordinals
    are accepted as playback authority.
    """

    def __init__(
        self, *, catalog: AlbumCatalog,
        source: Callable[[str], tuple[str, str] | None],
        apply: Callable[[MediaRef, str], None],
        unavailable: Callable[[MediaRef], str | None],
        on_update: Callable[[dict[str, Any]], None],
        clock: Callable[[], float] = time.monotonic,
        catalogue_choices: Callable[[str, Callable[[], bool]], list[MediaRef]] | None = None,
    ) -> None:
        self.catalog = catalog
        self.source = source
        self.apply = apply
        self.unavailable = unavailable
        self.on_update = on_update
        self.clock = clock
        self.catalogue_choices = catalogue_choices
        self._condition = threading.Condition(threading.RLock())
        self._worker: threading.Thread | None = None
        self._pending: tuple[int, str, str, object] | None = None
        self._generation = 0
        self._closed = False
        self._running = False
        self._binding: tuple[str, str] | None = None
        self._expires = 0.0
        self._album: AlbumRef | None = None
        self._tracks: dict[str, AlbumTrack] = {}
        self._candidates: dict[str, PlaybackCandidate] = {}
        self._state: dict[str, Any] = {
            "schema_version": 1, "request_id": "0" * 32, "revision": 0,
            "item_id": "", "state": "closed", "title": "Release selection",
            "artist": None, "tracks": [], "candidates": [], "message": None,
        }

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return copy.deepcopy(self._state)

    def _notify(self) -> None:
        with suppress(Exception):
            self.on_update(self.snapshot())

    def _change(self, state: str, **values: Any) -> None:
        self._state.update(state=state, revision=self._state["revision"] + 1, **values)

    def _valid(self, request_id: str, revision: int | None = None, *, generation: int | None = None) -> bool:
        if (
            self._closed or request_id != self._state["request_id"]
            or (generation is not None and generation != self._generation)
            or (revision is not None and revision != self._state["revision"])
            or self.clock() >= self._expires or self._binding is None
        ):
            return False
        try:
            return self.source(self._state["item_id"]) == self._binding
        except Exception:
            # A failed source recheck must revoke the choice, not stop the worker.
            return False

    def _schedule(self, operation: str, argument: object) -> None:
        self._pending = (self._generation, self._state["request_id"], operation, argument)
        if self._worker is None:
            self._worker = threading.Thread(target=self._work, name="release-selection", daemon=True)
            self._worker.start()
        self._condition.notify_all()

    def begin(self, item_id: str, request_id: str, page: int = 0) -> None:
        is_catalogue = item_id.startswith("catalogue:") and self.catalogue_choices is not None
        if (not HANDLE.fullmatch(request_id) or not (is_catalogue or item_id.startswith("release:"))
            or len(item_id) > 128 or type(page) is not int or not 0 <= page < 8 or (page and not is_catalogue)):
            raise ValueError("Release selection request is invalid")
        with self._condition:
            if self._closed or self._state["state"] == "working":
                raise ValueError("Selection is unavailable while an action is running")
            binding = self.source(item_id)
            if binding is None:
                raise ValueError("Enable online discovery and select a current release card")
            self._binding = binding
            self._generation += 1
            self._expires = self.clock() + 600
            self._tracks = {}
            self._candidates = {}
            self._album = None
            self._state.pop("page", None)
            self._state.pop("has_more", None)
            self._change(
                "loading", request_id=request_id, item_id=item_id, tracks=[], candidates=[],
                title="Loading this release edition", artist=None, message=None,
            )
            self._schedule("catalogue", (binding[0], page)) if is_catalogue else self._schedule("release", binding[0])
        self._notify()

    def choose(self, request_id: str, revision: int, choice_id: str, intent: str) -> None:
        if (
            not HANDLE.fullmatch(request_id) or not HANDLE.fullmatch(choice_id)
            or type(revision) is not int or revision < 1 or intent not in {"versions", "play", "queue"}
        ):
            raise ValueError("Release selection request is invalid")
        with self._condition:
            if not self._valid(request_id, revision):
                raise ValueError(STALE)
            if intent == "versions":
                track = self._tracks.get(choice_id)
                if track is None or self._state["state"] not in {"tracks", "choices", "complete", "error"}:
                    raise ValueError(STALE)
                self._candidates = {}
                self._change("loading", candidates=[], message="Finding versions; nothing will play automatically")
                self._schedule("versions", track)
            else:
                candidate = self._candidates.get(choice_id)
                if candidate is None or self._state["state"] != "choices":
                    raise ValueError(STALE)
                if self.unavailable(candidate.media):
                    raise ValueError("This version is blocked or unavailable")
                self._change("working", message="Applying your selected version")
                self._schedule(intent, candidate.media)
        self._notify()

    def cancel(self, request_id: str) -> None:
        with self._condition:
            if request_id != self._state["request_id"]:
                return
            if self._state["state"] == "working":
                raise ValueError("Selection is unavailable while an action is running")
            self._binding = None
            self._generation += 1
            self._pending = None
            self._tracks = {}
            self._candidates = {}
            self._change("closed", tracks=[], candidates=[], message=None)
        self._notify()

    def _work(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                assert self._pending is not None
                generation, request_id, operation, argument = self._pending
                self._pending = None
                self._running = True
            try:
                self._perform(generation, request_id, operation, argument)
            except Exception:
                # Provider messages can contain local paths and signed URLs.
                with self._condition:
                    if not self._closed and generation == self._generation:
                        self._change("error", candidates=[], message="Could not complete selection; try again")
            finally:
                with self._condition:
                    if (not self._closed and generation == self._generation
                        and self._state["state"] != "closed" and not self._valid(request_id)):
                        self._change("error", candidates=[], message=STALE)
                    self._running = False
                    self._condition.notify_all()
                if not self._closed:
                    self._notify()

    def _perform(self, generation: int, request_id: str, operation: str, argument: object) -> None:
        with self._condition:
            if not self._valid(request_id, generation=generation):
                if generation == self._generation and not self._closed:
                    self._change("error", candidates=[], message=STALE)
                return
            album = self._album
        if operation == "catalogue":
            assert self.catalogue_choices is not None and isinstance(argument, tuple)
            identifier, page = argument

            def stale() -> bool:
                with self._condition:
                    return not self._valid(request_id, generation=generation)

            media_choices = self.catalogue_choices(identifier, stale)
            with self._condition:
                if not self._valid(request_id, generation=generation):
                    return
                self._candidates = {uuid.uuid4().hex: PlaybackCandidate(media, "published-media")
                                    for media in media_choices[page * 15:(page + 1) * 15]}
                self._change(
                    "choices", title="Published media choices", page=page,
                    has_more=(page + 1) * 15 < min(len(media_choices), 120),
                    candidates=[{
                        "id": key, "title": _text(candidate.media.title, "Published media"),
                        "artist": _text(candidate.media.artist or candidate.media.album, "Publisher supplied media", 160),
                        "source": candidate.media.source.value, "duration": _duration(candidate.media.duration),
                        "match": candidate.match, "playable": self.unavailable(candidate.media) is None,
                        "published_at": _text(candidate.media.resolver_data.get("published"), "Date unknown", 100),
                        "explicit": candidate.media.resolver_data.get("explicit") in (True, "true", "yes", "explicit"),
                    } for key, candidate in self._candidates.items()],
                    message="Publisher order; up to 120 entries. Live radio is not a finite download. Nothing plays until selected.",
                )
        elif operation == "release":
            assert isinstance(argument, str)
            result = self.catalog.inspect_release(argument)
            with self._condition:
                if not self._valid(request_id, generation=generation):
                    return
                self._album = result
                self._tracks = {uuid.uuid4().hex: track for track in result.tracks}
                self._change(
                    "tracks", title=_text(result.title, "Release edition"),
                    artist=_text(result.album_artist, "Unknown artist", 160),
                    tracks=[{
                        "id": key, "title": _text(track.title, "Recording"),
                        "artist": _text(track.artist, "Unknown artist", 160),
                        "duration": _duration(track.duration), "position": track.position,
                    } for key, track in self._tracks.items()],
                    message="Select a recording to inspect playable versions",
                )
        elif operation == "versions":
            assert album is not None and isinstance(argument, AlbumTrack)

            def cancelled() -> bool:
                with self._condition:
                    return not self._valid(request_id, generation=generation)

            choices = self.catalog.playback_candidates(album, argument, cancelled=cancelled)
            with self._condition:
                if not self._valid(request_id, generation=generation):
                    return
                self._candidates = {uuid.uuid4().hex: candidate for candidate in choices[:15]}
                self._change("choices", candidates=[{
                    "id": key, "title": _text(candidate.media.title, "Media version"),
                    "artist": _text(candidate.media.artist, "Unknown artist", 160),
                    "source": candidate.media.source.value,
                    "duration": _duration(candidate.media.duration), "match": candidate.match,
                    "playable": self.unavailable(candidate.media) is None,
                } for key, candidate in self._candidates.items()], message=(
                    "Check the title, performer, and duration before choosing"
                    if choices else "No playable versions found; nothing has changed"
                ))
        else:
            assert isinstance(argument, MediaRef)
            if self.unavailable(argument):
                raise ValueError("This version is blocked or unavailable")
            with self._condition:
                if not self._valid(request_id, generation=generation):
                    return
            self.apply(argument, operation)
            with self._condition:
                if self._valid(request_id, generation=generation):
                    self._change(
                        "complete", candidates=[],
                        message="Added to queue" if operation == "queue" else "Started selected version",
                    )

    def wait(self, timeout: float = 2.0) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: not self._running and self._pending is None, timeout)

    def close(self, timeout: float = 1.0) -> None:
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
        if self._worker and self._worker is not threading.current_thread():
            self._worker.join(timeout)
