"""Exercise consent, provider identities, secure persistence and loopback origin checks."""

import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from mariana import account_services as services
from mariana import connections_http, jams
from mariana.connections import Accounts
from mariana.database import MarianaDatabase


class Vault(dict):
    def set(self, id, value):
        self[id] = value

    def delete(self, id):
        self.pop(id, None)


@pytest.fixture
def hub(tmp_path):
    db = MarianaDatabase(tmp_path / "accounts.db")
    account = Accounts(db, Vault(), port=0)
    yield account
    if account.pending:
        account.run(["cancel", account.pending["provider"]])
    db.close()


@pytest.mark.parametrize("provider", ["spotify", "musicbrainz", "youtube", "tiktok"])
def test_native_consent_verifies_provider_identity_and_keeps_tokens_in_vault(hub, monkeypatch, provider):
    monkeypatch.setenv("MARIANA_" + provider.upper() + "_CLIENT_ID", "public-client")
    monkeypatch.setenv("MARIANA_" + provider.upper() + "_CLIENT_SECRET", "publisher-secret")
    requests = []
    uid = "UC" + "a" * 22

    def api(method, url, **kwargs):
        requests.append((method, url, kwargs))
        if "token" in url:
            return {"access_token": "access-private", "refresh_token": "refresh-private", "expires_in": 3600}
        if provider == "spotify":
            return {"name": "ignored", "display_name": "Listener", "account_id": "stable", "id": "listener"}
        if provider == "musicbrainz":
            return {"sub": "listener", "name": "Listener"}
        if provider == "youtube":
            return {"items": [{"id": uid, "snippet": {"title": "Listener"}}]}
        return {"data": {"user": {"open_id": "stable", "display_name": "Listener"}}}

    monkeypatch.setattr(services, "api", api)
    url = hub.run(["connect", provider])["authorize"]
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "publisher-secret" not in url and "access-private" not in url
    verifier = hub.pending["verifier"]
    if provider == "tiktok":
        assert query["code_challenge"] == [hashlib.sha256(verifier.encode()).hexdigest()]
    cb = query["redirect_uri"][0]
    browser = build_opener(ProxyHandler({}))
    with pytest.raises(HTTPError) as failure:
        browser.open(cb + "?code=test&state=bad", timeout=3)
    assert failure.value.code == 400 and hub.pending
    with browser.open(cb + "?" + urlencode({"code": "test", "state": query["state"][0]}), timeout=3) as response:
        assert "Connected" in response.read().decode()
    assert requests[0][2]["data"]["code_verifier"] == verifier
    assert hub.public(provider)["name"] == "Listener"
    assert "access-private" in hub.vault[provider]
    assert "access-private" not in json.dumps(hub.run(["list"]))
    assert "refresh-private" not in json.dumps(hub.db.get_state("connections.identity." + provider))
    hub.run(["disconnect", provider])
    assert not hub.vault and not hub.public(provider)


def test_lastfm_denial_and_approval_and_recent_listens(hub, monkeypatch):
    monkeypatch.setenv("MARIANA_LASTFM_API_KEY", "key")
    monkeypatch.setenv("MARIANA_LASTFM_API_SECRET", "secret")

    def api(method, url, **kwargs):
        row = dict(kwargs["data"])
        sig = row.pop("api_sig")
        assert row.pop("format") == "json"
        assert (
            sig
            == hashlib.md5(
                ("".join(k + row[k] for k in sorted(row)) + "secret").encode(), usedforsecurity=False
            ).hexdigest()
        )
        if row["method"] == "auth.getToken":
            return {"token": "grant"}
        if row["method"] == "auth.getSession":
            return {"session": {"name": "Listener", "key": "session"}}
        return {"recenttracks": {"track": [{"name": "Window", "artist": {"#text": "Suggahunny"}}]}}

    monkeypatch.setattr(services, "api", api)
    assert hub.run(["connect", "lastfm"])["authorize"].startswith("https://www.last.fm/")
    assert not hub.public("lastfm")
    assert "Listener" in hub.run(["finish", "lastfm"])["message"]
    assert hub.run(["activity", "lastfm"])["items"] == ["Window · Suggahunny"]
    with pytest.raises(ValueError, match="Connect"):
        hub.run(["finish", "lastfm"])


