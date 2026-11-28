"""Live loopback and foreground command ownership for the browser companion."""
import http.client
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from mariana.web_session import NativeSession, make_server, serve_session

ASSETS = Path(__file__).resolve().parents[1] / "web/player"


def post(port, path, bearer, data=None, **headers):
    head = {"Origin": f"http://127.0.0.1:{port}", "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}", **headers}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        conn.request("POST", "/api/" + path, json.dumps(data or {}), head)
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def test_native_server_is_origin_bound_one_time_and_expires():
    now = [0]
    session = NativeSession(clock=lambda: now[0])
    visible = [True]
    with make_server(session, ASSETS, [], lambda: visible[0]) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port, invite = server.server_port, session.invite
            for header in ({"Origin": "https://other.example"}, {"Host": "other.example"},
                           {"Sec-Fetch-Site": "cross-site"}, {"Content-Type": "text/plain"}):
                assert post(port, "pair", invite, **header)[0] in {403, 415}
            assert post(port, "pair", invite[:-1])[0] == 403
            assert post(port, "state", invite)[0] == 403
            code, result = post(port, "pair", invite)
            assert code == 200 and result["catalog"] == []
            token = result["token"]
            assert post(port, "pair", invite)[0] == 403
            assert post(port, "assist", invite, {"line": "d", "cursor": 1})[0] == 403
            for bad_cursor in (-1, 1, 4):
                # The clef occupies two UTF-16 units, so 1 splits a code point.
                assert post(port, "assist", token, {"line": "𝄞", "cursor": bad_cursor})[0] == 400
            code, options = post(port, "assist", token, {"line": "hotspots st", "cursor": 11})
            assert code == 200
            assert any("status" in opt["value"] for opt in options["suggestions"])
            assert session.job is None
            for invalid in ("x\nnext", "", "web session", "\u202etitle"):
                assert post(port, "command", token, {"command": invalid})[0] == 400
            assert post(port, "command", token, {"command": "karaoke status"})[0] == 202
            assert post(port, "command", token, {"command": "p"})[0] == 409
            assert session.take() == "karaoke status"
            assert post(port, "state", token)[1]["job"]["state"] == "review"
            assert session.take() is None
            visible[0] = False
            assert post(port, "state", token)[0] == 410
            visible[0] = True
            now[0] = 91
            assert post(port, "state", token)[0] == 410
        finally:
            server.shutdown()
            thread.join(2)


def test_browser_command_runs_in_foreground_with_terminal_review_and_private_output():
    ready = threading.Event()
    invitation = []
    opened = []
    worker_errors = []
    results = []
    answers = iter(["", "r", "s"])

    def launch(url):
        invitation.append(url)
        ready.set()

    def dispatch(cmd):
        opened.append(cmd)
        print(f"output of {cmd}")
        return None

    def browser():
        try:
            assert ready.wait(3)
            url = urlparse(invitation[0])
            port = url.port
            key = parse_qs(url.fragment)["pair"][0]
            token = post(port, "pair", key)[1]["token"]
            for command in ["now", "quit --yes", "private example", "help lyrics"]:
                assert post(port, "command", token, {"command": command})[0] == 202
                end = time.monotonic() + 3
                while time.monotonic() < end:
                    _, result = post(port, "state", token)
                    job = result["job"]
                    if job["state"] == "done":
                        assert result["playback"]["title"] == "My music"
                        assert "uri" not in result["playback"]
                        results.append(job["output"])
                        break
                    time.sleep(.02)
                else:
                    pytest.fail("The terminal did not complete the submitted command")
            assert post(port, "close", token)[0] == 200
        except BaseException as error:
            worker_errors.append(error)

    thread = threading.Thread(target=browser, daemon=True)
    thread.start()
    serve_session(assets=ASSETS, catalog=[], project=lambda: SimpleNamespace(title="My music", uri="private"),
                  dispatch=dispatch, available=lambda: not worker_errors, open_browser=launch,
                  read=lambda _: next(answers), write=lambda _: None)
    thread.join(3)
    assert not worker_errors, worker_errors
    assert opened == ["now", "private example", "help lyrics"]
    assert results == ["output of now", "Skipped at the Mariana terminal.", "Command finished in the terminal.",
                       "output of help lyrics"]


def test_terminal_review_closes_when_browser_leaves(monkeypatch):
    import prompt_toolkit
    from prompt_toolkit.input.defaults import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    from mariana.web_session import review_at_terminal

    with create_pipe_input() as pipe:
        native = prompt_toolkit.PromptSession(input=pipe, output=DummyOutput())
        monkeypatch.setattr(prompt_toolkit, "PromptSession", lambda: native)
        end = time.monotonic() + .08
        assert review_at_terminal("Review the request: ", lambda: time.monotonic() < end) == ""


