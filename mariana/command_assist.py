"""Span-aware, local command assistance. Suggestions only describe edits."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from itertools import islice

from .command_catalog import COMMAND_CATALOG
from .command_parser import CommandSyntaxError, CommandToken, command_tokens
from .commands import ALIAS_COMPATIBILITY

MAX_INPUT = 4096
MAX_TOKENS = 128
MAX_RESULTS = 30
_GRAMMARS = ("command_grammar_core.json", "command_grammar_studio.json")
_CONFIRM = frozenset(("--yes", "-y", "--assume-yes", "yes", "y"))
_WORD = re.compile(r"[-a-zA-Z0-9_./+*?=]+\Z")
_SPELLING = re.compile(r"(?:--?|[./])?[a-zA-Z][a-zA-Z0-9_-]{1,63}\Z")

ValueProvider = Callable[[str, str, tuple[str, ...]], Iterable[str]]


@dataclass(frozen=True, slots=True)
class Suggestion:
    text: str
    start: int
    end: int
    label: str
    summary: str
    kind: str

    def apply(self, line: str) -> tuple[str, int]:
        return line[:self.start] + self.text + line[self.end:], self.start + len(self.text)


@dataclass
class _Rule:
    path: tuple[str, ...]
    arguments: tuple[str, ...]
    flags: tuple[str, ...]
    values: dict
    flag_values: dict
    summary: str
    risk: str
    inline_flags: bool
    accepted_prefixes: dict

    @property
    def parts(self):
        return self.path + tuple(f"<{name}>" for name in self.arguments)


def _store_rule(table, path, *, arguments=(), flags=(), values=None, flag_values=None, summary="", risk="", inline_flags=False, accepted_prefixes=None):
    parts = tuple(path.split())
    if not parts:
        return
    prior = table.get(parts)
    table[parts] = _Rule(parts, tuple(arguments), tuple(flags), values or {}, flag_values or {},
                         summary or (prior.summary if prior else ""), risk or (prior.risk if prior else ""), inline_flags, accepted_prefixes or {})


@lru_cache(maxsize=1)
def _manifests():
    resources = (files("mariana").joinpath(name) for name in _GRAMMARS)
    return tuple(json.loads(resource.read_text(encoding="utf-8")) for resource in resources if resource.is_file())


def declared_commands(surface="native"):
    """Iterate registered command forms for a single player, including their operand hints."""
    for manifest in _manifests():
        for row in manifest["commands"]:
            if row.get("surface", "native") in ("both", surface):
                yield row


@lru_cache(maxsize=2)
def _grammar(surface):
    rows = {}
    aliases = set()
    exact_aliases = set()
    patterns = []
    if surface == "native":
        for spec in COMMAND_CATALOG:
            if not spec.suggest:
                continue
            base = dict(summary=spec.summary, risk=spec.risk.value)
            _store_rule(rows, spec.canonical, **base)
            for form in spec.forms:
                path = " ".join((spec.canonical, *form.tokens))
                _store_rule(rows, path, arguments=form.argument_kinds, flags=form.flags, **base)
        for item in ALIAS_COMPATIBILITY:
            if item.status == "retired":
                continue
            target = exact_aliases if item.scope == "exact" else aliases
            for alias in item.aliases:
                target.add((tuple(item.canonical.split()), tuple(alias.split())))
    for row in declared_commands(surface):
        path = row["path"]
        _store_rule(rows, path, arguments=row.get("arguments", ()), flags=row.get("flags", ()),
                    values=row.get("values"), flag_values=row.get("flagValues"), summary=row.get("description", ""),
                    inline_flags=bool(row.get("inlineFlags")), accepted_prefixes=row.get("acceptedPrefixes"))
        for alias in row.get("aliases", ()):
            aliases.add((tuple(path.split()), tuple(alias.split())))
    for data in _manifests():
        for item in data.get("headPatterns", ()):
            if item.get("surface", "native") in ("both", surface):
                patterns.append((re.compile(item["pattern"], re.IGNORECASE), item.get("canonical", "")))
    # Expanding token-scoped aliases across descendants preserves 'lv search',
    # while exact aliases only cover the one command the dispatcher recognizes.
    original = dict(rows)
    expanded_aliases = sorted(aliases | exact_aliases)
    for path, rule in original.items():
        for canonical, alias in expanded_aliases:
            if path[:len(canonical)] != canonical:
                continue
            if (canonical, alias) in exact_aliases and path != canonical:
                continue
            new = alias + path[len(canonical):]
            rows.setdefault(new, _Rule(new, rule.arguments, rule.flags, rule.values, rule.flag_values,
                                       rule.summary, rule.risk, rule.inline_flags, rule.accepted_prefixes))
    groups = defaultdict(list)
    for rule in rows.values():
        groups[rule.path[0].casefold()].append(rule)
    return groups, patterns


def literal_paths(surface="native"):
    """Static command spellings for callers of the legacy prefix-only API."""
    groups, _ = _grammar(surface)
    for rules in groups.values():
        for rule in rules:
            if all(_WORD.fullmatch(part) for part in rule.path):
                yield " ".join(rule.path), _description(rule)


def _description(rule):
    return f"{rule.summary} [{rule.risk}]" if rule.risk else rule.summary


def _placeholder(part):
    return part[1:-1] if part.startswith("<") and part.endswith(">") else None


def _choices(rule, name):
    if name in rule.values:
        return tuple(rule.values[name])
    # The original catalogue also uses short enum expressions such as
    # 'off|gentle|balanced|strong'. Descriptive argument names stay opaque.
    if "|" in name and all(_WORD.fullmatch(word) for word in name.split("|")):
        return tuple(name.split("|"))
    return ()


@dataclass
class _Context:
    rule: _Rule
    part: str
    flags: tuple
    pending: str
    specificity: int


def _context(rule, previous):
    parts = rule.parts
    position = specificity = 0
    seen = set()
    pending = ""
    for token in previous:
        word = token.value.casefold()
        if pending:
            choices = rule.flag_values.get(pending, ())
            if choices and word not in (item.casefold() for item in choices):
                return None
            pending = ""
            continue
        flag, equals, attached = word.partition("=")
        if equals and rule.inline_flags and flag in rule.flag_values and position >= len(rule.path):
            choices = rule.flag_values[flag]
            if choices and attached not in (item.casefold() for item in choices):
                return None
            seen.add(flag)
            continue
        if not token.quoted and word in rule.flags and position >= len(rule.path):
            seen.add(word)
            if word in rule.flag_values:
                pending = word
            continue
        if position >= len(parts):
            # Some native grammars accept unquoted multiword searches and paths.
            # Keep offering a route's options after them without synthesizing text.
            if not rule.arguments:
                return None
            continue
        part = parts[position]
        name = _placeholder(part)
        if name is None:
            if word != part.casefold():
                return None
            specificity += 2
        else:
            choices = _choices(rule, name)
            if choices:
                if word not in (value.casefold() for value in choices):
                    return None
                specificity += 1
        position += 1
    flags = tuple(f for f in rule.flags if f not in seen and f.startswith("-"))
    return _Context(rule, parts[position] if position < len(parts) else "",
                    flags if position >= len(rule.path) else (), pending, specificity)


def _contexts(previous, surface):
    groups, patterns = _grammar(surface)
    if not previous:
        # Collapse hundreds of variants into one description per command head.
        return [_Context(min(rules, key=lambda r:len(r.path)), rules[0].path[0], (), "", 0)
                for rules in groups.values()]
    first = previous[0]
    rules = groups.get(first.value.casefold(), ())
    if not rules:
        for pattern, canonical in patterns:
            if pattern.fullmatch(first.value):
                replacements = tuple(CommandToken(w, first.start, first.end, False) for w in canonical.split())
                if not replacements:
                    return []
                previous = (*replacements, *previous[1:])
                rules = groups.get(previous[0].value.casefold(), ())
                break
    matches = [ctx for rule in rules if (ctx := _context(rule, previous)) is not None]
    best = max((ctx.specificity for ctx in matches), default=0)
    return [ctx for ctx in matches if ctx.specificity == best]


def _displayable(text):
    # Joiners occur inside language scripts and emoji sequences such as singers.
    return all(ch.isprintable() or ch in "\u200c\u200d\u00a0" for ch in text)


def _valid(text, limit, surface):
    return (isinstance(text, str) and len(text) <= MAX_INPUT and surface in ("native", "portable")
            and type(limit) is int and 0 < limit <= MAX_RESULTS and _displayable(text.replace("\t", " ")))


def _variants(contexts, prefix, previous, provider):
    """Yield (word, kind, explanation). Never send the line itself to a value source."""
    providers = {}
    for ctx in contexts:
        rule = ctx.rule
        summary = _description(rule)
        if ctx.pending:
            choices = rule.flag_values[ctx.pending]
            yield from ((choice, "value", summary) for choice in choices)
            if not choices:
                # The optional mapping names the value kind for flags like --to.
                providers.setdefault(ctx.pending, summary)
            continue
        name = _placeholder(ctx.part)
        if name is not None:
            choices = _choices(rule, name)
            yield from ((choice, "value", summary) for choice in choices)
            if not choices:
                providers.setdefault(name, summary)
        elif ctx.part:
            yield ctx.part, "command", summary
        yield from ((flag, "flag", summary) for flag in ctx.flags)
    if provider:
        words = tuple(t.value for t in previous)
        for name, summary in providers.items():
            try:
                for value in islice(provider(name, prefix, words), 80):
                    if isinstance(value, str) and value and len(value) <= MAX_INPUT and _displayable(value):
                        yield value, "value", summary
            except (ValueError, OSError, RuntimeError):
                continue


def _quoted_value(value, original):
    quote = original[0] if original.startswith(('"', "'")) else '"'
    if not original.startswith(('"', "'")) and not any(ch.isspace() or ch in ('"', "'") for ch in value):
        return value
    for delimiter in (quote, "'" if quote == '"' else '"'):
        candidate = delimiter + value.replace(delimiter, delimiter * 2) + delimiter
        try:
            # Include another operand because a terminal quoted Windows root
            # has different backslash semantics at the very end of a line.
            if [t.value for t in command_tokens(candidate + " next")] == [value, "next"]:
                return candidate
        except CommandSyntaxError:
            pass
    # A file name can contain both quote marks immediately after backslashes.
    # Encode its whitespace runs as quoted segments and escape literal quotes
    # outside those segments, following the dispatch lexer's concatenation rules.
    pieces = re.split(r"(\\*\s+)", value)
    delimiters = ('"', "'")
    return "".join((delimiters[i//2 % 2] + piece + delimiters[i//2 % 2]) if i % 2 else re.sub(r"""(['"])""", r"\\\1", piece)
                   for i, piece in enumerate(pieces))


def _distance(typed, word, bound):
    """Bounded optimal-string-alignment distance, including adjacent transposition."""
    if abs(len(typed) - len(word)) > bound:
        return bound + 1
    old = list(range(len(word) + 1))
    older = None
    for i, a in enumerate(typed, 1):
        current = [i]
        for j, b in enumerate(word, 1):
            cost = min(old[j] + 1, current[-1] + 1, old[j-1] + (a != b))
            if older is not None and j > 1 and a == word[j-2] and typed[i-2] == b:
                cost = min(cost, older[j-2] + 1)
            current.append(cost)
        if min(current) > bound:
            return bound + 1
        older, old = old, current
    return old[-1]


def _accepts_word(name, word):
    # A clock boundary can share a grammar position with a literal "start"
    # or "end". Every accepted absolute time contains at least one digit.
    if name in {"start-time", "end-time", "start-seconds", "end-seconds", "seconds"}:
        return any(ch.isdigit() for ch in word)
    return True


def _fixes(contexts, token, *, is_head=False):
    word = token.value.casefold()
    size = len(word.lstrip("./-"))
    if token.quoted or not _SPELLING.fullmatch(word) or size < (3 if is_head else 2):
        return []
    is_flag = word.startswith("--")
    # A valid user-supplied name, search, path, or flag value may resemble a
    # literal. Submit-time correction is restricted to closed grammar positions.
    for ctx in contexts:
        name = _placeholder(ctx.part)
        if ctx.pending and not ctx.rule.flag_values[ctx.pending]:
            return []
        if name and any(value.casefold().startswith(word) for value in ctx.rule.accepted_prefixes.get(name, ())):
            return []
        if name is not None and not _choices(ctx.rule, name) and not is_flag and _accepts_word(name, word):
            return []
    bound = 2 if len(word.lstrip("./-")) >= 7 else 1
    variants = {}
    for value, kind, summary in _variants(contexts, "", (), None):
        lower = value.casefold()
        if lower == word:
            return []
        if lower in _CONFIRM or not _SPELLING.fullmatch(lower) or is_flag != (kind == "flag"):
            continue
        # A punctuation prefix carries semantics (e.g. /find versus .find).
        if word[:1] in "./-" and lower[:1] != word[:1]:
            continue
        if word[0].isalnum() and not lower[0].isalnum():
            continue
        score = _distance(word, lower, bound)
        if score <= bound:
            variants.setdefault(value, (score, value, summary))
    ranked = sorted(variants.values(), key=lambda r: (r[0], r[1].casefold()))
    if size == 2 and len(ranked) > 1:
        return []
    return ranked


def _edit(text, active, label, kind, summary, append_space):
    raw = text[active.start:active.end]
    value = _quoted_value(label, raw) if kind == "value" else label
    directory = kind == "value" and value.rstrip("'\"").endswith(("/", "\\"))
    if append_space and not directory and active.end == len(text):
        value += " "
    return Suggestion(value, active.start, active.end, label, summary, kind)


def _inline_slot(text, cursor, token, contexts):
    """Map an argparse-style --name=value to a value or flag-name edit span."""
    raw = text[token.start:token.end]
    if not raw.startswith("--") or "=" not in raw:
        return None
    flag, _, _ = raw.partition("=")
    split = token.start + len(flag)
    eligible = [ctx for ctx in contexts if ctx.rule.inline_flags and ctx.flags and not ctx.pending]
    if not eligible:
        return None
    eligible_flags = [ctx for ctx in eligible if flag.casefold() in ctx.rule.flag_values and flag.casefold() in ctx.flags]
    if cursor <= split or not eligible_flags:
        flag_token = CommandToken(flag, token.start, split, False)
        return flag_token, eligible
    operand = command_tokens(text[split+1:token.end], partial=True)
    value = operand[0].value if operand else ""
    slot = CommandToken(value, split + 1, token.end, bool(operand and operand[0].quoted))
    return slot, [_Context(ctx.rule, "", (), flag.casefold(), ctx.specificity) for ctx in eligible_flags]


def command_suggestions(text: str, cursor: int, *, limit=12, surface="native",
                        value_provider: ValueProvider | None = None) -> tuple[Suggestion, ...]:
    """Return bounded opt-in edits to the token under the cursor."""
    if not _valid(text, limit, surface) or not isinstance(cursor, int) or not 0 <= cursor <= len(text):
        return ()
    tokens = command_tokens(text, partial=True)
    if len(tokens) > MAX_TOKENS:
        return ()
    active = next((t for t in tokens if t.start <= cursor <= t.end), CommandToken("", cursor, cursor, False))
    previous = tuple(t for t in tokens if t.end <= active.start and t is not active)
    contexts = _contexts(previous, surface)
    inline = _inline_slot(text, cursor, active, contexts)
    if inline:
        active, contexts = inline
    prefixes = command_tokens(text[active.start:min(cursor, active.end)], partial=True)
    prefix = prefixes[0].value if prefixes else ""
    folded = prefix.casefold()
    found = {}
    for value, kind, summary in _variants(contexts, prefix, previous, value_provider):
        if active.quoted and kind != "value":
            continue
        if value.casefold() in _CONFIRM and (len(folded.lstrip("-")) < 1 or not folded.startswith("-")):
            continue
        key = value.casefold()
        if key.startswith(folded):
            found.setdefault(key, (value, kind, summary))
    if not found:
        fixes = _fixes(contexts, active, is_head=not previous)
        if not contexts:
            return command_corrections(text, limit=limit, surface=surface)
        return tuple(_edit(text, active, value, "correction", summary, True) for _, value, summary in fixes[:limit])
    order = {"command": 0, "value": 1, "flag": 2}
    common = ("help", "play", "queue", "artist", "dj", "tone", "karaoke", "jam", "podbean", "librivox", "theme", "tui")
    priorities = {word: i for i, word in enumerate(common)} if not prefix and not previous else {}
    matches = sorted(found.values(), key=lambda r: (r[0].casefold() != folded, order[r[1]],
                                                    priorities.get(r[0], len(priorities)), r[0].casefold()))
    return tuple(_edit(text, active, value, kind, summary, True) for value, kind, summary in matches[:limit])


def command_corrections(text: str, *, limit=3, surface="native") -> tuple[Suggestion, ...]:
    """Offer a spelling edit in the first invalid syntax slot; never modify inputs."""
    if not _valid(text, limit, surface):
        return ()
    tokens = command_tokens(text, partial=True)
    if not tokens or len(tokens) > MAX_TOKENS:
        return ()
    groups, patterns = _grammar(surface)
    if tokens[0].value.casefold() not in groups and any(pattern.fullmatch(tokens[0].value) for pattern, _ in patterns):
        # The indexed head is valid; later flags are checked in its canonical context.
        start = 1
    else:
        start = 0
    for index in range(start, len(tokens)):
        token = tokens[index]
        contexts = _contexts(tokens[:index], surface)
        if not contexts:
            return ()
        inline = _inline_slot(text, token.end, token, contexts)
        if inline:
            token, contexts = inline
        matches = _fixes(contexts, token, is_head=index == 0)
        if matches:
            return tuple(_edit(text, token, value, "correction", summary, False)
                         for _, value, summary in matches[:limit])
    return ()
