"""SQL-like read-only query engine over durable library state.

Selects media without mutating it. Mutations happen only through explicit
bulk actions (fav/playlist/tag/rm) that consume the last query result set.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QueryPredicate:
    field: str
    operator: str
    value: str


@dataclass(frozen=True, slots=True)
class QueryRequest:
    scope: str
    scope_name: str | None
    predicates: tuple[QueryPredicate, ...] = ()
    logic: tuple[str, ...] = ()  # 'and'/'or' between predicates
    order_field: str | None = None
    order_desc: bool = False
    limit: int | None = None


TEXT_FIELDS = frozenset(
    {
        "title",
        "artist",
        "album",
        "author",
        "handle",
        "creator",
        "publisher",
        "provider",
        "tag",
        "tags",
        "source",
        "format",
        "name",
    }
)
NUMERIC_FIELDS = frozenset({"rate", "rating", "duration", "size", "year", "published", "date"})
FLAG_FIELDS = frozenset({"fav", "favorite", "favourite", "blocked", "rated", "unrated"})
SCOPES = frozenset(
    {"library", "favs", "favorites", "favourites", "blocked", "queue", "playlist", "playlists", "catalogue", "ratings"}
)
ORDER_FIELDS = TEXT_FIELDS | NUMERIC_FIELDS | frozenset({"published", "updated"})

_OPERATOR = re.compile(r"(>=|<=|!=|=|>|<|~|:)")
_MAX_QUERY_CHARS = 1024


def parse_query(tokens: list[str]) -> QueryRequest:
    """Parse: query <scope> [playlist \"<name>\"] where <pred> [and|or ...] [order by <f> [desc]] [limit N]."""
    if not tokens or tokens[0].casefold() != "query":
        raise ValueError(
            "Usage: query <scope> where <field><op><value> [and|or ...] [order by <field> [asc|desc]] [limit N]"
        )
    rest = list(tokens[1:])
    if not rest:
        raise ValueError(
            'Usage: query <scope> where ... (scopes: library|favs|blocked|queue|playlist "<name>"|playlists|catalogue|ratings)'
        )
    scope = rest.pop(0).casefold()
    if scope not in SCOPES:
        raise ValueError(f"Unknown query scope: {scope}")
    scope_name: str | None = None
    if scope == "playlist":
        if not rest:
            raise ValueError("Playlist query requires a playlist name after --in playlist / query playlist")
        scope_name = rest.pop(0).strip().strip("\"'")
        if not scope_name:
            raise ValueError("Playlist query requires a non-empty playlist name")
    # Allow `query library where ...` or bare `query library <preds>`
    if rest and rest[0].casefold() == "where":
        rest.pop(0)
    if not rest:
        raise ValueError('Query requires at least one predicate (e.g. where rate>=3 and tag="late night")')
    joined = " ".join(rest)
    if len(joined) > _MAX_QUERY_CHARS:
        raise ValueError("Query must be 1024 characters or fewer")
    # Split off trailing `order by ...` and `limit N` (case-insensitive).
    # Strip LIMIT first so ORDER BY stays trailing-matchable.
    order_field: str | None = None
    order_desc = False
    limit: int | None = None
    limit_match = re.search(r"\blimit\s+(\d+)\s*$", joined, re.I)
    if limit_match:
        limit = int(limit_match.group(1))
        if not 1 <= limit <= 5000:
            raise ValueError("Query limit must be between 1 and 5000")
        joined = joined[: limit_match.start()].strip()
    order_match = re.search(r"\border\s+by\s+([A-Za-z_]+)(?:\s+(asc|desc))?\s*$", joined, re.I)
    if order_match:
        order_field = order_match.group(1).casefold()
        if order_field not in ORDER_FIELDS:
            raise ValueError(f"Unknown order field: {order_field}")
        order_desc = (order_match.group(2) or "asc").casefold() == "desc"
        joined = joined[: order_match.start()].strip()
    parts = re.split(r"\s+(and|or)\s+", joined, flags=re.I)
    if not parts or not parts[0].strip():
        raise ValueError("Query requires at least one predicate")
    predicates: list[QueryPredicate] = []
    logic: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            logic.append(part.casefold())
            continue
        predicates.append(_parse_predicate(part.strip()))
    if len(logic) != max(0, len(predicates) - 1):
        raise ValueError("Query logic must join predicates with and/or")
    return QueryRequest(scope, scope_name, tuple(predicates), tuple(logic), order_field, order_desc, limit)


def _parse_predicate(text: str) -> QueryPredicate:
    # Flag form: `fav`, `blocked`, `rated`, `unrated` (no operator).
    if re.fullmatch(r"[A-Za-z_]+", text or ""):
        name = text.casefold()
        if name in FLAG_FIELDS:
            return QueryPredicate(name, "is", "true")
        raise ValueError(f"Unknown query predicate: {text}")
    match = _OPERATOR.search(text)
    if not match:
        # Bare `field value` defaults to substring match.
        bits = text.split(None, 1)
        if len(bits) == 2 and bits[0].casefold() in TEXT_FIELDS | NUMERIC_FIELDS | FLAG_FIELDS:
            return QueryPredicate(
                bits[0].casefold(), "~" if bits[0].casefold() in TEXT_FIELDS else "=", bits[1].strip().strip("\"'")
            )
        raise ValueError(f"Query predicate needs an operator (=, !=, >, >=, <, <=, ~): {text}")
    operator = match.group(1)
    field = text[: match.start()].strip().casefold()
    value = text[match.end() :].strip().strip("\"'")
    if field not in TEXT_FIELDS | NUMERIC_FIELDS | FLAG_FIELDS:
        raise ValueError(f"Unknown query field: {field}")
    if field in FLAG_FIELDS and operator not in {"=", "!=", "is"}:
        raise ValueError(f"Flag predicate {field} supports only = / !=")
    if not value:
        raise ValueError(f"Query predicate {field} requires a value")
    if len(value) > 256:
        raise ValueError("Query predicate value must be 256 characters or fewer")
    return QueryPredicate(field, operator, value)


def split_bulk_selection(text: str, *, maximum: int) -> list[int]:
    """Parse `1,2,6`, `3-5,9`, or `all` against a 1-based result list."""
    cleaned = (text or "").strip().casefold()
    if cleaned in {"all", "*"}:
        return list(range(1, maximum + 1))
    selected: list[int] = []
    for chunk in cleaned.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            bits = chunk.split("-", 1)
            try:
                start, end = int(bits[0]), int(bits[1])
            except ValueError:
                raise ValueError(f"Invalid bulk selection: {chunk}") from None
            if not 1 <= start <= end <= maximum:
                raise ValueError(f"Bulk selection out of range: {chunk} (1-{maximum})")
            selected.extend(range(start, end + 1))
            continue
        try:
            number = int(chunk)
        except ValueError:
            raise ValueError(f"Invalid bulk selection: {chunk}") from None
        if not 1 <= number <= maximum:
            raise ValueError(f"Bulk selection out of range: {chunk} (1-{maximum})")
        selected.append(number)
    # Stable dedupe preserving display order.
    seen: set[int] = set()
    ordered: list[int] = []
    for number in selected:
        if number not in seen:
            seen.add(number)
            ordered.append(number)
    if not ordered:
        raise ValueError("Bulk selection is empty")
    return ordered


def shlex_join(tokens: list[str]) -> str:
    return shlex.join(tokens)
