"""On-demand client for text conversations on an explicitly chosen Matrix homeserver."""

from __future__ import annotations

import getpass
import json
import re
import uuid
import warnings
from urllib.parse import quote, unquote, urlsplit

import requests

from . import fan_polls
from .paired_trust import KeyringPairingSecrets, PairingError

_MAX_RESPONSE = 512 * 1024
_ACCOUNT = "current-account"
_HELP = """fanroom login <https://homeserver>    enter an existing Matrix access token at the hidden prompt
fanroom status | rooms | forget       inspect account, list joined rooms, or remove saved credentials
fanroom join <#alias:server|!id>      join an artist room on the homeserver
fanroom read <!id> [1-50]             read recent text messages with event IDs
fanroom wait <!id> [1-25 seconds]     wait once for incoming room activity
fanroom post <!id> <message>          send a message to an unencrypted room
fanroom reply <!id> <$event> <text>   reply to a room message
fanroom react <!id> <$event> <emoji>  add a reaction
fanroom thread <!id> <$root> [cursor] show a thread and its latest replies, 20 per page
fanroom thread-post <!id> <$root> <text>  add a threaded reply
fanroom poll <!id> "Question?" "A" "B"    create a disclosed single-choice poll
fanroom poll-show <!id> <$poll>            show the question, choices and vote totals
fanroom vote <!id> <$poll> <number>        send or replace your vote
fanroom poll-end <!id> <$poll>             close your poll
fanroom report <!id> <$event> <why>   submit an event report to the homeserver
fanroom leave <!id>                   leave this room"""


def _origin(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https" or not url.hostname or url.username is not None
        or url.password is not None or url.query or url.fragment or url.path not in ("", "/")
        or not re.fullmatch(r"[a-zA-Z0-9.\-:\[\]]+", url.netloc) or url.port == 0
    ):
        raise ValueError("Enter the HTTPS origin of your own Matrix homeserver, such as https://matrix.example.org")
    return "https://" + url.netloc.lower()


def _identifier(value: str, prefixes: str) -> str:
    if not (1 < len(value) <= 255 and value[0] in prefixes and all(c.isprintable() and not c.isspace() for c in value)):
        raise ValueError(f"Expected a Matrix ID starting with one of {prefixes!r}")
    return quote(value, safe="")


def _display(value: object, limit: int = 250) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(c if c.isprintable() else " " for c in value[:limit])


def _request(origin, token, method, path, *, missing=False, read_timeout=8, version="v3", **kwargs):
    if (version not in {"v1", "v3"} or not re.fullmatch(r"(?:[A-Za-z0-9._~/-]|%[0-9A-Fa-f]{2})+", path)
            or any(unquote(part) in {"", ".", ".."} for part in path.split("/"))):
        raise ValueError("Invalid Matrix API path")
    url = f"{_origin(origin)}/_matrix/client/{version}/{path}"
    try:
        with requests.request(method, url, headers={"Authorization": "Bearer " + token} if token else {},
                              allow_redirects=False, timeout=(4, read_timeout), stream=True, **kwargs) as response:
            data = bytearray()
            for chunk in response.iter_content(16 * 1024):
                if len(data) + len(chunk) > _MAX_RESPONSE:
                    raise ValueError("Matrix response is too large")
                data.extend(chunk)
            try:
                body = json.loads(data)
            except (ValueError, RecursionError):
                raise ValueError(f"Matrix returned an invalid response (HTTP {response.status_code})") from None
            if not isinstance(body, dict):
                raise ValueError("Invalid Matrix response")
            if missing and response.status_code == 404 and body.get("errcode") == "M_NOT_FOUND":
                return None
            if not 200 <= response.status_code < 300:
                code = _display(body.get("errcode"), 60)
                raise ValueError(f"Matrix refused this operation (HTTP {response.status_code}, {code})")
            return body
    except requests.RequestException:
        raise ValueError("Matrix connection failed. Inspect the room before retrying a send.") from None


