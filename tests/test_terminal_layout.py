"""Render the actual prompt-toolkit canvas, using terminal-cell coordinates."""

from types import SimpleNamespace

import pytest
from prompt_toolkit import Application
from prompt_toolkit.data_structures import Point, Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.layout import Layout
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.output import DummyOutput

from mariana.terminal_workspace import TerminalWorkspace, WorkspaceRow, matching_rows
from mariana.terminal_layout import cells, wrap


class Output(DummyOutput):
    def __init__(self, size):
        self.resize(*size)

    def resize(self, columns, rows):
        self.size = Size(rows=rows, columns=columns)

    def get_size(self):
        return self.size


def render(view, dimensions, steps=(), start_page="Library"):
    """Apply resize/mouse operations successively against completed real frames."""
    output = Output(dimensions)
    frames = []
    actions = iter(steps)

    def after_render(app):
        if app.is_done:
            return
        screen = app.renderer.last_rendered_screen
        size = output.get_size()
        lines = [
            "".join(screen.data_buffer[y][x].char for x in range(size.columns)).rstrip()
            for y in range(size.rows)
        ]
        frames.append(lines)
        step = next(actions, None)
        if step is None:
            app.loop.call_soon(app.exit)
        else:
            def update():
                step(app, output, lines)
                app.invalidate()
            app.loop.call_soon(update)

    with create_pipe_input() as pipe:
        app = Application(layout=Layout(view.container, focused_element=view.focus_control),
                          full_screen=True, key_bindings=view.bindings, input=pipe, output=output,
                          mouse_support=True, after_render=after_render)
        app.run(pre_run=lambda: view.switch(start_page))
    return frames


def mixer():
    pb = SimpleNamespace(title="Blue Hour", artist="Luna", state="playing", display_state="Playing",
                         media_id="recording", source="local", seekable=True, duration_seconds=120,
                         position_seconds=42, queue_position=2, queue_count=6, live=False)
    runs = []
    view = TerminalWorkspace(lambda: pb, lambda: "Vampire", lambda cmd: None, on_run=runs.append,
                             library_rows=lambda: [(f"North {x}", "Ada Finch", f"play {x}", f"/{x}.wav")
                                                   for x in range(1, 85)])
    return view, pb, runs


@pytest.mark.parametrize("size", [(120, 30), (80, 24), (45, 17), (32, 10)])
def test_transport_and_browser_fit_the_terminal(size):
    view, _pb, _runs = mixer()
    view.set_activity("show", "Saved queue snapshot\nNext revision available")
    frame, = render(view, size)
    canvas = "\n".join(frame)
    assert "Playing" in canvas and "Blue Hour" in canvas and "0:42 / 2:00" in canvas
    assert "Pause" in canvas and "Library" in canvas and "North 1" in canvas
    assert "Outpu" not in frame[-1].replace("Output", "")
    assert "Output" in frame[-1] or "Log" in frame[-1]
    if size[0] >= 76:
        assert "│" in canvas and "Latest output" in canvas
        assert "Next revision available" in canvas
    elif size[1] >= 15:
        assert "│" not in canvas and "Ctrl+O  show" in canvas and "Next revision available" in canvas
    else:
        assert "│" not in canvas


def test_resizes_keep_track_selection_and_restore_compact_result_after_inspection():
    view, _pb, _runs = mixer()
    view.set_activity("dj status", "Both decks are ready")
    frames = render(view, (100, 30), [
        lambda *_: view._move(2),
        lambda _app, out, _lines: out.resize(45, 17),
        lambda *_: view._toggle_inspector(),
        lambda *_: view._toggle_inspector(),
        lambda _app, out, _lines: out.resize(120, 36),
    ])
    assert all(any("› North 3" in line for line in frame) for frame in frames[1:])
    assert "Both decks are ready" in "\n".join(frames[2])
    assert "play 3" in "\n".join(frames[3])
    assert "Both decks are ready" in "\n".join(frames[4])
    assert "Latest output" in "\n".join(frames[5])


def test_pointer_transport_seek_and_tab_navigation_use_native_callbacks():
    view, pb, runs = mixer()

    def click(label, offset=0, *, change_track=False):
        def send(app, _output, lines):
            row = next(y for y, line in enumerate(lines) if label in line)
            col = lines[row].index(label) + offset
            if change_track:
                # Simulate a player replacing the track between drawing and input.
                old = pb
                view.project = lambda: SimpleNamespace(**{**vars(old), "media_id": "new-recording"})
            mouse = MouseEvent(Point(x=col, y=row), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset())
            app.renderer.mouse_handlers.mouse_handlers[row][col](mouse)
        return send

    frames = render(view, (100, 30), [click("Space Pause"), click("─", 1), click("─", 1, change_track=True),
                                      click("F4 Queue")])
    assert runs[0] == "p" and len(runs) == 2
    assert runs[1].startswith("seek ") and runs[1].endswith("s")
    seconds = float(runs[1].removeprefix("seek ")[:-1])
    assert 42 <= seconds < 70
    assert "playing track changed" in frames[-2][-1]
    assert view.page == "Queue"


def test_tagged_library_tracks_can_be_found_by_original_filename():
    track = WorkspaceRow("The release title", "Echo Current", "play 7", "Library",
                         identity=r"D:\Private Folder\session-rough-cut.flac")
    queue = WorkspaceRow("The release title", "Echo Current", "queue jump 1", "Queue", identity="opaque-id")
    assert matching_rows([track, queue], "rough cut".replace(" ", "-")) == [track]
    assert not matching_rows([track, queue], "Private Folder")
    assert not matching_rows([track, queue], "opaque-id")


def test_panel_wrap_respects_words_and_terminal_cell_width():
    lines = wrap("A clear phrase and 東方の長い名前", 12)
    assert lines[:2] == ["A clear", "phrase and"]
    assert all(cells(line) <= 12 for line in lines)
