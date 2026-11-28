"""A terminal workspace that exposes only the current session recovery controls."""
from prompt_toolkit.filters import has_focus
from prompt_toolkit.formatted_text.base import OneStyleAndTextTuple
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import FormattedTextControl, Window

# The native dispatcher checks the session/focus policy again before each action.
_CONTROLS = {
    None: ('Restoring player access', ()),
    'hidden': ('Display hidden', (
        ('Show the player', 'vis'),
    )),
    'replay': ('Session replay controls playback', (
        ('Show replay status', 'session status'), ('Stop replay', 'session stop'),
    )),
    'focus': ('Focus mode is active', (
        ('Show focus status', 'focus status'), ('Request unlock', 'focus off'),
        ('Verify approval', 'focus verify'), ('Cancel unlock request', 'focus cancel'),
    )),
    'recovery': ('Focus recovery is required', (
        ('Show recovery status', 'focus status'), ('Recover focus settings', 'focus recover'),
    )),
}


class TerminalRecoveryWorkspace:
    """A fresh, redacted view for one restriction; it never reads the library or playhead."""
    page = 'Recovery'

    def __init__(self, restriction, dispatch, visible):
        self.restriction = restriction
        self._last = object()
        self.visible = visible
        self.selected = 0
        self.message = ''
        self.bindings = KeyBindings()
        self.focus_control = FormattedTextControl(self._lines, focusable=True, show_cursor=False)
        self.container = Window(self.focus_control, wrap_lines=True)

        self.refresh()
        browsing = has_focus(self.focus_control)

        @self.bindings.add('up', filter=browsing)
        def previous(_event):
            self.refresh()
            self.selected = max(0, self.selected - 1)

        @self.bindings.add('down', filter=browsing)
        def following(_event):
            self.refresh()
            self.selected = min(len(self.controls) - 1, self.selected + 1)

        @self.bindings.add('enter', filter=browsing)
        def activate(_event):
            self.refresh()
            dispatch(self.controls[self.selected][1])

    def _lines(self) -> list[OneStyleAndTextTuple]:
        self.refresh()
        rows: list[OneStyleAndTextTuple] = [('class:title', f'  Mariana · {self.title}\n\n')]
        for index, (label, _cmd) in enumerate(self.controls):
            selected = index == self.selected
            rows.append(('class:selected' if selected else '', f"  {'›' if selected else ' '} {label}\n"))
        rows.append(('class:muted', '\n  ↑ ↓  Select    Enter  Run    Q  Exit'))
        if self.message and self.visible():
            rows.append(('', '\n\n  ' + self.message))
        return rows

    def set_activity(self, command, plain_text):
        self.refresh()
        if self.visible() and command in {token for _, token in self.controls}:
            self.message = str(plain_text).strip()[-1600:]

    def refresh(self):
        restriction = self.restriction()
        if restriction != self._last:
            self._last = restriction
            self.title, controls = _CONTROLS[restriction]
            self.controls = (*controls, ('Exit Mariana', 'exit'))
            self.selected = 0
            self.message = ''
