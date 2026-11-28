"""Full-screen navigation over Mariana's live session and native command catalog."""
from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from prompt_toolkit.application.current import get_app
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.widgets import TextArea

from .command_catalog import COMMAND_CATALOG, CommandCategory
from .terminal_layout import WorkspaceSize, cells, wrap
from .terminal_layout import clip as _clip


@dataclass(frozen=True, slots=True)
class WorkspaceRow:
    title: str
    detail: str
    command: str
    group: str = ""
    arguments: str = ""
    aliases: str = ""
    effect: str = ""
    playable: bool = False
    identity: str = ""


PAGES = (
    ("f2", "Player"), ("f3", "Library"), ("f4", "Queue"),
    ("f5", "Discover"), ("f6", "Commands"), ("f7", "Keys"), ("f8", "DJ"),
)
# These shortcuts are templates in the editor. Ordinary CLI validation,
# focus-mode restrictions and confirmations still belong to the session.
PLAYER_SHORTCUTS = (
    WorkspaceRow("Track details", "Inspect the current recording and source.", "now*", "Now playing"),
    WorkspaceRow("Chapters", "List the current recording's chapter markers.", "chapters list", "Now playing"),
    WorkspaceRow("Microphone and live captions", "Record your mic or transcribe with an offline model.", "speech help", "Sound"),
    WorkspaceRow("Karaoke", "Sing word-timed lyrics, including duets.", "karaoke start", "Now playing"),
    WorkspaceRow("Lyrics", "Show lyrics for the current recording.", "lyrics", "Now playing"),
    WorkspaceRow("Playlists", "Browse your named playlists.", "playlist list", "Collections"),
    WorkspaceRow("Music wall", "View your collection and reviews.", "wall list", "Collections"),
    WorkspaceRow("Clip and share", "Mark a range and share it from the current recording.", "clip status", "Sharing"),
    WorkspaceRow("DJ studio", "Mix two decks, set cues and record the stereo master.", "dj status", "Sound"),
    WorkspaceRow("Tone generator", "Edit this sine-tone preview or choose another waveform.", "tone sine 440 --seconds 2", "Sound"),
    WorkspaceRow("Twinkle · harmony and chorus", "Play the factory arrangement, or edit its tempo and chorus level.",
                 "tone procedure play twinkle", "Sound"),
    WorkspaceRow("Effects rack", "Inspect the active sound effects and microphone monitor.", "fx status", "Sound"),
    WorkspaceRow("Equalizer", "Inspect equalizer, output levels and voice processing.", "eq status", "Sound"),
    WorkspaceRow("Terminal appearance", "List the available palettes.", "theme list", "Settings"),
    WorkspaceRow("Desktop panels", "Choose an Electron view, such as albums or mini.", "desktop open ", "Desktop"),
    WorkspaceRow("Playback diagnostics", "Inspect Mariana's active playback status.", "now", "Now playing"),
)
LIBRARY_ACTIONS = (
    WorkspaceRow("Find a recording", "Filter your full indexed library.", "ls ", "Library"),
    WorkspaceRow("Recent plays", "Browse recently played recordings.", "recents", "Library"),
    WorkspaceRow("Library roots", "Show configured music folders.", "library roots", "Library"),
    WorkspaceRow("Refresh index", "Scan library roots for changed files.", "library scan changed", "Library"),
)
def dj_actions():
    rows = []
    for name in ("A", "B"):
        group = f"Deck {name}"
        for label, command, detail, direct in (
            ("Load", f"load {name} ", "Choose a local file, library index or current.", False),
            ("Play", f"play {name}", "Start at the deck playhead.", True),
            ("Pause", f"pause {name}", "Pause at the current position.", True),
            ("Seek", f"seek {name} ", "Enter a position in seconds.", False),
            ("Set cue", f"cue {name} set 1", "Store the current position. Choose slot 1 through 8.", False),
            ("Jump to cue", f"cue {name} go 1", "Recall a stored cue. Choose slot 1 through 8.", False),
            ("Loop", f"loop {name} ", "Enter a start and end in seconds, or off.", False),
            ("Gain", f"gain {name} 100", "Set deck gain from 0 to 200 percent.", False),
            ("Rate", f"rate {name} 1", "Change playback speed and pitch together.", False),
        ):
            rows.append(WorkspaceRow(f"{label} {name}", detail, "dj " + command, group, playable=direct))
    rows.extend([
        WorkspaceRow("Crossfader", "Enter 0 for A or 100 for B. Add seconds for a timed fade.",
                     "dj crossfade 50", "Mixer"),
        WorkspaceRow("Start recording", "Begin a new stereo WAV master.", "dj record start", "Recorder", playable=True),
        WorkspaceRow("Finish recording", "Finish the WAV and display its location.", "dj record stop", "Recorder", playable=True),
        WorkspaceRow("Export recording", "Copy your finished WAV to a new filename.", "dj export ", "Recorder"),
        WorkspaceRow("Share recording", "Open the local share page for your last recording.", "dj share", "Recorder"),
        WorkspaceRow("Stop both decks", "Stop and rewind both loaded decks.", "dj stop all", "Mixer", playable=True),
    ])
    return tuple(rows)


