"""Keyboard-operated terminal view of the running Mariana playback session."""

import re
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from prompt_toolkit import Application
from prompt_toolkit.application.current import get_app
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.key_bindings import DynamicKeyBindings
from prompt_toolkit.key_binding.bindings.named_commands import get_by_name
from prompt_toolkit.key_binding.bindings.scroll import scroll_page_down, scroll_page_up
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import ConditionalContainer, DynamicContainer, Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import DynamicStyle, Style, merge_styles
from prompt_toolkit.widgets import TextArea

from .terminal_io import TerminalIO, current_session
from .terminal_prompt import CommandCompleter, SessionHistory, _windows_word_erase_key
from .terminal_workspace import TerminalWorkspace
from .terminal_palette import CommandPalette
from .theme_palette import PRESETS, active_theme, resolved_theme


def clock(seconds):
    if seconds is None:
        return "–"
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f"{minutes}:{seconds:02}"


def player_lines(playback, palette_name):
    title = " — ".join(str(item) for item in (playback.artist, playback.title) if item)
    queue = (f"  ·  Queue {playback.queue_position}/{playback.queue_count}"
             if playback.queue_position is not None else "")
    duration = playback.duration_seconds
    progress = []
    if duration and duration > 0 and not playback.live:
        filled = round(24 * max(0.0, min(1.0, playback.position_seconds / duration)))
        progress = [("class:accent", "  " + "━" * filled), ("class:muted", "─" * (24 - filled) + "\n")]
    return [
        ("class:accent", "  Mariana\n\n"),
        ("class:title", f"  {title or 'Nothing playing'}\n"),
        ("", f"  {playback.display_state}{queue}\n\n"),
        ("class:accent", f"  {clock(playback.position_seconds)} / {'Live' if playback.live else clock(playback.duration_seconds)}\n"),
        *progress,
        ("class:muted", f"\n  {palette_name}\n"),
        ("", "  Space  Play/pause    ← / →  Seek 10s\n  [ / ]  Previous/next    T  Theme    Q  Close"),
    ]


# User-visible command output can contain terminal style/cursor sequences.
# The dashboard owns the terminal, including during native prompts.
_TERMINAL_CODES = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


_TRANSCRIPT_LIMIT = 512 * 1024
_TRIMMED = "[Earlier output trimmed from this transcript.]\n"


class _OutputTail:
    def __init__(self, limit=_TRANSCRIPT_LIMIT):
        self.limit = limit
        self.parts = deque()
        self.size = 0
        self.head_offset = 0
        self.trimmed = False

    def write(self, value):
        if not value:
            return
        if len(value) >= self.limit:
            self.trimmed |= self.size > 0 or len(value) > self.limit
            self.parts.clear()
            self.head_offset = 0
            value = value[-self.limit:]
            self.size = 0
        self.parts.append(value)
        self.size += len(value)
        while self.size > self.limit:
            self.trimmed = True
            drop = min(self.size - self.limit, len(self.parts[0]) - self.head_offset)
            self.head_offset += drop
            self.size -= drop
            if self.head_offset == len(self.parts[0]):
                self.parts.popleft()
                self.head_offset = 0

    def text(self):
        return "".join(self.parts)[self.head_offset:]


def _append_command(previous, command, captured, limit=_TRANSCRIPT_LIMIT):
    response = _TERMINAL_CODES.sub("", captured.text()).replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    if captured.trimmed:
        response = _TRIMMED + response
    entry = ("› " + command + ("\n" if response else "") if command else "") + response
    start = len(previous) + (2 if previous else 0)
    text = (previous + "\n\n" if previous else "") + entry
    if len(text) > limit:
        # Keep the newest result and put its starting position in view when possible.
        keep = limit - len(_TRIMMED)
        start = max(0, start - len(text) + keep + len(_TRIMMED))
        text = _TRIMMED + text[-keep:]
    return Document(text, start)


