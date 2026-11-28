"""Keep portable command coverage and published choice sets tied to the actual players."""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from mariana.account_services import OAUTH, PROVIDERS
from mariana.clips import FORMATS
from mariana.theme_palette import PRESETS, color_keys
from mariana.tones import CHORDS, WAVES

ROOT = Path(__file__).resolve().parents[1]
ROWS = json.loads((ROOT / "mariana/command_grammar_studio.json").read_text(encoding="utf-8"))["commands"]


def routes(surface):
    found = {}
    for row in ROWS:
        if row["surface"] not in ("both", surface):
            continue
        for name in [row["path"], *row.get("aliases", [])]:
            assert name not in found, f"Duplicate {surface} syntax: {name}"
            found[name] = row
    return found


def test_all_portable_dispatch_roots_have_completion_and_no_foreign_roots():
    code = (ROOT / "web/player/player.js").read_text(encoding="utf-8")
    begin = code.index("switch (cmd.toLowerCase())", code.index("async function command(text)"))
    dispatch = code[begin:].split("\n}", 1)[0]
    expected = set(re.findall(r"case '([^']+)':", dispatch))
    assert {name.split()[0] for name in routes("portable")} == expected


def test_theme_and_effect_choices_follow_the_runtime_registries():
    native, portable = routes("native"), routes("portable")
    assert set(native["clip export"]["flagValues"]["--format"]) == set(FORMATS)
    assert set(portable["clip export"]["flagValues"]["--format"]) == {"wav", "story", "video"}
    assert "--format" not in portable["clip share"].get("flags", [])
    for grammar in [native, portable]:
        assert set(grammar["tone harmony"]["flagValues"]["--chord"]) == set(CHORDS)
        assert set(grammar["tone sweep"]["flagValues"]["--wave"]) == set(WAVES)
        assert set(grammar["theme <preset>"]["values"]["preset"]) == set(PRESETS)
        assert set(grammar["accounts link <service>"]["values"]["service"]) == set(PROVIDERS)
        assert set(grammar["accounts connect <service>"]["values"]["service"]) == {*OAUTH, "lastfm"}
        assert "--curve" not in grammar["tone harmony"]["flags"]
        assert "--wave" not in grammar["tone sine"]["flags"]
    assert set(native["theme color <token>"]["values"]["token"]) == set().union(
        *(color_keys(theme).values() for theme in PRESETS)
    )


class PlaybackRates(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_rates = False
        self.rates = set()

    def handle_starttag(self, tag, attrs):
        if tag == "select":
            self.in_rates = dict(attrs).get("id") == "rate"

    def handle_endtag(self, tag):
        if tag == "select":
            self.in_rates = False

    def handle_data(self, data):
        if self.in_rates and data.strip():
            self.rates.add(data.strip())


def test_speed_choices_and_surface_specific_commands():
    native, portable = routes("native"), routes("portable")
    rates = PlaybackRates()
    rates.feed((ROOT / "web/player/index.html").read_text(encoding="utf-8"))
    assert set(portable["speed <rate>"]["values"]["rate"]) == rates.rates
    for name in ("speech jam", "dj record disk", "dj pfl <deck> <state>", "strudel queue", "voice", "accounts connect snapchat"):
        assert name in portable and name not in native
    for routes_by_name in (native, portable):
        assert "--yes" in routes_by_name["strudel delete"]["flags"]
    for name in ("dj mixxx", "web session", "tui", "artist follow", "fanroom vote"):
        assert name in native and name not in portable
    assert "dj play all" in native and "dj play all" not in portable
    assert native["dj cue <deck> set <slot>"]["values"]["slot"] == list("12345678")
    assert native["librivox queue <book> all"] == native["lv queue <book> all"]
    assert native["librivox previous"] == native["libri prev"]
    assert "librivox queue current" in native and "librivox queue current" not in portable
    assert "pod vendors" in native and ".pods vendors" not in native


def test_rows_only_publish_explicit_literals_and_scoped_flags():
    for row in ROWS:
        assert row["description"].strip()
        assert row["surface"] in ("both", "native", "portable")
        fields = set(re.findall(r"<([^> ]+)>", row["path"]))
        assert set(row.get("values", {})) <= fields
        assert set(row.get("flagValues", {})) <= set(row.get("flags", []))
        for values in (*row.get("values", {}).values(), *row.get("flagValues", {}).values()):
            assert isinstance(values, list) and len(set(values)) == len(values)
            assert all(isinstance(value, str) and value and not re.search(r"\s", value) for value in values)