DJ_ACTIONS = dj_actions()
QUEUE_ACTIONS = (
    WorkspaceRow("Queue tree", "Inspect groups and their playback order.", "queue tree", "Queue"),
    WorkspaceRow("Add to queue", "Enter a library index or supported queue source.", "queue add ", "Queue"),
    WorkspaceRow("Playback order", "Inspect or change queue ordering.", "queue order ", "Queue"),
)
KEYS = (
    ("F2 … F8", "Switch workspace views. F8 opens the DJ mixer."),
    ("Tab / Shift+Tab", "Move to the next or previous view while browsing."),
    ("↑ / ↓", "Move through tracks, queued items or commands."),
    ("PgUp / PgDn", "Scroll one page of items."),
    ("Home / End", "Select the first or last match."),
    ("/", "Filter the current view by title, artist, command, alias or description."),
    ("Enter", "Play a selected track or edit the selected command. In the filter, return to results."),
    (": or F1", "Enter any Mariana command, including aliases and commands with interactive prompts."),
    ("Ctrl+K / Ctrl+R", "Search the command palette or previous inputs. Enter edits the selection; Esc keeps your draft."),
    ("Ctrl+O", "Read command output. Ctrl+Up and Ctrl+Down jump between commands."),
    ("i", "Toggle selection details. Narrow terminals expand details below the list."),
    ("Space · [ · ]", "Play/pause, previous recording, next recording."),
    ("← / →", "Seek backward or forward ten seconds."),
    ("t", "Cycle the theme."),
    ("q", "Leave the current terminal workspace."),
)


def _plain(value):
    """Untrusted media metadata must occupy just one printable terminal line."""
    return " ".join("".join(c if c.isprintable() else " " for c in str(value or "")).split())


def _fold(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.casefold()) if not unicodedata.combining(c))


@lru_cache(maxsize=2048)
def _keywords(row):
    filename = row.identity.replace("\\", "/").rsplit("/", 1)[-1] if row.group == "Library" else ""
    return _fold(" ".join((row.title, row.command, row.detail, row.group, row.arguments, row.aliases, filename)))


def matching_rows(rows, query):
    tokens = _fold(query).split()
    if not tokens:
        return rows
    matches = [row for row in rows if all(token in _keywords(row) for token in tokens)]
    needle = " ".join(tokens)
    return sorted(matches, key=lambda row: (
        _fold(row.command).strip() != needle and _fold(row.title) != needle,
        not _fold(row.title).startswith(needle),
    ))


