from mariana.command_assist import declared_commands
from mariana.terminal_workspace import catalog_rows, matching_rows


def test_fullscreen_directory_covers_native_grammar_without_inserting_slot_markers():
    rows = catalog_rows()
    titles = {row.title: row for row in rows}
    assert {form["path"] for form in declared_commands()} <= titles.keys()
    cue = titles["dj cue <deck> set <slot>"]
    assert cue.command == "dj cue " and not cue.playable
    assert "A / B" in cue.arguments
    assert cue in matching_rows(rows, "dj cue set slot")
    assert "--limit" in titles["librivox search"].arguments
    assert "voice" not in titles  # This single-word route belongs to the portable browser.
