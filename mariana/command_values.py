"""Local argument suggestions. This module never starts Mariana or resolves network media."""

from __future__ import annotations

import heapq
import json
import os
import re
import sqlite3
from collections.abc import Iterable
from functools import lru_cache
from itertools import islice
from pathlib import Path

_LIMIT = 40
_MEDIA = frozenset(".mp3 .wav .flac .ogg .oga .opus .m4a .m4b .aac .aif .aiff .wma .alac .mp4 .mkv .webm .mov .m4v .avi".split())
_EXTENSIONS = {
    "audio-file": _MEDIA, "audio-path": _MEDIA, "media-file": _MEDIA, "media-path": _MEDIA,
    "wav-file": {".wav"}, "ttml": {".xml", ".ttml"}, "ttml-path": {".xml", ".ttml"},
    "first-ttml": {".xml", ".ttml"}, "second-ttml": {".xml", ".ttml"}, "timing-sheet": {".json"},
    "invite-file": {".json"}, "source-path": {".js", ".txt", ".strudel", ".mjs"},
    "playlist-file": {".m3u8", ".m3u"}, "m3u-file": {".m3u8", ".m3u"},
    "caption-file": {".srt", ".vtt", ".ass", ".ssa", ".sub"}, "subtitle-file": {".srt", ".vtt", ".ass", ".ssa", ".sub"},
}
_PATH_KINDS = frozenset({"file", "path", "existing-file", "input-path", "indexed-path", "local-path",
                         "output-path", "directory", "folder", "model-directory"}) | _EXTENSIONS.keys()


def _safe(value):
    return isinstance(value, str) and 0 < len(value) <= 1024 and all(ch.isprintable() for ch in value)


def _paths(prefix: str, kind: str) -> Iterable[str]:
    # UNC/device namespaces, URLs and drive-relative aliases can contact a host or
    # resolve to a different working directory. Only inspect the typed local parent.
    if (len(prefix) > 1024 or (prefix and not _safe(prefix)) or "://" in prefix
            or prefix.startswith(("//", "\\\\")) or re.match(r"^[A-Za-z]:(?![/\\])", prefix)):
        return ()
    if prefix == "~":
        return ("~" + os.sep,)
    if os.name == "nt":
        cut = max(prefix.rfind("/"), prefix.rfind("\\")) + 1
    else:
        cut = prefix.rfind("/") + 1
    parent, partial = prefix[:cut], prefix[cut:]
    directory = Path(parent or ".").expanduser()
    suffixes = _EXTENSIONS.get(kind)
    dirs_only = kind in {"directory", "folder", "model-directory", "output-path"} or kind.startswith("new-")
    ending = "/" if parent.endswith("/") else os.sep
    try:
        matches = []
        with os.scandir(directory) as entries:
            for entry in islice(entries, 8192):
                name = entry.name
                if ((name.startswith(".") and not partial.startswith("."))
                        or not name.casefold().startswith(partial.casefold()) or not _safe(name)):
                    continue
                try:
                    folder = entry.is_dir()
                    if not folder and (dirs_only or suffixes and Path(name).suffix.casefold() not in suffixes
                                       or not entry.is_file()):
                        continue
                except OSError:
                    continue
                matches.append(parent + name + (ending if folder else ""))
        return heapq.nsmallest(_LIMIT, matches, key=str.casefold)
    except (OSError, RuntimeError, ValueError):
        return ()


def _indices(count: int, prefix: str) -> Iterable[str]:
    # Prefix ranges keep typing "22" fast even in large libraries.
    if not prefix:
        return (str(i) for i in range(1, min(count, _LIMIT) + 1))
    if len(prefix) > 12 or not re.fullmatch(r"[1-9][0-9]*", prefix):
        return ()
    low, high = int(prefix), int(prefix)
    found = []
    while low <= count and len(found) < _LIMIT:
        found.extend(str(i) for i in range(low, min(count + 1, high + 1, low + _LIMIT - len(found))))
        low, high = low * 10, high * 10 + 9
    return found


@lru_cache(maxsize=3)
def _bundled(filename):
    return json.loads(Path(__file__).with_name(filename).read_text(encoding="utf-8"))


