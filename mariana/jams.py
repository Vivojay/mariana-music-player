"""Invite-only Matrix listening rooms. Audio stays in each participant's player."""
from __future__ import annotations

import json
import math
import time

from . import fanrooms
from .jam_login import browser_token
from .paired_trust import KeyringPairingSecrets, PairingError

ROOM_TYPE = "io.github.vivojay.mariana.jam"
HOST = ROOM_TYPE + ".host"
CUE = ROOM_TYPE + ".cue"
SUGGEST = ROOM_TYPE + ".suggest"
HELP = """jam login https://homeserver    sign in through your browser
jam status | rooms | invites | logout
jam create NAME                 create an invite-only listening room
jam invite !room @user          invite a Matrix account
jam join #alias|!room           join and show the canonical room ID
jam members !room | jam leave !room
jam suggest !room TITLE         add a track suggestion
jam timeline !room              view the latest suggestions and cues
jam cue !room play|pause|seek SECONDS TITLE    host publishes a playback cue
jam send !room                  share your loaded track and playhead
jam current !room               read the host's latest cue
jam apply !room                 apply the fixed cue to the matching loaded title
jam sync !room                  align to the current host position at normal speed"""


def _text(value):
    if not isinstance(value, str) or len(value) > 200 or not value.strip() or not value.isprintable():
        raise ValueError("Enter a title or room name of 1–200 printable characters.")
    return value.strip()


def _cue(content):
    action = content.get("action")
    seconds = content.get("seconds")
    if (action not in ("play", "pause", "seek") or type(seconds) not in (int, float)
            or not 0 <= seconds <= 864000 or not math.isfinite(seconds)):
        raise ValueError("Choose play, pause or seek and a position from 0 to 864000 seconds.")
    return {"action": action, "seconds": seconds, "title": _text(content.get("title"))}


def _description(cue):
    return f"{cue['action']} at {cue['seconds']:g}s · {cue['title']}"


def login_to_homeserver(origin, *, secrets=None, request=fanrooms._request, login=browser_token):
    message = fanrooms.login_to_homeserver(
        origin, secrets=secrets, request=request, prompt=lambda approved: login(approved, request)
    )
    return {"message": message}


def run(args, *, secrets=None, request=fanrooms._request, login=browser_token, clock=time.time):
    if args and args[0].casefold() == "login" and len(args) == 2:
        return login_to_homeserver(args[1], secrets=secrets, request=request, login=login)
    return run_room_command(args, secrets=secrets, request=request, clock=clock)


