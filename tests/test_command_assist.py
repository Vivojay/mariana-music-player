import itertools

import pytest

from mariana.command_assist import command_corrections, command_suggestions
from mariana.command_parser import command_tokens, split_command


def options(line, *, surface="native", cursor=None, provider=None):
    return {edit.label: edit for edit in command_suggestions(
        line, len(line) if cursor is None else cursor, limit=30, surface=surface, value_provider=provider
    )}


@pytest.mark.parametrize(("line", "expected"), [
    ("donwload", "download"),
    ("downlaod", "download"),
    ("lv serach 葉子", "lv search 葉子"),
    ('artist   searhc "O’Connor"   --keep', 'artist   search "O’Connor"   --keep'),
    ("dj cue A ge 2", "dj cue A go 2"),
    ("region 33 strat 4", "region 33 start 4"),
    ("stems mix dums", "stems mix drums"),
    ("tone sweep 20 400 --waev sine", "tone sweep 20 400 --wave sine"),
    ("tone harmony 220 --chrod=major", "tone harmony 220 --chord=major"),
    ("tone harmony 220 --chord=majro", "tone harmony 220 --chord=major"),
    ("hotspots claer --yes", "hotspots clear --yes"),
])
def test_correct_only_the_syntax_token(line, expected):
    edits = command_corrections(line)
    assert edits and edits[0].kind == "correction"
    assert edits[0].apply(line)[0] == expected


@pytest.mark.parametrize("line", [
    'artist search "serch"',
    'playlist create dewlete',
    'playlist delete "cleer"',
    'session record llist',
    "find --regex stpo",
    ".find22 refrseh --in favorites",
    "accounts link instagram suppperstar",
    "hotspots clear --yea",
    "dj load A C:\\Private\\suggahunny.wav",
    "strudel delete Project y",
    ".+11",
    ".42",
    "speech speaker Jay",
    'http://test.invalid/play?access_token=serch',
])
def test_corrections_leave_valid_operands_legacy_forms_and_confirmation_alone(line):
    assert command_corrections(line) == ()


def test_quoted_value_span_retains_existing_suffix_and_spelling():
    value = r"D:\C DOWNLOADS\嬉しい 🌑 Story.wav"
    line = r'dj load A "D:\C DOWN old.wav" --existing'
    cursor = line.index("DOWN") + 4
    calls = []

    def provider(kind, prefix, words):
        calls.append((kind, prefix, words))
        return [value] if kind == "file-or-library-index" else []

    selected = options(line, cursor=cursor, provider=provider)[value]
    updated, caret = selected.apply(line)
    assert split_command(updated) == ["dj", "load", "A", value, "--existing"]
    assert updated[caret:] == " --existing"
    assert selected.start == line.index('"') and line[selected.end:] == " --existing"
    assert ("file-or-library-index", r"D:\C DOWN", ("dj", "load", "A")) in calls


def test_quote_escape_roundtrips_private_paths_and_titles_before_following_tokens():
    # Native Windows paths keep literal backslashes, including final separators.
    # Unix titles may legally combine both quotation marks with backslashes.
    values = [r"D:\C DOWNLOADS" + "\\", "Rehearsal 'III' 🎙.wav", 'two \\" sets', 'literal\\']
    values.extend("".join(parts) for parts in itertools.product(("x", " ", "'", '"', "\\"), repeat=3))
    for value in values:
        line = 'dj load A "" --next'
        suggestion = options(line, cursor=line.index('""') + 1, provider=lambda *_, choice=value: [choice])[value]
        result, _ = suggestion.apply(line)
        assert split_command(result) == ["dj", "load", "A", value, "--next"]


@pytest.mark.parametrize(("line", "expected"), [
    ("lv sea", {"search"}),
    ("dj cue a ", {"go", "set"}),
    ("dj cue b set ", set("12345678")),
    (".find22 P!nk --in f", {"favorites"}),
    ("tone sweep 20 200 --wave s", {"sine", "square", "sawtooth"}),
    ("eq deesser ba", {"balanced"}),
    ("lv open current a", {"archive"}),
])
def test_arguments_and_flags_are_scoped_to_the_resolved_route(line, expected):
    assert expected <= options(line).keys()


def test_surface_and_flag_value_boundaries():
    assert "mp4" in options("clip export --format ")
    assert "mp4" not in options("clip export --format ", surface="portable")
    assert "mixxx" in options("dj mix")
    assert "mixxx" not in options("dj mix", surface="portable")
    line = "tone harmony 220 --chord=ma --level 25"
    value = options(line, cursor=line.index("=ma") + 3)["major"]
    assert value.apply(line)[0] == "tone harmony 220 --chord=major --level 25"
    assert "--chord" not in options("tone harmony 220 --chord=major --")
    assert "--yes" not in options("hotspots clear --")
    assert options("hotspots clear --ye")["--yes"].kind == "flag"
    assert "--yes" not in options("artist search --ye")
    assert "y" not in options("strudel delete Project ")


def test_mid_command_edits_and_an_earlier_misspelling_retain_bytes():
    line = "  dj  cua A set 2"
    choice = options(line, cursor=line.index("cua") + 2)["cue"]
    assert choice.apply(line) == ("  dj  cue A set 2", len("  dj  cue"))
    earlier = options('artist serch "Jay Kay"')["search"]
    assert earlier.apply('artist serch "Jay Kay"') == ('artist search "Jay Kay"', len("artist search"))


def test_span_tokenizer_keeps_whitespace_and_quoted_windows_paths():
    line = r"""  DJ  load B  'C:\An artist\'   """
    parts = command_tokens(line)
    assert [part.value for part in parts] == split_command(line)
    last = parts[-1]
    assert last.quoted and line[last.start:last.end] == r"'C:\An artist\'"
    partial = command_tokens('play "recording name', partial=True)[-1]
    assert partial.value == 'recording name' and partial.quoted


def test_engine_is_bounded_and_static_utf8_edits_use_python_offsets():
    line = "dj cue A ge 2"
    for cursor in (-1, len(line) + 1):
        assert not command_suggestions(line, cursor)
    assert not command_corrections("x" * 4097)
    assert not command_suggestions("a\nb", 0)
    assert not command_suggestions(" ".join(["x"] * 129), 0)
    assert not command_suggestions(line, 2, limit=31)
    assert not command_suggestions(line, 2, surface="unknown")



def test_valid_help_prefixes_win_over_fuzzy_suggestions():
    assert not command_corrections("help playb")
    assert not command_corrections("help online")
    assert command_corrections("help palyback")[0].apply("help palyback")[0].casefold() == "help playback"
    assert "playback" in {word.lower() for word in options("help playb")}


def test_emoji_joiners_are_preserved_on_both_sides_of_an_edit():
    line = "lv search 👩‍🎤 --limti 2"
    edit = command_corrections(line)[0]
    assert edit.apply(line)[0] == "lv search 👩‍🎤 --limit 2"
