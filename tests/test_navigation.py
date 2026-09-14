"""Collection navigation contracts independent of application command routing."""

from dataclasses import FrozenInstanceError

import pytest

from mariana.command_catalog import COMMAND_CATALOG, CommandRisk
from mariana.command_parser import split_command
from mariana.commands import normalize_command
from mariana.models import MediaRef, MediaSource
from mariana.navigation import (
    NavigationContext,
    NavigationEntry,
    NavigationScope,
    join_relative_references,
    parse_navigation,
    parse_relative_reference,
)


@pytest.mark.parametrize(("text", "offset", "immediate", "scope", "name"), [
    ("next", 1, False, NavigationScope.AUTO, None),
    (".prev 3", -3, True, NavigationScope.AUTO, None),
    (".next 2 --in favs", 2, True, NavigationScope.FAVORITES, None),
    ('prev --in playlist "Night Drive"', -1, False, NavigationScope.PLAYLIST, "Night Drive"),
    ("next library", 1, False, NavigationScope.LIBRARY, None),
    ("prev queue", -1, False, NavigationScope.QUEUE, None),
    ("next 3 lib", 3, False, NavigationScope.LIBRARY, None),
    (".prev 2 q", -2, True, NavigationScope.QUEUE, None),
    (".next 2 favorites", 2, True, NavigationScope.FAVORITES, None),
    ('prev playlist "Night Drive"', -1, False, NavigationScope.PLAYLIST, "Night Drive"),
    ("next results", 1, False, NavigationScope.RESULTS, None),
    ("next 2 --in library", 2, False, NavigationScope.LIBRARY, None),
    ("NEXT 2 --IN FAVOURITES", 2, False, NavigationScope.FAVORITES, None),
    ("prev current", -1, False, NavigationScope.AUTO, None),
    ("next playlist", 1, False, NavigationScope.PLAYLIST, None),
])
def test_navigation_parser_accepts_counts_modes_and_collection_operands(text, offset, immediate, scope, name):
    command, *arguments = split_command(text)
    original = list(arguments)
    request = parse_navigation(command, arguments)
    assert (request.offset, request.immediate, request.scope, request.scope_name) == (offset, immediate, scope, name)
    assert arguments == original


@pytest.mark.parametrize("arguments", [
    ["0"], ["-1"], ["two"], ["1", "2"], ["--in"], ["--in", "unknown"],
    ["queue", "library"], ["2", "unknown"], ["0", "library"], ["library", "2"],
    ["queue", "--in", "library"], ["2", "--in", "library", "--in", "queue"],
    ["1.5"], ["--in", "results", "name"],
])
def test_navigation_rejects_invalid_counts_and_conflicting_collections(arguments):
    with pytest.raises(ValueError):
        parse_navigation("next", arguments)


def test_navigation_rejects_unknown_command():
    with pytest.raises(ValueError, match="Unknown navigation command"):
        parse_navigation("seek", ["2"])


def test_navigation_context_preserves_occurrences_and_only_explicitly_moves_cursor():
    media = MediaRef(MediaSource.URL, "https://media.test/track", title="Shared title")
    other = MediaRef(MediaSource.URL, "https://media.test/other", title="Shared title")
    entries = tuple(NavigationEntry(media, media.stable_id, index + 1, "Shared title",
                                    NavigationScope.QUEUE, f"occurrence-{index}") for index in range(2))
    context = NavigationContext(NavigationScope.QUEUE, entries, 0, "queue")
    assert context.matches(media) and not context.matches(other) and not context.matches(None)
    assert context.target(-1) is None and context.target(2) is None
    assert context.target(1) == (1, entries[1])
    assert context.cursor == 0
    selected = context.at(1)
    assert selected.cursor == 1 and context.cursor == 0
    assert selected.entries is context.entries and selected.entries[1].occurrence_id == "occurrence-1"
    with pytest.raises(FrozenInstanceError):
        context.cursor = 1  # type: ignore[misc]
    for outside in (-1, 2):
        with pytest.raises(ValueError, match="outside the collection"):
            context.at(outside)


def test_unselected_and_empty_contexts_do_not_match_active_media():
    media = MediaRef(MediaSource.URL, "https://media.test/track")
    entry = NavigationEntry(media, media.stable_id, 1, "Track", NavigationScope.RESULTS)
    unselected = NavigationContext(NavigationScope.RESULTS, (entry,), -1)
    assert not unselected.matches(media)
    assert unselected.target(1) == (0, entry)
    empty = NavigationContext(NavigationScope.RESULTS, (), -1)
    assert not empty.matches(media) and empty.target(1) is None


@pytest.mark.parametrize(("text", "offset", "scope"), [
    ("+2", 2, NavigationScope.AUTO), ("- 3", -3, NavigationScope.AUTO),
    ("+2 --in queue", 2, NavigationScope.QUEUE),
    ("-1 --in playlist Night Drive", -1, NavigationScope.PLAYLIST),
])
def test_relative_media_references_use_the_same_validated_counts(text, offset, scope):
    request = parse_relative_reference(text)
    assert request is not None and request.offset == offset and request.scope == scope
    assert not request.immediate


@pytest.mark.parametrize("text", ["+0", "-0", "+2 --in unknown"])
def test_relative_media_references_reject_invalid_navigation(text):
    with pytest.raises(ValueError):
        parse_relative_reference(text)


@pytest.mark.parametrize("text", ["2", "2.5", "C:/Music/+2.mp3", "+2.mp3", "-track", "https://media.test/+2"])
def test_nonrelative_media_reference_is_not_reinterpreted(text):
    assert parse_relative_reference(text) is None


def test_join_relative_references_preserves_other_operands_and_its_input():
    values = ["+", "2", "-1", "4", "a b.mp3", "-", "track"]
    assert join_relative_references(values) == ["+2", "-1", "4", "a b.mp3", "-", "track"]
    assert values == ["+", "2", "-1", "4", "a b.mp3", "-", "track"]


@pytest.mark.parametrize(("text", "expected"), [
    ("+3 lib", "next 3 lib"), (".-2 q", ".prev 2 q"),
    ("+2 --in library", "next 2 --in library"),
    ('  .+2 playlist "Night Drive"  ', '.next 2 playlist "Night Drive"'),
])
def test_compact_navigation_normalization_preserves_collection_operands(text, expected):
    assert normalize_command(text) == expected


def test_navigation_catalog_distinguishes_previews_from_playback_and_lists_supported_scopes():
    specs = {spec.canonical: spec for spec in COMMAND_CATALOG}
    scopes = {("library",), ("queue",), ("favorites",), ("playlist",), ("results",)}
    for command in ("next", "prev", ".next", ".prev"):
        spec = specs[command]
        assert spec.risk == (CommandRisk.STATE_CHANGING if command.startswith(".") else CommandRisk.READ_ONLY)
        assert {form.tokens for form in spec.forms} == scopes | {()}
        assert spec.forms[0].argument_kinds == ("positive-count", "collection")
        assert spec.forms[0].flags == ("--in",)

    for command in ("fav", "playlist"):
        assert {("next",), ("prev",), ("previous",)} <= {form.tokens for form in specs[command].forms}
    assert "1-100 steps" in specs["queue"].summary