def test_profile_link_is_distinct_from_authorized_identity_and_works_without_registration(hub, monkeypatch):
    assert hub.run(["link", "bandcamp", "listener"])["link"] == "https://bandcamp.com/listener"
    assert hub.run(["open", "bandcamp"]) == {"open": "https://bandcamp.com/listener"}
    assert hub.public("bandcamp") is None
    with pytest.raises(ValueError):
        hub.run(["link", "bandcamp", "//foreign.test/path"])
    monkeypatch.delenv("MARIANA_SPOTIFY_CLIENT_ID", raising=False)
    with pytest.raises(ValueError, match="public profile"):
        hub.run(["connect", "spotify"])
    hub.run(["unlink", "bandcamp"])
    assert hub.run(["open", "bandcamp"])["open"] == "https://bandcamp.com/"
    hub.run(["link", "listenbrainz", "listener"])
    monkeypatch.setattr(
        services,
        "api",
        lambda *a, **k: {"payload": {"listens": [{"track_metadata": {"track_name": "Solo", "artist_name": "Artist"}}]}},
    )
    assert hub.run(["activity", "listenbrainz"])["items"] == ["Solo · Artist"]


def test_local_http_account_handler_requires_exact_origin_and_custom_header(hub, monkeypatch):
    monkeypatch.setattr(connections_http, "hub", lambda: hub)

    class API(BaseHTTPRequestHandler):
        def do_POST(self):
            assert connections_http.handle_accounts_post(self)

        def log_message(self, *_):
            pass

    browser = build_opener(ProxyHandler({}))
    with ThreadingHTTPServer(("127.0.0.1", 0), API) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        origin = f"http://127.0.0.1:{server.server_port}"

        def post(origin_header, csrf):
            return browser.open(
                Request(
                    origin + "/api/accounts",
                    data=b'["list"]',
                    headers={"Origin": origin_header, "Content-Type": "application/json", "X-Mariana-Accounts": csrf},
                ),
                timeout=2,
            )

        try:
            with pytest.raises(HTTPError) as denied:
                post("https://foreign.example", "1")
            assert denied.value.code == 403
            with pytest.raises(HTTPError) as denied:
                post(origin, "")
            assert denied.value.code == 403
            with post(origin, "1") as response:
                assert len(json.load(response)["services"]) == len(services.PROVIDERS)
        finally:
            server.shutdown()


def test_browser_jam_login_requires_launcher_approved_origin(monkeypatch):
    executed = []
    monkeypatch.setattr(jams, "run_room_command", executed.append)
    monkeypatch.setattr(jams, "login_to_homeserver", lambda origin: executed.append(["login", origin]))
    monkeypatch.setattr(
        connections_http, "_local_post", lambda handler, _path, _header, execute, *_limits: execute(handler)
    )
    monkeypatch.delenv("MARIANA_MATRIX_ORIGIN", raising=False)
    with pytest.raises(services.AccountError, match="native terminal"):
        connections_http.handle_jam_post(["login", "https://matrix.example.org"])
    monkeypatch.setenv("MARIANA_MATRIX_ORIGIN", "https://matrix.example.org")
    with pytest.raises(services.AccountError, match="configured for this launcher"):
        connections_http.handle_jam_post(["login", "https://other.example.org"])
    assert executed == []
    connections_http.handle_jam_post(["login", "https://MATRIX.example.org/"])
    connections_http.handle_jam_post(["rooms"])
    assert executed == [["login", "https://matrix.example.org"], ["rooms"]]
