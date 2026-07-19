from dataclasses import FrozenInstanceError, replace

import pytest

from mariana.command_catalog import (
    COMMAND_CATALOG,
    CommandAlias,
    CommandCategory,
    CommandRisk,
    serialize_command_catalog,
    validate_command_catalog,
)
from mariana.commands import ALIAS_COMPATIBILITY


def test_command_catalog_is_immutable_deterministic_and_structurally_safe():
    validate_command_catalog()
    first = serialize_command_catalog()
    assert first == serialize_command_catalog()
    assert len(first) == sum(spec.suggest for spec in COMMAND_CATALOG)
    assert tuple((row["category"], row["canonical"].casefold()) for row in first) == tuple(
        sorted((row["category"], row["canonical"].casefold()) for row in first)
    )
    assert set(first[0]) == {
        "key",
        "canonical",
        "category",
        "summary",
        "risk",
        "aliases",
        "forms",
        "availability",
    }
    serialized_keys = {key for row in first for key in row}
    assert not serialized_keys & {
        "handler",
        "path",
        "url",
        "credential",
        "token",
        "cookie",
        "header",
        "media_id",
        "resolver_data",
    }
    with pytest.raises(FrozenInstanceError):
        COMMAND_CATALOG[0].summary = "changed"  # type: ignore[misc]


def test_command_catalog_covers_aliases_without_normally_suggesting_retired_or_compatibility_forms():
    expected = {
        (alias, entry.canonical, entry.scope, entry.status)
        for entry in ALIAS_COMPATIBILITY
        for alias in entry.aliases
    }
    actual = {
        (alias.spelling, spec.canonical, alias.scope, alias.status)
        for spec in COMMAND_CATALOG
        for alias in spec.aliases
    }
    assert actual == expected

    normal = {row["canonical"]: row for row in serialize_command_catalog()}
    assert normal["m"]["aliases"] == ("mute",)
    assert normal["now"]["aliases"] == ()
    assert "/rs" not in normal

    matched = {row["canonical"]: row for row in serialize_command_catalog(typed_prefix=".")}
    assert matched["now"]["aliases"] == (".",)
    assert "/rs" not in matched
    all_compatibility = {
        row["canonical"]: row for row in serialize_command_catalog(include_compatibility=True)
    }
    assert all_compatibility["volume"]["aliases"] == ("vh", "volh", "volumeh")
    assert "/rs" not in all_compatibility


def test_command_catalog_preserves_scoped_argument_namespaces_and_risk():
    specs = {spec.canonical: spec for spec in COMMAND_CATALOG}
    assert specs["play"].forms[0].argument_kinds == ("library-index",)
    assert specs["queue ys"].forms[0].argument_kinds == ("free-text",)
    assert specs["rm"].forms[0].argument_kinds == ("library-index",)
    assert specs["rm"].forms[0].flags == ("--yes",)
    assert specs["rm"].risk is CommandRisk.DESTRUCTIVE
    assert specs["fav"].category is CommandCategory.FAVORITES


def test_command_catalog_classifies_guarded_compound_commands_without_mislabeling_safe_ones():
    specs = {spec.canonical: spec for spec in COMMAND_CATALOG}

    for canonical in (
        "library clean --missing",
        "playlist clear",
        "playlist delete",
        "rm",
        "del",
        "rename",
    ):
        assert specs[canonical].risk is CommandRisk.DESTRUCTIVE

    for canonical in ("help", "library", "lyrics", "now", "progress"):
        assert specs[canonical].risk is CommandRisk.READ_ONLY

    assert specs["library scan"].risk is CommandRisk.STATE_CHANGING
    assert specs["lyrics edit"].risk is CommandRisk.STATE_CHANGING
    assert specs["queue clear"].risk is CommandRisk.STATE_CHANGING
    assert specs["playlist export"].risk is CommandRisk.EXTERNAL_ACTION
    for canonical in (
        "library clean --missing",
        "lyrics edit",
        "playlist clear",
        "playlist delete",
        "queue clear",
    ):
        assert specs[canonical].forms[0].flags == ("--yes",)


def test_serialized_destructive_aliases_retain_risk_without_execution_metadata():
    rows = {row["canonical"]: row for row in serialize_command_catalog(include_compatibility=True)}

    assert rows["rm"]["risk"] == rows["del"]["risk"] == "destructive"
    assert rows["playlist delete"]["risk"] == "destructive"
    assert rows["lyrics"]["risk"] == "read-only"
    serialized = repr(tuple(rows.values())).casefold()
    for private_name in (
        "confirmation_handler",
        "execute",
        "handler",
        "insertion_text",
        "private_id",
        "resolver_data",
    ):
        assert private_name not in serialized


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        ((*COMMAND_CATALOG, COMMAND_CATALOG[0]), "Duplicate command key"),
        (
            (*COMMAND_CATALOG, replace(COMMAND_CATALOG[0], key="another", canonical="HELP")),
            "Duplicate canonical command",
        ),
        (
            (replace(COMMAND_CATALOG[0], category="Unknown"), *COMMAND_CATALOG[1:]),  # type: ignore[arg-type]
            "Unknown command category",
        ),
        (
            (
                replace(
                    COMMAND_CATALOG[0],
                    aliases=(*COMMAND_CATALOG[0].aliases, CommandAlias("pause", "token", "native")),
                ),
                *COMMAND_CATALOG[1:],
            ),
            "Alias collides with canonical command",
        ),
        (
            (
                replace(COMMAND_CATALOG[2], aliases=()),
                *COMMAND_CATALOG[:2],
                *COMMAND_CATALOG[3:],
            ),
            "compatibility alias registry",
        ),
    ],
)
def test_command_catalog_rejects_ambiguous_or_incomplete_metadata(catalog, message):
    with pytest.raises(ValueError, match=message):
        validate_command_catalog(catalog)
