"""The native command gate and process exit contract also apply inside the terminal workspace."""
import threading
from types import SimpleNamespace

import main
from mariana import terminal_player


def test_workspace_uses_the_live_parser_and_restores_outer_command_ownership(monkeypatch):
    busy = threading.Event()
    busy.set()  # mainprompt owns the command which opens the view.
    replay = threading.Event()
    restricted = []
    calls, messages = [], []
    monkeypatch.setattr(main, "COMMAND_BUSY", busy)
    monkeypatch.setattr(main, "_SESSION_REPLAY_ACTIVE", replay)
    monkeypatch.setattr(main, "FOCUS_MODE", SimpleNamespace(
        allows_command=lambda _tokens: not restricted, recovery_required=False,
    ))
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(main, "SAY", lambda **kw: messages.append(kw["display_message"]))
    monkeypatch.setattr(main, "IPrint", lambda msg, **_kw: messages.append(msg))

    def tone(args):
        assert busy.is_set()
        calls.append(args)
        return False  # Handler results other than a confirmed exit do not shut down the player.

    monkeypatch.setattr(main, "tone_command", tone)
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")

    def view(_project, _appearance, dispatch, *, is_visible, **_sources):
        assert not busy.is_set()
        assert dispatch("tui") is None
        assert "already open" in messages[-1]
        assert dispatch('tone sine 440 --label "Quiet room"') is None
        assert calls == [["sine", "440", "--label", "Quiet room"]]
        assert not busy.is_set()
        replay.set()
        assert not is_visible()
        assert dispatch("tone square") is None
        assert "Session replay" in messages[-1]
        replay.clear()
        restricted.append(True)
        assert not is_visible()
        assert dispatch("tone square") is None
        assert "Focus mode" in messages[-1]
        restricted.clear()
        assert is_visible()
        assert len(calls) == 1
        return dispatch("quit")

    monkeypatch.setattr(terminal_player, "run_player", view)
    assert main.process("tui") is False
    assert busy.is_set()
    assert not main._TUI_GATE.locked()


def test_text_routes_respect_embedded_workspace_and_configured_cli_editor(monkeypatch, tmp_path):
    from mariana import terminal_text
    from mariana.models import MediaRef, MediaSource
    from mariana.terminal_io import TerminalIO

    folder = tmp_path / "Jay's songs & [sets]"
    folder.mkdir()
    song = folder / '演出.mp3'
    sidecar = song.with_suffix('.lrc')
    library = folder / 'collection.txt'
    lyrics = folder / 'lyrics.txt'
    history = folder / 'history.log'
    for item in (song, sidecar, library, lyrics, history):
        item.write_bytes(b'test')
    media = MediaRef(MediaSource.LOCAL, str(song))
    monkeypatch.setattr(main, 'RUNTIME_PATHS', SimpleNamespace(library_file=library, logs=folder))
    monkeypatch.setattr(main, 'LYRICS_TEXT_PATH', lyrics)
    monkeypatch.setattr(main, '_preference_media', lambda entry: entry)
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: SimpleNamespace(media=media, state='paused'))
    monkeypatch.setattr(main, 'FOCUS_MODE', SimpleNamespace(allows_command=lambda _tokens: True))
    monkeypatch.setattr(main, '_SESSION_REPLAY_ACTIVE', threading.Event())
    monkeypatch.setattr(main, 'DEFAULT_EDITOR', 'configured editor')
    monkeypatch.setattr(main, 'IPrint', lambda *_args, **_kw: None)
    monkeypatch.setattr(main, 'visible', True)
    generated, external, internal = [], [], []
    monkeypatch.setattr(main, 'lyrics_ops', lambda **kw: generated.append(kw))
    monkeypatch.setattr(main.sp, 'Popen', lambda argv, **kw: external.append((argv, kw)))
    monkeypatch.setattr(terminal_text, 'open_text_file', lambda path, **kw: internal.append((path, kw)))
    routes = [('open lib', library, 'Library', False), ('open lyr', lyrics, 'Lyrics', False),
              ('open hist', history, 'Command history', True), ('lyrics edit', sidecar, 'Lyrics sidecar', False)]
    with TerminalIO(lambda: None, lambda _text: None).worker():
        for command, *_ in routes:
            main.process(command)
    assert external == []
    assert internal == [(path, {'title': title, 'read_only': read_only}) for _, path, title, read_only in routes]

    for command, *_ in routes:
        main.process(command)
    assert external == [(['configured editor', str(path)], {'shell': False}) for _, path, _, _ in routes]
    assert generated == [{'show_window': False}] * 2