def catalog_rows(catalog=COMMAND_CATALOG):
    """Include every canonical command, documented subcommand and searchable alias."""
    include_grammar = catalog is COMMAND_CATALOG
    catalog = tuple(catalog)
    rows = {}
    for spec in catalog:
        aliases = ", ".join(alias.spelling for alias in spec.aliases)
        args = dict.fromkeys(arg for form in spec.forms for arg in (*form.argument_kinds, *form.flags))
        rows[spec.canonical] = WorkspaceRow(
            spec.canonical, spec.summary, spec.canonical, str(spec.category), "  ".join(args), aliases, str(spec.risk)
        )
    for spec in catalog:
        for form in spec.forms:
            if not form.tokens:
                continue
            command = " ".join((spec.canonical, *form.tokens))
            if command not in rows:
                parent = rows[spec.canonical]
                rows[command] = WorkspaceRow(
                    command, parent.detail, command, parent.group,
                    "  ".join((*form.argument_kinds, *form.flags)) or parent.arguments, parent.aliases, parent.effect,
                )
    if include_grammar:
        from .command_assist import declared_commands

        for form in declared_commands():
            name = form["path"]
            parent = rows.get(name)
            family = rows.get(name.partition(" ")[0])
            # A slot can occur between keywords (e.g. dj cue <deck> set <slot>).
            # Place the editable prefix in the command bar. Keep the full syntax visible in the directory.
            prefix = name.partition("<")[0]
            aliases = dict.fromkeys([*(parent.aliases.split(", ") if parent and parent.aliases else ()),
                                     *form.get("aliases", ())])
            hints = [*form.get("arguments", ()), *form.get("flags", ())]
            slots = form.get("values", {})
            hints.extend(f"{key}: {' / '.join(options)}" for key, options in slots.items() if options)
            rows[name] = WorkspaceRow(
                name, form.get("description") or (parent.detail if parent else ""), prefix,
                parent.group if parent else family.group if family else "Commands",
                "  ".join(hints) or (parent.arguments if parent else ""),
                ", ".join(aliases), parent.effect if parent else "",
            )
    return sorted(rows.values(), key=lambda row: row.command.casefold())


