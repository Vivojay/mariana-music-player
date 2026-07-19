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
    _spec("playback.play", "play", CommandCategory.PLAYBACK, "Play an indexed item", risk=CommandRisk.STATE_CHANGING, forms=_forms(arguments=("library-index",))),
    _spec("playback.pause", "pause", CommandCategory.PLAYBACK, "Pause playback", risk=CommandRisk.STATE_CHANGING, availability=("current-media",)),
    _spec("playback.stop", "stop", CommandCategory.PLAYBACK, "Stop playback", risk=CommandRisk.STATE_CHANGING, availability=("current-media",)),
    _spec("playback.next", "next", CommandCategory.PLAYBACK, "Advance playback", risk=CommandRisk.STATE_CHANGING),
    _spec("playback.previous", "prev", CommandCategory.PLAYBACK, "Return to previous playback", risk=CommandRisk.STATE_CHANGING),
    _spec("playback.next-immediate", ".next", CommandCategory.PLAYBACK, "Advance and play immediately", risk=CommandRisk.STATE_CHANGING),
    _spec("playback.previous-immediate", ".prev", CommandCategory.PLAYBACK, "Return and play immediately", risk=CommandRisk.STATE_CHANGING),
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
    _spec("queue", "queue", CommandCategory.QUEUE, "Inspect or change the playback queue", risk=CommandRisk.STATE_CHANGING, forms=_forms("list", "tree", "add", "insert", "remove", "move", "jump", "order", "repeat", "reset", "ys", "youtube")),
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
    _spec("download.media-link", "download-ml", CommandCategory.DOWNLOADS, "Download extractor-supported media", risk=CommandRisk.EXTERNAL_ACTION),
    _spec("library", "library", CommandCategory.LIBRARY, "Inspect indexed media", forms=_forms("roots", "status", "info", "verify")),
    _spec("library.scan", "library scan", CommandCategory.LIBRARY, "Scan configured library roots", risk=CommandRisk.STATE_CHANGING),
    _spec("library.clean-missing", "library clean --missing", CommandCategory.LIBRARY, "Confirm removal of missing catalog records", risk=CommandRisk.DESTRUCTIVE, forms=_forms(flags=("--yes",))),
    _spec("library.reload", "reload", CommandCategory.LIBRARY, "Reload indexed media", risk=CommandRisk.STATE_CHANGING),
    _spec("library.rename", "rename", CommandCategory.LIBRARY, "Preview or apply a safe media rename", risk=CommandRisk.DESTRUCTIVE, forms=_forms("short")),
    _spec("favorite", "fav", CommandCategory.FAVORITES, "Inspect or change favourite state", risk=CommandRisk.STATE_CHANGING, forms=_forms("current", "list")),
    _spec("favorites", "favs", CommandCategory.FAVORITES, "List favourite media", forms=_forms("list")),
    _spec("block", "block", CommandCategory.FAVORITES, "Block media from playback", risk=CommandRisk.STATE_CHANGING, forms=_forms("current")),
    _spec("unblock", "unblock", CommandCategory.FAVORITES, "Restore media playability", risk=CommandRisk.STATE_CHANGING),
    _spec("blocked", "blocked", CommandCategory.FAVORITES, "List blocked media", forms=_forms("list")),
    _spec("region", "region", CommandCategory.FAVORITES, "Inspect or change preferred playback bounds", risk=CommandRisk.STATE_CHANGING, forms=_forms("show", "set", "clear", "clear-start", "clear-end", "current")),
    _spec("regions", "regions", CommandCategory.FAVORITES, "List preferred playback bounds"),
    _spec("playlist", "playlist", CommandCategory.PLAYLISTS, "Inspect or change playlists", risk=CommandRisk.STATE_CHANGING, forms=_forms("list", "create", "show", "add", "remove", "move", "order", "play", "queue", "import")),
    _spec("playlist.export", "playlist export", CommandCategory.PLAYLISTS, "Export a playlist with bound overwrite approval", risk=CommandRisk.EXTERNAL_ACTION, forms=_forms(arguments=("playlist-name", "output-path"), flags=("--yes",))),
    _spec("playlist.delete", "playlist delete", CommandCategory.PLAYLISTS, "Confirm deletion of a bound playlist revision", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("playlist-name",), flags=("--yes",))),
    _spec("playlist.clear", "playlist clear", CommandCategory.PLAYLISTS, "Confirm clearing of a bound playlist revision", risk=CommandRisk.DESTRUCTIVE, forms=_forms(arguments=("playlist-name",), flags=("--yes",))),
    _spec("album", "album", CommandCategory.PLAYLISTS, "Search or inspect albums", forms=_forms("search", "show", "tracks", "play", "queue", "save")),
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
