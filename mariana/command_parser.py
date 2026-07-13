"""Command tokenization that preserves quoted Windows paths."""

from __future__ import annotations


class CommandSyntaxError(ValueError):
    """Raised when an interactive command contains incomplete quoting."""


def split_command(command: str) -> list[str]:
    """Split a command without treating Windows backslashes as escapes.

    Single and double quotes group whitespace. Two adjacent matching quote
    characters inside a quoted value encode one literal quote character.
    """

    tokens: list[str] = []
    token: list[str] = []
    quote: str | None = None
    index = 0
    token_started = False
    while index < len(command):
        character = command[index]
        if quote:
            if character == quote:
                if index + 1 < len(command) and command[index + 1] == quote:
                    token.append(character)
                    index += 2
                    continue
                quote = None
            else:
                token.append(character)
            token_started = True
        elif character in {'"', "'"}:
            quote = character
            token_started = True
        elif character.isspace():
            if token_started:
                tokens.append("".join(token))
                token = []
                token_started = False
        else:
            token.append(character)
            token_started = True
        index += 1
    if quote:
        raise CommandSyntaxError(f"Missing closing {quote} quote")
    if token_started:
        tokens.append("".join(token))
    return tokens
