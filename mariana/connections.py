"""Local account consent, keychain storage, profile bookmarks and read-only lists."""
from __future__ import annotations

import hmac
import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

from . import account_services as service
from .account_services import PROVIDERS, AccountError

CALLBACK_PORT = 8789
HELP = ("accounts list | connect SERVICE | finish lastfm | verify SERVICE | activity SERVICE | "
        "link SERVICE username | open SERVICE | unlink SERVICE | disconnect SERVICE")
TTL = 300


class Accounts:
    def __init__(self, database, vault=None, port=CALLBACK_PORT):
        self.db = database
        self.vault = vault
        self.port = port
        self.lock = threading.RLock()
        self.pending = None
        self.notice = {}

    def stored(self, method, provider, *args):
        if self.vault is None:
            from .paired_trust import KeyringPairingSecrets
            self.vault = KeyringPairingSecrets(service="io.github.vivojay.mariana.accounts")
        try:
            return getattr(self.vault, method)(provider, *args)
        except Exception:
            raise AccountError("Unlock or enable the operating-system credential store to use sign-in.") from None

    def public(self, provider):
        return self.db.get_state("connections.identity." + provider, None)

    def bookmark(self, provider):
        return self.db.get_state("connections.link." + provider, "")

    def status(self):
        self.expire()
        return [{"id": provider, **entry, "available": service.enabled(provider), "identity": self.public(provider),
                 "link": self.bookmark(provider), "pending": bool(self.pending and self.pending["provider"] == provider),
                 "notice": self.notice.get(provider, "")} for provider, entry in PROVIDERS.items()]

    def expire(self):
        if self.pending and time.monotonic() >= self.pending["deadline"]:
            self.notice[self.pending["provider"]] = "Sign-in expired. Connect again."
            self.pending = None

    def start(self, provider):
        if not service.enabled(provider):
            raise AccountError("Sign-in is unavailable in this build. You can save and open a public profile.")
        self.expire()
        if self.pending:
            raise AccountError("An authorization is in progress. Finish or cancel that sign-in first.")
        self.stored("get", provider)  # Confirm a protected store before asking for consent.
        state = secrets.token_urlsafe(32)
        attempt = {"provider": provider, "state": state, "verifier": secrets.token_urlsafe(64),
                   "deadline": time.monotonic() + TTL}
        if provider == "lastfm":
            token = service.last_request("auth.getToken").get("token")
            if not isinstance(token, str) or not token:
                raise AccountError("Last.fm did not supply an authorization request.")
            attempt["token"] = token
            url = "https://www.last.fm/api/auth/?" + urlencode({"api_key": service.settings(provider)[0], "token": token})
        else:
            host = "localhost" if provider == "musicbrainz" else "127.0.0.1"
            try:
                server = ThreadingHTTPServer(("127.0.0.1", self.port), self.callback_handler(attempt, host))
            except OSError:
                raise AccountError("The local sign-in port is busy. Complete sign-in in the other Mariana window.") from None
            attempt["callback"] = f"http://{host}:{server.server_port}/accounts/callback"
            attempt["server"] = server
            url = service.authorize(provider, attempt["callback"], state, attempt["verifier"])
        self.notice.pop(provider, None)
        self.pending = attempt
        if provider != "lastfm":
            threading.Thread(target=self.wait, args=(attempt,), name="mariana-consent", daemon=True).start()
        return url

    def wait(self, attempt):
        server = attempt["server"]
        with server:
            server.timeout = 0.25
            while True:
                with self.lock:
                    self.expire()
                    if self.pending is not attempt:
                        return
                server.handle_request()

    def callback_handler(self, attempt, host):
        account = self

        class Callback(BaseHTTPRequestHandler):
            server: ThreadingHTTPServer

            def log_message(self, *_):
                pass  # A callback URL contains a single-use code.

            def do_GET(self):
                target = urlsplit(self.path)
                try:
                    params = parse_qs(target.query, max_num_fields=32)
                except ValueError:
                    self.send_error(400, "Invalid authorization response")
                    return
                state = params.get("state", [])
                code = params.get("code", [])
                allowed = (self.headers.get("Host") == f"{host}:{self.server.server_port}"
                           and target.path == "/accounts/callback" and len(state) == 1
                           and hmac.compare_digest(state[0].encode(), attempt["state"].encode()))
                with account.lock:
                    account.expire()
                    if not allowed or account.pending is not attempt:
                        self.send_error(400, "Invalid or expired sign-in request")
                        return
                    account.pending = None  # Consume once, including on denial.
                    provider = attempt["provider"]
                    try:
                        if params.get("error") or len(code) != 1 or not code[0]:
                            raise AccountError("Sign-in was declined. You can try again.")
                        row = service.tokens(provider, grant_type="authorization_code", code=code[0],
                                             redirect_uri=attempt["callback"], code_verifier=attempt["verifier"])
                        person = service.identity(provider, row["access_token"])
                        account.save(provider, row, person)
                        message = "Connected. You can close this tab and return to Mariana."
                    except (AccountError, OSError) as error:
                        message = str(error)
                    account.notice[provider] = message
                content = message.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                self.wfile.write(content)

        return Callback

    def save(self, provider, tokens, person):
        try:
            expires = time.time() + max(0, int(tokens.get("expires_in", 3600)))
        except (ValueError, TypeError):
            raise AccountError("The service returned an invalid token lifetime.") from None
        saved = {**person, "access_token": tokens["access_token"], "refresh_token": tokens.get("refresh_token", ""),
                 "expires": expires}
        self.stored("set", provider, json.dumps(saved))
        self.db.set_state("connections.identity." + provider, person)

    def finish_lastfm(self):
        self.expire()
        if not self.pending or self.pending["provider"] != "lastfm":
            raise AccountError("Choose Connect to Last.fm first.")
        row = service.last_request("auth.getSession", token=self.pending["token"]).get("session") or {}
        name, token = service.clean(row.get("name")), row.get("key")
        if not name or not isinstance(token, str) or not token:
            raise AccountError("Last.fm did not confirm your account identity.")
        self.pending = None
        self.save("lastfm", {"access_token": token}, {"id": name, "name": name, "url": service.profile_url("lastfm", name)})
        return "Connected to Last.fm as " + name + "."

    def credential(self, provider):
        raw = self.stored("get", provider)
        if not raw:
            raise AccountError("Connect this service first.")
        try:
            account = json.loads(raw)
        except ValueError:
            raise AccountError("The saved connection is unreadable. Disconnect and reconnect.") from None
        if provider != "lastfm" and time.time() + 60 >= account["expires"]:
            refresh = account.get("refresh_token")
            if not refresh:
                raise AccountError("This session has expired. Connect again.")
            updated = service.tokens(provider, grant_type="refresh_token", refresh_token=refresh)
            updated.setdefault("refresh_token", refresh)
            person = service.identity(provider, updated["access_token"])
            if person["id"] != account["id"]:
                raise AccountError("The provider returned a different identity. Reconnect explicitly.")
            self.save(provider, updated, person)
            account.update(updated)
        return account

    def run(self, args):
        with self.lock:
            if not args or args == ["list"]:
                return {"services": self.status()}
            if args == ["help"]:
                return {"message": HELP}
            if len(args) < 2 or args[1] not in PROVIDERS:
                raise AccountError(HELP)
            action, provider, *values = args
            if action == "link" and values:
                url = service.profile_url(provider, " ".join(values))
                self.db.set_state("connections.link." + provider, url)
                return {"message": "Saved public profile link.", "link": url}
            if values:
                raise AccountError(HELP)
            if action == "connect":
                return {"authorize": self.start(provider), "message": "Approve sign-in in your browser."}
            if action == "finish" and provider == "lastfm":
                return {"message": self.finish_lastfm()}
            if action == "cancel":
                if self.pending and self.pending["provider"] == provider:
                    self.pending = None
                    return {"message": "Sign-in cancelled."}
                raise AccountError("No sign-in in progress for this service.")
            if action == "unlink":
                self.db.set_state("connections.link." + provider, "")
                return {"message": "Removed public profile link."}
            if action == "disconnect":
                if self.pending and self.pending["provider"] == provider:
                    self.pending = None
                self.stored("delete", provider)
                self.db.set_state("connections.identity." + provider, None)
                self.notice.pop(provider, None)
                return {"message": "Removed the local account grant. You can revoke Mariana in the provider's app settings."}
            if action == "open":
                return {"open": self.bookmark(provider) or (self.public(provider) or {}).get("url") or PROVIDERS[provider]["site"]}
            if action == "activity" and provider == "listenbrainz":
                profile = self.bookmark(provider)
                if not profile:
                    raise AccountError("Save a ListenBrainz profile link first.")
                username = urlsplit(profile).path.rsplit("/", 1)[-1]
                data = service.api("GET", f"https://api.listenbrainz.org/1/user/{username}/listens", params={"count": 10})
                listens = (data.get("payload") or {}).get("listens") or []
                rows = [t.get("track_metadata") or {} for t in listens if isinstance(t, dict)]
                return {"items": [service.clean(t.get("track_name")) + " · " + service.clean(t.get("artist_name")) for t in rows]}
            if action in ("activity", "verify"):
                account = self.credential(provider)
                if action == "activity":
                    return {"items": service.listening(provider, account)}
                if provider == "lastfm":
                    row = service.last_request("user.getInfo", sk=account["access_token"]).get("user") or {}
                    if service.clean(row.get("name")).casefold() != account["id"].casefold():
                        raise AccountError("Last.fm could not verify your account. Connect again.")
                else:
                    who = service.identity(provider, account["access_token"])
                    if who["id"] != account["id"]:
                        raise AccountError("Your identity has changed. Connect again.")
                    self.db.set_state("connections.identity." + provider, who)
                return {"message": "Account verified by " + PROVIDERS[provider]["name"] + "."}
            raise AccountError(HELP)


