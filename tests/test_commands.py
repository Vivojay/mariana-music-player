from mariana.commands import (
    ALIAS_COMPATIBILITY,
    EXACT_ALIASES,
    TOKEN_ALIASES,
    SearchAction,
    SearchMode,
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


def test_search_rows_normalizes_unicode_punctuation_and_loose_matching():
    rows = [(1, "Café—Live 2022"), (2, "Quiet Studio"), (3, "Live Session")]
    assert search_rows(rows, parse_search(["find", "cafe", "live"])) == [rows[0]]
    assert search_rows(rows, parse_search(["lfind", "quiet", "session"])) == rows[1:]
    assert search_rows(rows, parse_search(["rfind", "live", "2022"])) == [rows[0]]
