from types import SimpleNamespace

import pytest
from prompt_toolkit import Application
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.output import DummyOutput

from mariana.command_catalog import COMMAND_CATALOG
from mariana.terminal_workspace import PAGES, TerminalWorkspace, catalog_rows, matching_rows


class TerminalOutput(DummyOutput):
    def __init__(self, columns, rows):
        self.size = Size(rows=rows, columns=columns)

    def get_size(self):
        return self.size


def workspace(**kwargs):
    return TerminalWorkspace(lambda: SimpleNamespace(title="東 / North", artist="Björk", duration_seconds=60,
                                                    position_seconds=30, display_state="playing"),
                             lambda: "Vampire", **kwargs)


def drive(view, keys, *, columns=100, rows=25):
    """Run real prompt-toolkit input, layout, bindings and rendering without a terminal."""
    bindings = KeyBindings()
    frames = []

    @bindings.add("f10")
    def snapshot(_event):
        frames.append({
            "page": view.page,
            "selected": view.matches[view.position].title if view.matches else None,
            "filter": view.query_by_page.get(view.page),
            "list": "".join(fragment[1] for fragment in view._list_lines()),
            "deck": "".join(fragment[1] for fragment in view._deck()),
            "detail": "".join(fragment[1] for fragment in view._compact_detail()),
            "nav_height": view._nav_height(),
            "error": view._error,
        })

    @bindings.add("f12")
    def close(event):
        event.app.exit()

    output = TerminalOutput(columns, rows)
    with create_pipe_input() as pipe:
        app = Application(layout=Layout(view.container, focused_element=view.focus_control), full_screen=True,
                          key_bindings=merge_key_bindings([view.bindings, bindings]), input=pipe, output=output)
        pipe.send_text(keys.replace("@snap", "\x1b[21~") + "\x1b[24~")
        app.run()
    return frames


def test_catalog_includes_every_command_form_argument_and_alias():
    rows = catalog_rows(iter(COMMAND_CATALOG))
    commands = {row.command: row for row in rows}
    for spec in COMMAND_CATALOG:
        assert spec.canonical in commands
        for form in spec.forms:
            assert " ".join((spec.canonical, *form.tokens)) in commands
        for alias in spec.aliases:
            assert commands[spec.canonical] in matching_rows(rows, alias.spelling)
    assert "--yes" in commands["playlist delete"].arguments
    assert commands["playlist delete"].effect == "destructive"


@pytest.mark.parametrize(("columns", "rows", "nav_height"), [(39, 16, 2), (80, 24, 1), (120, 34, 1)])
def test_workspace_shortcuts_filter_and_edit_native_command(columns, rows, nav_height):
    edits = []
    runs = []
    view = workspace(on_edit=edits.append, on_run=runs.append)
    frames = drive(view, "@snap" + "\t@snap" * (len(PAGES) - 1) + "\x1b[17~/playlist delete\r@snap\r",
                   columns=columns, rows=rows)
    assert [f["page"] for f in frames[:len(PAGES)]] == [page for _, page in PAGES]
    assert frames[0]["nav_height"] == nav_height
    assert "0:30 / 1:00" in frames[0]["deck"]
    assert frames[-1]["filter"] == "playlist delete"
    assert frames[-1]["selected"] == "playlist delete"
    assert "playlist-name" in frames[-1]["detail"]
    assert edits == ["playlist delete"]
    assert runs == []


def test_discover_search_and_library_filter_are_independent_and_restore_selection():
    edits, plays = [], []
    src = lambda: [("Jóga", "Björk", "play 2"), ("Intro", "坂本龍一", "play 3")]
    view = workspace(on_edit=edits.append, on_run=plays.append, library_rows=src)
    frames = drive(view, "\x1bOR/bjork\r@snap\r\x1b[15~/artist search\r@snap\r\x1bOR@snap")
    assert [f["selected"] for f in frames] == ["Jóga", "artist search", "Jóga"]
    assert plays == ["play 2"]
    assert edits == ["artist search"]
    assert "Björk" in frames[0]["detail"]


def test_play_resolves_reordered_queue_by_stable_id():
    queue = iter([
        [("Same title", "A", "queue jump 1", "a"), ("Same title", "B", "queue jump 2", "b")],
        [("Same title", "B", "queue jump 1", "b"), ("Same title", "A", "queue jump 2", "a")],
    ])
    plays = []
    view = workspace(on_edit=pytest.fail, on_run=plays.append, queue_rows=queue.__next__)
    drive(view, "\x1bOS\x1b[B\r")
    assert plays == ["queue jump 1"]


def test_removed_recording_is_not_replaced_by_new_occupant_of_its_index():
    library = iter([[("Before", "artist", "play 1", "/a")], [("After", "artist", "play 1", "/b")]])
    view = workspace(on_edit=pytest.fail, on_run=pytest.fail, library_rows=library.__next__)
    frame, = drive(view, "\x1bOR\r@snap")
    assert frame["selected"] == "After"
    assert "Select the recording again" in frame["error"]


def test_empty_filter_and_queue_actions_remain_navigable():
    edits = []
    view = workspace(on_edit=edits.append)
    frames = drive(view, "\x1bOS/zzzzz\r@snap\r/\x7f\x7f\x7f\x7f\x7f\r\x1b[F@snap\r")
    assert frames[0]["selected"] is None
    assert "No matches" in frames[0]["list"]
    assert frames[-1]["selected"] == "Playback order"
    assert edits == ["queue order "]



def test_dj_view_reads_live_deck_state_and_executes_native_controls():
    edits, runs = [], []
    view = workspace(on_edit=edits.append, on_run=runs.append,
                     dj_status=lambda: "A · Intro.wav · playing · 2/5s\nB · empty\nCrossfader 23%")
    frames = drive(view, "\x1b[19~@snap\r\x1b[B\r@snap")
    assert frames[0]["page"] == "DJ"
    assert "Intro.wav" in frames[0]["deck"] and "23%" in frames[0]["deck"]
    assert edits == ["dj load A "]
    assert runs == ["dj play A"]
