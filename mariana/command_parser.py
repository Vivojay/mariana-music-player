"""Command tokenization that preserves quoted Windows paths."""

from __future__ import annotations

from dataclasses import dataclass


class CommandSyntaxError(ValueError):
    """Raised when an interactive command contains incomplete quoting."""


def _windows_path_prefix(command: str, start: int) -> bool:
    """Recognize explicit path syntax without inspecting the filesystem."""
    prefix = command[start:start + 3]
    # A terminal quoted root cannot be escaped-quote text: that would need
    # another closing delimiter. Do not guess when more operands follow.
    if prefix[:2] == "\\" + command[start - 1] and not command[start + 2:].strip():
        return True
    return (
        (len(prefix) >= 2 and prefix[0].isascii() and prefix[0].isalpha() and prefix[1] == ":")
        or prefix.startswith((".\\", "..\\"))
        or (prefix.startswith("\\") and len(prefix) >= 2 and prefix[1] not in {'"', "'"})
    )


@dataclass(frozen=True, slots=True)
class CommandToken:
    value: str
    start: int
    end: int
    quoted: bool


def command_tokens(command: str, *, partial: bool = False) -> list[CommandToken]:
    """Tokenize once for dispatch and editing, preserving exact source spans."""
    tokens: list[CommandToken] = []
    start = 0
    quoted = False
    token: list[str] = []
    quote: str | None = None
    path_quotes = False
    index = 0
    token_started = False
    while index < len(command):
        character = command[index]
        if not token_started:
            start = index
        if quote:
            if (
                not path_quotes
                and character == "\\"
                and index + 1 < len(command)
                and command[index + 1] == quote
            ):
                token.append(quote)
                token_started = True
                index += 2
                continue
            if character == quote:
                if index + 1 < len(command) and command[index + 1] == quote:
                    token.append(character)
                    index += 2
                    continue
                quote = None
            else:
                token.append(character)
            token_started = True
        elif (
            character == "\\"
            and index + 1 < len(command)
            and command[index + 1] in {'"', "'"}
        ):
            token.append(command[index + 1])
            token_started = True
            index += 2
            continue
        elif character in {'"', "'"}:
            quoted = True
            quote = character
            path_quotes = _windows_path_prefix(command, index + 1)
            token_started = True
        elif character.isspace():
            if token_started:
                tokens.append(CommandToken("".join(token), start, index, quoted))
                quoted = False
                token = []
                token_started = False
        else:
            token.append(character)
            token_started = True
        index += 1
    if quote and not partial:
        raise CommandSyntaxError(f"Missing closing {quote} quote")
    if token_started:
        tokens.append(CommandToken("".join(token), start, index, quoted))
    return tokens


def split_command(command: str) -> list[str]:
    """Split a command without treating Windows backslashes as escapes.

    Single and double quotes group whitespace. Two adjacent matching quote
    characters inside a quoted value encode one literal quote character. A
    backslash escapes a quote outside quoted text, or only the active quote
    delimiter inside it. Explicit quoted Windows paths (drive, rooted/UNC,
    .\\ or ..\\ prefixes) keep every backslash literal, including the final
    separator before their closing quote. Use doubled delimiters for a literal
    quote in those path operands. Other quoted text retains quote escaping.
    A root-only backslash operand is recognized when it ends the command,
    apart from trailing whitespace, to avoid ambiguous free-text escapes.
    """
    return [token.value for token in command_tokens(command)]