def _clock(value):
    if value is None:
        return "–"
    hours, remain = divmod(max(0, int(value)), 3600)
    minutes, seconds = divmod(remain, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


class TerminalWorkspace:
    def __init__(self, project, palette_name, on_edit, *, library_rows=None, queue_rows=None, catalog=None, on_run=None, dj_status=None, on_output=None, on_palette=None):
        self.project = project
        self.palette_name = palette_name
        self.on_edit = on_edit
        self.on_run = on_run
        self.dj_status = dj_status
        self.on_output = on_output
        self.on_palette = on_palette
        self.inspector = None
        self.last_command = ""
        self.last_lines = []
        self.queue_preview = []
        self.last_click = None
        self.sources = {"Library": library_rows, "Queue": queue_rows}
        self.catalog = catalog_rows(COMMAND_CATALOG if catalog is None else catalog)
        self.discover = sorted(
            (r for r in self.catalog if r.group in {str(CommandCategory.ONLINE), str(CommandCategory.RADIO)}
             or r.command.startswith(("home", "artist", "librivox", "jam", "fanroom", "wall"))),
            key=lambda r: (r.command not in {"artist discover", "artist search", "artist emerging", "home choices",
                                              "home picks", "home sources", "librivox search", "radio search"},
                           r.command.casefold()),
        )
        self.page = "Player"
        self.searching = False
        self.positions = {}
        self.query_by_page = {}
        self.active_rows = []
        self.matches = []
        self.position = 0
        self.offset = 0
        self.media_count = 0
        self._error = ""
        self.search = TextArea(height=1, multiline=False, prompt=[("class:key", "  Find › ")],
                               wrap_lines=False, style="class:panel")
        self.search.buffer.on_text_changed += self._filter_changed
        self.focus_control = FormattedTextControl(self._list_lines, focusable=True, show_cursor=False)
        self.body = Window(self.focus_control, wrap_lines=False, always_hide_cursor=True, height=Dimension(min=2))
        self.bindings = KeyBindings()
        self._bind()
        self._load()
        show_side = Condition(lambda: bool(self._size().side))
        self.container = HSplit([
            self.navigation_strip(),
            self.player_strip(),
            ConditionalContainer(self.search, Condition(lambda: self.searching)),
            Window(FormattedTextControl(self._heading), height=1, wrap_lines=False, style="class:bar"),
            VSplit([
                self.body,
                ConditionalContainer(Window(width=1, char="│", style="class:muted"), show_side),
                ConditionalContainer(HSplit([
                    Window(FormattedTextControl(self._detail), wrap_lines=False, style="class:panel"),
                    ConditionalContainer(Window(FormattedTextControl(self._lower_panel), style="class:bar",
                                                height=lambda: min(9, max(4, self._size().rows // 4)),
                                                wrap_lines=False),
                                         Condition(lambda: bool(self.last_command or (self.queue_preview and self.page != "Queue")))),
                ], width=lambda: self._size().side), show_side),
            ]),
            ConditionalContainer(Window(FormattedTextControl(self._compact), wrap_lines=False, style="class:panel",
                                        height=lambda: self._size().compact_rows),
                                 Condition(lambda: bool(self._size().compact_rows))),
            Window(FormattedTextControl(self._footer), height=1, wrap_lines=False, style="class:bar"),
        ])

    def _size(self):
        size = get_app().output.get_size()
        return WorkspaceSize(size.columns, size.rows, self.inspector)

    def navigation_strip(self):
        """Create a navigation bar for either the browser or results view."""
        return Window(FormattedTextControl(self._navigation), height=self._nav_height,
                      wrap_lines=False, style="class:bar")

    def player_strip(self):
        """Create a player with mouse controls operating on the same session."""
        return Window(FormattedTextControl(self._deck), height=self._deck_height,
                      wrap_lines=False)

    def set_activity(self, command, text):
        """Show a compact preview, leaving the full output in its own view."""
        # Limit processing of long commands such as a full library listing.
        tail = str(text or "")[-8192:]
        tail = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))", "", tail)
        self.last_command = _plain(command)
        self.last_lines = [_plain(line) for line in tail.splitlines() if line.strip()][-8:]

    def _toggle_inspector(self):
        size = self._size()
        if size.columns >= 76:
            self.inspector = False if size.side else None
        else:
            self.inspector = None if self.inspector else True

    def _load(self):
        self._error = ""
        if self.page in self.sources:
            source = self.sources[self.page]
            try:
                media = [WorkspaceRow(_plain(label), _plain(detail), cmd, self.page, playable=True,
                                      identity=str(identity[0]) if identity else "")
                         for label, detail, cmd, *identity in (source() if source else ())]
            except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self._error = _plain(exc)
                media = []
            self.active_rows = media + list(LIBRARY_ACTIONS if self.page == "Library" else QUEUE_ACTIONS)
            self.media_count = len(media)
            if self.page == "Queue":
                self.queue_preview = [row.title for row in media[:4]]
        elif self.page == "Commands":
            self.active_rows = self.catalog
        elif self.page == "Discover":
            self.active_rows = self.discover
        elif self.page == "DJ":
            self.active_rows = list(DJ_ACTIONS)
        elif self.page == "Keys":
            self.active_rows = [WorkspaceRow(key, detail, "", "Keyboard") for key, detail in KEYS]
        else:
            self.active_rows = list(PLAYER_SHORTCUTS)
        self.matches = matching_rows(self.active_rows, self.query_by_page.get(self.page, ""))
        self.position = min(self.positions.get(self.page, 0), max(0, len(self.matches) - 1))
        self.offset = 0

    def refresh(self):
        selected = self.matches[self.position].identity if self.matches else None
        self.positions[self.page] = self.position
        self._load()
        if selected:
            self.position = next((i for i, row in enumerate(self.matches) if row.identity == selected), self.position)

    def switch(self, page):
        if page not in {label for _, label in PAGES}:
            raise ValueError("Unknown workspace view")
        self.positions[self.page] = self.position
        self.page = page
        self.searching = False
        self._load()
        get_app().layout.focus(self.focus_control)

    def _filter_changed(self, _buffer):
        query = self.search.text
        self.query_by_page[self.page] = query
        self.matches = matching_rows(self.active_rows, query)
        self.position = 0
        self.offset = 0

    def _begin_filter(self):
        self.searching = True
        self.search.text = self.query_by_page.get(self.page, "")
        self.search.buffer.cursor_position = len(self.search.text)
        get_app().layout.focus(self.search)

    def _move(self, amount):
        self.position = max(0, min(self.position + amount, len(self.matches) - 1))

    def _height(self):
        size = self._size()
        info = self.body.render_info
        geometry = (size, self.page, self.searching)
        if info is not None and geometry == getattr(self, "_previous_geometry", None):
            return max(1, info.window_height)
        reserved = size.nav_rows + self._deck_height() + 2 + size.compact_rows + int(self.searching)
        return max(1, size.rows - reserved)

    def _bind(self):
        browsing = Condition(lambda: get_app().layout.has_focus(self.focus_control))
        filtering = Condition(lambda: get_app().layout.has_focus(self.search))
        for key, page in PAGES:
            self.bindings.add(key)(lambda event, name=page: self.switch(name))
        names = [page for _, page in PAGES]
        for key, step in (("tab", 1), ("s-tab", -1)):
            self.bindings.add(key, filter=browsing)(lambda event, n=step: self.switch(
                names[(names.index(self.page) + n) % len(names)]))
        for key, step in (("up", -1), ("down", 1), ("home", -10**9), ("end", 10**9)):
            self.bindings.add(key, filter=browsing)(lambda event, count=step: self._move(count))
        for key, step in (("pageup", -1), ("pagedown", 1)):
            self.bindings.add(key, filter=browsing)(lambda event, n=step: self._move(n * self._height()))
        self.bindings.add("i", filter=browsing)(lambda event: self._toggle_inspector())
        self.bindings.add("/", filter=browsing)(lambda event: self._begin_filter())

        @self.bindings.add("escape", filter=filtering)
        @self.bindings.add("enter", filter=filtering)
        def finish_filter(event):
            if event.key_sequence[-1].key == "escape":
                self.search.text = ""
            self.searching = False
            event.app.layout.focus(self.focus_control)

        @self.bindings.add("enter", filter=browsing)
        def choose(_event):
            self.activate()

    def activate(self):
        if not self.matches:
            return
        row = self.matches[self.position]
        if not row.command:
            return
        callback = self.on_edit
        if row.playable and self.on_run:
            # A native play/jump command may address a mutable item number. Re-read
            # that number from the stable path or queue ID at activation time.
            self.refresh()
            current = [item for item in self.active_rows if item.playable and
                       ((row.identity and item.identity == row.identity) or item == row)]
            if len(current) != 1:
                self._error = self._error or f"{self.page} changed. Select the recording again."
                return
            row = current[0]
            callback = self.on_run
        return callback(row.command)

    def _press(self, callback):
        def handle(event):
            if event.event_type == MouseEventType.MOUSE_UP:
                callback()
            return None
        return handle

    def _nav_height(self):
        return self._size().nav_rows

    def _navigation(self) -> list[OneStyleAndTextTuple]:
        size = self._size()
        short = {"Discover": "Find", "Commands": "Cmds"}
        items = []
        for key, page in PAGES:
            name = short.get(page, page) if size.columns < 75 else page
            label = f" {key.upper()} {name} "
            items.append(("class:selected" if self.page == page else "class:muted", label,
                          self._press(lambda name=page: self.switch(name))))
        if size.nav_rows == 2:
            if sum(cells(item[1]) for item in items[3:]) > size.columns:
                items = [(style, text.rstrip(), handler) for style, text, handler in items]
            return [*items[:3], ("", "\n"), *items[3:]]
        available = size.columns
        if sum(cells(item[1]) for item in items) > available:
            # A short terminal has room for a moving window of tabs. The
            # selected view and the keys for neighbouring views stay visible.
            current = [name for _, name in PAGES].index(self.page)
            start, end = current, current + 1
            width = cells(items[current][1])
            while start or end < len(items):
                costs = []
                if start:
                    costs.append((current - start, cells(items[start - 1][1]), -1))
                if end < len(items):
                    costs.append((end - current - 1, cells(items[end][1]), 1))
                choices = [c for c in costs if c[1] + width + 4 <= available]
                if not choices:
                    break
                _, amount, direction = min(choices)
                start -= direction == -1
                end += direction == 1
                width += amount
            visible: list[OneStyleAndTextTuple] = list(items[start:end])
            if start:
                visible.insert(0, ("class:key", "‹ ", self._press(lambda: self.switch(PAGES[start - 1][1]))))
            if end < len(items):
                visible.append(("class:key", " ›", self._press(lambda: self.switch(PAGES[end][1]))))
            return visible
        menu: list[OneStyleAndTextTuple] = list(items)
        brand = " MARIANA  "
        used = sum(cells(item[1]) for item in items)
        if available - used >= len(brand):
            menu.insert(0, ("class:key", brand))
            used += len(brand)
        theme = _plain(self.palette_name())
        if theme and available - used >= cells(theme) + 4:
            menu.append(("class:muted", theme.rjust(available - used - 1) + " "))
        return menu

    def _deck_height(self):
        if self.page == "DJ":
            return 3
        return 3 if self._size().rows >= 12 else 2

    def _transport(self, command):
        return self._press(lambda: (self.on_run or self.on_edit)(command))

    def _deck(self) -> list[OneStyleAndTextTuple]:
        size = self._size()
        width = size.columns
        if self.page == "DJ":
            status = self.dj_status() if self.dj_status else None
            lines = (status or "A · empty\nB · empty\nCrossfader 0% · Recording off").splitlines()[:3]
            output: list[OneStyleAndTextTuple] = []
            for i, line in enumerate(lines):
                parts = _plain(line).split(" · ")
                if i < 2 and len(parts) >= 4:
                    identity, title, state, position = parts[:4]
                    tail = f"  {state}  {position}"
                    title = _clip(title, max(4, width - cells(identity + tail) - 5))
                    line = f"{identity}  {title}{tail}"
                    if width - cells(line) > 14 and len(parts) > 4:
                        line += "   " + "  ".join(parts[4:])
                elif i == 2 and len(parts) >= 3 and width < 65:
                    recording = next((p for p in parts if p.startswith("Recording ")), "")
                    line = "  ".join((parts[0], parts[1], "REC" if recording and recording != "Recording off" else ""))
                output.append(("class:key" if i == 2 else "class:title", " " + _clip(_plain(line), width - 2)))
                if i < len(lines) - 1:
                    output.append(("", "\n"))
            return output

        pb = self.project()
        title = _plain(getattr(pb, "title", "")) or "Nothing playing"
        active = bool(getattr(pb, "media_id", None) or getattr(pb, "title", None))
        artist = _plain(getattr(pb, "artist", ""))
        state = _plain(getattr(pb, "display_state", "")) or ("Playing" if active else "Stopped")
        live = bool(getattr(pb, "live", False))
        duration = getattr(pb, "duration_seconds", None)
        elapsed = getattr(pb, "position_seconds", 0) or 0
        seekable = active and bool(getattr(pb, "seekable", duration)) and not live
        source = _plain(getattr(pb, "source", ""))
        position = getattr(pb, "queue_position", None)
        count = getattr(pb, "queue_count", None)
        metadata = []
        if source and width >= 65:
            metadata.append(source.upper())
        if position is not None and width >= 37:
            metadata.append(f"{'Queue' if width >= 58 else 'Q'} {position}/{count}")
        right = ("   " + "  ·  ".join(metadata)) if metadata else ""
        tag = " " + _clip(state, 12) + "  "
        budget = max(1, width - cells(tag + right) - 1)
        # Reserve part of the title line for the artist even with long titles.
        if artist and budget >= 16:
            a = _clip(artist, max(6, budget // 3))
            name = _clip(title, budget - cells(a) - 3) + " · " + a
        else:
            name = _clip(title, budget)
        deck: list[OneStyleAndTextTuple] = [("class:key", tag), ("class:title", name)]
        if metadata:
            deck.append(("class:muted", " " * max(0, budget - cells(name)) + right))
        deck.append(("", "\n"))
        if not active:
            deck.extend([("class:accent", " F3 Library ", self._press(lambda: self.switch("Library"))),
                         ("class:muted", " · "), ("class:accent", " F4 Queue ", self._press(lambda: self.switch("Queue")))])
            if self._deck_height() == 3:
                deck.extend([("", "\n"), ("class:muted", " Select a recording to start playback.")])
            return deck

        timing = " " + _clock(elapsed) + " / " + ("LIVE" if live else _clock(duration))
        deck.append(("class:title", timing))
        chapter = _plain(getattr(getattr(pb, "chapter", None), "title", ""))
        chapter = _clip(chapter, min(35, width // 3)) if width >= 82 else ""
        short_row = self._deck_height() == 2
        playing = state.casefold() in ("playing", "buffering", "crossfading")
        short_button = " Pause " if playing else " Play "
        reserve = (cells(short_button) + 2) if short_row else 0
        bar = min(58, max(0, width - cells(timing) - cells(chapter) - reserve - (6 if chapter else 3)))
        if duration and duration > 0 and not live and bar >= 4:
            filled = round(bar * max(0.0, min(1.0, elapsed / duration)))
            origin = cells(timing) + 2
            def scrub(event):
                if not seekable or event.event_type != MouseEventType.MOUSE_UP:
                    return
                current = self.project()
                identity = getattr(pb, "media_id", None) or getattr(pb, "title", None)
                current_id = getattr(current, "media_id", None) or getattr(current, "title", None)
                if current_id != identity or not getattr(current, "seekable", seekable):
                    self._error = "The playing track changed. Select its position again."
                    return
                target = duration * max(0.0, min(1.0, (event.position.x - origin) / max(1, bar - 1)))
                (self.on_run or self.on_edit)(f"seek {target:.2f}s")
            deck.extend([("", "  "), ("class:accent", "━" * filled, scrub), ("class:muted", "─" * (bar - filled), scrub)])
        if chapter:
            deck.append(("class:muted", "  " + chapter))
        if short_row:
            deck.append(("class:key", short_button, self._transport("p")))
            return deck
        deck.append(("", "\n"))
        controls = [
            ("[ Prev", ".prev"), ("← −10s", "seek -10s"), ("Space " + short_button.strip(), "p"),
            ("→ +10s", "seek +10s"), ("] Next", ".next"),
        ]
        if width < 45:
            controls = [("[ Prev", ".prev"), ("Space " + short_button.strip(), "p"), ("] Next", ".next")]
        for label, command in controls:
            if command.startswith("seek") and not seekable:
                continue
            deck.append(("class:accent" if command == "p" else "class:muted", " " + label + " ", self._transport(command)))
        return deck

    def _heading(self):
        query = self.query_by_page.get(self.page, "")
        count = len(self.matches)
        if query:
            status = f"  {count} for “{_plain(query)}”"
        elif self.page in self.sources:
            status = f"  {self.media_count} track" + ("" if self.media_count == 1 else "s")
        else:
            what = {"Commands": "forms", "Discover": "commands", "Player": "actions", "Keys": "shortcuts", "DJ": "controls"}
            status = f"  {count} {what[self.page]}"
        amount = f" {self.position + 1}/{count} " if count > self._height() else ""
        size = self._size()
        budget = max(1, size.columns - len(amount) - cells(self.page) - 2)
        label = _clip(status, budget)
        return [("class:key", " " + self.page), ("class:muted", label),
                ("class:muted", " " * max(0, budget - cells(label)) + amount if amount else "")]

    def _list_lines(self) -> list[OneStyleAndTextTuple]:
        if not self.matches:
            return [("class:muted", " " + _clip("No matches. Press / to change the filter.", self._size().body - 1))]
        height = self._height()
        self._previous_geometry = (self._size(), self.page, self.searching)
        width = max(1, self._size().body - 3)
        self.offset = min(self.offset, self.position)
        self.offset = max(0, self.offset, self.position - height + 1)
        self.offset = min(self.offset, max(0, len(self.matches) - height))
        out: list[OneStyleAndTextTuple] = []
        for index in range(self.offset, min(self.offset + height, len(self.matches))):
            row = self.matches[index]
            active = index == self.position
            style = "class:selected" if active else ""
            detail = row.detail if self.page in ("Library", "Queue", "Keys") else row.group
            if row.group == "Library" and detail.startswith("Library · #"):
                detail = detail.removeprefix("Library · ")
            detail_width = min(width // 3, 36) if width >= 31 else 0
            name_width = width - (detail_width + 2 if detail_width else 0)
            name = _clip(row.title, name_width)
            tail = _clip(detail, detail_width)
            text = name.ljust(len(name) + max(0, name_width - cells(name)))
            def pick(event, i=index, identity=row.identity or row.command or row.title):
                if event.event_type in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
                    self._move(-3 if event.event_type == MouseEventType.SCROLL_UP else 3)
                    return
                if event.event_type == MouseEventType.MOUSE_UP:
                    now = time.monotonic()
                    double = self.last_click is not None and self.last_click[:3] == (self.page, i, identity) and now - self.last_click[3] <= .35
                    self.last_click = None if double else (self.page, i, identity, now)
                    self.position = i
                    get_app().layout.focus(self.focus_control)
                    if double:
                        self.activate()
            out.extend([(style, "› " if active else "  ", pick), (style, text, pick)])
            if detail_width:
                out.append((style if active else "class:muted", "  " + tail + " " * (detail_width - cells(tail)), pick))
            if index + 1 < min(self.offset + height, len(self.matches)):
                out.append(("", "\n"))
        return out

    def _inspector_content(self, width):
        if not self.matches:
            return []
        row = self.matches[self.position]
        lines = [("class:muted", row.group)]
        lines.extend(("class:title", title) for title in wrap(row.title, width))
        if row.detail and row.detail != row.title:
            lines.extend(("", line) for line in wrap(row.detail, width))
        if row.command and row.command != row.title:
            lines.extend(("class:accent", line) for line in wrap(row.command, width))
        if row.arguments:
            lines.extend(("class:accent", line) for line in wrap(row.arguments, width))
        if row.aliases:
            lines.extend(("class:muted", line) for line in wrap("Aliases  " + row.aliases, width))
        if row.effect:
            lines.append(("class:muted", row.effect))
        return self._panel_lines(lines, width)

    @staticmethod
    def _panel_lines(lines, width, action=None):
        formatted = []
        for index, (style, line) in enumerate(lines):
            if index:
                formatted.append(("", "\n"))
            fragment = (style, " " + _clip(line, width))
            formatted.append((*fragment, action) if action else fragment)
        return formatted

    def _detail(self):
        width = self._size().side or self._size().columns
        return self._inspector_content(max(1, width - 2))

    def _compact_detail(self):
        if not self.matches:
            return []
        row = self.matches[self.position]
        width = max(1, self._size().columns - 2)
        command = "  ".join(filter(None, (row.command, row.arguments)))
        return self._panel_lines([("", row.detail), ("class:accent", command)], width)

    def _lower_panel(self):
        if self.last_command:
            return self._activity()
        width = max(1, self._size().side - 2)
        lines = [("class:key", "Queue preview   F4")]
        lines.extend(("", title) for title in self.queue_preview)
        return self._panel_lines(lines, width, self._press(lambda: self.switch("Queue")))

    def _activity(self):
        size = self._size()
        columns = max(1, (size.side or size.columns) - 2)
        rows = min(9, max(4, size.rows // 4)) if size.side else size.compact_rows
        heading = "Latest output   Ctrl+O" if size.side else "Ctrl+O  " + self.last_command
        lines = [("class:key", heading)]
        if size.side:
            lines.append(("class:accent", "› " + self.last_command))
        wrapped = [line for text in self.last_lines for line in wrap(text, columns)]
        room = max(0, rows - len(lines))
        if room:
            lines.extend(("", line) for line in wrapped[-room:])
        return self._panel_lines(lines, columns, self._press(self.on_output) if self.on_output else None)

    def _compact(self):
        if self.inspector:
            return self._inspector_content(max(1, self._size().columns - 2))
        return self._activity() if self.last_command else self._compact_detail()

    def _footer(self) -> list[OneStyleAndTextTuple]:
        size = self._size()
        if self._error:
            return [("class:accent", " " + _clip(self._error, size.columns - 1))]
        if self.searching:
            return [("class:key", " Enter"), ("", " results   "), ("class:key", "Esc"), ("", " clear filter")]
        if self.page == "Keys" and self.matches:
            return [("class:accent", " " + _clip(self.matches[self.position].detail, size.columns - 1))]
        direct = bool(self.matches and self.matches[self.position].playable and self.on_run)
        entry = ("Run" if self.page == "DJ" else "Play") if direct else "Edit"
        shortcuts = [(":", "Command", lambda: self.on_edit(None)), ("/", "Filter", self._begin_filter),
                     ("i", "Details", self._toggle_inspector), ("Ctrl+O", "Output", self.on_output)]
        if size.columns >= 76 and self.on_palette:
            shortcuts.insert(0, ("Ctrl+K", "Palette", self.on_palette))
        if size.columns >= 60:
            shortcuts.insert(0, ("Enter", entry, self.activate))
        if size.columns < 48:
            shortcuts = [(":", "Cmd", lambda: self.on_edit(None)), ("/", "Find", self._begin_filter),
                         ("i", "Info", self._toggle_inspector), ("^O", "Output" if size.columns >= 33 else "Log", self.on_output)]
        fragments: list[OneStyleAndTextTuple] = []
        for key, label, callback in shortcuts:
            handler = self._press(callback) if callback else None
            pieces = [("class:key", " " + key), ("", " " + label + " ")]
            fragments.extend((*piece, handler) if handler else piece for piece in pieces)
        return fragments
