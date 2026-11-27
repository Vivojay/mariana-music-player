"""Disclosed, single-choice Matrix polls using the widely deployed MSC3381 event schema."""

from __future__ import annotations

import uuid
from collections import Counter
from urllib.parse import quote

START = "org.matrix.msc3381.poll.start"
VOTE = "org.matrix.msc3381.poll.response"
END = "org.matrix.msc3381.poll.end"
TEXT = "org.matrix.msc1767.text"
DISCLOSED = "org.matrix.msc3381.poll.disclosed"


def _label(value, limit):
    return isinstance(value, str) and value.isprintable() and 0 < len(value.strip()) <= len(value) <= limit


def _valid_event(event, room_id):
    return (
        isinstance(event, dict) and event.get("room_id", room_id) == room_id
        and _label(event.get("sender"), 255) and event["sender"].startswith("@") and ":" in event["sender"]
        and _label(event.get("event_id"), 255) and event["event_id"].startswith("$")
        and isinstance(event.get("content"), dict)
    )


def _read_start(event, room_id, poll_id):
    if not _valid_event(event, room_id) or event.get("type") != START or event["event_id"] != poll_id:
        raise ValueError("Choose the ID of a visible poll in this room.")
    poll = event["content"].get(START)
    if not isinstance(poll, dict) or poll.get("kind") != DISCLOSED or poll.get("max_selections", 1) != 1:
        raise ValueError("Mariana currently supports disclosed, single-choice polls.")
    question = poll.get("question")
    answers = poll.get("answers")
    if not isinstance(question, dict) or not _label(question.get(TEXT), 500) or not isinstance(answers, list):
        raise ValueError("Invalid Matrix poll.")
    if not 2 <= len(answers) <= 20 or any(
        not isinstance(a, dict) or not _label(a.get("id"), 255) or not _label(a.get(TEXT), 200) for a in answers
    ):
        raise ValueError("Invalid Matrix poll options.")
    ids = [a["id"] for a in answers]
    if len(ids) != len(set(ids)):
        raise ValueError("Invalid duplicate option IDs.")
    return question[TEXT], answers


def _historical_moderator(fetch, room_path, room_id, event):
    context = fetch(room_path + "context/" + quote(event["event_id"], safe=""), params={"limit": 0})
    anchor = context.get("event")
    if (not isinstance(anchor, dict) or anchor.get("event_id") != event["event_id"]
            or anchor.get("sender") != event["sender"] or anchor.get("room_id", room_id) != room_id):
        raise ValueError("Cannot verify a moderator's poll closure.")
    state = context.get("state")
    if not isinstance(state, list):
        raise ValueError("Cannot verify historical room permissions.")
    by_type = {s.get("type"): s for s in state if isinstance(s, dict) and s.get("state_key") == ""
               and s.get("type") in ("m.room.create", "m.room.power_levels") and isinstance(s.get("content"), dict)}
    create = by_type.get("m.room.create")
    if not create:
        raise ValueError("Cannot verify historical room permissions.")
    version = create["content"].get("room_version", "1")
    if version not in {str(i) for i in range(1, 13)}:
        raise ValueError("Use a full Matrix client to verify moderator closure in this room version.")
    sender = event["sender"]
    additional = create["content"].get("additional_creators", [])
    if version == "12" and (sender == create.get("sender") or (isinstance(additional, list) and sender in additional)):
        return True
    powers = by_type.get("m.room.power_levels", {}).get("content", {})
    users = powers.get("users", {})
    if not isinstance(users, dict):
        raise ValueError("Invalid historical room permissions.")
    default = 100 if not powers and sender == create.get("sender") else powers.get("users_default", 0)
    user_level, required = users.get(sender, default), powers.get("redact", 50)
    if not all(type(value) is int or (isinstance(value, str) and value.removeprefix("-").isdigit()) for value in (user_level, required)):
        raise ValueError("Invalid historical room permissions.")
    return int(user_level) >= int(required)


