"""Immutable, privacy-safe command metadata for future completion surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from mariana.commands import ALIAS_COMPATIBILITY


class CommandCategory(StrEnum):
    GETTING_STARTED = "Getting started"
    PLAYBACK = "Playback"
    SEEK_FADE = "Seek and fade"
    QUEUE = "Queue"
    ONLINE = "Search and online sources"
    DOWNLOADS = "Downloads"
    LIBRARY = "Library"
    FAVORITES = "Favourites and blocked media"
    PLAYLISTS = "Playlists and albums"
    LYRICS = "Lyrics"
    RADIO = "Radio and stations"
    DISCORD = "Discord Presence"
    SETTINGS = "Settings"
    DIAGNOSTICS = "Diagnostics"
    DESTRUCTIVE = "Dangerous/destructive commands"


class CommandRisk(StrEnum):
    READ_ONLY = "read-only"
    STATE_CHANGING = "state-changing"
    DESTRUCTIVE = "destructive"
    EXTERNAL_ACTION = "external-action"


@dataclass(frozen=True, slots=True)
class CommandAlias:
    spelling: str
    scope: str
    status: str


@dataclass(frozen=True, slots=True)
class CommandForm:
    tokens: tuple[str, ...] = ()
    argument_kinds: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommandSpec:
    key: str
    canonical: str
    category: CommandCategory
    summary: str
    risk: CommandRisk = CommandRisk.READ_ONLY
    forms: tuple[CommandForm, ...] = ()
    aliases: tuple[CommandAlias, ...] = ()
    availability: tuple[str, ...] = ()
    suggest: bool = True


def _aliases_for(canonical: str) -> tuple[CommandAlias, ...]:
    return tuple(
        CommandAlias(alias, entry.scope, entry.status)
        for entry in ALIAS_COMPATIBILITY
        if entry.canonical == canonical
        for alias in entry.aliases
    )


def _forms(*tokens: str, arguments: tuple[str, ...] = (), flags: tuple[str, ...] = ()) -> tuple[CommandForm, ...]:
    base = (CommandForm(argument_kinds=arguments, flags=flags),) if arguments or flags else ()
    return base + tuple(CommandForm((token,)) for token in tokens)


def _spec(
    key: str,
    canonical: str,
    category: CommandCategory,
    summary: str,
    *,
    risk: CommandRisk = CommandRisk.READ_ONLY,
    forms: tuple[CommandForm, ...] = (),
    availability: tuple[str, ...] = (),
    suggest: bool = True,
) -> CommandSpec:
    return CommandSpec(
        key,
        canonical,
        category,
        summary,
        risk,
        forms,
        _aliases_for(canonical),
        availability,
        suggest,
    )


COMMAND_CATALOG = (
    _spec("help", "help", CommandCategory.GETTING_STARTED, "Show command help", forms=_forms(arguments=("help-topic",))),
    _spec("library.all", "all", CommandCategory.GETTING_STARTED, "List indexed media"),
    _spec("status.now", "now", CommandCategory.PLAYBACK, "Show current playback"),
    _spec("status.now-detail", "now*", CommandCategory.PLAYBACK, "Show detailed current playback"),
    _spec("status.progress", "progress", CommandCategory.PLAYBACK, "Show playback progress"),
    _spec("status.chapters", "chapters", CommandCategory.PLAYBACK, "Inspect chapters or jump within current media", risk=CommandRisk.STATE_CHANGING, forms=_forms("list", "current", "show", "find", "goto", "next", "prev", "first", "last", "restart", "help"), availability=("current-media",)),
    _spec("captions", "captions", CommandCategory.PLAYBACK, "Choose video captions; remember local track and timing preferences", risk=CommandRisk.STATE_CHANGING, forms=_forms("status", "tracks", "select", "auto", "load", "replace", "on", "off", "clear", "offset", "shift"), availability=("current-media",)),
    _spec("captions.language", "captions language", CommandCategory.SETTINGS, "Show or persist ordered caption language codes; auto clears them", risk=CommandRisk.STATE_CHANGING, forms=_forms("auto", arguments=("language-codes",))),
    _spec("avsync", "avsync", CommandCategory.PLAYBACK, "Adjust picture timing against current audio", risk=CommandRisk.STATE_CHANGING, forms=_forms("status", "set", "shift", "reset"), availability=("current-media",)),
    _spec("home", "home", CommandCategory.GETTING_STARTED, "Open the local-first homepage", forms=_forms("status")),
    _spec("home.enable", "home enable", CommandCategory.SETTINGS, "Show the homepage on startup", risk=CommandRisk.STATE_CHANGING),
    _spec("home.disable", "home disable", CommandCategory.SETTINGS, "Do not show the homepage on startup", risk=CommandRisk.STATE_CHANGING),
    _spec("home.online-enable", "home online enable", CommandCategory.SETTINGS, "Allow online homepage discovery", risk=CommandRisk.EXTERNAL_ACTION),
    _spec("home.online-disable", "home online disable", CommandCategory.SETTINGS, "Disable online homepage discovery", risk=CommandRisk.STATE_CHANGING),
    _spec("home.refresh", "home refresh", CommandCategory.ONLINE, "Refresh opted-in homepage discoveries", risk=CommandRisk.EXTERNAL_ACTION, availability=("homepage-online-enabled",)),
    _spec("thumb", "thumb", CommandCategory.SETTINGS, "Show current artwork status", forms=_forms("status")),
    _spec("thumb.enable", "thumb enable", CommandCategory.SETTINGS, "Enable automatic online artwork", risk=CommandRisk.EXTERNAL_ACTION),
    _spec("thumb.disable", "thumb disable", CommandCategory.SETTINGS, "Disable automatic online artwork", risk=CommandRisk.STATE_CHANGING),
    _spec("thumb.show", "thumb show", CommandCategory.SETTINGS, "Display current media artwork", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms(flags=("--fetch",)), availability=("current-media",)),
    _spec("playback.play", "play", CommandCategory.PLAYBACK, "Play an indexed item", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("library-index",))),
    _spec("playback.pause", "pause", CommandCategory.PLAYBACK, "Pause playback", risk=CommandRisk.STATE_CHANGING, availability=("current-media",)),
    _spec("playback.stop", "stop", CommandCategory.PLAYBACK, "Stop playback", risk=CommandRisk.STATE_CHANGING, availability=("current-media",)),
    _spec("playback.next", "next", CommandCategory.PLAYBACK, "Preview ahead; optionally choose a collection without changing the active scope", forms=_forms("library", "queue", "favorites", "playlist", "results", arguments=("positive-count", "collection"), flags=("--in",))),
    _spec("playback.previous", "prev", CommandCategory.PLAYBACK, "Preview behind; optionally choose a collection without changing the active scope", forms=_forms("library", "queue", "favorites", "playlist", "results", arguments=("positive-count", "collection"), flags=("--in",))),
    _spec("playback.next-immediate", ".next", CommandCategory.PLAYBACK, "Advance and play within the current or explicitly chosen collection", risk=CommandRisk.STATE_CHANGING, forms=_forms("library", "queue", "favorites", "playlist", "results", arguments=("positive-count", "collection"), flags=("--in",))),
    _spec("playback.previous-immediate", ".prev", CommandCategory.PLAYBACK, "Return and play within the current or explicitly chosen collection", risk=CommandRisk.STATE_CHANGING, forms=_forms("library", "queue", "favorites", "playlist", "results", arguments=("positive-count", "collection"), flags=("--in",))),
    _spec("playback.mute", "m", CommandCategory.PLAYBACK, "Toggle mute", risk=CommandRisk.STATE_CHANGING),
    _spec("playback.volume", "volume", CommandCategory.PLAYBACK, "Set playback volume", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("volume",))),
    _spec("playback.autonext", "autonext", CommandCategory.PLAYBACK, "Configure automatic advance", risk=CommandRisk.STATE_CHANGING, forms=_forms("on", "off", "status")),
    _spec("playback.random", "rand", CommandCategory.PLAYBACK, "Select random indexed media", risk=CommandRisk.STATE_CHANGING),
    _spec("playback.random-detail", "rand*", CommandCategory.PLAYBACK, "Inspect random indexed media"),
    _spec("playback.random-immediate", ".rand", CommandCategory.PLAYBACK, "Play random indexed media", risk=CommandRisk.STATE_CHANGING),
    _spec("playback.random-source", "/rand", CommandCategory.PLAYBACK, "Play random source media", risk=CommandRisk.STATE_CHANGING),
    _spec("playback.random-index", "=rand", CommandCategory.PLAYBACK, "Return a random library index"),
    _spec("seek", "seek", CommandCategory.SEEK_FADE, "Seek within finite media", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("seek-target",)), availability=("finite-media",)),
    _spec("fade", "fade", CommandCategory.SEEK_FADE, "Fade playback volume", risk=CommandRisk.STATE_CHANGING, forms=_forms("in", "out", "to", "from")),
    _spec("queue", "queue", CommandCategory.QUEUE, "Inspect or change the playback queue; next/previous accept 1-100 steps per command", risk=CommandRisk.STATE_CHANGING, forms=_forms("list", "tree", "add", "insert", "remove", "move", "jump", "next", "previous", "order", "repeat", "reset", "ys", "youtube")),
    _spec("queue.clear", "queue clear", CommandCategory.QUEUE, "Confirm and clear the playback queue", risk=CommandRisk.STATE_CHANGING, forms=_forms(flags=("--yes",))),
    _spec("queue.youtube", "queue ys", CommandCategory.QUEUE, "Queue an online search result", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms(arguments=("free-text",))),
    _spec("search.find", "find", CommandCategory.ONLINE, "Search indexed media", forms=_forms(arguments=("free-text",))),
    _spec("search.raw", "rfind", CommandCategory.ONLINE, "Search indexed media literally", forms=_forms(arguments=("free-text",))),
    _spec("search.loose", "lfind", CommandCategory.ONLINE, "Search indexed media loosely", forms=_forms(arguments=("free-text",))),
    _spec("youtube.search", "/ys", CommandCategory.ONLINE, "Search and play YouTube media", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms(arguments=("free-text",))),
    _spec("youtube.link", "/yl", CommandCategory.ONLINE, "Play a YouTube link", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms(arguments=("url",))),
    _spec("media.link", "/ml", CommandCategory.ONLINE, "Play an extractor-supported link", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms(arguments=("url",))),
    _spec(
        "reddit.retired",
        "/rs",
        CommandCategory.ONLINE,
        "Show retired Reddit command guidance",
        suggest=False,
    ),
    _spec("download.video", "download-yv", CommandCategory.DOWNLOADS, "Download video media", risk=CommandRisk.EXTERNAL_ACTION),
    _spec("download.audio", "download-ya", CommandCategory.DOWNLOADS, "Download audio media", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms("status")),
    _spec(
        "download.default",
        "dl",
        CommandCategory.DOWNLOADS,
        "Confirm and download active or most-recent finite online media",
        risk=CommandRisk.EXTERNAL_ACTION,
        forms=_forms(flags=("--yes",)),
    ),
    _spec("download.media-link", "download-ml", CommandCategory.DOWNLOADS, "Download extractor-supported media", risk=CommandRisk.EXTERNAL_ACTION),
    _spec("library", "library", CommandCategory.LIBRARY, "Inspect indexed media", forms=_forms("roots", "status", "info", "verify")),
    _spec("library.scan", "library scan", CommandCategory.LIBRARY, "Scan configured library roots", risk=CommandRisk.STATE_CHANGING),
    _spec("library.clean-missing", "library clean --missing", CommandCategory.LIBRARY, "Confirm removal of missing catalog records", risk=CommandRisk.DESTRUCTIVE, forms=_forms(flags=("--yes",))),
    _spec("library.reload", "reload", CommandCategory.LIBRARY, "Reload indexed media", risk=CommandRisk.STATE_CHANGING),
    _spec("library.rename", "rename", CommandCategory.LIBRARY, "Preview or apply a safe media rename", risk=CommandRisk.DESTRUCTIVE, forms=_forms("short")),
    _spec("favorite", "fav", CommandCategory.FAVORITES, "Inspect or change favourite state", risk=CommandRisk.STATE_CHANGING, forms=_forms("current", "list", "next", "prev", "previous")),
    _spec("favorites", "favs", CommandCategory.FAVORITES, "List favourite media", forms=_forms("list")),
    _spec("block", "block", CommandCategory.FAVORITES, "Block media from playback", risk=CommandRisk.STATE_CHANGING, forms=_forms("current")),
    _spec("unblock", "unblock", CommandCategory.FAVORITES, "Restore media playability", risk=CommandRisk.STATE_CHANGING),
    _spec("blocked", "blocked", CommandCategory.FAVORITES, "List blocked media", forms=_forms("list")),
    _spec(
        "region", "region", CommandCategory.FAVORITES,
        "Set only start: region current start <time>; only end: region current end <time>. "
        "Use a library index instead of current for another track; help region shows all forms.",
        risk=CommandRisk.STATE_CHANGING,
        forms=(
            CommandForm(argument_kinds=("current-or-library-index", "start-time", "end-time")),
            CommandForm(tokens=("current", "start"), argument_kinds=("time",)),
            CommandForm(tokens=("current", "end"), argument_kinds=("time",)),
            CommandForm(tokens=("help",)),
            *(CommandForm(tokens=(operation,), argument_kinds=("current-or-library-index",))
              for operation in ("show", "clear", "clear-start", "clear-end")),
        ),
    ),
    _spec("regions", "regions", CommandCategory.FAVORITES, "List preferred playback bounds"),
    _spec("playlist", "playlist", CommandCategory.PLAYLISTS, "Inspect or change playlists", risk=CommandRisk.STATE_CHANGING, forms=_forms("list", "create", "show", "add", "remove", "move", "order", "play", "next", "prev", "previous", "queue", "import")),
    _spec("playlist.history", "playlist history", CommandCategory.PLAYLISTS, "List current and retained playlist revisions", forms=_forms(arguments=("playlist-name",))),
    _spec("playlist.restore", "playlist restore", CommandCategory.PLAYLISTS, "Restore a retained tree as a new revision after confirmation", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("playlist-name", "revision"), flags=("--yes",))),
    _spec(
        "collection.transfer-copy",
        "transfer copy",
        CommandCategory.PLAYLISTS,
        "Copy one or more ordered selections between playlists and favourites",
        risk=CommandRisk.STATE_CHANGING,
        forms=_forms(
            arguments=("to collection", "from collection", "items 1,2,6|3-5|all"),
            flags=("--dry-run",),
        ),
    ),
    _spec(
        "collection.transfer-move",
        "transfer move",
        CommandCategory.PLAYLISTS,
        "Atomically move ordered selections between playlists and favourites",
        risk=CommandRisk.DESTRUCTIVE,
        forms=_forms(
            arguments=("to collection", "from collection", "items 1,2,6|3-5|all"),
            flags=("--dry-run", "--yes"),
        ),
    ),
    _spec("playlist.export", "playlist export", CommandCategory.PLAYLISTS, "Export a playlist with bound overwrite approval", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms(arguments=("playlist-name", "output-path"), flags=("--yes",))),
    _spec("playlist.delete", "playlist delete", CommandCategory.PLAYLISTS, "Confirm deletion of a bound playlist revision", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("playlist-name",), flags=("--yes",))),
    _spec("playlist.clear", "playlist clear", CommandCategory.PLAYLISTS, "Confirm clearing of a bound playlist revision", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("playlist-name",), flags=("--yes",))),
    _spec("album", "album", CommandCategory.PLAYLISTS, "Search or inspect albums", forms=_forms("search", "show", "tracks", "play", "queue", "save")),
    _spec("tag", "tag", CommandCategory.LIBRARY, "List durable media tags; tag help explains targets and search", forms=_forms("help", "list", "show", "find")),
    _spec("tag.create", "tag create", CommandCategory.LIBRARY, "Create a tag without changing media files", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("tag-name",), flags=("--description",))),
    _spec("tag.attach", "tag attach", CommandCategory.LIBRARY, "Attach tags to current media or a stable library selection", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("current-or-library-index", "tag-name"))),
    _spec("tag.detach", "tag detach", CommandCategory.LIBRARY, "Remove tag assignments without deleting definitions", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("current-or-library-index", "tag-name"))),
    _spec("tag.rename", "tag rename", CommandCategory.LIBRARY, "Rename a tag while preserving assignments", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("tag-name", "new-name"))),
    _spec("tag.delete", "tag delete", CommandCategory.LIBRARY, "Delete a tag; attached tags require confirmation", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("tag-name",), flags=("--yes",))),
    _spec("tag.find", "tag find", CommandCategory.LIBRARY, "Search all, any, or excluded tags and reusable groups", forms=_forms(flags=("--all", "--any", "--not", "--group", "--source", "--limit"))),
    _spec("tag.play", "tag play", CommandCategory.LIBRARY, "Play an explicitly selected bound tag result", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("tag-result-number",))),
    _spec("tag.queue", "tag queue", CommandCategory.LIBRARY, "Append an explicitly selected tag result to the queue", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("tag-result-number",))),
    _spec("tag.group", "tag group", CommandCategory.LIBRARY, "Manage reusable tag groups", risk=CommandRisk.STATE_CHANGING, forms=_forms("create", "list", "show", "rename", "delete", "add", "remove")),
    _spec("lyrics", "lyrics", CommandCategory.LYRICS, "Show current lyrics"),
    _spec("lyrics.edit", "lyrics edit", CommandCategory.LYRICS, "Create or open an adjacent lyrics sidecar safely", risk=CommandRisk.STATE_CHANGING, forms=_forms(flags=("--yes",))),
    _spec("radio", "radio", CommandCategory.RADIO, "Search, play, or inspect radio", risk=CommandRisk.STATE_CHANGING, forms=_forms("search", "list", "play", "add", "info", "metadata", "resync", "health", "leveling")),
    _spec("station", "station", CommandCategory.RADIO, "Control recommendation stations", risk=CommandRisk.STATE_CHANGING, forms=_forms("start", "stop", "pause", "resume", "status", "next")),
    _spec("discord", "discord", CommandCategory.DISCORD, "Configure Discord Rich Presence", risk=CommandRisk.STATE_CHANGING, forms=_forms("presence")),
    _spec("theme", "theme", CommandCategory.SETTINGS, "Inspect or change the theme", risk=CommandRisk.STATE_CHANGING, forms=_forms("list")),
    _spec("desktop", "desktop", CommandCategory.SETTINGS, "Configure desktop behavior", risk=CommandRisk.STATE_CHANGING, forms=_forms("close")),
    _spec("sleep", "sleep", CommandCategory.SETTINGS, "Configure the sleep timer", risk=CommandRisk.STATE_CHANGING, forms=_forms("status", "cancel")),
    _spec("media", "media", CommandCategory.DIAGNOSTICS, "Inspect current or indexed media", forms=_forms("info", "probe", "fingerprint", "identify", "local-match")),
    _spec("tools", "tools", CommandCategory.DIAGNOSTICS, "Inspect managed tools", forms=_forms("status")),
    _spec("remove", "rm", CommandCategory.DESTRUCTIVE, "Move indexed media to trash", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("library-index",), flags=("--yes",))),
    _spec("delete-alias", "del", CommandCategory.DESTRUCTIVE, "Move indexed media to trash", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("library-index",), flags=("--yes",))),
    _spec("exit", "exit", CommandCategory.DESTRUCTIVE, "Exit Mariana", risk=CommandRisk.STATE_CHANGING, forms=_forms(flags=("--yes",))),
    _spec("hotspots", "hotspots", CommandCategory.SETTINGS, "Inspect local personal interaction hotspots", forms=_forms("status", "current")),
    _spec("hotspots.enable", "hotspots enable", CommandCategory.SETTINGS, "Enable local playback-event capture", risk=CommandRisk.STATE_CHANGING),
    _spec("hotspots.disable", "hotspots disable", CommandCategory.SETTINGS, "Disable local playback-event capture", risk=CommandRisk.STATE_CHANGING),
    _spec("hotspots.retention", "hotspots retention", CommandCategory.SETTINGS, "Set local playback-event retention", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("days",))),
    _spec("hotspots.logging", "hotspots logging", CommandCategory.SETTINGS, "Configure optional playback-event log forwarding", risk=CommandRisk.STATE_CHANGING, forms=_forms("on", "off")),
    _spec("hotspots.clear", "hotspots clear", CommandCategory.SETTINGS, "Clear local personal interaction history", risk=CommandRisk.DESTRUCTIVE, forms=_forms(flags=("--yes",))),
    _spec("eq", "eq", CommandCategory.SETTINGS, "Inspect local listening equalizer", forms=_forms("status")),
    _spec("eq.configure", "eq on", CommandCategory.SETTINGS, "Enable local listening equalizer", risk=CommandRisk.STATE_CHANGING),
    _spec("eq.off", "eq off", CommandCategory.SETTINGS, "Bypass local listening equalizer", risk=CommandRisk.STATE_CHANGING),
    _spec("eq.band", "eq band", CommandCategory.SETTINGS, "Set a graphic EQ band", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("frequency", "gain-db"))),
    _spec("eq.preamp", "eq preamp", CommandCategory.SETTINGS, "Set EQ preamp", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("gain-db",))),
    _spec("eq.reset", "eq reset", CommandCategory.SETTINGS, "Restore flat EQ without changing bypass", risk=CommandRisk.STATE_CHANGING),
    _spec("eq.preset-list", "eq preset list", CommandCategory.SETTINGS, "List factory and user EQ presets"),
    _spec("eq.preset-apply", "eq preset apply", CommandCategory.SETTINGS, "Apply a tonal preset", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("preset-name",))),
    _spec("eq.preset-save", "eq preset save", CommandCategory.SETTINGS, "Save a new user EQ preset", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("preset-name",))),
    _spec("eq.preset-delete", "eq preset delete", CommandCategory.SETTINGS, "Delete a named user EQ preset", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("preset-name",))),
    _spec("playback.loop", "loop", CommandCategory.PLAYBACK, "Loop current finite media once or indefinitely", risk=CommandRisk.STATE_CHANGING, forms=_forms("status", "once", "infinite", "off", "1", "on", "forever"), availability=("current-media",)),
    _spec("playback.reset", "reset", CommandCategory.PLAYBACK, "Rewind finite media while preserving active play/pause state", risk=CommandRisk.STATE_CHANGING, availability=("finite-media",)),
    _spec("playback.reset-immediate", ".reset", CommandCategory.PLAYBACK, "Rewind finite media and play immediately", risk=CommandRisk.STATE_CHANGING, availability=("finite-media",)),
    _spec("playback.restart", "restart", CommandCategory.PLAYBACK, "Return to the preferred-region start, or absolute zero when no start is set", risk=CommandRisk.STATE_CHANGING, availability=("finite-media",)),
)


_ALLOWED_SCOPES = {"exact", "token", "both"}
_ALLOWED_STATUSES = {"native", "compatibility-only", "retired"}


def validate_command_catalog(catalog: tuple[CommandSpec, ...] = COMMAND_CATALOG) -> None:
    """Reject ambiguous or structurally unsafe command metadata."""
    keys: set[str] = set()
    canonical: set[str] = set()
    aliases: set[str] = set()
    covered_aliases: set[tuple[str, str, str, str]] = set()
    for spec in catalog:
        if not spec.key or spec.key in keys:
            raise ValueError(f"Duplicate command key: {spec.key}")
        keys.add(spec.key)
        normalized = spec.canonical.casefold()
        if not normalized or normalized in canonical:
            raise ValueError(f"Duplicate canonical command: {spec.canonical}")
        canonical.add(normalized)
        if not isinstance(spec.category, CommandCategory):
            raise ValueError(f"Unknown command category: {spec.category}")
        if not isinstance(spec.risk, CommandRisk):
            raise ValueError(f"Unknown command risk: {spec.risk}")
        if not spec.summary or len(spec.summary) > 240 or any(ord(character) < 32 for character in spec.summary):
            raise ValueError(f"Unsafe command summary: {spec.key}")
        structural_values = (
            spec.key,
            spec.canonical,
            *spec.availability,
            *(value for form in spec.forms for value in (*form.tokens, *form.argument_kinds, *form.flags)),
        )
        if any(not value or len(value) > 128 or any(ord(character) < 32 for character in value) for value in structural_values):
            raise ValueError(f"Unsafe command metadata: {spec.key}")
        for alias in spec.aliases:
            normalized_alias = alias.spelling.casefold()
            if (
                not normalized_alias
                or len(alias.spelling) > 128
                or any(ord(character) < 32 for character in alias.spelling)
                or normalized_alias in aliases
                or normalized_alias in canonical
            ):
                raise ValueError(f"Ambiguous command alias: {alias.spelling}")
            if alias.scope not in _ALLOWED_SCOPES or alias.status not in _ALLOWED_STATUSES:
                raise ValueError(f"Invalid command alias metadata: {alias.spelling}")
            aliases.add(normalized_alias)
            covered_aliases.add((alias.spelling, spec.canonical, alias.scope, alias.status))

    expected_aliases = {
        (alias, entry.canonical, entry.scope, entry.status)
        for entry in ALIAS_COMPATIBILITY
        for alias in entry.aliases
    }
    collision = aliases & canonical
    if collision:
        raise ValueError(f"Alias collides with canonical command: {sorted(collision)[0]}")
    if covered_aliases != expected_aliases:
        raise ValueError("Command catalog does not cover the compatibility alias registry")


def serialize_command_catalog(
    *,
    include_compatibility: bool = False,
    typed_prefix: str = "",
) -> tuple[dict[str, Any], ...]:
    """Return deterministic public metadata without handlers or private state."""
    validate_command_catalog()
    prefix = typed_prefix.casefold()
    rows = []
    for spec in sorted(COMMAND_CATALOG, key=lambda item: (item.category.value, item.canonical.casefold(), item.key)):
        if not spec.suggest:
            continue
        visible_aliases = [
            alias.spelling
            for alias in spec.aliases
            if alias.status == "native"
            or (
                alias.status == "compatibility-only"
                and (include_compatibility or bool(prefix and alias.spelling.casefold().startswith(prefix)))
            )
        ]
        rows.append(
            {
                "key": spec.key,
                "canonical": spec.canonical,
                "category": spec.category.value,
                "summary": spec.summary,
                "risk": spec.risk.value,
                "aliases": tuple(visible_aliases),
                "forms": tuple(
                    {
                        "tokens": form.tokens,
                        "argument_kinds": form.argument_kinds,
                        "flags": form.flags,
                    }
                    for form in spec.forms
                ),
                "availability": spec.availability,
            }
        )
    return tuple(rows)


validate_command_catalog()
