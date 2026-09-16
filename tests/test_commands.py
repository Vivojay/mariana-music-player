import pytest

from mariana.commands import (
    ALIAS_COMPATIBILITY,
    EXACT_ALIASES,
    TOKEN_ALIASES,
    SearchAction,
    SearchMode,
    SearchScope,
    is_search_command,
    normalize_command,
    parse_search,
    search_rows,
)


def test_legacy_aliases_normalize_without_changing_arguments():
    assert normalize_command(".") == "now"
    assert normalize_command(".*") == "now*"
    assert normalize_command("+ 2") == "next 2"
    assert normalize_command(".-") == ".prev"
    assert normalize_command("mute") == "m"
    assert normalize_command("DL-YV https://example.test/a") == "download-yv https://example.test/a"
    assert normalize_command("DL-ML https://example.test/a") == "download-ml https://example.test/a"
    assert normalize_command('/ysq "artist title" 5') == 'queue ys "artist title" 5'
    assert normalize_command("/rpan 2") == "/rs 2"
    assert normalize_command(". C:/Music/a song.mp3") == ". C:/Music/a song.mp3"


def test_alias_registry_is_the_dispatch_source_of_truth():
    assert ALIAS_COMPATIBILITY
    for entry in ALIAS_COMPATIBILITY:
        for alias in entry.aliases:
            if entry.scope in {"exact", "both"}:
                assert EXACT_ALIASES[alias] == entry.canonical
            if entry.scope in {"token", "both"}:
                assert TOKEN_ALIASES[alias] == entry.canonical
            assert entry.status in {"native", "compatibility-only", "retired"}


def test_search_parser_preserves_raw_numbers_and_prefix_actions():
    normal = parse_search(["find", "mix", "2"])
    assert normal.limit == 2 and normal.query == ("mix",)
    raw = parse_search(["rfind", "mix", "2"])
    assert raw.mode == SearchMode.RAW and raw.limit is None and raw.query == ("mix", "2")
    assert parse_search([".lf", "cafe"]).action == SearchAction.FIRST
    assert parse_search(["/find", "song"]).action == SearchAction.RANDOM


def test_indexed_immediate_search_is_one_based_and_limits_collection():
    indexed = parse_search([".f3", "live"])
    assert indexed.action == SearchAction.INDEXED
    assert indexed.query == ("live",)
    assert indexed.limit == 3
    assert indexed.result_index == 3
    assert parse_search([".find2", "mix"]).result_index == 2
    assert parse_search([".rf2", "mix", "2022"]).mode == SearchMode.RAW
    assert parse_search([".lf2", "quiet", "session"]).mode == SearchMode.LOOSE
    assert is_search_command(".F3")
    with pytest.raises(ValueError, match="1 or greater"):
        parse_search([".f0", "live"])


def test_search_rows_normalizes_unicode_punctuation_and_loose_matching():
    rows = [(1, "Café—Live 2022"), (2, "Quiet Studio"), (3, "Live Session")]
    assert search_rows(rows, parse_search(["find", "cafe", "live"])) == [rows[0]]
    assert search_rows(rows, parse_search(["lfind", "quiet", "session"])) == rows[1:]
    assert search_rows(rows, parse_search(["rfind", "live", "2022"])) == [rows[0]]


def test_find_regex_matches_display_text_case_insensitively_and_preserves_limits():
    rows = [(1, "Alpha - Live"), (2, "Beta - Studio"), (3, "Gamma - LIVE")]
    request = parse_search(["find", "--regex", r"^(alpha|gamma) - live$", "1"])

    assert request.mode == SearchMode.REGEX
    assert request.query == (r"^(alpha|gamma) - live$",)
    assert request.limit == 1
    assert search_rows(rows, request) == [rows[0]]


def test_find_regex_supports_scopes_and_indexed_immediate_selection():
    request = parse_search([".f2", "--in", "favs", "--re", r"^live (one|two)$"])

    assert request.mode == SearchMode.REGEX
    assert request.scope == SearchScope.FAVORITES
    assert request.action == SearchAction.INDEXED
    assert request.result_index == 2
    assert request.query == (r"^live (one|two)$",)


@pytest.mark.parametrize(
    ("tokens", "message"),
    [
        (["find", "--regex", "["], "Invalid find regular expression"),
        (["find", "--regex", ""], "must not be empty"),
        (["find", "--regex", "a" * 513], "512 characters or fewer"),
        (["find", "--regex", "--re", "live"], "only one --regex"),
    ],
)
def test_find_regex_rejects_invalid_patterns(tokens, message):
    with pytest.raises(ValueError, match=message):
        parse_search(tokens)


def test_search_parser_accepts_explicit_collection_scopes_without_changing_the_query():
    favorites = parse_search(["find", "--in", "favs", "quiet", "2"])
    assert favorites.scope == SearchScope.FAVORITES
    assert favorites.query == ("quiet",)
    assert favorites.limit == 2

    playlist = parse_search([".f3", "live", "--in", "playlist", "Night Drive"])
    assert playlist.scope == SearchScope.PLAYLIST
    assert playlist.scope_name == "Night Drive"
    assert playlist.query == ("live",)
    assert playlist.result_index == 3

    assert parse_search(["find", "mix", "--in", "blacklist"]).scope == SearchScope.BLOCKED
    assert parse_search(["find", "mix", "--in", "queue"]).scope == SearchScope.QUEUE
    assert parse_search(["find", "mix", "--in", "lib"]).scope == SearchScope.LIBRARY


@pytest.mark.parametrize(
    ("tokens", "message"),
    [
        (["find", "mix", "--in"], "requires"),
        (["find", "mix", "--in", "unknown"], "Unknown search scope"),
        (["find", "mix", "--in", "playlist"], "playlist name"),
        (["find", "mix", "--in", "queue", "--in", "favs"], "only one"),
    ],
)
def test_search_parser_rejects_invalid_collection_scopes(tokens, message):
    with pytest.raises(ValueError, match=message):
        parse_search(tokens)
