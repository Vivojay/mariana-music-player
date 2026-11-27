"""Check direct and nested terminal launch, ownership and policy changes."""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "main.py"


@pytest.mark.parametrize("arg", ["--tui", "tui"])
def test_direct_view_requires_a_terminal_before_boot(tmp_path, arg):
    result = subprocess.run([sys.executable, str(SCRIPT), arg], cwd=tmp_path, stdin=subprocess.DEVNULL,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2
    assert "needs an interactive terminal" in result.stderr
    assert result.stdout == ""


def test_launcher_help_is_available_before_audio_setup(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0
    assert "--tui" in result.stdout


@pytest.mark.parametrize("direct", [True, False])
def test_direct_launch_owns_the_terminal_until_shutdown(monkeypatch, direct):
    import main
    from mariana import command_prompt

    events = []
    monkeypatch.setattr(main, "_START_IN_TUI", direct)
    monkeypatch.setattr(main, "visible", True)
    monkeypatch.setattr(main, "prompt_text", lambda: "")
    monkeypatch.setattr(command_prompt, "read_command", lambda _prompt, **_options: events.append("prompt") or "quit")

    def process(command):
        assert main.COMMAND_BUSY.is_set()
        events.append(command)
        return False

    def tui(arguments, *, direct):
        assert main.COMMAND_BUSY.is_set() and direct
        assert arguments == []
        events.append("fullscreen")
        return False

    monkeypatch.setattr(main, "process", process)
    monkeypatch.setattr(main, "tui_command", tui)
    monkeypatch.setattr(main, "exitplayer", lambda: events.append("shutdown"))
    main.mainprompt()
    assert events == (["fullscreen", "shutdown"] if direct else ["prompt", "quit", "shutdown"])
    assert not main.COMMAND_BUSY.is_set()


def test_direct_launch_supplies_one_application_with_full_and_recovery_views(monkeypatch):
    import main
    from mariana import terminal_player

    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(main.sys.stdout, "isatty", lambda: True)
    mode = ["hidden"]
    monkeypatch.setattr(main, "_tui_restriction", lambda: mode[0])
    monkeypatch.setattr(main, "visible", True)
    starts = []

    def view(project, appearance, dispatch, *, direct, is_visible, recovery_view, **kwargs):
        starts.append(1)
        assert direct and not is_visible()
        assert callable(project) and callable(kwargs["library_rows"])
        screen = recovery_view(lambda _cmd: None)
        for restriction in ["hidden", None, "focus", "recovery", "replay", None]:
            mode[0] = restriction
            assert is_visible() == (restriction is None)
            screen.refresh()
            assert screen.controls[-1][1] == "exit"
            if restriction == "replay":
                assert ("Stop replay", "session stop") in screen.controls
        return False

    monkeypatch.setattr(terminal_player, "run_player", view)
    assert main.tui_command([], direct=True) is False
    assert starts == [1] and not main._TUI_GATE.locked()


def test_redacted_recovery_view_uses_only_rescue_actions_and_respects_hidden_output():
    from mariana.terminal_recovery import TerminalRecoveryWorkspace

    visible = [False]
    view = TerminalRecoveryWorkspace(lambda: "hidden", lambda _: None, lambda: visible[0])
    assert view.controls == (("Show the player", "vis"), ("Exit Mariana", "exit"))
    view.set_activity("vis", "private entry")
    assert "private entry" not in str(view._lines())
    visible[0] = True
    view.set_activity("play 1", "unrelated private entry")
    assert not view.message
    view.set_activity("vis", "Restored")
    assert "Restored" in str(view._lines())
    visible[0] = False
    assert "Restored" not in str(view._lines())


def test_direct_terminal_unlocks_without_reentering_the_alternate_screen(monkeypatch):
    import threading
    from types import SimpleNamespace

    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from mariana.terminal_workspace import TerminalWorkspace
    from mariana.terminal_player import run_player
    from mariana.terminal_recovery import TerminalRecoveryWorkspace

    class Display(DummyOutput):
        entered = left = 0

        def enter_alternate_screen(self):
            self.entered += 1

        def quit_alternate_screen(self):
            self.left += 1

    display = Display()
    restricted = threading.Event()
    restricted.set()
    unlocked = threading.Event()
    commands = []
    marker = "Recovered statistics backup /private-test-location"
    presentations = []
    def observe(view_type):
        original = view_type.set_activity
        def activity(view, command, body):
            if marker in body:
                presentations.append((view_type, restricted.is_set()))
            return original(view, command, body)
        monkeypatch.setattr(view_type, "set_activity", activity)
    observe(TerminalWorkspace)
    observe(TerminalRecoveryWorkspace)

    def project():
        assert not restricted.is_set()
        unlocked.set()
        return SimpleNamespace(title="Visible track", artist="", display_state="Paused",
                               queue_position=None, queue_count=0, live=False,
                               duration_seconds=30, position_seconds=2)

    with create_pipe_input() as pipe:
        def dispatch(command):
            commands.append(command)
            if command == "vis":
                restricted.clear()
            elif command == "quit":
                return False

        def keys():
            pipe.send_text("\r")
            if unlocked.wait(4):
                pipe.send_text("q")
            else:
                pipe.close()

        worker = threading.Thread(target=keys)
        worker.start()
        try:
            assert run_player(
                project, lambda: {}, dispatch, input=pipe, output=display, direct=True,
                startup_notices=(marker,), is_visible=lambda: not restricted.is_set(),
                recovery_view=lambda play: TerminalRecoveryWorkspace(lambda: "hidden", play, lambda: False),
            ) is False
        finally:
            worker.join(timeout=5)

    assert presentations == [(TerminalWorkspace, False)]
    assert commands == ["vis", "quit"]
    assert (display.entered, display.left) == (1, 1)

def test_recoverable_boot_notices_keep_ordinary_cli_and_defer_direct_output(monkeypatch, capsys):
    import main

    capsys.readouterr()
    monkeypatch.setattr(main, "_STARTUP_NOTICES", [])
    monkeypatch.setattr(main, "_START_IN_TUI", False)
    main._boot_notice("Lyrics unavailable", "Info", "Skipped")
    assert capsys.readouterr().out == "Info\nSkipped\n"
    assert main._STARTUP_NOTICES == []
    monkeypatch.setattr(main, "_START_IN_TUI", True)
    main._boot_notice("Lyrics unavailable", "Info", "Skipped")
    main._boot_notice("Recovered statistics at P")
    assert capsys.readouterr().out == ""
    assert main._STARTUP_NOTICES == ["Lyrics unavailable", "Recovered statistics at P"]
