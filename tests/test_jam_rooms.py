"""Two independent Mariana clients against a loopback HTTPS Matrix protocol fixture."""
import json
import shutil
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import ProxyHandler, build_opener

import pytest
import truststore

from mariana import fanrooms, jams
from mariana.jam_login import browser_token


class Memory(dict):
    def set(self, key, value):
        self[key] = value

    def delete(self, key):
        self.pop(key, None)


def test_two_user_jam(tmp_path, monkeypatch, request):
    openssl = shutil.which("openssl")
    if not openssl:
        pytest.skip("OpenSSL binary required for fixture HTTPS certificate.")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run([openssl, "req", "-x509", "-nodes", "-newkey", "rsa:2048", "-days", "1", "-subj", "/CN=localhost",
                    "-addext", "subjectAltName=DNS:localhost", "-keyout", str(key), "-out", str(cert)],
                   check=True, capture_output=True)
    # Use the standard TLS context throughout the fixture, including accepted
    # connections. The Matrix client still validates against the fixture CA.
    if ssl.SSLContext is truststore.SSLContext:
        truststore.extract_from_ssl()
        request.addfinalizer(truststore.inject_into_ssl)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(cert))
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    host, guest = "@host:test", "@guest:test"
    tokens = {"alice-token": host, "bob-token": guest}
    room_id = "!jam:test"
    members, invited, events, state = set(), set(), [], {}

    class Matrix(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, data):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self):
            target = unquote(urlsplit(self.path).path).removeprefix("/_matrix/client/v3/")
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            user = tokens.get(token)
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or "{}")
            if target == "login" and self.command == "GET" and not token:
                return self.reply(200, {"flows": [{"type": "m.login.sso"}]})
            if target == "login" and self.command == "POST" and data["token"] == "one-use" and not token:
                return self.reply(200, {"access_token": "alice-token"})
            if not user:
                return self.reply(401, {"errcode": "M_UNKNOWN_TOKEN"})
            if target == "account/whoami":
                return self.reply(200, {"user_id": user})
            if target == "logout":
                del tokens[token]
                return self.reply(200, {})
            if target == "createRoom":
                assert data["preset"] == "private_chat" and data["visibility"] == "private"
                assert data["power_level_content_override"]["events"][jams.CUE] == 100
                state["m.room.create"] = data["creation_content"]
                members.add(user)
                return self.reply(200, {"room_id": room_id})
            if target == "sync":
                return self.reply(200, {"rooms": {"invite": {room_id: {}} if user in invited else {}}})
            if target == "joined_rooms":
                return self.reply(200, {"joined_rooms": [room_id] if user in members else []})
            if target == "join/" + room_id and user in invited:
                members.add(user)
                invited.remove(user)
                return self.reply(200, {"room_id": room_id})
            if user not in members or not target.startswith(f"rooms/{room_id}/"):
                return self.reply(403, {"errcode": "M_FORBIDDEN"})
            operation = target.split("/", 2)[2]
            if operation == "invite":
                invited.add(data["user_id"])
            elif operation == "leave":
                members.remove(user)
            elif operation == "joined_members":
                return self.reply(200, {"joined": {key_0: {} for key_0 in members}})
            elif operation.startswith("event/"):
                result = next((item for item in events if item["event_id"] == operation.split("/")[1]), None)
                return self.reply(200, result) if result else self.reply(404, {"errcode": "M_NOT_FOUND"})
            elif operation == "messages":
                return self.reply(200, {"chunk": events[::-1]})
            elif operation.startswith("state/") and self.command == "GET":
                event = operation[6:]
                if event in state:
                    if event == jams.CUE and parse_qs(urlsplit(self.path).query).get("format") == ["event"]:
                        return self.reply(200, next(item for item in reversed(events) if item["type"] == jams.CUE))
                    return self.reply(200, state[event])
                return self.reply(404, {"errcode": "M_NOT_FOUND"})
            elif operation == "state/" + jams.CUE or operation.startswith("send/" + jams.SUGGEST + "/"):
                event = operation.split("/")[1]
                if event == jams.CUE:
                    if user != host:
                        return self.reply(403, {"errcode": "M_FORBIDDEN"})
                    state[event] = data
                entry = {"type": event, "sender": user, "content": data, "origin_server_ts": 1_000_000, "event_id": "$" + str(len(events) + 1)}
                if event == jams.CUE:
                    entry["state_key"] = ""
                events.append(entry)
                return self.reply(200, {"event_id": "$" + str(len(events))})
            else:
                return self.reply(404, {"errcode": "M_NOT_FOUND"})
            return self.reply(200, {})

        do_GET = do_POST = do_PUT = dispatch

    with ThreadingHTTPServer(("127.0.0.1", 0), Matrix) as server:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(cert, key)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            origin = f"https://localhost:{server.server_port}"
            a, b = Memory(), Memory()

            def sign_in(url):
                # The fixture acts as the external browser after an approved SSO sign-in.
                callback = parse_qs(urlsplit(url).query)["redirectUrl"][0]
                assert url.startswith(origin + "/_matrix/client/v3/login/sso/redirect?")
                def visit():
                    opener = build_opener(ProxyHandler({}))
                    with opener.open(callback + "?loginToken=one-use", timeout=4) as result:
                        assert result.status == 200
                threading.Thread(target=visit, daemon=True).start()
                return True

            def browser_login(origin, request):
                return browser_token(origin, request, open_browser=sign_in, ttl=5)

            assert host in jams.run(["login", origin], secrets=a, login=browser_login)["message"]
            fanrooms.run(["login", origin], secrets=b, prompt=lambda _: "bob-token")

            def run(store, *args):
                return jams.run(args, secrets=store)

            assert run(a, "create", "Evening rehearsal")["room_id"] == room_id
            with pytest.raises(ValueError, match="403"):
                run(b, "join", room_id)
            run(a, "invite", room_id, guest)
            assert room_id in run(b, "invites")["message"]
            assert run(b, "join", room_id)["room_id"] == room_id
            assert guest in run(a, "members", room_id)["message"]
            run(b, "suggest", room_id, "Practice piece")
            assert guest in run(a, "timeline", room_id)["message"]
            with pytest.raises(ValueError, match="Only the host"):
                run(b, "cue", room_id, "play", "12", "False cue")
            run(a, "cue", room_id, "seek", "14.5", "Practice piece")
            assert run(b, "current", room_id)["cue"] == {"title": "Practice piece", "seconds": 14.5, "action": "seek"}
            read = run(b, "timeline", room_id)["message"]
            assert "suggested Practice piece" in read and "seek at 14.5s" in read
            run(a, "cue", room_id, "play", "10", "Practice piece")
            sync = jams.run(["sync", room_id], secrets=b, clock=lambda: 1002.5)
            assert sync["cue"]["seconds"] == 12.5
            assert run(b, "current", room_id)["cue"]["seconds"] == 10
            events[-1]["sender"] = guest
            with pytest.raises(ValueError, match="verify"):
                run(b, "current", room_id)
            run(b, "leave", room_id)
            assert guest not in run(a, "members", room_id)["message"]
            with pytest.raises(ValueError, match="Join this room"):
                run(b, "current", room_id)
            run(b, "logout")
            assert not b and "bob-token" not in tokens
        finally:
            server.shutdown()
            worker.join(3)


