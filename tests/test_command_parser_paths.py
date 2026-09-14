"""Quoted path operands must not be reinterpreted as text escape sequences."""

import pytest

from mariana.command_parser import CommandSyntaxError, split_command


@pytest.mark.parametrize("path", [
    "\\",
    "C:\\",
    "C:\\Music\\",
    "C:\\Music Library\\",
    "C:relative\\",
    "\\\\server\\share\\",
    "\\\\?\\C:\\Music\\",
    ".\\Music\\",
    "..\\Music Library\\",
    "\\Music\\",
])
@pytest.mark.parametrize("quote", ['"', "'"])
def test_explicit_windows_path_keeps_its_final_separator(path, quote):
    assert split_command(f"open {quote}{path}{quote}") == ["open", path]


@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize("trailing", [" ", "\t\n"])
def test_terminal_drive_root_path_allows_trailing_whitespace(quote, trailing):
    assert split_command(f"open {quote}\\{quote}{trailing}") == ["open", "\\"]


def test_windows_paths_do_not_consume_following_options_or_quoted_arguments():
    assert split_command('transfer "C:\\Music\\" "D:\\New Library\\" --yes') == [
        "transfer", "C:\\Music\\", "D:\\New Library\\", "--yes",
    ]


def test_quote_rules_are_local_to_each_argument():
    assert split_command(r'open "C:\Music\" "say \"hello\""') == [
        "open", "C:\\Music\\", 'say "hello"',
    ]


def test_doubled_quotes_still_work_in_explicit_path_arguments():
    assert split_command("open 'C:\\Artist''s Music\\'") == ["open", "C:\\Artist's Music\\"]


@pytest.mark.parametrize(("command", "expected"), [
    (r'/ys "She said \"hello\""', ["/ys", 'She said "hello"']),
    (r"find 'artist\'s live set'", ["find", "artist's live set"]),
    (r'find "a \" quote in the middle"', ["find", 'a " quote in the middle']),
    (r"find don\'t stop", ["find", "don't", "stop"]),
    (r'find "\""', ["find", '"']),
    (r"find '\''", ["find", "'"]),
    (r'find "\" hello"', ["find", '" hello']),
    (r"find '\' hello'", ["find", "' hello"]),
    ('find ""', ["find", ""]),
])
def test_free_text_quoting_remains_supported(command, expected):
    assert split_command(command) == expected


@pytest.mark.parametrize("command", ['open "C:\\Music', "open '..\\Music", 'find "unfinished'])
def test_missing_path_or_text_delimiter_is_still_rejected(command):
    with pytest.raises(CommandSyntaxError, match="Missing closing"):
        split_command(command)