def _events(fetch, room_path, room_id, poll_id):
    params = {"limit": 100, "dir": "b"}
    relations = {}
    seen_tokens = set()
    for _ in range(5):
        page = fetch(room_path + "relations/" + quote(poll_id, safe="") + "/m.reference", params=params, version="v1")
        chunk = page.get("chunk")
        if not isinstance(chunk, list) or len(chunk) > 100:
            raise ValueError("Invalid poll results page.")
        for event in chunk:
            if not _valid_event(event, room_id) or event.get("type") not in (VOTE, END):
                continue
            relation = event["content"].get("m.relates_to")
            if (isinstance(relation, dict) and relation.get("rel_type") == "m.reference" and
                    relation.get("event_id") == poll_id and type(event.get("origin_server_ts")) is int and event["origin_server_ts"] >= 0):
                relations[event["event_id"]] = event
        cursor = page.get("next_batch")
        if not cursor:
            return sorted(relations.values(), key=lambda e: (e["origin_server_ts"], e["event_id"]))
        if not _label(cursor, 1024) or cursor in seen_tokens:
            raise ValueError("Incomplete poll pagination. No totals are available.")
        seen_tokens.add(cursor)
        params = {**params, "from": cursor}
    raise ValueError("This poll exceeds Mariana's 500-relation limit. Open it in a full Matrix client.")


def _results(fetch, room_path, room_id, owner, answers, events):
    options = {answer["id"] for answer in answers}
    closed = None
    checks = 0
    for event in events:
        if event["type"] == END and isinstance(event["content"].get(END), dict):
            if event["sender"] != owner:
                checks += 1
                if checks > 5:
                    raise ValueError("Too many disputed closing events to verify. Open this poll in a full Matrix client.")
                if not _historical_moderator(fetch, room_path, room_id, event):
                    continue
            closed = event["origin_server_ts"]
            break
    latest = {}
    for event in events:
        if event["type"] != VOTE or (closed is not None and event["origin_server_ts"] > closed):
            continue
        vote = event["content"].get(VOTE)
        choices = vote.get("answers") if isinstance(vote, dict) else None
        valid = isinstance(choices, list) and choices and all(isinstance(key, str) and key in options for key in choices)
        latest[event["sender"]] = choices[0] if valid else None
    return closed is not None, Counter(key for key in latest.values() if key is not None)


def execute(action, values, room_path, room_id, account, fetch, publish):
    if action == "poll":
        if not 3 <= len(values) <= 21:
            raise ValueError('Usage: fanroom poll !room "Question?" "Choice one" "Choice two" [more choices]')
        question, *choices = values
        if not _label(question, 500) or any(not _label(choice, 200) for choice in choices):
            raise ValueError("Use a printable question (1–500 characters) and choices (1–200 characters).")
        if len(set(choice.strip().casefold() for choice in choices)) != len(choices):
            raise ValueError("Use distinct poll choices.")
        answers = [{"id": uuid.uuid4().hex, TEXT: choice} for choice in choices]
        return publish(START, {
            TEXT: question + "\n" + "\n".join(f"{i}. {choice}" for i, choice in enumerate(choices, 1)),
            START: {"kind": DISCLOSED, "max_selections": 1, "question": {TEXT: question}, "answers": answers},
        })
    if len(values) != (2 if action == "vote" else 1) or not _label(values[0], 255) or not values[0].startswith("$"):
        raise ValueError("Usage: fanroom poll-show|poll-end !room $poll, or fanroom vote !room $poll OPTION")
    poll_id = values[0]
    start = fetch(room_path + "event/" + quote(poll_id, safe=""))
    question, answers = _read_start(start, room_id, poll_id)
    if action == "poll-end" and start["sender"] != account:
        raise ValueError("Only the poll creator can close a poll through Mariana.")
    events = _events(fetch, room_path, room_id, poll_id)
    closed, counts = _results(fetch, room_path, room_id, start["sender"], answers, events)
    if action == "poll-show":
        return "\n".join([question + (" [closed]" if closed else " [open]"), *(
            f"{i}. {choice[TEXT]} — {counts[choice['id']]} votes" for i, choice in enumerate(answers, 1)
        )])
    if closed:
        raise ValueError("The poll has closed.")
    relation = {"rel_type": "m.reference", "event_id": poll_id}
    if action == "poll-end":
        return publish(END, {"m.relates_to": relation, END: {}, TEXT: f"Poll closed: {question}"})
    idx = int(values[1])
    if not 1 <= idx <= len(answers):
        raise ValueError("Choose a displayed option number.")
    return publish(VOTE, {"m.relates_to": relation, VOTE: {"answers": [answers[idx - 1]["id"]]}})
