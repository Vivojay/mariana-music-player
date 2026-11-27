from mariana.web_console_style import styled_console_output


def test_ansi_projection_retains_only_bounded_sgr():
    text = (
        "ready\r\n\x1b[1;32mplay\x1b[m\x9b38;5;43mnext\x1b[0m\x1b[2J"
        "\x1b[=12m\x1b[" + "1" * 100 + "m"
    )
    assert styled_console_output(text) == "ready\n\x1b[1;32mplay\x1b[m\x1b[38;5;43mnext\x1b[0m"


def test_ansi_projection_drops_device_hyperlink_and_unterminated_control_payloads():
    text = (
        "start\x1b]8;;https://example.invalid/private\x07link text\x1b]8;;\x1b\\"
        "\x1bPhidden DCS\x1b\\\x9d0;sensitive title\x9c\x00\tend\x1b]0;unfinished title"
    )
    assert styled_console_output(text) == "startlink text\tend"
    assert styled_console_output("before\x1b[1;") == "before"
    assert styled_console_output("x" * 40000) == "x" * 32000
