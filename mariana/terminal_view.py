"""Give a live command view the same terminal owner as the command that opened it."""
from __future__ import annotations

from prompt_toolkit.application import Application
from prompt_toolkit.layout import Layout

from .terminal_io import current_session


class TerminalView:
    def __init__(self):
        # Key handlers and redraws run on the TUI's event-loop thread, where
        # worker-local session lookup would lose the command's owner.
        self.owner = current_session()
        self.application = None

    def finish(self, result=None):
        if self.owner is not None:
            self.owner.close_view(result)
        elif self.application is not None and self.application.is_running and not self.application.is_done:
            self.application.exit(result=result)

    def run(self, container, *, focus, bindings, style, interval, input=None, output=None):
        if self.owner is not None:
            return self.owner.run_view(container, focus=focus, bindings=bindings, style=style, refresh_interval=interval)
        if self.application is None:
            self.application = Application(layout=Layout(container, focused_element=focus), full_screen=True,
                                           refresh_interval=interval, key_bindings=bindings, style=style,
                                           input=input, output=output)
        return self.application.run()
