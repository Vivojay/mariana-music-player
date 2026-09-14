"""Tag commands with host-bound targets and structured, navigation-ready results."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import MediaRef, MediaSource, canonical_uri, has_durable_podcast_identity
from .navigation import NavigationEntry, NavigationScope
from .preferences import MediaPreferences
from .presence import sanitize_presence_text
from .tags import (
    MediaTag,
    TagDefinition,
    TagError,
    TagGroup,
    TagInUseError,
    TagNotFoundError,
    TagStore,
    _description,
    _normalized_name,
)

TAG_USAGE = (
    'tag create <name> [--description <text>] | list | rename <name> <new-name> | '
    'delete <name> [--yes] | attach|detach <current|library-index> <tag>... | '
    'show [current|library-index] | find --all|--any|--not <tag>... '
    '[--group <name>] [--source <source>] [--limit <count>] | '
    'play|queue <tag-result-number> | group <operation>'
)
GROUP_USAGE = (
    'tag group create <name> [--description <text>] | list | show <name> | '
    'rename <name> <new-name> | delete <name> [--yes] | add|remove <name> <tag>...'
)


@dataclass(frozen=True, slots=True)
class TagCommandResult:
    """Data for a CLI host to render without generating or replaying commands.

    ``entries`` contains bound search occurrences, never library-index commands.
    Unavailable occurrences retain their identity and label with ``media=None``.
    ``changed_count`` counts added/removed memberships, where applicable.
    """

    operation: str
    message: str
    tags: tuple[TagDefinition, ...] = ()
    groups: tuple[TagGroup, ...] = ()
    media_tags: tuple[MediaTag, ...] = ()
    media: MediaRef | None = None
    entries: tuple[NavigationEntry, ...] = ()
    changed_count: int | None = None
    cancelled: bool = False


def _display(value: str) -> str:
    return "".join(character for character in value if not unicodedata.category(character).startswith("C"))


def _options(
    arguments: Sequence[str], *, values: tuple[str, ...] = (), switches: tuple[str, ...] = ()
) -> tuple[list[str], dict[str, str | bool]]:
    positional: list[str] = []
    options: dict[str, str | bool] = {}
    index = 0
    while index < len(arguments):
        token = arguments[index]
        key = token.casefold()
        if token == "--":
            positional.extend(arguments[index + 1 :])
            break
        if key in options:
            raise TagError(f"Duplicate option: {token}")
        if key in switches:
            options[key] = True
        elif key in values:
            index += 1
            if index >= len(arguments) or arguments[index].startswith("--"):
                raise TagError(f"{token} requires a value")
            options[key] = arguments[index]
        elif token.startswith("--"):
            raise TagError(f"Unknown option: {token}")
        else:
            positional.append(token)
        index += 1
    return positional, options


class TagCommandService:
    """Execute argument tokens after ``tag`` using the application's target resolver.

    The resolver receives only ``current`` or a positive library-index string and
    must return the stable MediaRef for that exact selection, without persisting
    anything. It is invoked once per command. Confirmation receives display text,
    not a command; the selected immutable tag/group ID is retained across it.
    """

    def __init__(
        self,
        store: TagStore,
        *,
        resolve_target: Callable[[str], MediaRef | None],
        confirm: Callable[[str], bool] | None = None,
    ):
        self.store = store
        self.resolve_target = resolve_target
        self.confirm = confirm
        self.preferences = MediaPreferences(store.database)

    def execute(self, arguments: Sequence[str]) -> TagCommandResult:
        if isinstance(arguments, str) or any(not isinstance(value, str) for value in arguments):
            raise TagError("Tag commands require already-tokenized text arguments")
        if not arguments:
            arguments = ("list",)
        operation = arguments[0].casefold()
        rest = arguments[1:]
        if operation in {"help", "--help"} and not rest:
            return TagCommandResult("help", f"Usage: {TAG_USAGE}\n{GROUP_USAGE}")
        if operation == "group":
            return self._group(rest)
        if operation in {"find", "search"}:
            return self._find(rest)
        if operation == "list" and not rest:
            tags = self.store.list_tags()
            return TagCommandResult("list", f"{len(tags)} tag(s)", tags=tags)
        if operation == "create":
            names, options = _options(rest, values=("--description",))
            if len(names) != 1:
                raise TagError("Usage: tag create <name> [--description <text>]")
            description = _description(str(options["--description"])) if "--description" in options else None
            tag = self.store.ensure_tag(names[0], description=description)
            return TagCommandResult("create", f'Tag: {_display(tag.name)}', tags=(tag,))
        if operation == "rename":
            names, _ = _options(rest)
            if len(names) != 2:
                raise TagError("Usage: tag rename <name> <new-name>")
            tag = self.store.update_tag(names[0], name=names[1])
            return TagCommandResult("rename", f'Renamed tag: {_display(tag.name)}', tags=(tag,))
        if operation == "delete":
            names, options = _options(rest, switches=("--yes",))
            if len(names) != 1:
                raise TagError("Usage: tag delete <name> [--yes]")
            return self._delete_tag(names[0], assume_yes=bool(options.get("--yes")))
        if operation in {"attach", "detach", "show"}:
            return self._media_command(operation, rest)
        raise TagError(f"Usage: {TAG_USAGE}")

    def _tag(self, reference: str) -> TagDefinition:
        key = _normalized_name(reference, kind="Tag")[1]
        tags = self.store.list_tags()
        result = next((tag for tag in tags if tag.tag_id == reference), None)
        result = result or next((tag for tag in tags if tag.name.casefold() == key), None)
        if result is None:
            raise TagNotFoundError(f"Unknown tag: {reference}")
        return result

    def _group_definition(self, reference: str) -> TagGroup:
        key = _normalized_name(reference, kind="Tag group")[1]
        groups = self.store.list_groups()
        result = next((group for group in groups if group.group_id == reference), None)
        result = result or next((group for group in groups if group.name.casefold() == key), None)
        if result is None:
            raise TagNotFoundError(f"Unknown tag group: {reference}")
        return result

    def _delete_tag(self, reference: str, *, assume_yes: bool) -> TagCommandResult:
        tag = self._tag(reference)
        try:
            self.store.delete_tag(tag.tag_id)
        except TagInUseError as error:
            if not assume_yes:
                if self.confirm is None:
                    raise TagInUseError(f"{error}. Repeat with --yes to detach and delete this tag") from None
                if not self.confirm(
                    f'Delete tag "{_display(tag.name)}" and remove it from all media and tag groups?'
                ):
                    return TagCommandResult("delete", "Tag deletion cancelled", cancelled=True)
                if self._tag(tag.tag_id) != tag:
                    raise TagError("Tag changed during confirmation; run the command again") from None
            self.store.delete_tag(tag.tag_id, detach=True)
        return TagCommandResult("delete", f'Deleted tag: {_display(tag.name)}', tags=(tag,))

    def _target(self, target: str) -> MediaRef:
        value = target.casefold()
        if value in {"current", "now"}:
            value = "current"
        elif not re.fullmatch(r"[0-9]{1,19}", value) or int(value) < 1:
            raise TagError("Tag target must be current or a positive library index; URLs and paths are not targets")
        media = self.resolve_target(value)
        if media is None:
            raise TagNotFoundError("No media is available for this tag target")
        if not isinstance(media, MediaRef) or not media.stable_id:
            raise TagError("Tag target has no stable media identity")
        if value != "current" and media.source != MediaSource.LOCAL:
            raise TagError("A library-index tag target must resolve to indexed local media")
        if media.source == MediaSource.LOCAL:
            row = self.store.database.fetchone(
                "SELECT canonical_path,state FROM library_files WHERE library_id=?", (media.stable_id,)
            )
            if row is None:
                raise TagError("Only indexed local media can be tagged")
            if row["state"] != "available" or not Path(row["canonical_path"]).is_file():
                raise TagError("The indexed tag target is missing or unavailable")
            if canonical_uri(MediaSource.LOCAL, row["canonical_path"]) != canonical_uri(
                MediaSource.LOCAL, media.original_uri
            ):
                raise TagError("Tag target changed; resolve the current library item again")
        elif media.source == MediaSource.YOUTUBE:
            parsed = urlparse(canonical_uri(MediaSource.YOUTUBE, media.original_uri))
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if (
                parsed.scheme not in {"http", "https"}
                or parsed.netloc != "www.youtube.com"
                or parsed.path != "/watch"
                or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id)
            ):
                raise TagError("This YouTube source has no durable video identity")
        elif media.source != MediaSource.PODCAST or not has_durable_podcast_identity(media):
            raise TagError("This source has no supported durable tag identity; arbitrary streams cannot be tagged")
        return media

    def _media_command(self, operation: str, arguments: Sequence[str]) -> TagCommandResult:
        values, _ = _options(arguments)
        if operation == "show":
            if len(values) > 1:
                raise TagError("Usage: tag show [current|library-index]")
            media = self._target(values[0] if values else "current")
            assignments = self.store.list_media_tags(media.stable_id)
            return TagCommandResult(
                "show", f"{len(assignments)} tag(s)", tags=tuple(entry.tag for entry in assignments),
                media_tags=assignments, media=media,
            )
        if len(values) < 2:
            raise TagError(f"Usage: tag {operation} <current|library-index> <tag>...")
        names = values[1:]
        for name in names:
            _normalized_name(name, kind="Tag")
        media = self._target(values[0])
        before = {tag.tag_id for tag in self.store.list_tags(stable_id=media.stable_id)}
        if operation == "attach":
            self.preferences.remember(media)
            self.store.attach(media.stable_id, names)
        else:
            self.store.detach(media.stable_id, names)
        assignments = self.store.list_media_tags(media.stable_id)
        after = {entry.tag.tag_id for entry in assignments}
        changed = len(after - before) if operation == "attach" else len(before - after)
        return TagCommandResult(
            operation, f'{"Attached" if operation == "attach" else "Detached"} {changed} tag(s)',
            tags=tuple(entry.tag for entry in assignments), media_tags=assignments,
            media=media, changed_count=changed,
        )

    def _group(self, arguments: Sequence[str]) -> TagCommandResult:
        if not arguments:
            arguments = ("list",)
        operation, rest = arguments[0].casefold(), arguments[1:]
        options_values = ("--description",) if operation == "create" else ()
        switches = ("--yes",) if operation == "delete" else ()
        names, options = _options(rest, values=options_values, switches=switches)
        if operation == "list" and not names:
            groups = self.store.list_groups()
            return TagCommandResult("group-list", f"{len(groups)} tag group(s)", groups=groups)
        if operation == "create" and len(names) == 1:
            description = _description(str(options["--description"])) if "--description" in options else None
            group = self.store.create_group(names[0], description=description)
        elif operation == "rename" and len(names) == 2:
            group = self.store.update_group(names[0], name=names[1])
        elif operation in {"show", "delete"} and len(names) == 1:
            group = self._group_definition(names[0])
        elif operation in {"add", "remove"} and len(names) >= 2:
            group = self._group_definition(names[0])
            for name in names[1:]:
                _normalized_name(name, kind="Tag")
            before = {tag.tag_id for tag in self.store.list_tags(group=group.group_id)}
            if operation == "add":
                self.store.add_to_group(group.group_id, names[1:])
            else:
                self.store.remove_from_group(group.group_id, names[1:])
            members = self.store.list_tags(group=group.group_id)
            after = {tag.tag_id for tag in members}
            changed = len(after - before) if operation == "add" else len(before - after)
            return TagCommandResult(
                f"group-{operation}", f'{"Added" if operation == "add" else "Removed"} {changed} group member(s)',
                tags=members, groups=(group,), changed_count=changed,
            )
        else:
            raise TagError(f"Usage: {GROUP_USAGE}")
        members = self.store.list_tags(group=group.group_id)
        if operation == "delete":
            if members and not options.get("--yes"):
                if self.confirm is None:
                    raise TagInUseError("Tag group has members. Repeat with --yes to delete the group; tags are kept")
                if not self.confirm(f'Delete tag group "{_display(group.name)}"? Tags and media assignments are kept.'):
                    return TagCommandResult("group-delete", "Tag-group deletion cancelled", cancelled=True)
                if self._group_definition(group.group_id) != group or self.store.list_tags(group=group.group_id) != members:
                    raise TagError("Tag group changed during confirmation; run the command again")
            self.store.delete_group(group.group_id)
            return TagCommandResult("group-delete", f'Deleted tag group: {_display(group.name)}', groups=(group,))
        return TagCommandResult(
            f"group-{operation}", f'Tag group: {_display(group.name)} ({len(members)} tag(s))',
            groups=(group,), tags=members,
        )

    def _find(self, arguments: Sequence[str]) -> TagCommandResult:
        buckets: dict[str, list[str]] = {"--all": [], "--any": [], "--not": []}
        single: dict[str, str] = {}
        index = 0
        while index < len(arguments):
            option = arguments[index].casefold()
            index += 1
            if option in buckets:
                start = index
                while index < len(arguments) and not arguments[index].startswith("--"):
                    buckets[option].append(arguments[index])
                    index += 1
                if start == index:
                    raise TagError(f"{option} requires at least one tag")
            elif option in {"--group", "--source", "--limit"}:
                if option in single:
                    raise TagError(f"Duplicate option: {option}")
                if index >= len(arguments) or arguments[index].startswith("--"):
                    raise TagError(f"{option} requires a value")
                single[option] = arguments[index]
                index += 1
            else:
                raise TagError(f"Unknown tag search option: {option}; use --all, --any, --not, or --group")
        if not any(buckets.values()) and "--group" not in single:
            raise TagError("Tag search requires --all, --any, --not, or --group")
        source = single.get("--source")
        if source is not None:
            source = source.casefold()
            if source not in {member.value for member in MediaSource}:
                raise TagError(f"Unknown tag search source: {source}")
        raw_limit = single.get("--limit")
        if raw_limit is not None and (
            not re.fullmatch(r"[0-9]{1,19}", raw_limit) or int(raw_limit) > 2**63 - 1
        ):
            raise TagError("Tag query limit must be a non-negative signed 64-bit integer")
        limit = int(raw_limit) if raw_limit is not None else None
        group_tags = self.store.list_tags(group=single["--group"]) if "--group" in single else None
        for names in buckets.values():
            for name in names:
                _normalized_name(name, kind="Tag")
        # An empty reusable group selects nothing, not every stored media item.
        group_ids = set(self.store.tagged_media(any_of=[tag.tag_id for tag in group_tags])) if group_tags else set()
        identities = self.store.tagged_media(
            all_of=buckets["--all"], any_of=buckets["--any"], none_of=buckets["--not"], source=source,
            limit=limit if group_tags is None else None,
        )
        if group_tags is not None:
            identities = tuple(stable_id for stable_id in identities if stable_id in group_ids)
            if limit is not None:
                identities = identities[:limit]
        entries = tuple(self._search_entry(stable_id, position) for position, stable_id in enumerate(identities, 1))
        return TagCommandResult("find", f"{len(entries)} tagged media result(s)", entries=entries)

    def _search_entry(self, stable_id: str, position: int) -> NavigationEntry:
        media = self.preferences.media(stable_id)
        label = sanitize_presence_text(media.title) if media else None
        label = label or "Media"
        if media and media.source == MediaSource.LOCAL:
            row = self.store.database.fetchone(
                "SELECT canonical_path,state FROM library_files WHERE library_id=?", (stable_id,)
            )
            if row and row["state"] == "available" and Path(row["canonical_path"]).is_file():
                media = replace(media, original_uri=row["canonical_path"])
            else:
                media = None
        if media is None:
            label += " [Unavailable]"
        return NavigationEntry(
            media=media, stable_id=stable_id, position=position, label=label,
            source_scope=NavigationScope.RESULTS, occurrence_id=stable_id,
        )

    def resolve_result(self, entry: NavigationEntry) -> NavigationEntry:
        """Refresh a selected occurrence by stable ID before host playback/queueing.

        The host owns the result-number selection, playback policy, and action.
        No target/index resolver runs here, even if the library order changed.
        """
        if not isinstance(entry, NavigationEntry) or entry.source_scope != NavigationScope.RESULTS:
            raise TagError("Select a bound tag search result first")
        refreshed = self._search_entry(entry.stable_id, entry.position)
        if refreshed.media is None:
            raise TagNotFoundError("The selected tag result is missing or unavailable; run the search again")
        if entry.media is not None and entry.media.source != refreshed.media.source:
            raise TagError("The selected tag result changed source; run the search again")
        return refreshed
