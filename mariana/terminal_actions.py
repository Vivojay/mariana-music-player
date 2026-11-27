"""A terminal presentation for the same release selections that power Mariana Home."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import uuid4

from .discovery import STALE, DiscoverySelection
from .homepage import HomepageService
from .models import MediaRef

PICKER_COMMANDS = {"picks", "pick", "choices", "versions", "play", "queue", "cancel"}


def _positive(value: str, name: str) -> int:
    if not value.isascii() or not value.isdecimal() or len(value) > 12 or int(value) < 1:
        raise ValueError(f"{name} must be a positive whole number")
    return int(value)


def _show_choices(state: dict, write: Callable[[str], None]) -> None:
    if state["state"] == "closed":
        write("No selection is open. Use home picks to find a release or programme.")
        return
    revision = state["revision"]
    write(f"{state['title']} · {state['state']} · revision {revision}")
    if state.get("message"):
        write(state["message"])
    rows = state["candidates"] if state["state"] == "choices" else state["tracks"]
    for index, row in enumerate(rows, 1):
        details = [row["artist"], row.get("source")]
        if row.get("duration"):
            details.append(f"{int(row['duration']) // 60}:{int(row['duration']) % 60:02d}")
        if row.get("playable") is False:
            details.append("unavailable")
        write(f"{index}. {row['title']} · " + " · ".join(value for value in details if value))
    if state["state"] == "loading":
        write("Run home choices to see the results.")
    elif state["state"] == "choices" and rows:
        write(f"Use home play {revision} <row> or home queue {revision} <row>.")
    elif state["state"] == "tracks" and rows:
        write(f"Use home versions {revision} <row> to find versions for a recording.")
    if state.get("has_more"):
        write(f"Next page: home pick {state['item_id']} {state['page'] + 2}")


def run_release_picker(
    arguments: Sequence[str], home: HomepageService, picker: DiscoverySelection,
    write: Callable[[str], None], apply: Callable[[MediaRef, str], None],
):
    operation = arguments[0].casefold()
    if operation == "picks":
        snapshot = home.snapshot()
        if not snapshot["online_enabled"]:
            write("Online discovery is off. Use home online enable to inspect playable cards.")
            return []
        terms = [term.casefold() for term in arguments[1:]]
        cards = [
            item for section in snapshot["sections"]
            for item in section["items"]
            if item["id"].startswith(("release:", "catalogue:"))
            and all(term in f"{item['title']} {item['source']} {section['title']}".casefold() for term in terms)
            and home.release_target(item["id"]) is not None
        ]
        for item in cards:
            write(f"{item['title']} · {item['source']} · home pick {item['id']}")
        if not cards:
            write("No current playable cards matched.")
        return cards
    if operation == "pick" and len(arguments) in (2, 3):
        page = _positive(arguments[2], "Page") if len(arguments) == 3 else 1
        picker.begin(arguments[1], uuid4().hex, page=page - 1)
    elif operation == "cancel" and len(arguments) == 1:
        picker.cancel(picker.snapshot()["request_id"])
    elif operation in {"versions", "play", "queue"} and len(arguments) == 3:
        state = picker.snapshot()
        revision = _positive(arguments[1], "Revision")
        if state["revision"] != revision:
            raise ValueError(STALE)
        index = _positive(arguments[2], "Row number")
        rows = state["tracks"] if operation == "versions" else state["candidates"]
        if index > len(rows):
            raise ValueError("Choose a row shown by home choices")
        picker.choose(
            state["request_id"], revision, rows[index - 1]["id"], operation,
            foreground_apply=apply if operation != "versions" else None,
        )
    elif operation != "choices" or len(arguments) != 1:
        raise ValueError("Usage: home picks [query] | pick <card-id> [page] | choices | "
                         "versions|play|queue <revision> <row> | cancel")
    state = picker.snapshot()
    _show_choices(state, write)
    return state
