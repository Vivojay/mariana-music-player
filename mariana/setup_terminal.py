"""Full-screen first-run and media-tool questions for the direct terminal launcher."""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from prompt_toolkit.application import Application, create_app_session, get_app_session
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import ConditionalContainer, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Button, TextArea

from .terminal_io import TerminalIO, current_session
from .theme_palette import resolved_theme

_CONTROL = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_YES_NO = re.compile(r"(?:y\s*/\s*n|yes\s*/\s*no)", re.I)


class _SharedScreen:
    def __init__(self, output):
        self.output = output
        self.entered = False

    @property
    def __class__(self):
        # prompt_toolkit uses an isinstance check for native Windows mouse events.
        return self.output.__class__

    def __getattr__(self, name):
        return getattr(self.output, name)

    def enter_alternate_screen(self):
        if not self.entered:
            self.output.enter_alternate_screen()
            self.entered = True
        else:
            self.output.erase_screen()
            self.output.cursor_goto(0, 0)

    def quit_alternate_screen(self):
        # Individual applications release their layouts. The direct launcher
        # retains its physical buffer until setup and playback have finished.
        pass

    def release(self):
        if self.entered:
            self.output.reset_attributes()
            self.output.quit_alternate_screen()
            self.output.show_cursor()
            self.output.flush()
            self.entered = False


@contextmanager
def direct_screen():
    """Share one alternate buffer across setup, reconfiguration and the player."""
    original = get_app_session()
    screen = _SharedScreen(original.output)
    try:
        with create_app_session(input=original.input, output=screen):
            yield
    finally:
        screen.release()


def run_setup(title, action, appearance, *, input=None, output=None):
    """Run only the existing synchronous setup operation away from the UI thread."""
    lock = threading.Lock()
    text = ""
    version = 0
    painted = -1
    displayed = None
    finished = threading.Event()

    def write(chunk):
        nonlocal text, version
        if current_session() is host and host.cancelled.is_set():
            raise KeyboardInterrupt
        clean = _CONTROL.sub("", chunk).replace("\r\n", "\n")
        with lock:
            # Progress meters replace a line with CR. Keep the last update.
            if "\r" in clean:
                for part in re.split(r"(\r)", clean):
                    text = text[:text.rfind("\n") + 1] if part == "\r" else text + part
            else:
                text += clean
            text = text[-32768:]
            version += 1
        app.invalidate()

    def perform():
        with host.worker():
            try:
                value = action()
                if host.cancelled.is_set():
                    raise KeyboardInterrupt
                return value
            except (KeyboardInterrupt, EOFError):
                raise
            except Exception as error:
                print(f"\n{title} failed: {error}")
                host.prompt("Press Enter to close setup. ")
                raise SystemExit(1) from error

    def resolve(value):
        if displayed is not None:
            host.answer(displayed, value)

    def submit(buffer):
        resolve(buffer.text)
        return True

    history = TextArea(read_only=True, scrollbar=True, wrap_lines=True, focusable=False)
    answer = TextArea(multiline=False, height=1, prompt="› ", accept_handler=submit)
    secret = TextArea(multiline=False, height=1, prompt="› ", password=True, accept_handler=submit)
    waiting = Condition(lambda: displayed is not None)
    yes_no = Condition(lambda: displayed is not None and not displayed.secret and bool(_YES_NO.search(displayed.title)))
    hidden = Condition(lambda: displayed is not None and displayed.secret)
    keys = KeyBindings()

    @keys.add("c-c", eager=True)
    @keys.add("escape", eager=True)
    def cancel(_event):
        host.cancel()

    @keys.add("tab")
    def next_field(event):
        event.app.layout.focus_next()

    @keys.add("s-tab")
    def previous_field(event):
        event.app.layout.focus_previous()

    @keys.add("pageup")
    @keys.add("pagedown")
    def scroll(event):
        lines = max(1, app.output.get_size().rows - 8)
        if event.key_sequence[0].key == "pageup":
            history.buffer.cursor_up(lines)
        else:
            history.buffer.cursor_down(lines)

    def prompt_text():
        return displayed.title.strip() if displayed else (
            "Stopping after the current operation…" if host.cancelled.is_set() else "Working…")

    colors = resolved_theme(appearance)["chrome"]
    style = Style.from_dict({"": f"bg:{colors['background'][:7]} {colors['text'][:7]}",
                             "title": f"bold {colors['accent'][:7]}", "hint": colors["muted"][:7],
                             "button.focused": f"bg:{colors['accent'][:7]} {colors['background'][:7]}"})
    container = HSplit([
        Window(FormattedTextControl(f"  Mariana  /  {title}"), height=2, style="class:title"),
        history, Window(height=1),
        Window(FormattedTextControl(prompt_text), wrap_lines=True, dont_extend_height=True, style="class:title"),
        ConditionalContainer(answer, waiting & ~hidden), ConditionalContainer(secret, waiting & hidden),
        ConditionalContainer(VSplit([Button("Yes", handler=lambda: resolve("y")),
                                     Button("No", handler=lambda: resolve("n"))], padding=1), yes_no),
        Window(FormattedTextControl("  Enter  Submit     Tab  Next control     Esc  Leave setup"),
               height=1, style="class:hint"),
    ])

    def sync(_app):
        nonlocal displayed, painted
        with lock:
            if painted != version:
                history.buffer.set_document(Document(text, len(text)), bypass_readonly=True)
                painted = version
        current = host.dialog
        if displayed is not current:
            displayed = current
            answer.buffer.reset()
            secret.buffer.reset()
            if displayed is not None:
                app.layout.focus(secret if displayed.secret else answer)
        if finished.is_set() and not app.is_done:
            app.exit()

    # Construct the real terminal's input and renderer before capturing command
    # streams. Only the wizard worker receives answers and changes setup state.
    app = Application(layout=Layout(container), full_screen=True, key_bindings=keys, before_render=sync,
                      mouse_support=True, style=style, input=input, output=output)
    host = TerminalIO(app.invalidate, write)
    with host.capture(), ThreadPoolExecutor(max_workers=1, thread_name_prefix="mariana-setup") as worker:
        result = None

        def complete(_):
            finished.set()
            app.invalidate()

        def begin():
            nonlocal result
            result = worker.submit(perform)
            result.add_done_callback(complete)

        try:
            app.run(pre_run=begin)
            return result.result()
        finally:
            host.cancel()
