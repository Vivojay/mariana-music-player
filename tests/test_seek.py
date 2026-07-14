import pytest

from mariana.seek import SeekSyntaxError, format_seek_position, parse_seek_target


@pytest.mark.parametrize(
    ("arguments", "position", "duration", "expected"),
    [
        (["90"], 20, 200, 90),
        (["+30"], 20, 200, 50),
        (["-30"], 20, 200, 0),
        ([":30"], 20, 200, 30),
        (["01:20"], 20, 200, 80),
        (["01:20:30"], 20, 10_000, 4_830),
        (["1:02:03:04"], 20, 100_000, 93_784),
        (["1d", "2h", "3m", "4s"], 20, 100_000, 93_784),
        (["+30s"], 20, 200, 50),
        (["-2m"], 200, 500, 80),
        (["+1h"], 100, 5_000, 3_700),
        (["50%"], 20, 200, 100),
        (["start"], 20, 200, 0),
    ],
)
def test_parse_seek_target_supports_human_friendly_forms(arguments, position, duration, expected):
    assert parse_seek_target(arguments, position=position, duration=duration).seconds == expected


def test_seek_end_and_relative_overflow_stop_before_exact_eof():
    expected = 199.75
    assert parse_seek_target(["end"], position=20, duration=200).seconds == expected
    assert parse_seek_target(["+1h"], position=20, duration=200).seconds == expected
    assert parse_seek_target(["200"], position=20, duration=200).seconds == expected
    assert parse_seek_target(["100%"], position=20, duration=200).seconds == expected


def test_relative_seek_clamps_at_start():
    assert parse_seek_target(["-2m"], position=20, duration=200).seconds == 0


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        [""],
        ["later"],
        ["1.5"],
        ["101%"],
        ["-1%"],
        ["2m", "1h"],
        ["1h", "2h"],
        ["1d", "bad"],
        ["1:two"],
        ["1:2:3:4:5"],
        ["201"],
    ],
)
def test_parse_seek_target_rejects_ambiguous_or_unsafe_values(arguments):
    with pytest.raises(SeekSyntaxError):
        parse_seek_target(arguments, position=20, duration=200)


def test_duration_dependent_seek_forms_require_a_known_duration():
    with pytest.raises(SeekSyntaxError):
        parse_seek_target(["50%"], position=20)
    with pytest.raises(SeekSyntaxError):
        parse_seek_target(["end"], position=20)


def test_seek_position_display_handles_four_field_targets():
    assert format_seek_position(93_784) == "1d 02:03:04"