def run_room_command(args, *, secrets=None, request=fanrooms._request, clock=time.time):
    action, *values = args or ["help"]
    action = action.casefold()
    if action == "help":
        return {"message": HELP}
    if action == "login":
        raise ValueError("Usage: jam login https://homeserver")
    store = secrets if secrets is not None else KeyringPairingSecrets(service="io.github.vivojay.mariana.matrix")
    try:
        if action in ("status", "rooms", "join", "leave"):
            message = fanrooms.run_room_command(action, values, secrets=store, request=request)
            result = {"message": message}
            if action == "join":
                result["room_id"] = message.removeprefix("Joined ")
            return result
        saved = store.get(fanrooms._ACCOUNT)
        if not saved:
            raise ValueError("Sign in with jam login https://homeserver first.")
        origin, token, account = fanrooms._credentials(saved)

        def call(method, path, **kwargs):
            return request(origin, token, method, path, **kwargs)

        if action == "logout" and not values:
            call("POST", "logout", json={})
            if store.get(fanrooms._ACCOUNT) == saved:
                store.delete(fanrooms._ACCOUNT)
            return {"message": "Signed out of this Matrix session."}
    except PairingError:
        raise ValueError("Matrix login requires a supported operating-system credential store.") from None
    if action == "create" and values:
        name = _text(" ".join(values))
        result = call("POST", "createRoom", json={
            "name": name, "preset": "private_chat", "visibility": "private",
            "creation_content": {"type": ROOM_TYPE, HOST: account},
            "power_level_content_override": {"events": {CUE: 100, SUGGEST: 0}},
        })
        room_id = result.get("room_id")
        if not isinstance(room_id, str):
            raise ValueError("Room creation unconfirmed. Check jam rooms before retrying.")
        fanrooms._identifier(room_id, "!")
        return {"room_id": room_id, "message": f"Created {name} · {room_id}"}
    if action == "invites" and not values:
        empty = {"types": []}
        sync_filter = {"presence": empty, "account_data": empty, "room": {
            "timeline": empty, "state": empty, "ephemeral": empty, "account_data": empty}}
        rooms = call("GET", "sync", params={"filter": json.dumps(sync_filter), "timeout": 0}).get("rooms", {})
        entries = rooms.get("invite", {}) if isinstance(rooms, dict) else None
        if not isinstance(entries, dict):
            raise ValueError("Homeserver returned invalid invitations.")
        return {"message": "\n".join(fanrooms._display(r) for r in entries) or "No pending room invitations."}
    if not values or action not in {"members", "invite", "suggest", "timeline", "cue", "current", "sync"}:
        raise ValueError(HELP)
    room = "rooms/" + fanrooms._identifier(values[0], "!") + "/"
    joined_rooms = call("GET", "joined_rooms").get("joined_rooms")
    if not isinstance(joined_rooms, list) or values[0] not in joined_rooms:
        raise ValueError("Join this room before using its listening controls.")
    info = call("GET", room + "state/m.room.create")
    host = info.get(HOST)
    if info.get("type") != ROOM_TYPE or not isinstance(host, str):
        raise ValueError("This room is not a Mariana jam. Use jam create NAME or open it with fanroom.")
    if action == "members" and len(values) == 1:
        joined = call("GET", room + "joined_members").get("joined")
        if not isinstance(joined, dict):
            raise ValueError("Homeserver returned invalid membership.")
        return {"message": "\n".join(fanrooms._display(user) + (" (host)" if user == host else "")
                                     for user in sorted(joined))}
    if action == "invite" and len(values) == 2:
        fanrooms._identifier(values[1], "@")
        call("POST", room + "invite", json={"user_id": values[1]})
        return {"message": "Invited " + values[1]}
    fanrooms._require_plain_room(origin, token, room, request)
    if action == "suggest" and len(values) >= 2:
        message = fanrooms._send_event(origin, token, room, SUGGEST, {"title": _text(" ".join(values[1:]))}, request)
        return {"message": message}
    if action == "cue" and len(values) >= 4:
        if account != host:
            raise ValueError("Only the host can publish playback cues.")
        cue = _cue({"action": values[1], "seconds": float(values[2]), "title": " ".join(values[3:])})
        result = call("PUT", room + "state/" + CUE, json=cue)
        if not isinstance(result.get("event_id"), str):
            raise ValueError("Cue delivery unconfirmed. Check jam current before retrying.")
        return {"cue": cue, "message": "Shared " + _description(cue)}
    if action in {"current", "sync"} and len(values) == 1:
        event = call("GET", room + "state/" + CUE, params={"format": "event"}, missing=True)
        if event is None:
            return {"message": "The host has not shared a cue yet."}
        if "event_id" in event:
            # Confirm the ID against the room timeline. An older server may
            # ignore format=event and return arbitrary event content instead.
            event_id = event["event_id"]
            if not isinstance(event_id, str):
                raise ValueError("The host cue had no valid Matrix event ID.")
            event = call("GET", room + "event/" + fanrooms._identifier(event_id, "$"))
            if event.get("event_id") != event_id:
                raise ValueError("The host cue event could not be verified.")
        else:
            # Older homeservers return only the content. Verify the author of a
            # matching timeline event before using its data for local playback.
            entries = call("GET", room + "messages", params={"dir": "b", "limit": 50,
                "filter": json.dumps({"types": [CUE], "senders": [host]})}).get("chunk")
            event = next((entry for entry in entries if isinstance(entry, dict) and entry.get("content") == event),
                         {}) if isinstance(entries, list) else {}
        if (event.get("type") != CUE or event.get("sender") != host or event.get("state_key") != ""
                or event.get("room_id", values[0]) != values[0] or not isinstance(event.get("content"), dict)):
            raise ValueError("Could not verify that the room host published this cue.")
        cue = _cue(event["content"])
        if action == "sync" and cue["action"] == "play":
            issued = event.get("origin_server_ts")
            if type(issued) is not int or not 0 < issued < 2**53:
                raise ValueError("This server did not timestamp the host cue. Use jam apply for the fixed mark.")
            cue["seconds"] += max(0.0, clock() - issued / 1000)
        return {"cue": cue, "message": _description(cue)}
    if action == "timeline" and len(values) == 1:
        entries = call("GET", room + "messages", params={
            "dir": "b", "limit": 50, "filter": json.dumps({"types": [CUE, SUGGEST]})}).get("chunk")
        if not isinstance(entries, list):
            raise ValueError("Invalid Matrix room timeline.")
        lines = []
        for event in reversed(entries):
            if not isinstance(event, dict) or not isinstance(event.get("content"), dict):
                continue
            sender = fanrooms._display(event.get("sender"))
            content = event["content"]
            try:
                if event.get("type") == CUE and sender == host:
                    lines.append("Host cue · " + _description(_cue(content)))
                elif event.get("type") == SUGGEST:
                    lines.append(sender + " suggested " + _text(content.get("title")))
            except (ValueError, OverflowError):
                continue
        return {"message": "\n".join(lines) or "No recent suggestions or playback cues."}
    raise ValueError(HELP)