_instance = None
_init_lock = threading.Lock()


def hub(database=None):
    global _instance
    with _init_lock:
        if _instance is None:
            if database is None:
                from .database import MarianaDatabase
                from .paths import runtime_paths
                database = MarianaDatabase(runtime_paths().database)
            _instance = Accounts(database)
        return _instance


def command(arguments, database):
    result = hub(database).run(arguments)
    if "services" in result:
        lines = []
        for item in result["services"]:
            status = ("verified as " + item["identity"]["name"] if item["identity"] else
                      "sign-in available" if item["available"] else "public profiles")
            lines.append(f"{item['id']} · {status}" + (" · " + item["link"] if item["link"] else "")
                         + (" · " + item["notice"] if item["notice"] else ""))
        return "\n".join([*lines, HELP])
    if "authorize" in result or "open" in result:
        target = result.get("authorize") or result["open"]
        try:
            opened = webbrowser.open(target)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            if "authorize" in result:
                hub(database).run(["cancel", arguments[1]])
            # Never put authorization URLs, which may contain request credentials, in the transcript.
            raise AccountError("Could not open the default browser. Set a default browser and try again.")
        return ("Approve in Last.fm, then enter accounts finish lastfm." if arguments == ["connect", "lastfm"]
                else "Opened in your default browser. Use accounts list to check the result.")
    return result.get("message") or "\n".join(result.get("items", [])) or "No entries."