def _local_names(database, table: str, prefix):
    if database is None:
        return ()
    # The source is selected by the command, never by the buffer's contents.
    sql = {
        "playlists": "SELECT name FROM playlists WHERE name_key LIKE ? ESCAPE '!' ORDER BY name_key LIMIT ?",
        "tags": "SELECT name FROM tags WHERE name_key LIKE ? ESCAPE '!' ORDER BY name_key LIMIT ?",
        "tag_groups": "SELECT name FROM tag_groups WHERE name_key LIKE ? ESCAPE '!' ORDER BY name_key LIMIT ?",
    }[table]
    pattern = prefix.casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    return (row["name"] for row in database.fetchall(sql, (pattern, _LIMIT)))


def _node_paths(nodes, groups_only):
    for node in nodes:
        if not groups_only or node["type"] == "group":
            yield node["path"]
        yield from _node_paths(node.get("children", ()), groups_only)


def make_value_provider(runtime=None):
    """Bind to an already initialized player. No credential store or live API is consulted."""
    def candidates(kind, prefix, tokens):
        kind = kind.removeprefix("optional-")
        command = tuple(str(token).casefold() for token in tokens[:2])
        library_count = len(getattr(runtime, "_sound_files", ()))
        if kind in {"file-or-library-index", "media", "media-reference", "library-index or path or relative reference",
                    "url or local reference", "URL or local reference"}:
            return (*_indices(library_count, prefix), *_paths(prefix, "media-file"))
        if kind == "--to" and command and command[0] in {"download-ya", "dl-ya", "librivox", "libri", "lv"}:
            return _paths(prefix, "directory")
        if kind == "file-or-url":
            return _paths(prefix, "playlist-file" if command == ("playlist", "import") else "file")
        if kind in _PATH_KINDS or kind.startswith("new-") and ("file" in kind or "path" in kind or "sheet" in kind):
            return _paths(prefix, kind)
        if kind == "current-or-library-index":
            return ("current", *_indices(library_count, prefix))
        if kind in {"library-index", "library-number"}:
            return _indices(library_count, prefix)
        if kind in {"queue-position", "queue-index", "queue-number"}:
            queue = getattr(runtime, "QUEUE", None)
            if queue is None:
                return ()
            count = queue.playback_position(None)[1] + (1 if command == ("queue", "insert") else 0)
            return _indices(count, prefix)
        if kind in {"playlist", "playlist-name", "existing-playlist", "playlist-name-or-id", "queue-snapshot-name"}:
            return _local_names(getattr(runtime, "DATABASE", None), "playlists", prefix)
        if command[:1] == ("playlist",) and len(tokens) >= 3:
            store = getattr(getattr(runtime, "QUEUE", None), "playlists", None)
            if store is not None and kind == "revision" and command == ("playlist", "restore"):
                return (str(rev) for rev in store.revisions(tokens[2]))
            if store is not None and kind in {"item-position", "--parent", "--group"}:
                nodes = _node_paths(store.nodes(tokens[2]), groups_only=kind != "item-position")
                return (*(["root"] if kind == "--parent" else []), *nodes)
        if kind in {"queue-group", "queue-node", "group", "--group", "--parent"} and command[:1] == ("queue",):
            queue = getattr(runtime, "QUEUE", None)
            if queue is None:
                return ()
            return (*(["root"] if kind == "--parent" else []), *_node_paths(queue.tree(), kind != "queue-node"))
        if kind in {"tag-name", "--all", "--any", "--not", "tag-group", "--group"} and command[:1] == ("tag",):
            table = "tag_groups" if kind in {"tag-group", "--group"} else "tags"
            return _local_names(getattr(runtime, "DATABASE", None), table, prefix)
        if kind == "--source" and command[:1] == ("tag",):
            from .models import MediaSource
            return tuple(source.value for source in MediaSource)
        if kind == "tag-result" and command[:1] == ("tag",):
            context = getattr(runtime, "_LAST_TAG_CONTEXT", None)
            return _indices(len(getattr(context, "entries", ())), prefix)
        if kind == "procedure-name" and command[:1] == ("tone",):
            from .tone_procedures import procedure_names
            paths = getattr(runtime, "RUNTIME_PATHS", None)
            database = paths.state("tone-procedures.sqlite3") if paths else None
            return procedure_names(database, prefix, _LIMIT)
        if kind == "radio-station":
            database = getattr(runtime, "DATABASE", None)
            if database:
                return (row["slug"] for row in database.fetchall(
                    "SELECT slug FROM radio_stations WHERE enabled=1 AND slug LIKE ? ORDER BY slug LIMIT ?",
                    (prefix + "%", _LIMIT)))
        if kind in {"eq-preset", "preset-name"} and command == ("eq", "preset") and len(tokens) >= 3:
            service = getattr(runtime, "EQUALIZER", None)
            if service is not None and tokens[2].casefold() in {"apply", "delete"}:
                custom = tuple(service.presets)
                if tokens[2].casefold() == "delete":
                    return custom
                from .equalizer import FACTORY_PRESETS
                return (*FACTORY_PRESETS, *custom)
        if kind in {"theme", "theme-name", "preset-name"} and command[:1] == ("theme",):
            return _bundled("theme_presets.json")
        if kind in {"color-key", "theme-key", "token", "color-token"} and command == ("theme", "color"):
            themes = _bundled("theme_presets.json")
            appearance = getattr(runtime, "SETTINGS", {}).get("appearance", {})
            theme = themes.get(appearance.get("terminal theme"), themes["aurora"])
            return (f"{group}.{key}" for group in ("chrome", "terminal") for key in theme[group])
        if kind in {"provider", "provider-id", "service", "service-id"} and command[:1] == ("accounts",):
            return _bundled("connection_providers.json")
        if command[:1] == ("strudel",):
            store = getattr(runtime, "STRUDEL_PROJECTS", None)
            if store is not None and kind in {"project", "project-name-or-id", "project-id"}:
                return (p.project_id if kind == "project-id" else p.name for p in store.list())
            if store is not None and kind == "revision" and len(tokens) == 3:
                return (str(store.get(tokens[2]).revision),)
        if command[:1] == ("karaoke",) and kind in {"singer", "singer-name"}:
            sheet = getattr(getattr(runtime, "KARAOKE", None), "sheet", None)
            return ("all", *getattr(sheet, "singers", ()))
        if command[:1] in {("librivox",), ("lv",), ("libri",)}:
            books = getattr(getattr(runtime, "LIBRIVOX", None), "results", ())
            if kind in {"book-ref", "book-reference", "result-or-id"}:
                return (*_indices(len(books), prefix), *("id:" + book.catalog_id for book in books))
            if kind in {"chapter", "chapter-or-all"} and len(tokens) >= 3:
                ref = tokens[2]
                book = next((b for n, b in enumerate(books, 1) if ref in {str(n), "id:" + b.catalog_id}), None)
                return (*_indices(book.section_count, prefix),) if book else ()
        if command[:1] == ("podbean",):
            shelf = getattr(runtime, "_podbean_shelf", None)
            if kind in {"episode-number", "episode-index"}:
                return _indices(len(getattr(shelf, "rows", ())), prefix)
            if kind in {"show", "show-slug-or-feed", "show-slug"}:
                db = getattr(runtime, "DATABASE", None)
                followed = db.get_state("podbean.followed.v1", {}) if db is not None else {}
                choices = list(followed) if isinstance(followed, dict) else []
                if command != ("podbean", "unfollow") and shelf is not None:
                    choices.extend([shelf.slug, *getattr(shelf, "search_results", {})])
                return choices
        if command[:1] == ("artist",) and kind in {"followed-id", "artist-id", "item-id"}:
            database = getattr(runtime, "DATABASE", None)
            if database is None:
                return ()
            if kind == "item-id" and command == ("artist", "read"):
                return (row["item_id"] for row in database.fetchall(
                    "SELECT item_id FROM artist_inbox WHERE is_read=0 AND item_id LIKE ? ORDER BY item_id LIMIT ?",
                    (prefix + "%", _LIMIT)))
            if command != ("artist", "follow"):
                pattern = "artist.follow." + prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
                return (row["key"].removeprefix("artist.follow.") for row in database.fetchall(
                    "SELECT key FROM app_state WHERE key LIKE ? ESCAPE '!' ORDER BY key LIMIT ?", (pattern, _LIMIT)))
        if command[:1] == ("session",) and kind in {"session-name", "recipe-name"} and command != ("session", "record"):
            paths = getattr(runtime, "RUNTIME_PATHS", None)
            return (f.stem for f in paths.state("sessions").glob("*.jsonl")
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", f.stem)) if paths else ()
        return ()

    def provide(kind, prefix, tokens):
        if not isinstance(prefix, str) or len(prefix) > 1024:
            return ()
        try:
            values = (v for v in candidates(kind, prefix, tokens) if _safe(v) and v.casefold().startswith(prefix.casefold()))
            return tuple(dict.fromkeys(islice(values, _LIMIT)))
        except (OSError, RuntimeError, ValueError, sqlite3.Error, KeyError):
            # A locked database, removed directory or conflicting project edit
            # leaves the user free to continue typing and run the command.
            return ()
    return provide
