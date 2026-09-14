import pytest

import main
from mariana.command_parser import CommandSyntaxError, split_command
from mariana.models import MediaRef, MediaSource


def test_command_parser_preserves_windows_paths_and_quoted_names():
    assert split_command('playlist create "Road Trip" --description "A long drive"') == [
        "playlist",
        "create",
        "Road Trip",
        "--description",
        "A long drive",
    ]
    assert split_command('playlist export "Road Trip" "C:\\Music Library\\lists\\trip.m3u8"')[-1] == (
        "C:\\Music Library\\lists\\trip.m3u8"
    )
    assert split_command('queue group create ""')[-1] == ""
    assert split_command('playlist create "Say ""Hello"""')[-1] == 'Say "Hello"'
    with pytest.raises(CommandSyntaxError, match="Missing closing"):
        split_command('playlist create "unfinished')


def test_matching_quote_delimiters_can_be_escaped():
    assert split_command(r'/ys "She said \"hello\""') == ["/ys", 'She said "hello"']
    assert split_command(r"find 'artist\'s live set'") == ["find", "artist's live set"]


def test_quotes_can_be_escaped_in_unquoted_search_terms():
    assert split_command(r"find don\'t stop") == ["find", "don't", "stop"]
    assert split_command(r'find say\"hello') == ["find", 'say"hello']


def test_opposite_quotes_and_adjacent_quoted_segments_form_one_argument():
    assert split_command('/ys "text with \'quote"') == ["/ys", "text with 'quote"]
    assert split_command("find 'text with double\" quote'") == [
        "find",
        'text with double" quote',
    ]
    assert split_command('find "one "\'two\'') == ["find", "one two"]


def test_find_matches_a_title_containing_literal_quotes(monkeypatch):
    title = 'The "Quoted" Song'
    printed = []
    media = MediaRef(MediaSource.LOCAL, "quoted.mp3", stable_id="quoted-id", title=title)
    monkeypatch.setattr(main, "_sound_files_names_enumerated", [(1, title)])
    monkeypatch.setattr(main, "_library_media", lambda _index: media)
    monkeypatch.setattr(main.PREFERENCES, "rating", lambda _media: 0)
    monkeypatch.setattr(main.PREFERENCES, "is_blocked", lambda _media: False)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))

    main.process(r'find "The \"Quoted\" Song"')

    assert any(title in value for value in printed)
