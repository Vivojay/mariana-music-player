"""UTF-8 text views owned by the current terminal workspace."""
from __future__ import annotations

import codecs
import os
import re
import stat
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import FormattedTextControl, HSplit, Window
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from .output_targets import BoundOutputTarget, OutputTargetError, bind_output_target
from .terminal_view import TerminalView

_MAX_BYTES = 512 * 1024
_NEWLINE = re.compile(r'\r\n|\r|\n')
_SAVE_LOCK = threading.Lock()
_STYLE = Style.from_dict({'title': 'bold', 'hint': 'italic'})


def _normal(text):
    return _NEWLINE.sub('\n', text)


def _encoded_edit(raw, text):
    """Retain BOM, line endings and the editor's choice of final newline."""
    old = raw.decode('utf-8-sig')
    original_endings = _NEWLINE.findall(old)
    text = _normal(text)
    default = Counter(original_endings).most_common(1)[0][0] if original_endings else os.linesep
    if len(set(original_endings)) <= 1:
        result = text.replace('\n', default)
    else:
        old_lines, new_lines = _normal(old).split('\n'), text.split('\n')
        endings = [default] * (len(new_lines) - 1)
        for op, old_start, old_end, new_start, new_end in SequenceMatcher(None, old_lines, new_lines).get_opcodes():
            if op in {'equal', 'replace'}:
                for before, after in zip(range(old_start, min(old_end, len(original_endings))),
                                         range(new_start, min(new_end, len(endings))), strict=False):
                    endings[after] = original_endings[before]
        result = ''.join(line + end for line, end in zip(new_lines, endings, strict=False)) + new_lines[-1]
    return (codecs.BOM_UTF8 if raw.startswith(codecs.BOM_UTF8) else b'') + result.encode('utf-8')


def _read(target, *, tail=False):
    """Read the bound regular file and cap the read even if it grows."""
    if target.file_signature is None:
        raise ValueError('The requested text file does not exist.')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    with os.fdopen(os.open(target.path, flags), 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino, info.st_mode) != target.file_signature[:3]:
            raise ValueError('The text file changed before it could be opened.')
        truncated = info.st_size > _MAX_BYTES
        if truncated and tail:
            handle.seek(info.st_size - _MAX_BYTES)
        data = handle.read(_MAX_BYTES + (0 if tail else 1))
        if not tail and len(data) > _MAX_BYTES:
            raise ValueError('The terminal editor accepts UTF-8 files up to 512 KiB.')
    if not tail:
        target.revalidate()
    return data, truncated


@dataclass
class _TextFile:
    target: BoundOutputTarget
    raw: bytes
    text: str

    @classmethod
    def open(cls, path):
        target = bind_output_target(path)
        raw, _ = _read(target)
        if b'\0' in raw:
            raise ValueError('The terminal editor requires a UTF-8 text file.')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError as error:
            raise ValueError('The terminal editor requires a UTF-8 text file.') from error
        return cls(target, raw, _normal(text))

    def save(self, text):
        if text == self.text:
            return
        if len(text) > _MAX_BYTES:
            raise ValueError('The edited file exceeds 512 KiB.')
        data = _encoded_edit(self.raw, text)
        if len(data) > _MAX_BYTES:
            raise ValueError('The edited file exceeds 512 KiB.')
        target = self.target
        with _SAVE_LOCK:
            previous, _ = _read(target)
            if previous != self.raw:
                raise ValueError('The file was edited elsewhere. Saving this draft would overwrite those changes.')
            mode = stat.S_IMODE(target.file_signature[2])
            if not mode & 0o222 or not os.access(target.path, os.W_OK):
                raise ValueError('This file is read-only.')
            fd, staged = tempfile.mkstemp(prefix='.mariana-edit-', dir=target.path.parent)
            try:
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(staged, mode & 0o777)
                target.activate(staged)
            finally:
                Path(staged).unlink(missing_ok=True)


def _open_view(title, source, save=None):
    view = TerminalView()
    editor = TextArea(text=source, multiline=True, wrap_lines=True, scrollbar=True,
                      read_only=save is None, focus_on_click=True)
    hint = ['']
    discard = [False]
    keys = KeyBindings()
    normal_hint = ('Esc  Close' if save is None else 'Ctrl+S  Save and close     Esc  Cancel')

    def finish(_event):
        if save is None or editor.text == source or discard[0]:
            view.finish()
        else:
            discard[0] = True
            hint[0] = 'Discard unsaved changes? Press Esc again to discard, or keep editing.'

    keys.add('escape', eager=True)(finish)
    keys.add('c-c', eager=True)(finish)
    if save is None:
        keys.add('q')(finish)
    else:
        @keys.add('c-s', eager=True)
        def request_save(_event):
            view.finish(('save', editor.text))

        def edited(_):
            if discard[0]:
                discard[0] = False
                hint[0] = ''
        editor.buffer.on_text_changed += edited

    layout = HSplit([
        Window(FormattedTextControl(lambda: [('class:title', '  ' + title)]), height=1),
        editor,
        Window(FormattedTextControl(lambda: [('class:hint', '  ' + (hint[0] or normal_hint))]), wrap_lines=True,
               dont_extend_height=True),
    ])
    while True:
        answer = view.run(layout, focus=editor, bindings=keys, style=_STYLE, interval=.3)
        if not answer or save is None:
            return
        try:
            if view.owner:
                view.owner.require_foreground()
                if view.owner.cancelled.is_set():
                    raise KeyboardInterrupt
            save(answer[1])
            return
        except (OSError, OutputTargetError, ValueError) as error:
            discard[0] = False
            hint[0] = str(error) + '   Ctrl+S  Retry     Esc  Cancel'


def view_text(title: str, text: str) -> None:
    """Show supplied text in a read-only native view; Escape or Q returns."""
    _open_view(title, _normal(text))


def open_text_file(path: Path | str, *, title: str, read_only: bool = False) -> None:
    path = Path(path)
    if read_only:
        raw, truncated = _read(bind_output_target(path), tail=True)
        text = raw.decode('utf-8-sig', errors='replace')
        if truncated:
            text = '[Most recent 512 KiB; earlier history omitted]\n' + text
        view_text(f'{title} · {path.name}', text)
        return
    document = _TextFile.open(path)
    _open_view(f'{title} · {path.name}', document.text, document.save)