def _secret_prompt(origin):
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(f"Matrix access token for {origin} (hidden): ")
        except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
            raise ValueError("Login cancelled or a hidden token prompt is unavailable") from None


def _messages(timeline):
    if not isinstance(timeline, list):
        raise ValueError("Homeserver returned an invalid timeline")
    lines = []
    for event in timeline:
        if not isinstance(event, dict):
            continue
        content = event.get("content")
        if event.get("type") == "m.room.encrypted":
            message = "[Encrypted message. Open your encrypted Matrix client.]"
        elif not isinstance(content, dict):
            continue
        elif event.get("type") == "m.room.message" and content.get("msgtype") == "m.text":
            message = _display(content.get("body"), 2000)
        elif event.get("type") in (fan_polls.START, fan_polls.END):
            message = "[Poll] " + _display(content.get(fan_polls.TEXT), 1500)
        elif event.get("type") == "m.reaction" and isinstance(content.get("m.relates_to"), dict):
            relation = content["m.relates_to"]
            message = f"[Reaction {_display(relation.get('key'), 32)} to {_display(relation.get('event_id'))}]"
        else:
            continue
        lines.append(f"{_display(event.get('sender'))}  {message}  [{_display(event.get('event_id'))}]")
    return "\n".join(lines) or "No room messages in this update."


def _room_text(event, room_id):
    if not isinstance(event, dict) or event.get("room_id", room_id) != room_id:
        return False
    sender, event_id, content = event.get("sender"), event.get("event_id"), event.get("content")
    return (
        isinstance(sender, str) and sender.startswith("@") and ":" in sender and sender.isprintable()
        and isinstance(event_id, str) and event_id.startswith("$") and event_id.isprintable()
        and event.get("type") == "m.room.message" and isinstance(content, dict)
        and content.get("msgtype") == "m.text" and isinstance(content.get("body"), str)
    )


def _is_thread_reply(event, room_id, root):
    if not _room_text(event, room_id):
        return False
    relation = event["content"].get("m.relates_to")
    return isinstance(relation, dict) and relation.get("rel_type") == "m.thread" and relation.get("event_id") == root


def _thread(origin, token, room_path, room_id, root, request, *, cursor=None, new_message=None):
    target = _identifier(root, "$")
    parent = request(origin, token, "GET", room_path + "event/" + target)
    if not _room_text(parent, room_id) or parent["event_id"] != root or parent["content"].get("m.relates_to"):
        raise ValueError("Choose an original, visible text message from this room as the thread root.")
    if new_message is not None:
        _require_plain_room(origin, token, room_path, request)
        unsigned = parent.get("unsigned")
        relations = unsigned.get("m.relations") if isinstance(unsigned, dict) else None
        summary = relations.get("m.thread") if isinstance(relations, dict) else None
        latest = summary.get("latest_event") if isinstance(summary, dict) else None
        previous = latest["event_id"] if latest is not None and _is_thread_reply(latest, room_id, root) else root
        return _send_event(origin, token, room_path, "m.room.message", {
            "msgtype": "m.text", "body": new_message, "m.relates_to": {
                "rel_type": "m.thread", "event_id": root, "is_falling_back": True,
                "m.in_reply_to": {"event_id": previous},
            },
        }, request)
    params = {"dir": "b", "limit": 20}
    if cursor:
        if not 1 <= len(cursor) <= 1024 or not cursor.isprintable():
            raise ValueError("Invalid thread cursor.")
        params["from"] = cursor
    page = request(origin, token, "GET", room_path + "relations/" + target + "/m.thread/m.room.message",
                   params=params, version="v1")
    if not isinstance(page.get("chunk"), list):
        raise ValueError("Homeserver returned an invalid thread")
    replies = []
    seen = {root}
    for event in page["chunk"]:
        if _is_thread_reply(event, room_id, root) and event["event_id"] not in seen:
            replies.append(event)
            seen.add(event["event_id"])
    output = [_messages([parent]), f"Thread replies on this page: {len(replies)}"]
    if replies:
        output.append(_messages(replies[::-1]))
    if page.get("next_batch"):
        output.append("Earlier replies cursor: " + _display(page["next_batch"], 1024))
    return "\n".join(output)


