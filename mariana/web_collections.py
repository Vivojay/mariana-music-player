"""Bounded collection views and identity-bound commands for the paired browser."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time

from .albums import AlbumError
from .playlists import PlaylistError
from .presence import sanitize_presence_text
from .radio import RadioError

PAGE_SIZE = 30
COLLECTIONS = frozenset(("queue", "playlists", "albums", "favorites", "live"))
_POSITIONS = {"queue", "favorites"}
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{4,410}\.[0-9a-f]{64}\Z")
_FAILURE = "That collection item changed or no longer exists. Refresh the collection and try again."


def _text(value, fallback=""):
    return sanitize_presence_text(value, maximum=160) or fallback


def _description(*parts):
    return " · ".join(text for part in parts if (text := _text(part)))


def _title(media):
    return _text(media.title, "Local recording" if media.source.value == "local" else "Media")


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def _seal(secret, *claim):
    payload = base64.urlsafe_b64encode(json.dumps(claim, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return payload.decode() + "." + signature


def _open(secret, key):
    if not isinstance(key, str) or not _TOKEN.fullmatch(key):
        raise ValueError("Invalid collection selection.")
    encoded, signature = key.split(".")
    expected = hmac.new(secret.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("This collection selection does not belong to this browser session.")
    try:
        claim = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        kind, identifier, revision, position = claim
    except (TypeError, ValueError, binascii.Error) as error:
        raise ValueError("Invalid collection selection.") from error
    if (not isinstance(kind, str) or kind not in COLLECTIONS or not isinstance(identifier, str) or not _SAFE_ID.fullmatch(identifier)
            or not isinstance(revision, str) or type(position) is not int or position < 0):
        raise ValueError("Invalid collection selection.")
    return kind, identifier, revision, position


class WebCollections:
    """Read the native stores. Actions are validated, then run by the native command dispatcher."""

    def __init__(self, *, queue, albums, favorites, radio):
        self.queue = queue
        self.albums = albums
        self.favorites = favorites
        self.radio = radio
        self._salt = secrets.token_hex(32)
        self._local_albums = ()
        self._local_album_expiry = 0.0

    def _queue_revision(self, items, index):
        return _digest([(item.queue_id, item.media.stable_id, item.added_at, item.group_id)
                        for item in items[max(0, index - 1):index + 2]])

    def _album_revision(self, album):
        return _digest([(track.disc_number, track.track_number, track.title,
                         track.media.stable_id if track.media else None) for track in album.tracks])

    def _favorite_revision(self, entry):
        return _digest((entry.stable_id, entry.updated_at))

    def _radio_revision(self, station):
        return _digest((station.station_id, station.slug, station.favorite, station.endpoints))

    def _queue_actions(self, items, index):
        n = index + 1
        actions = {"play": ("Play", f"queue jump {n}")}
        if index and items[index].group_id == items[index - 1].group_id:
            actions["up"] = ("Move up", f"queue move {n} {n - 1}")
        if n < len(items) and items[index].group_id == items[index + 1].group_id:
            actions["down"] = ("Move down", f"queue move {n} {n + 1}")
        actions["remove"] = ("Remove", f"queue remove {n}")
        return actions

    def _playlist_actions(self, playlist):
        if not playlist.tree.get("items"):
            return {}
        identifier = playlist.playlist_id
        return {"play": ("Play all · replace queue", f"playlist play {identifier}"),
                "queue": ("Add to queue", f"playlist queue {identifier}")}

    def _album_actions(self, album, position):
        if position:
            track = album.tracks[position - 1]
            if track.media is None:
                return {}
            suffix = f"{album.album_id} --tracks {track.disc_number}.{track.track_number}"
            return {"play": ("Play track · replace queue", f"album play {suffix}"),
                    "queue": ("Add track to queue", f"album queue {suffix}")}
        if not album.tracks or any(track.media is None for track in album.tracks):
            return {}
        return {"play": ("Play all · replace queue", f"album play {album.album_id}"),
                "queue": ("Add to queue", f"album queue {album.album_id}")}

    def _radio_actions(self, station):
        return {"play": ("Play live", f"radio play {station.station_id}"),
                "favorite": (("Unstar" if station.favorite else "Star"),
                             f"radio favorite {station.station_id}" + (" off" if station.favorite else ""))}

    def _load_albums(self):
        now = time.monotonic()
        if now >= self._local_album_expiry:
            self._local_albums = tuple(self.albums.local_albums())
            self._local_album_expiry = now + 30.0
        local_ids = {item.album_id for item in self._local_albums}
        cached = self.albums.database.fetchall(
            "SELECT album_id FROM albums WHERE json_valid(album_json) "
            "AND json_extract(album_json, '$.resolution_scope') <> 'local' "
            "ORDER BY updated_at DESC LIMIT 250"
        )
        for row in cached:
            if row["album_id"] not in local_ids:
                try:
                    yield self.albums.get(row["album_id"])
                except AlbumError:
                    continue
        yield from self._local_albums

    def _row(self, secret, claim, title, description="", *, actions=None, detail=False, active=False):
        # References for actions come from internal identifiers, never display labels or input.
        key = _seal(secret, *claim) if _SAFE_ID.fullmatch(claim[1]) else ""
        links = [{"name": name, "label": label, "command": command}
                 for name, (label, command) in (actions or {}).items()] if key else []
        return {"title": title, "description": description, "key": key,
                "detail": bool(key and detail), "active": bool(active), "actions": links}

    def _list(self, kind, secret):
        if kind == "queue":
            items = self.queue.items()
            current = self.queue.current()
            groups = {group.group_id: group.name for group in self.queue.groups()}
            for index, item in enumerate(items):
                media = item.media
                yield self._row(secret, (kind, str(index), self._queue_revision(items, index), 0),
                                _title(media), _description(media.artist, media.album, groups.get(item.group_id)),
                                actions=self._queue_actions(items, index),
                                active=current is not None and current.queue_id == item.queue_id)
        elif kind == "playlists":
            for playlist in self.queue.playlists.list():
                yield self._row(secret, (kind, playlist.playlist_id, str(playlist.revision), 0),
                                _text(playlist.name, "Playlist"), _description(
                                    f"{len(playlist.tree.get('items', []))} tracks", playlist.description),
                                actions=self._playlist_actions(playlist), detail=True)
        elif kind == "albums":
            for album in self._load_albums():
                tracks = f"{len(album.tracks)} tracks" if album.tracks else "Track list not loaded"
                scope = "Local album" if album.resolution_scope == "local" else "Saved edition"
                yield self._row(secret, (kind, album.album_id, self._album_revision(album), 0),
                                _text(album.title, "Album"),
                                _description(album.album_artist, album.date, scope, tracks),
                                actions=self._album_actions(album, 0), detail=True)
        elif kind == "favorites":
            for index, entry in enumerate(self.favorites()):
                source = entry.source.value.title() if entry.source else ""
                actions = {"play": ("Play", f".fav {index + 1}")} if entry.availability not in {"missing", "pending"} else {}
                yield self._row(secret, (kind, str(index), self._favorite_revision(entry), 0),
                                _text(entry.label, "Saved recording"), source, actions=actions)
        else:
            for station in self.radio.list():
                yield self._row(secret, (kind, station.station_id, self._radio_revision(station), 0),
                                _text(station.name, "Internet radio"),
                                _description(station.country, station.provider, "Starred" if station.favorite else None),
                                actions=self._radio_actions(station))

    def _target(self, kind, identifier, revision, position):
        try:
            if kind == "queue":
                items = self.queue.items()
                index = int(identifier)
                return self._queue_actions(items, index) if index < len(items) and (
                    revision == self._queue_revision(items, index)) else None
            if kind == "favorites":
                entries = self.favorites()
                index = int(identifier)
                if index >= len(entries) or revision != self._favorite_revision(entries[index]):
                    return None
                if entries[index].availability in {"missing", "pending"}:
                    return None
                return {"play": ("Play", f".fav {index + 1}")}
            if kind == "playlists":
                playlist = self.queue.playlists.get(identifier)
                return playlist if str(playlist.revision) == revision else None
            if kind == "albums":
                album = self.albums.get(identifier)
                if revision != self._album_revision(album) or position > len(album.tracks):
                    return None
                return album
            station = self.radio.get(identifier)
            return self._radio_actions(station) if revision == self._radio_revision(station) else None
        except (AlbumError, PlaylistError, RadioError):
            return None

    def _detail(self, kind, secret, key):
        group, identifier, revision, position = _open(secret, key)
        if group != kind or group in _POSITIONS or group == "live" or position:
            raise ValueError("Invalid collection detail request.")
        selected = self._target(group, identifier, revision, position)
        if selected is None:
            raise ValueError(_FAILURE)
        if group == "playlists":
            tracks = (self._row(secret, (group, identifier, revision, 0), _title(media),
                                _description(media.artist, media.album)) for media in
                      self.queue.playlists.flattened_media(selected.tree))
            header = self._row(secret, (group, identifier, revision, 0), _text(selected.name, "Playlist"),
                               _text(selected.description), actions=self._playlist_actions(selected))
        else:
            tracks = (self._row(secret, (group, identifier, revision, i),
                                _text(track.title, "Track"), _description(
                                    f"{track.disc_number}.{track.track_number}", track.artist,
                                    None if track.media else "Unresolved"),
                                actions=self._album_actions(selected, i))
                      for i, track in enumerate(selected.tracks, 1))
            header = self._row(secret, (group, identifier, revision, 0), _text(selected.title, "Album"),
                               _description(selected.album_artist, selected.date, selected.disambiguation),
                               actions=self._album_actions(selected, 0))
        return header, tracks

    def read(self, data, token):
        kind, query, offset = data.get("collection"), data.get("query", ""), data.get("offset", 0)
        if (not isinstance(kind, str) or kind not in COLLECTIONS or not isinstance(query, str)
                or len(query) > 160 or type(offset) is not int or not 0 <= offset <= 10_000_000):
            raise ValueError("Invalid collection search.")
        key, secret = data.get("detail"), self._salt + token
        detail, rows = self._detail(kind, secret, key) if key is not None else (None, self._list(kind, secret))
        words = query.casefold().split()
        page, total = [], 0
        for row in rows:
            label = (row["title"] + " " + row["description"]).casefold()
            if all(word in label for word in words):
                if offset <= total < offset + PAGE_SIZE:
                    page.append(row)
                total += 1
        queue_state = self.queue.state() if kind == "queue" else {}
        repeat = queue_state.get("repeat_mode")
        status = {"repeat": repeat if repeat in ("off", "one", "all") else "off",
                  "consume": bool(queue_state.get("consume_mode")),
                  "autofill": bool(queue_state.get("autofill"))}
        return {"collection": kind, "pageSize": PAGE_SIZE, "total": total, "offset": offset,
                "rows": page, "detail": detail, "status": status}

    def command(self, selection, token):
        if not isinstance(selection, dict) or set(selection) != {"key", "action"} or not isinstance(selection["action"], str):
            raise ValueError("Invalid collection action.")
        kind, identifier, revision, position = _open(self._salt + token, selection["key"])
        target = self._target(kind, identifier, revision, position)
        if target is None:
            raise ValueError(_FAILURE)
        actions = (self._playlist_actions(target) if kind == "playlists" else
                   self._album_actions(target, position) if kind == "albums" else target)
        try:
            return actions[selection["action"]][1]
        except KeyError as error:
            raise ValueError("That action is unavailable for this item.") from error
