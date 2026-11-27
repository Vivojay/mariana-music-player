"""Cross-surface palette validation and keyboard interaction regressions."""

import threading
import unittest
from types import SimpleNamespace

from prompt_toolkit.input.defaults import create_pipe_input
from prompt_toolkit.output import DummyOutput

from mariana.terminal_player import player_lines, run_player
from mariana.theme_palette import COLOR, PRESETS, active_theme, change_theme, resolved_theme


class PaletteTests(unittest.TestCase):
    def test_all_presets_are_rgb_and_editable(self):
        self.assertEqual(len(PRESETS), 10)
        for name, base in PRESETS.items():
            for group in ("chrome", "terminal"):
                for key, color in base[group].items():
                    self.assertRegex(color, COLOR)
                    appearance = change_theme({"terminal theme": name}, ["color", f"{group}.{key}", "#10111299"])
                    self.assertEqual(resolved_theme(appearance)[group][key], "#10111299")
                    self.assertEqual(PRESETS[name][group][key], color)

    def test_saved_colors_are_scoped_to_the_preset(self):
        before = {"terminal theme": "winamp", "other": "keep"}
        customized = change_theme(before, ["color", "terminal.brightRed", "#aabbcc"])
        switched = change_theme(customized, ["redblood"])
        self.assertNotEqual(resolved_theme(switched)["terminal"]["brightRed"], "#aabbcc")
        self.assertEqual(resolved_theme(change_theme(switched, ["winamp"]))["terminal"]["brightRed"], "#aabbcc")
        reset = change_theme(customized, ["reset"])
        self.assertEqual(resolved_theme(reset), PRESETS["winamp"])
        self.assertEqual(before, {"terminal theme": "winamp", "other": "keep"})

    def test_malformed_input_and_preexisting_settings(self):
        self.assertEqual(active_theme({"terminal theme": []}), "aurora")
        for arguments in (["color", "chrome.accent", "red"], ["color", "bad", "#ffffff"], ["fake"]):
            with self.assertRaises(ValueError):
                change_theme({}, arguments)
        self.assertEqual(resolved_theme({"theme colors": {"aurora": {"chrome.accent": "garbage"}}}), PRESETS["aurora"])

    def test_player_handles_live_and_absent_metadata(self):
        state = SimpleNamespace(artist="", title="", queue_position=None, queue_count=0,
                                live=True, display_state="Playing", position_seconds=62, duration_seconds=None)
        output = "".join(line for _, line in player_lines(state, "Dracula"))
        self.assertIn("Nothing playing", output)
        self.assertIn("1:02 / Live", output)
        self.assertIn("Dracula", output)

    def test_player_runs_its_real_keyboard_loop(self):
        state = SimpleNamespace(artist="Artist", title="Title", queue_position=1, queue_count=2,
                                live=False, display_state="Playing", position_seconds=12, duration_seconds=90)
        actions = []
        with create_pipe_input() as pipe:
            def dispatch(command):
                actions.append(command)
                pipe.send_text("q")
            # Simulate one theme change; a timeout also closes the view if dispatch regresses.
            pipe.send_text("t")
            timeout = threading.Timer(3, lambda: pipe.send_text("q"))
            timeout.start()
            try:
                run_player(lambda: state, lambda: {"terminal theme": "redblood"}, dispatch,
                           input=pipe, output=DummyOutput())
            finally:
                timeout.cancel()
        self.assertEqual(actions, ["theme aurora"])