def _require_plain_room(origin, token, room_path, request):
    encryption = request(origin, token, "GET", room_path + "state/m.room.encryption", missing=True)
    if encryption is not None:
        raise ValueError("This room uses encryption. Send through an encrypted Matrix client.")


def _send_event(origin, token, room_path, event_type, content, request):
    result = request(origin, token, "PUT", room_path + "send/" + event_type + "/" + uuid.uuid4().hex, json=content)
    if not isinstance(result.get("event_id"), str) or not result["event_id"].startswith("$"):
        raise ValueError("Delivery is uncertain. Inspect the timeline before sending again.")
    return "Sent " + _display(result["event_id"])


def _credentials(saved):
    try:
        record = json.loads(saved)
        if not isinstance(record, list) or len(record) != 3 or not all(isinstance(v, str) for v in record):
            raise ValueError
        origin, token, account = record
        origin = _origin(origin)
        _identifier(account, "@")
        if not re.fullmatch(r"[!-~]{1,4096}", token):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        raise ValueError("Saved Matrix login is invalid. Run fanroom login again.") from None
    return origin, token, account


def run(arguments, *, secrets=None, prompt=_secret_prompt, request=_request) -> str:
    action, *values = arguments or ["help"]
    action = action.casefold()
    if action == "help" and not values:
        return _HELP
    if action not in {"login", "status", "rooms", "join", "read", "wait", "post", "reply", "react", "thread", "thread-post", "poll", "poll-show", "vote", "poll-end", "report", "leave", "forget"}:
        raise ValueError(_HELP)
    store = secrets if secrets is not None else KeyringPairingSecrets(service="io.github.vivojay.mariana.matrix")
    try:
        if action == "login" and len(values) == 1:
            origin = _origin(values[0])
            token = prompt(origin)
            if not isinstance(token, str) or not re.fullmatch(r"[!-~]{1,4096}", token):
                raise ValueError("Empty or invalid access token")
            account = request(origin, token, "GET", "account/whoami").get("user_id")
            if not isinstance(account, str):
                raise ValueError("Homeserver did not identify this account")
            _identifier(account, "@")
            store.set(_ACCOUNT, json.dumps([origin, token, account]))
            return f"Connected as {_display(account)} on {origin}."
        if action == "forget" and not values:
            store.delete(_ACCOUNT)
            return "Removed this Mariana login from the credential store."
        if action == "login":
            raise ValueError("Usage: fanroom login <https://homeserver>. Enter the token only at the hidden prompt.")
        saved = store.get(_ACCOUNT)
    except PairingError:
        raise ValueError("Matrix login requires a supported operating-system credential store") from None
    if not saved:
        if action == "status" and not values:
            return "No saved Matrix login."
        raise ValueError("First run fanroom login <https://homeserver>")
    origin, token, account = _credentials(saved)
    if action == "status" and not values:
        return f"{_display(account)} on {origin}. Rooms refresh on request."
    if action == "rooms" and not values:
        rooms = request(origin, token, "GET", "joined_rooms").get("joined_rooms")
        if not isinstance(rooms, list):
            raise ValueError("Homeserver returned an invalid room list")
        return "\n".join(_display(room) for room in rooms if isinstance(room, str)) or "No joined rooms."
    if action == "join" and len(values) == 1:
        target = _identifier(values[0], "#!")
        joined = request(origin, token, "POST", "join/" + target, json={}).get("room_id")
        if not isinstance(joined, str) or not joined.startswith("!"):
            raise ValueError("Homeserver did not confirm the room ID")
        return "Joined " + _display(joined)
    if not values:
        raise ValueError(_HELP)
    room = "rooms/" + _identifier(values[0], "!") + "/"
    if action in {"poll", "poll-show", "vote", "poll-end"}:
        def fetch(path, **kwargs):
            return request(origin, token, "GET", path, **kwargs)

        def publish(event_type, content):
            _require_plain_room(origin, token, room, request)
            return _send_event(origin, token, room, event_type, content, request)

        return fan_polls.execute(action, values[1:], room, values[0], account, fetch, publish)
    if action == "leave" and len(values) == 1:
        request(origin, token, "POST", room + "leave", json={})
        return "Left the room."
    if action == "read" and len(values) in (1, 2):
        limit = int(values[1]) if len(values) == 2 else 12
        if not 1 <= limit <= 50:
            raise ValueError("Choose a message limit from 1 through 50.")
        timeline = request(origin, token, "GET", room + "messages", params={
            "dir": "b", "limit": limit, "filter": json.dumps({"types": ["m.room.message", "m.room.encrypted", "m.reaction", fan_polls.START, fan_polls.END]}),
        }).get("chunk")
        if not isinstance(timeline, list):
            raise ValueError("Homeserver returned an invalid timeline")
        return _messages(timeline[::-1])
    if action == "wait" and len(values) in (1, 2):
        seconds = int(values[1]) if len(values) == 2 else 10
        if not 1 <= seconds <= 25:
            raise ValueError("Choose a wait from 1 through 25 seconds.")
        empty = {"types": []}
        room_filter = {"rooms": [values[0]], "state": empty, "ephemeral": empty, "account_data": empty,
                       "timeline": {"types": ["m.room.message", "m.room.encrypted", "m.reaction", fan_polls.START, fan_polls.END], "limit": 50}}
        sync_filter = json.dumps({"room": room_filter, "presence": empty, "account_data": empty})
        cursor = request(origin, token, "GET", "sync", params={"filter": sync_filter, "timeout": 0}).get("next_batch")
        if not isinstance(cursor, str) or not cursor:
            raise ValueError("Homeserver did not return a sync cursor")
        result = request(origin, token, "GET", "sync", read_timeout=seconds + 5,
                         params={"filter": sync_filter, "since": cursor, "timeout": seconds * 1000})
        branch = result
        for key in ("rooms", "join", values[0], "timeline"):
            if not isinstance(branch, dict):
                raise ValueError("Invalid Matrix sync response")
            branch = branch.get(key, {})
        if not isinstance(branch, dict):
            raise ValueError("Invalid Matrix timeline")
        return _messages(branch.get("events", []))
    if action == "thread" and len(values) in (2, 3):
        return _thread(origin, token, room, values[0], values[1], request, cursor=values[2] if len(values) == 3 else None)
    if action == "thread-post" and len(values) >= 3:
        message = " ".join(values[2:]).strip()
        if not 1 <= len(message) <= 2000:
            raise ValueError("Enter 1–2,000 characters for a threaded reply.")
        return _thread(origin, token, room, values[0], values[1], request, new_message=message)
    if action == "report" and len(values) >= 3:
        event = _identifier(values[1], "$")
        reason = " ".join(values[2:]).strip()
        if not 1 <= len(reason) <= 1000:
            raise ValueError("Give a reason of 1–1,000 characters.")
        request(origin, token, "POST", room + "report/" + event, json={"reason": reason})
        return "Submitted the event report to your homeserver."
    if (action == "post" and len(values) >= 2) or (action in {"reply", "react"} and len(values) >= 3):
        event_type = "m.room.message"
        if action != "post":
            _identifier(values[1], "$")
        message = " ".join(values[1:] if action == "post" else values[2:]).strip()
        if not 1 <= len(message) <= 2000:
            raise ValueError("Enter 1–2,000 characters for a room message.")
        _require_plain_room(origin, token, room, request)
        content: dict[str, str | dict[str, object]] = {"msgtype": "m.text", "body": message}
        if action == "reply":
            content["m.relates_to"] = {"m.in_reply_to": {"event_id": values[1]}}
        if action == "react":
            if len(message) > 32:
                raise ValueError("Use a reaction of 1–32 characters.")
            event_type = "m.reaction"
            content = {"m.relates_to": {"rel_type": "m.annotation", "event_id": values[1], "key": message}}
        return _send_event(origin, token, room, event_type, content, request)
    raise ValueError(_HELP)