def test_loopback_rooms_require_same_origin_and_dedicated_header(monkeypatch):
    from urllib.error import HTTPError
    from urllib.request import Request

    from tools.build_web_player import PlayerRequest

    monkeypatch.setattr(jams, "run_room_command", lambda args: {"message": "received " + args[0]})
    with ThreadingHTTPServer(("127.0.0.1", 0), PlayerRequest) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f"http://127.0.0.1:{server.server_port}"
        def post(origin, header):
            headers = {"Origin": origin, "Content-Type": "application/json"}
            if header:
                headers["X-Mariana-Jam"] = "1"
            req = Request(base + "/api/jam", headers=headers, data=b'["rooms"]', method="POST")
            return build_opener(ProxyHandler({})).open(req, timeout=3)
        try:
            for origin, header in [(base, False), ("https://elsewhere.test", True)]:
                with pytest.raises(HTTPError) as refused:
                    post(origin, header)
                assert refused.value.code == 403
            with post(base, True) as response:
                assert response.headers["Cache-Control"] == "no-store"
                assert json.load(response) == {"message": "received rooms"}
        finally:
            server.shutdown()
            worker.join(3)


def test_room_dispatchers_do_not_sign_in():
    def forbidden_request(*_args, **_kwargs):
        pytest.fail("Room commands must not start a Matrix sign-in.")

    with pytest.raises(ValueError, match="Usage: jam login"):
        jams.run_room_command(["LOGIN", "https://matrix.example.org"], secrets=Memory(), request=forbidden_request)
    with pytest.raises(ValueError, match="fanroom login"):
        fanrooms.run_room_command("login", ["https://matrix.example.org"], secrets=Memory(), request=forbidden_request)
