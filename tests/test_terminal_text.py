import codecs
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from mariana import terminal_text as text_ui
from mariana.output_targets import OutputTargetError
from mariana.terminal_io import TerminalIO


@pytest.mark.parametrize('raw,edited,expected', [
    (codecs.BOM_UTF8 + b'a\r\nb\nc\r', 'a\nβ\nc\n', codecs.BOM_UTF8 + 'a\r\nβ\nc\r'.encode()),
    (b'a\r\nb', 'a\nb\n', b'a\r\nb\r\n'),
    (b'a\rb\r', 'a\nb', b'a\rb'),
    (b'a\nb', '1\na\nb', b'1\na\nb'),
])
def test_save_preserves_encoding_line_endings_and_existing_mode(tmp_path, raw, edited, expected):
    path = tmp_path / "Set [1] & Jay's 演出.lrc"
    path.write_bytes(raw)
    if os.name == 'posix':
        path.chmod(0o640)
    doc = text_ui._TextFile.open(path)
    before = path.stat()
    doc.save(doc.text)
    assert path.stat() == before
    doc.save(edited)
    assert path.read_bytes() == expected
    assert path.stat().st_mode == before.st_mode
    assert list(tmp_path.iterdir()) == [path]


def test_save_detects_an_external_edit_even_with_same_size_and_mtime(tmp_path):
    path = tmp_path / 'session.lrc'
    path.write_bytes(b'first')
    doc = text_ui._TextFile.open(path)
    before = path.stat()
    path.write_bytes(b'other')
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises((ValueError, OutputTargetError), match=r'edited elsewhere|changed'):
        doc.save('my draft')
    assert path.read_bytes() == b'other'
    assert list(tmp_path.iterdir()) == [path]


def test_refuses_link_redirect_before_save(tmp_path):
    approved = tmp_path / 'session.lrc'
    protected = tmp_path / 'other.lrc'
    approved.write_bytes(b'first')
    protected.write_bytes(b'other')
    doc = text_ui._TextFile.open(approved)
    approved.unlink()
    try:
        approved.symlink_to(protected)
    except OSError:
        pytest.skip('No symlink permission on this host')
    with pytest.raises((OSError, OutputTargetError, ValueError)):
        doc.save('draft')
    with pytest.raises(OutputTargetError):
        text_ui._TextFile.open(approved)
    assert protected.read_bytes() == b'other'


def test_editing_limits_and_read_only_history(tmp_path, monkeypatch):
    path = tmp_path / 'history.log'
    path.write_bytes(b'bad\xff')
    with pytest.raises(ValueError, match='UTF-8'):
        text_ui._TextFile.open(path)
    path.write_bytes(b'\0')
    with pytest.raises(ValueError, match='UTF-8'):
        text_ui._TextFile.open(path)
    path.write_bytes(b'HIDDEN' + b'\n' * (text_ui._MAX_BYTES - 4) + b'LAST')
    with pytest.raises(ValueError, match='512 KiB'):
        text_ui._TextFile.open(path)
    seen = []
    monkeypatch.setattr(text_ui, '_open_view', lambda title, body, save=None: seen.append((title, body, save)))
    text_ui.open_text_file(path, title='History', read_only=True)
    [(title, body, save)] = seen
    assert title == 'History · history.log' and save is None
    assert 'earlier history omitted' in body and 'HIDDEN' not in body and body.endswith('LAST')


def test_embedded_editor_save_cancel_and_conflicting_draft(tmp_path):
    path = tmp_path / 'band [2025].txt'
    path.write_bytes(b'original')
    changed = threading.Event()
    host = TerminalIO(changed.set, lambda _text: None)

    def open_doc():
        with host.worker():
            text_ui.open_text_file(path, title='Band')

    def dialog(previous=None):
        for _ in range(30):
            changed.clear()
            mounted = host.dialog
            if mounted is not None and mounted is not previous:
                return mounted
            changed.wait(.12)
        pytest.fail('Text editor did not open inside the active terminal')

    def press(view, key):
        [binding] = view.bindings.get_bindings_for_keys((key,))
        binding.handler(None)

    with ThreadPoolExecutor(max_workers=1) as workers:
        try:
            result = workers.submit(open_doc)
            view = dialog()
            view.focus.text = 'saved'
            press(view, 'c-s')
            result.result(timeout=3)
            assert path.read_bytes() == b'saved'

            result = workers.submit(open_doc)
            view = dialog()
            view.focus.text = 'my draft'
            path.write_bytes(b'from elsewhere')
            press(view, 'c-s')
            retry = dialog(view)
            assert retry.focus.text == 'my draft'
            press(retry, 'escape')
            assert host.dialog is retry
            press(retry, 'escape')
            result.result(timeout=3)
            assert path.read_bytes() == b'from elsewhere'

            def read():
                with host.worker():
                    text_ui.view_text('Lyrics', '歌\r\nline')
            result = workers.submit(read)
            view = dialog()
            assert view.focus.text == '歌\nline' and view.focus.buffer.read_only()
            press(view, 'q')
            result.result(timeout=3)
        finally:
            host.cancel()