class _Transcript:
    def __init__(self):
        self.lock = threading.Lock()
        self.previous = ""
        self.command = ""
        self.tail = _OutputTail()
        self.revision = 0
        self.generation = 0
        self.starts = deque(maxlen=2048)

    def clear(self, generation=None):
        with self.lock:
            if generation is not None and generation != self.generation:
                return
            self.previous = self.command = ""
            self.starts.clear()
            self.tail = _OutputTail()
            self.revision += 1

    def begin(self, command):
        with self.lock:
            if self.command or self.tail.size:
                previous = _append_command(self.previous, self.command, self.tail)
                self.starts = deque(self._positions(previous), maxlen=2048)
                self.previous = previous.text
            self.command = command
            self.tail = _OutputTail()
            self.revision += 1

    def reset_view(self, generation):
        with self.lock:
            self.generation = generation
            self.previous = self.command = ""
            self.starts.clear()
            self.tail = _OutputTail()
            self.revision += 1

    def write(self, text, generation=None):
        with self.lock:
            if generation is not None and generation != self.generation:
                return
            self.tail.write(text)
            self.revision += 1

    def _positions(self, doc):
        # doc.cursor_position identifies the start of the current command block,
        # even if user-generated output contains text resembling a command prompt.
        position = doc.cursor_position
        displaced = max(0, len(self.previous) + (2 if self.previous else 0) - position)
        first = len(_TRIMMED) if displaced else 0
        for start in self.starts:
            if start - displaced >= first:
                yield start - displaced
        if self.command:
            yield position

    def adjacent(self, cursor, direction):
        with self.lock:
            doc = _append_command(self.previous, self.command, self.tail)
            positions = list(self._positions(doc))
            if direction < 0:
                return next((x for x in reversed(positions) if x < cursor), 0)
            return next((x for x in positions if x > cursor), len(doc.text))

    def snapshot(self, revision):
        with self.lock:
            if self.revision == revision:
                return None
            document = _append_command(self.previous, self.command, self.tail)
            return self.revision, document, self.command, _TERMINAL_CODES.sub("", self.tail.text())


