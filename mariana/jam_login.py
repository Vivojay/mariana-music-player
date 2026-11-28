"""One-use browser login on a chosen Matrix homeserver."""
import secrets
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, quote, urlsplit


def browser_token(origin, request, open_browser=webbrowser.open, ttl=120):
    flows = request(origin, None, "GET", "login").get("flows", [])
    if not isinstance(flows, list) or not any(isinstance(flow, dict) and flow.get("type") == "m.login.sso" for flow in flows):
        raise ValueError("This homeserver does not offer Matrix browser SSO. Use fanroom login in the native terminal.")
    callback_path = "/finish/" + secrets.token_urlsafe(24)
    login_token = None

    class Callback(BaseHTTPRequestHandler):
        server: HTTPServer

        def setup(self):
            super().setup()
            self.connection.settimeout(3)

        def log_message(self, *_args):
            pass  # Callback URLs include a one-use login token.

        def do_GET(self):
            nonlocal login_token
            target = urlsplit(self.path)
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}" or target.path != callback_path:
                self.send_error(404)
                return
            values = parse_qs(target.query).get("loginToken", [])
            if len(values) != 1 or not 1 <= len(values[0]) <= 4096:
                self.send_error(400)
                return
            login_token = values[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(b"Return to Mariana to see your sign-in result.")

    with HTTPServer(("127.0.0.1", 0), Callback) as server:
        redirect = f"http://127.0.0.1:{server.server_port}{callback_path}"
        if not open_browser(origin + "/_matrix/client/v3/login/sso/redirect?redirectUrl=" + quote(redirect, safe="")):
            raise ValueError("Could not open a browser for Matrix sign-in.")
        deadline = time.monotonic() + ttl
        while login_token is None and time.monotonic() < deadline:
            server.timeout = min(1, max(0, deadline - time.monotonic()))
            server.handle_request()
    if login_token is None:
        raise ValueError("Matrix browser sign-in expired. Start sign-in again.")
    return request(origin, None, "POST", "login", json={
        "type": "m.login.token", "token": login_token, "initial_device_display_name": "Mariana",
    }).get("access_token")