def test_native_library_is_opt_in_and_bound_to_the_presented_recording():
    records = [(f"Title {n}", "Artist · Album" if n % 2 else "Video", f"play {n}",
                f"/private/folder/{n}.wav") for n in range(1, 47)]
    session = NativeSession()
    session.library = lambda: records
    session.library_path = lambda number: records[number - 1][3] if 0 < number <= len(records) else None
    status, paired = session.request("pair", session.invite, {"library": True}, [])
    assert status == 200
    token = paired["token"]
    assert session.request("library", "wrong", {}, [])[0] == 403
    assert session.request("library", token, {"offset": -1}, [])[0] == 400
    status, page = session.request("library", token, {"query": "ARTIST album", "offset": 1}, [])
    assert status == 200 and page["total"] == 23 and page["rows"][0]["number"] == 3
    assert set(page["rows"][0]) == {"number", "title", "detail", "key"}
    assert "/private" not in json.dumps(page)
    status, last_page = session.request("library", token, {"offset": 40}, [])
    assert status == 200 and last_page["rows"][0]["number"] == 41 and len(last_page["rows"]) == 6
    key = page["rows"][0]["key"]
    records[2], records[3] = records[3], records[2]
    status, _ = session.request("command", token, {"command":"play 3","libraryKey":key}, [])
    assert status == 409 and session.job is None
    status, _ = session.request("command", token, {"command":"queue add 4","libraryKey":key}, [])
    assert status == 202 and session.take() == "queue add 4" and session.job["state"] == "review"
    assert session.library_matches(*session.library_request)
    records[2], records[3] = records[3], records[2]
    assert not session.library_matches(*session.library_request)

    private = NativeSession()
    private.library = lambda: records
    _, paired = private.request("pair", private.invite, {}, [])
    assert not paired["library"]
    assert private.request("library", paired["token"], {}, [])[0] == 403


def test_session_approval_local_commands_and_browser_controls():
    import queue

    invite_ready = threading.Event()
    running = threading.Event()
    errors, dispatched, reviews, receipts = [], [], [], []
    terminal = queue.Queue()
    invitation = []

    def launch(url):
        invitation.append(url)
        invite_ready.set()

    def host_read(active, draft):
        while active():
            try:
                return True, terminal.get(timeout=.015)
            except queue.Empty:
                pass
        return False, draft

    def review(question):
        reviews.append(question)
        return "as" if len(reviews) == 1 else ""

    def dispatch(line):
        assert threading.get_ident() == owner
        dispatched.append(line)
        print(f"output {line}")

    def until(port, token, predicate):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            code, value = post(port, "state", token)
            assert code == 200
            if predicate(value):
                return value
            time.sleep(.015)
        raise AssertionError("Session did not publish the expected state.")

    def browser():
        try:
            assert invite_ready.wait(3)
            url = urlparse(invitation[0])
            key = parse_qs(url.fragment)["pair"][0]
            _, connected = post(url.port, "pair", key)
            token, port = connected["token"], url.port
            assert connected["session"]["mode"] == "review"

            def run(line):
                code, accepted = post(port, "command", token, {"command":line})
                assert code == 202, accepted
                return until(port, token, lambda s: s["job"]["id"] == accepted["id"]
                             and s["job"]["state"] == "done")

            first = run("help lyrics")
            assert first["session"]["mode"] == "session" and first["session"]["shareOutput"]
            assert first["job"]["output"] == "output help lyrics"
            assert run("queue list")["job"]["output"] == "output queue list"

            terminal.put("queue tree")
            terminal.put("web view flow")
            state = until(port, token, lambda s: bool(s["browserAction"]))
            event = state["browserAction"]
            assert (event["action"], event["value"]) == ("view", "flow")
            assert until(port,token, lambda s: True)["browserAction"] == event
            assert post(port, "browser-ack", key, {"id":event["id"]})[0] == 403
            assert post(port, "browser-ack", token, {"id":"bad"})[0] == 400
            assert post(port, "browser-ack", token, {"id":event["id"]})[0] == 200
            until(port, token, lambda s: s["browserAction"] is None)
            terminal.put("web status")
            assert post(port, "command", token, {"command":'"web" approve share'})[0] == 400
            assert post(port, "revoke", token)[1]["session"]["mode"] == "review"
            assert run("help playback")["job"]["output"] == "Skipped at the Mariana terminal."
            terminal.put("web close")
            running.set()
        except BaseException as error:
            errors.append(error)
            running.set()

    owner = threading.get_ident()
    thread = threading.Thread(target=browser, daemon=True)
    thread.start()
    serve_session(assets=ASSETS, catalog=[], project=SimpleNamespace, dispatch=dispatch,
                  available=lambda: not errors, open_browser=launch, read=review, terminal_read=host_read,
                  write=receipts.append)
    thread.join(4)
    assert running.is_set() and not errors, errors
    assert dispatched == ["help lyrics", "queue list", "queue tree"]
    assert len(reviews) == 2
    assert any("acknowledged" in receipt for receipt in receipts)


def test_trust_is_per_session_and_browser_actions_expire():
    from mariana.web_session import ACTION_LIMIT, SESSION_LIMIT, terminal_control
    now = [0]
    session = NativeSession(clock=lambda:now[0], trusted=True)
    review = NativeSession(clock=lambda:now[0])
    assert review.request("pair", review.invite, {}, [])[1]["session"]["mode"] == "review"
    _, paired = session.request("pair", session.invite, {}, [])
    token = paired["token"]
    assert paired["session"] == {"mode":"session", "shareOutput":False, "expirySeconds":SESSION_LIMIT}
    assert session.request("command", token, {"command":"queue list"}, [])[0] == 202
    assert session.take() == "queue list" and session.browser_policy("queue list") == (False, False)
    messages = []
    assert terminal_control(session, "web notice This is text.", messages.append)
    assert terminal_control(session, "web view console", messages.append)
    assert "waiting for acknowledgement" in messages[-1]
    now[0] += ACTION_LIMIT
    assert session.request("state", token, {}, [])[1]["browserAction"] is None
    assert "expired" in session.status()
    session.request("revoke", token, {}, [])
    assert session.browser_policy("queue list") == (True, False)
    now[0] = SESSION_LIMIT
    assert session.request("state", token, {}, [])[0] == 410
