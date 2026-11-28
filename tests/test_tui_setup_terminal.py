"""Exercise direct bootstrap through real prompt_toolkit renderers and input bytes."""
from __future__ import annotations

import asyncio
import io
import threading
from collections import deque
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import Application, create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output.vt100 import Vt100_Output

from mariana import setup_terminal

ENTER = "\x1b[?1049h"
LEAVE = "\x1b[?1049l"


@contextmanager
def terminal(monkeypatch, answers):
    """Send each key sequence only when its question appears in a rendered frame."""
    from mariana import terminal_player

    pending = deque(answers)
    frames = []
    data = io.StringIO()
    output = Vt100_Output(data, lambda: Size(rows=30, columns=108), enable_cpr=False)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=output):
        class Observed(Application):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.after_render += self.inspect_frame
                self.guarded = False

            def inspect_frame(self, _app):
                screen = self.renderer.last_rendered_screen
                if self.is_done or screen is None:
                    return
                if not self.guarded:
                    self.guarded = True
                    def timeout():
                        if not self.is_done:
                            self.exit(exception=AssertionError(f"Missing prompt: {list(pending)!r}"))
                    asyncio.get_running_loop().call_later(7, timeout)
                frame = "\n".join("".join(row[x].char for x in range(108)).rstrip()
                                  for row in (screen.data_buffer[y] for y in range(30)))
                frames.append(frame)
                if pending and pending[0][0] in frame:
                    pipe.send_text(pending.popleft()[1])

        monkeypatch.setattr(setup_terminal, "Application", Observed)
        monkeypatch.setattr(terminal_player, "Application", Observed)
        with setup_terminal.direct_screen():
            yield data, frames
    assert not pending
    assert data.getvalue().count(ENTER) == data.getvalue().count(LEAVE) == 1


def test_output_keeps_concrete_type_for_native_mouse_dispatch():
    from prompt_toolkit.output import DummyOutput

    output = DummyOutput()
    proxy = setup_terminal._SharedScreen(output)
    assert isinstance(proxy, type(output))
    assert proxy.fileno == output.fileno


def test_first_boot_questions_and_player_share_one_screen(monkeypatch, tmp_path):
    import first_boot_setup
    from mariana import terminal_player
    from mariana.paths import RuntimePaths
    from mariana.setup import SetupStateStore

    paths = RuntimePaths(tmp_path, tmp_path)
    store = SetupStateStore(paths)
    store.reset()
    threads = []
    def tools(**_kwargs):
        threads.append(threading.get_ident())
        print("Checking media tools.")
    monkeypatch.setattr(first_boot_setup, "runtime_paths", lambda: paths)
    monkeypatch.setattr(first_boot_setup, "setup_media_tools", tools)
    selections = [("locally stored", "n\r"), ("signature collection", "n\r"),
                  ("run Mariana Player now", "y\r"), ("Soundcheck", "q")]
    with terminal(monkeypatch, selections) as (data, frames):
        assert setup_terminal.run_setup("Set up Mariana", lambda: first_boot_setup.fbs(
            {"ver": {"maj": 0, "min": 7, "rel": 0}}, store), {}) is False
        assert store.load().status == "complete"
        assert len(threads) == 1 and threads[0] != threading.get_ident()
        assert any("Checking media tools" in frame and "Yes" in frame for frame in frames)
        assert LEAVE not in data.getvalue()
        track = SimpleNamespace(title="Soundcheck", artist="Example", display_state="Paused", live=False,
                                queue_position=None, queue_count=0, duration_seconds=60, position_seconds=0)
        assert terminal_player.run_player(lambda: track, dict, lambda _command: None) is None
        assert LEAVE not in data.getvalue()


def test_early_cancel_retains_first_boot_progress(monkeypatch, tmp_path):
    import first_boot_setup
    from mariana.paths import RuntimePaths
    from mariana.setup import SetupStateStore

    paths = RuntimePaths(tmp_path, tmp_path)
    store = SetupStateStore(paths)
    store.reset()
    monkeypatch.setattr(first_boot_setup, "runtime_paths", lambda: paths)
    monkeypatch.setattr(first_boot_setup, "setup_media_tools", lambda **_kwargs: None)
    with terminal(monkeypatch, [("locally stored", "\x03")]), pytest.raises(KeyboardInterrupt):
        setup_terminal.run_setup("Set up Mariana", lambda: first_boot_setup.fbs(
            {"ver": {"maj": 0, "min": 7, "rel": 0}}, store), {})
    state = store.load()
    assert state.status == "in_progress" and state.current_step == "library"
    assert state.completed_steps == ["tools"] and not paths.setup_lock.exists()


def test_error_stays_visible_until_acknowledged(monkeypatch):
    def wizard():
        raise OSError("Unable to open the selected directory")

    with terminal(monkeypatch, [("Press Enter to close setup", "\r")]) as (_, frames):
        with pytest.raises(SystemExit) as error:
            setup_terminal.run_setup("Set up Mariana", wizard, {})
        assert error.value.code == 1
        assert any("Unable to open the selected directory" in frame for frame in frames)


@pytest.mark.parametrize("answer", ["n", ""])
def test_media_tool_offer_and_audio_refresh_thread(monkeypatch, answer):
    import main

    states = {}
    actions = []
    current = threading.get_ident()
    missing = SimpleNamespace(complete=False, missing_required=(), missing_optional=("rsgain",))
    complete = SimpleNamespace(complete=True)
    probes = iter([missing, complete])
    monkeypatch.delenv("MARIANA_E2E", raising=False)
    monkeypatch.setattr(main, "_START_IN_TUI", True)
    monkeypatch.setattr(main, "discover_media_tools", lambda _settings: next(probes))
    monkeypatch.setattr(main, "find_javascript_runtime", lambda *_args: "deno")
    monkeypatch.setattr(main, "DATABASE", SimpleNamespace(get_state=states.get, set_state=states.__setitem__))
    def record(name):
        actions.append((name, threading.get_ident()))
    monkeypatch.setattr(main, "TOOLCHAIN", SimpleNamespace(install_missing=lambda names, **_kwargs: record("install") or {name: name for name in names}))
    monkeypatch.setattr(main, "persist_media_tools", lambda *_args, **_kwargs: record("save"))
    monkeypatch.setattr(main, "refresh_runtime_configuration", lambda **_kwargs: record("refresh"))
    monkeypatch.setattr(main, "IPrint", lambda message, **_kwargs: print(message))
    with terminal(monkeypatch, [("Automatically download", answer + "\r")]):
        status = main.ensure_managed_tool_migration()
    assert states.get("managed_tool_prompt_version")
    if answer == "n":
        assert status is missing and not actions
    else:
        assert status is complete
        assert [name for name, _ in actions] == ["install", "save", "refresh"]
        assert actions[0][1] == actions[1][1] != current
        assert actions[2][1] == current


def test_cli_uses_existing_input_on_main_thread(monkeypatch):
    import main

    monkeypatch.setattr(main, "_START_IN_TUI", False)
    monkeypatch.setattr("builtins.input", lambda _question: "manual")
    assert main._startup_questions("Tools", lambda: (input("How? "), threading.get_ident())) == (
        "manual", threading.get_ident())
