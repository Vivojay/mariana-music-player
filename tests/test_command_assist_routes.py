"""Every registered literal spelling should be reachable without an invented repair."""
import pytest

from mariana.command_assist import _grammar, command_corrections, command_suggestions


@pytest.mark.parametrize("surface", ["native", "portable"])
def test_exact_routes_and_aliases_are_reachable_without_a_correction(surface):
    groups, _ = _grammar(surface)
    for rules in groups.values():
        for rule in rules:
            # Choose a legal example for enum slots in the middle, e.g. deck A or B.
            tokens = [(rule.values.get(part[1:-1]) or ["Sample"])[0]
                      if part.startswith("<") else part for part in rule.path]
            line = " ".join(tokens)
            assert not command_corrections(line, surface=surface), (surface, line)
            if rule.path[-1].startswith("<"):
                continue
            options = command_suggestions(line, len(line), limit=30, surface=surface)
            assert any(opt.apply(line)[0].strip().casefold() == line.casefold() for opt in options), (surface, line)
