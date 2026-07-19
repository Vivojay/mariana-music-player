import json

import pytest

import main


def test_desktop_command_catalog_boundary_returns_versioned_safe_metadata():
    result = main._desktop_control_request("autocomplete.catalog", {})

    assert result["ok"] is True
    catalog = result["catalog"]
    assert catalog["schema_version"] == 1
    entries = catalog["entries"]
    assert entries
    assert tuple((row["category"], row["canonical"].casefold()) for row in entries) == tuple(
        sorted((row["category"], row["canonical"].casefold()) for row in entries)
    )
    by_command = {row["canonical"]: row for row in entries}
    assert by_command["now"]["aliases"] == ()
    assert "/rs" not in by_command

    serialized = json.dumps(result).casefold()
    for unsafe in (
        "handler",
        "media_id",
        "resolver_data",
        "https://",
        "c:\\\\users",
        "cookie",
        "credential",
    ):
        assert unsafe not in serialized


def test_desktop_command_catalog_requires_explicit_compatibility_aliases():
    included = main._desktop_control_request(
        "autocomplete.catalog", {"include_compatibility": True}
    )
    prefix_match = main._desktop_control_request(
        "autocomplete.catalog", {"typed_prefix": "."}
    )

    included_by_command = {
        row["canonical"]: row for row in included["catalog"]["entries"]
    }
    prefix_by_command = {
        row["canonical"]: row for row in prefix_match["catalog"]["entries"]
    }
    assert included_by_command["volume"]["aliases"] == ("vh", "volh", "volumeh")
    assert prefix_by_command["now"]["aliases"] == (".",)
    assert "/rs" not in included_by_command


@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": True},
        {"include_compatibility": "yes"},
        {"typed_prefix": False},
        {"typed_prefix": "x" * 65},
        {"typed_prefix": "now\n"},
    ],
)
def test_desktop_command_catalog_rejects_malformed_options(payload):
    assert main._desktop_control_request("autocomplete.catalog", payload) == {
        "ok": False,
        "error": "Command catalog request is invalid",
    }
