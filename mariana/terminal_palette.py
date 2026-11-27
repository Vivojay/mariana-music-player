"""Search command forms or recall a previous command into the editor."""

from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.widgets import TextArea

from .terminal_layout import cells, clip
from .terminal_workspace import WorkspaceRow, matching_rows


class CommandPalette:
    def __init__(self, catalog, history, choose):
        self.catalog = catalog
        self.history = history
        self.choose = choose
        self.mode = "Commands"
        self.rows = self.results = ()
        self.index = self.top = 0
        self.clear_armed = False
        self.saving = False
        self.notice = ""
        self.query = TextArea(multiline=False, height=1, wrap_lines=False,
                              prompt=[("class:key", " Find › ")], style="class:panel")
        self.query.buffer.on_text_changed += lambda _: self.filter()
        self.list = Window(FormattedTextControl(self._rows), always_hide_cursor=True, wrap_lines=False)
        self.container = HSplit([
            Window(FormattedTextControl(self._title), height=1, style="class:bar"),
            self.query, self.list,
            Window(FormattedTextControl(self._detail), height=1, wrap_lines=False, style="class:panel"),
            Window(FormattedTextControl(self._footer), height=1, style="class:bar"),
        ])

    def open(self, mode, query=""):
        self.mode, self.notice, self.clear_armed = mode, "", False
        if mode == "History":
            self.saving = self.history.saving
            self.rows = tuple(WorkspaceRow(line, "", line) for line in reversed(self.history.get_strings()))
        else:
            self.rows = self.catalog
        self.query.text = query
        self.query.buffer.cursor_position = len(query)
        self.filter()

    def filter(self):
        self.index = self.top = 0
        self.clear_armed = False
        if self.mode == "History":
            # Avoid adding private session inputs to the catalog's process-wide keyword cache.
            words = self.query.text.casefold().split()
            self.results = [row for row in self.rows if all(word in row.command.casefold() for word in words)]
        else:
            self.results = matching_rows(self.rows, self.query.text)

    def move(self, delta):
        self.clear_armed = False
        self.index = max(0, min(self.index + delta, len(self.results) - 1))

    def accept(self):
        if self.results:
            self.choose(self.results[self.index].command)

    def toggle_save(self):
        if self.mode == "History" and self.history.set_saving(not self.saving):
            self.open("History", self.query.text)
            self.notice = ("Safe playback commands will be saved." if self.saving
                           else "Saved commands erased. Session recall is on.")
        else:
            self.notice = self.history.error

    def clear(self):
        if not self.clear_armed:
            self.clear_armed = True
            self.notice = "Press Ctrl+X again to clear recalled commands."
            return
        if self.history.clear():
            self.open("History")
            self.notice = "Command history cleared."
        else:
            self.notice = self.history.error

    def _title(self):
        label = "Command palette" if self.mode == "Commands" else "Command history"
        info = ("  ·  saved + session" if self.saving else "  ·  this session") if self.mode == "History" else ""
        count = f"{len(self.results)}"
        width = get_app().output.get_size().columns
        heading = clip(f" {label}{info}", max(1, width - len(count) - 2))
        return [("class:title", heading), ("class:muted", " " * max(1, width - cells(heading) - len(count) - 1) + count)]

    def _rows(self):
        if not self.results:
            text = ("Enter a command with : to start your history." if self.mode == "History" and not self.rows
                    else "No matches. Edit your search.")
            return [("class:muted", " " + clip(text, get_app().output.get_size().columns - 1))]
        size = get_app().output.get_size()
        height = max(1, self.list.render_info.window_height if self.list.render_info else size.rows - 7)
        self.top = min(self.index, max(0, self.top, self.index - height + 1))
        self.top = min(self.top, max(0, len(self.results) - height))
        width = max(1, size.columns - 4)
        out = []
        for index in range(self.top, min(self.top + height, len(self.results))):
            row = self.results[index]
            def pick(event, i=index):
                if event.event_type == MouseEventType.MOUSE_UP:
                    self.index = i
                    self.accept()
                elif event.event_type == MouseEventType.SCROLL_UP:
                    self.move(-3)
                elif event.event_type == MouseEventType.SCROLL_DOWN:
                    self.move(3)
            prefix = " › " if index == self.index else "   "
            tail = clip(row.group, min(22, width // 4)) if width >= 60 else ""
            budget = max(1, width - cells(tail) - int(bool(tail)))
            label = clip(row.title, budget)
            body = prefix + label + " " * max(0, budget - cells(label)) + (" " + tail if tail else "")
            out.append(("class:selected" if index == self.index else "", body, pick))
            if index + 1 < min(self.top + height, len(self.results)):
                out.append(("", "\n"))
        return out

    def _detail(self):
        row = self.results[self.index] if self.results else None
        hint = ((row.arguments or row.detail) if row else "") if self.mode == "Commands" else ""
        return " " + clip(self.notice or hint or "Enter places the selection in the command editor.",
                          max(1, get_app().output.get_size().columns - 2))

    def _footer(self):
        width = get_app().output.get_size().columns
        if self.mode == "History":
            label = (" ↑↓ Select   Enter Edit   Ctrl+S Saving   Ctrl+X Clear   Esc Back" if width >= 65
                     else " ↕  Enter Edit  ^S Save  ^X Clear  Esc")
        else:
            label = " ↑↓ Select   Enter Edit   Ctrl+R History   Esc Back" if width >= 53 else " ↕  Enter Edit  ^R History  Esc"
        return clip(label, width)