def run_player(project, appearance, dispatch, *, library_rows=None, queue_rows=None, dj_status=None, value_provider=None,
               is_visible=lambda: True, input=None, output=None, direct=False, recovery_view=None, startup_notices=()):
    """Keep one screen and serial native dispatcher for the lifetime of a workspace."""
    bindings = KeyBindings()
    log = _Transcript()
    transcript = TextArea(read_only=True, scrollbar=True, focus_on_click=True, wrap_lines=True)
    completer = CommandCompleter(value_provider)
    history = SessionHistory()
    history_offset = 0
    draft = ""
    editor = TextArea(multiline=False, height=1, wrap_lines=False, prompt=[("class:key", "  › ")],
                      history=history, completer=completer, style="class:panel")
    answer = TextArea(multiline=False, height=1)
    secret = TextArea(multiline=False, height=1, password=True)
    may_display = True
    restricted = bool(direct and recovery_view and not is_visible())
    generation = 0
    command_generation = 0
    palette = palette_origin = None
    launched_at = elapsed = 0.0
    shown = None
    future = None
    queued = deque()
    closing = False
    revision = -1
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Mariana TUI command")

    def invalidate():
        app.invalidate()

    def write(value):
        active_command = current_session() is io
        epoch = command_generation if active_command else generation
        if value and (active_command or not restricted):
            log.write(value, epoch)
            invalidate()

    def clear_output():
        log.clear(command_generation)
        invalidate()

    io = TerminalIO(invalidate, write, clear_output)
    available = Condition(lambda: may_display and shown is None and io.dialog is None and palette is None)
    picking = Condition(lambda: may_display and not restricted and shown is None and io.dialog is None and palette is not None)
    normal = available & Condition(lambda: not restricted)
    reading = normal & Condition(lambda: get_app().layout.has_focus(transcript))
    editing = normal & Condition(lambda: get_app().layout.has_focus(editor))
    answering = Condition(lambda: shown is not None and shown.kind == "prompt" and shown is io.dialog)

    def edit(command=None):
        nonlocal history_offset
        history_offset = 0
        if command is not None:
            editor.buffer.document = Document(command, len(command))
        app.layout.focus(editor)

    def execute(command):
        try:
            with io.worker():
                return dispatch(command)
        except (KeyboardInterrupt, EOFError, SystemExit):
            log.write("\nCommand cancelled.\n", command_generation)
        except Exception as error:
            log.write(f"\n{type(error).__name__}: {error}\n", command_generation)
        return None

    def start(command):
        nonlocal future, command_generation, launched_at
        launched_at = time.monotonic()
        command_generation = generation
        io.cancelled.clear()
        log.begin(command)
        future = worker.submit(execute, command)
        future.add_done_callback(lambda _result: invalidate())

    def play(command):
        if closing or not may_display or io.dialog is not None or shown is not None:
            return
        if future is None:
            start(command)
        elif len(queued) < 32:
            queued.append(command)

    def open_output():
        app.layout.focus(transcript)

    def make_workspace():
        if restricted:
            return recovery_view(play)
        return TerminalWorkspace(project, lambda: PRESETS[active_theme(appearance())]["name"], edit,
                                 library_rows=library_rows, queue_rows=queue_rows, on_run=play,
                                 dj_status=dj_status, on_output=open_output, on_palette=lambda: open_palette("Commands"))

    workspace = make_workspace()
    browsing = available & Condition(lambda: get_app().layout.has_focus(workspace.focus_control))

    def choose_from_palette(command):
        nonlocal palette, palette_origin
        palette = palette_origin = None
        edit(command)

    def open_palette(mode):
        nonlocal palette, palette_origin
        if palette is None:
            palette_origin = app.layout.current_control
            palette = CommandPalette(workspace.catalog, history, choose_from_palette)
        palette.open(mode)
        app.layout.focus(palette.query)

    @bindings.add("c-k", filter=normal | picking)
    def show_commands(_event):
        open_palette("Commands")

    @bindings.add("c-r", filter=normal | picking)
    def show_history(_event):
        open_palette("History")

    @bindings.add("escape", filter=picking)
    @bindings.add("c-c", filter=picking)
    def dismiss_palette(event):
        nonlocal palette, palette_origin
        origin = palette_origin
        palette = palette_origin = None
        event.app.layout.focus(origin if origin is not None else workspace.focus_control)

    for key, step in (("up", -1), ("down", 1), ("pageup", -10), ("pagedown", 10)):
        bindings.add(key, filter=picking)(lambda event, delta=step: palette.move(delta))

    bindings.add("enter", filter=picking)(lambda event: palette.accept())
    picking_history = picking & Condition(lambda: palette.mode == "History")
    bindings.add("c-x", filter=picking_history)(lambda event: palette.clear())
    bindings.add("c-s", filter=picking_history)(lambda event: palette.toggle_save())
    # F9 also works in terminals that reserve Ctrl+S for flow control.
    bindings.add("f9", filter=picking_history)(lambda event: palette.toggle_save())

    def browse(event):
        if editing() and completer.offered_for == editor.text:
            completer.dismiss(editor.buffer)
            return
        editor.buffer.cancel_completion()
        event.app.layout.focus(workspace.focus_control)

    bindings.add("escape", filter=editing | reading)(browse)
    bindings.add("c-c", filter=editing | reading)(browse)

    @bindings.add("q", filter=browsing)
    @bindings.add("c-c", filter=browsing)
    @bindings.add("escape", filter=browsing)
    def close(event):
        nonlocal closing
        if direct:
            play("exit" if restricted else "quit")
        elif future is None:
            event.app.exit()
        else:
            closing = True
            queued.clear()
            io.cancel()

    @bindings.add("f1", filter=normal)
    @bindings.add(":", filter=(browsing & normal) | reading)
    def open_editor(_event):
        edit()

    @bindings.add("c-o", filter=normal)
    def toggle_output(event):
        if reading():
            browse(event)
        else:
            open_output()

    bindings.add("pageup", filter=reading)(scroll_page_up)
    bindings.add("pagedown", filter=reading)(scroll_page_down)

    for key, direction in (("c-up", -1), ("c-down", 1)):
        def move_block(_event, direction=direction):
            transcript.buffer.cursor_position = log.adjacent(transcript.buffer.cursor_position, direction)
        bindings.add(key, filter=reading)(move_block)

    @bindings.add("home", filter=reading)
    def first_line(_event):
        transcript.buffer.cursor_position = 0

    @bindings.add("end", filter=reading)
    def last_line(_event):
        transcript.buffer.cursor_position = len(transcript.text)

    @bindings.add("enter", filter=editing)
    def submit(_event):
        command = editor.text
        if command.strip() and not completer.offer(editor.buffer):
            editor.buffer.reset(append_to_history=True)
            open_output()
            play(command)

    @bindings.add("enter", filter=answering)
    def respond(_event):
        field = secret if shown.secret else answer
        value = field.text
        field.buffer.reset()
        io.answer(shown, value)

    @bindings.add("c-c", filter=answering)
    @bindings.add("escape", filter=answering)
    @bindings.add("c-d", filter=answering)
    def cancel_input(_event):
        queued.clear()
        secret.buffer.reset()
        answer.buffer.reset()
        io.cancel()

    @bindings.add("c-c", filter=(browsing | reading) & Condition(lambda: future is not None and not future.done()))
    def cancel_command(_event):
        queued.clear()
        io.cancel()
        write("\nCancellation requested.\n")

    @bindings.add("up", filter=editing)
    @bindings.add("down", filter=editing)
    def recall(event):
        nonlocal history_offset, draft
        entries = history.get_strings()
        if not history_offset:
            draft = editor.text
        step = 1 if event.key_sequence[-1].key == "up" else -1
        history_offset = max(0, min(len(entries), history_offset + step))
        value = entries[-history_offset] if history_offset else draft
        editor.buffer.document = Document(value, len(value))

    @bindings.add("tab", filter=editing)
    def complete(event):
        completer.accept(event.current_buffer)

    @bindings.add("s-tab", filter=editing)
    def previous_completion(event):
        completer.previous(event.current_buffer)

    if sys.platform == "win32":
        @bindings.add("backspace", filter=editing)
        def erase(event):
            cmd = ("backward-kill-word" if event.data == _windows_word_erase_key(event.app.input)
                   else "backward-delete-char")
            get_by_name(cmd).call(event)

    def transport(event):
        key = event.key_sequence[-1].key
        if key == "t":
            names = list(PRESETS)
            name = names[(names.index(active_theme(appearance())) + 1) % len(names)]
            play(f"theme {name}")
        else:
            play({" ": "p", "left": "seek -10s", "right": "seek +10s", "[": ".prev", "]": ".next"}[key])

    for key in (" ", "left", "right", "[", "]", "t"):
        bind = browsing & normal
        if key != "t":
            bind = bind & Condition(lambda: workspace.page != "DJ")
        bindings.add(key, filter=bind)(transport)

    @lru_cache(maxsize=16)
    def cached_style(background, text, accent, muted, panel):
        return Style.from_dict({"": f"bg:{background} {text}", "accent": f"bold {accent}",
                                "title": "bold", "muted": muted, "key": f"bold {accent}",
                                "panel": f"bg:{panel} {text}", "bar": f"bg:{panel} {text}",
                                "selected": f"bg:{accent} {background} bold"})

    def style():
        colors = resolved_theme({} if restricted else appearance())["chrome"]
        base = cached_style(*(colors[key][:7] for key in ("background", "text", "accent", "muted", "panel")))
        return merge_styles([base, shown.style]) if shown and shown.style else base

    def output_header():
        active = future is not None and not future.done()
        time_text = f"Running {time.monotonic() - launched_at:.1f}s" if active else f"Finished in {elapsed:.1f}s"
        state = ("  ·  " + time_text) if launched_at else ""
        waiting = f"  ·  {len(queued)} queued" if queued else ""
        return [("class:title", "  Command output"), ("class:accent" if active else "class:muted", state + waiting)]

    def make_surface():
        if restricted:
            body = workspace.container
        else:
            output_view = HSplit([
                workspace.navigation_strip(), workspace.player_strip(),
                Window(FormattedTextControl(output_header), height=1, style="class:bar"),
                transcript,
                Window(FormattedTextControl(lambda: " ↑↓ Scroll  PgUp/Dn  : Cmd  Esc Back" if app.output.get_size().columns <= 60
                       else "  Ctrl+↑/↓ Blocks   Ctrl+K Palette   Ctrl+R History   : Command   Esc Back"),
                       height=1, style="class:bar"),
            ])
            body = FloatContainer(HSplit([
                ConditionalContainer(workspace.container, ~reading),
                ConditionalContainer(output_view, reading),
                ConditionalContainer(editor, editing),
                ConditionalContainer(Window(FormattedTextControl(lambda: completer.notice(editor.text)), height=1),
                                     editing & Condition(lambda: bool(completer.notice(editor.text)))),
            ]), floats=[Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=5))])

        # Keep the native handler's printed options visible while it waits. A
        # separate, non-focusable window scrolls the transcript without moving
        # the edit cursor or revealing a masked response.
        prompt_log = Window(BufferControl(buffer=transcript.buffer, focusable=False), wrap_lines=True,
                            always_hide_cursor=True)
        question = Window(FormattedTextControl(lambda: "  " + _TERMINAL_CODES.sub("", shown.title)
                               if shown else ""), style="class:title", wrap_lines=True, dont_extend_height=True)
        field = DynamicContainer(lambda: secret if shown and shown.secret else answer)
        prompt_footer = Window(FormattedTextControl("  Enter Submit   Esc Cancel   PgUp/Dn Output"),
                               height=1, style="class:muted")
        if restricted:
            input_view = HSplit([workspace.container, question, field, prompt_footer])
        else:
            input_view = HSplit([
                workspace.player_strip(), Window(FormattedTextControl("  Command output"), height=1, style="class:bar"),
                prompt_log, question, field, prompt_footer,
            ])
        return body, input_view, prompt_log

    body, input_view, prompt_log = make_surface()

    def scroll_prompt(amount):
        # Keep the prompt focused. The transcript buffer drives prompt_log's
        # cursor position and has no relation to the secure input buffer.
        document = transcript.buffer.document
        step = max(1, (prompt_log.render_info.window_height if prompt_log.render_info else 5) - 1)
        row = max(0, min(document.line_count - 1, document.cursor_position_row + step * amount))
        transcript.buffer.cursor_position = (len(document.text) if row == document.line_count - 1
                                             else document.translate_row_col_to_index(row, 0))

    @bindings.add("pageup", filter=answering & Condition(lambda: not restricted))
    def prior_output(_event):
        scroll_prompt(-1)

    @bindings.add("pagedown", filter=answering & Condition(lambda: not restricted))
    def next_output(_event):
        scroll_prompt(1)

    blank = Window()
    def visible_body():
        if not may_display:
            return blank
        if shown:
            return shown.container if shown.kind == "view" else input_view
        return palette.container if palette is not None else body

    prior_focus = None
    def sync(app):
        nonlocal may_display, restricted, workspace, body, input_view, prompt_log, generation, startup_notices
        nonlocal shown, prior_focus, revision, future, closing, history, history_offset, draft, elapsed
        nonlocal palette, palette_origin, launched_at
        if app.is_done:
            return
        allowed = is_visible()
        if direct and recovery_view:
            if restricted != (not allowed):
                # Never render or retain a previous surface's projection after
                # a visibility change. Background work can finish but cannot
                # append its old-generation output to the newly active view.
                restricted = not allowed
                generation += 1
                queued.clear()
                io.cancel()
                shown = prior_focus = palette = palette_origin = None
                launched_at = elapsed = 0.0
                draft, history_offset = "", 0
                history = SessionHistory()
                editor.buffer.history = history
                completer.offered_for = completer.declined_for = None
                completer.corrections = ()
                editor.buffer.reset()
                answer.buffer.reset()
                secret.buffer.reset()
                log.reset_view(generation)
                transcript.buffer.set_document(Document(""), bypass_readonly=True)
                workspace = make_workspace()
                body, input_view, prompt_log = make_surface()
                # Drop the old focus stack with its library projections. The
                # application and renderer continue owning the same screen.
                app.layout = Layout(DynamicContainer(visible_body), focused_element=workspace.focus_control)
        else:
            may_display = allowed
        if not may_display or closing:
            queued.clear()
            if not io.cancelled.is_set():
                io.cancel()
            if future is None or future.done():
                result = future.result() if future is not None else None
                app.exit(result=result)
            return
        if startup_notices and not restricted:
            log.begin("Startup notices")
            log.write("\n".join(startup_notices), generation)
            startup_notices = ()
        snapshot = log.snapshot(revision)
        if snapshot is not None:
            revision, doc, label, latest = snapshot
            if not restricted:
                at_end = transcript.buffer.cursor_position == len(transcript.text)
                transcript.buffer.set_document(Document(doc.text, len(doc.text) if at_end else
                    min(transcript.buffer.cursor_position, len(doc.text))), bypass_readonly=True)
            workspace.set_activity(label, latest)
        dialog = io.dialog
        if dialog is not shown:
            if shown is None:
                prior_focus = app.layout.current_control
            shown = dialog
            secret.buffer.reset()
            answer.buffer.reset()
            if shown is not None:
                if shown.kind == "prompt":
                    app.layout.focus(secret if shown.secret else answer)
                else:
                    app.layout.focus(shown.focus if shown.focus is not None else shown.container)
            elif restricted:
                app.layout.focus(workspace.focus_control)
            else:
                app.layout.focus(prior_focus if prior_focus is not None else workspace.focus_control)
        if future is not None and future.done():
            result = future.result()
            elapsed = time.monotonic() - launched_at
            future = None
            if result is False:
                app.exit(result=False)
            else:
                workspace.refresh()
                if queued:
                    start(queued.popleft())

    # Keep live karaoke/speech frames responsive without constantly repainting
    # a static dashboard. Panel changes and new output invalidate immediately.
    async def redraw_views():
        import asyncio
        while True:
            interval = shown.interval if shown and shown.kind == "view" else 0.5
            await asyncio.sleep(max(0.03, min(interval, 0.5)))
            invalidate()

    app = Application(layout=Layout(DynamicContainer(visible_body), focused_element=workspace.focus_control),
                      full_screen=True, key_bindings=merge_key_bindings([
                          DynamicKeyBindings(lambda: workspace.bindings if available() else None), bindings,
                          DynamicKeyBindings(lambda: shown.bindings if shown and shown.kind == "view" else None)]),
                      mouse_support=True, before_render=sync, style=DynamicStyle(style), input=input, output=output)
    if not (direct and recovery_view) and not is_visible():
        worker.shutdown()
        return None
    with io.capture():
        try:
            return app.run(pre_run=lambda: app.create_background_task(redraw_views()))
        except (EOFError, KeyboardInterrupt):
            return False if direct else None
        finally:
            io.cancel()
            worker.shutdown(wait=True, cancel_futures=True)
