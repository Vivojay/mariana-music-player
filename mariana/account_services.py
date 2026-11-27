"""Provider-specific consent, identity and read-only music APIs."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

PROVIDERS = json.loads(Path(__file__).with_name("connection_providers.json").read_text(encoding="utf-8"))
LAST_API = "https://ws.audioscrobbler.com/2.0/"
OAUTH = {
    "spotify": ("https://accounts.spotify.com/authorize", "https://accounts.spotify.com/api/token",
                "user-read-private playlist-read-private"),
    "musicbrainz": ("https://musicbrainz.org/oauth2/authorize", "https://musicbrainz.org/oauth2/token", "profile"),
    "youtube": ("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
                "https://www.googleapis.com/auth/youtube.readonly"),
    "tiktok": ("https://www.tiktok.com/v2/auth/authorize/", "https://open.tiktokapis.com/v2/oauth/token/",
               "user.info.basic"),
}


class AccountError(ValueError):
    pass


def settings(provider):
    prefix = f"MARIANA_{provider.upper()}_"
    key = os.getenv(prefix + ("API_KEY" if provider == "lastfm" else "CLIENT_ID"), "").strip()
    secret = os.getenv(prefix + ("API_SECRET" if provider == "lastfm" else "CLIENT_SECRET"), "").strip()
    if key and (provider == "spotify" or secret):
        return key, secret
    from .connector_registration import read
    return read(provider)


def enabled(provider):
    if provider not in OAUTH and provider != "lastfm":
        return False
    key, secret = settings(provider)
    return bool(key and (provider == "spotify" or secret))


def clean(value):
    return " ".join("".join(c for c in value if c.isprintable()).split())[:200] if isinstance(value, str) else ""


def profile_url(provider, handle):
    handle = handle.strip().removeprefix("@")
    pattern = r"[\w.-][\w. -]{0,79}" if provider in ("musicbrainz", "listenbrainz") else r"[\w.-]{1,80}"
    if provider == "youtube":
        pattern = r"UC[\w-]{22}"
    if not re.fullmatch(pattern, handle) or handle in (".", ".."):
        raise AccountError("Enter a valid " + PROVIDERS[provider]["hint"] + ".")
    return PROVIDERS[provider]["profile"] + quote(handle, safe="")


def api(method, url, **kwargs):
    headers = {"Accept": "application/json", "User-Agent": "Mariana/0.7 (https://github.com/Vivojay/mariana-music-player)"}
    headers.update(kwargs.pop("headers", {}))
    try:
        response = requests.request(method, url, headers=headers, timeout=(4, 12), allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise AccountError(f"The service returned HTTP {response.status_code}. Check access or reconnect.")
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        if isinstance(error, AccountError):
            raise
        raise AccountError("The service could not be reached or returned an unreadable response.") from None
    if not isinstance(data, dict):
        raise AccountError("The service returned an unexpected response.")
    return data


def last_request(method, **kwargs):
    key, secret = settings("lastfm")
    fields = {"method": method, "api_key": key, **kwargs}
    signature = "".join(k + str(fields[k]) for k in sorted(fields)) + secret
    # Last.fm specifies MD5 for its API signature; the transport is HTTPS.
    fields["api_sig"] = hashlib.md5(signature.encode("utf-8"), usedforsecurity=False).hexdigest()
    data = api("POST", LAST_API, data={**fields, "format": "json"})
    if data.get("error"):
        code = data.get("error")
        if code == 14:
            raise AccountError("Approve Mariana on Last.fm first, then choose Finish sign-in.")
        raise AccountError(f"Last.fm declined this request (code {code}).")
    return data


def authorize(provider, callback, state, verifier):
    key, _ = settings(provider)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = digest.hex() if provider == "tiktok" else base64.urlsafe_b64encode(digest).decode().rstrip("=")
    params = {"client_key" if provider == "tiktok" else "client_id": key, "scope": OAUTH[provider][2],
              "response_type": "code", "redirect_uri": callback, "state": state,
              "code_challenge_method": "S256", "code_challenge": challenge}
    if provider in ("youtube", "musicbrainz"):
        params["access_type"] = "offline"
    return OAUTH[provider][0] + "?" + urlencode(params)


def tokens(provider, **params):
    key, secret = settings(provider)
    client = {"client_key" if provider == "tiktok" else "client_id": key}
    if provider != "spotify":
        client["client_secret"] = secret
    row = api("POST", OAUTH[provider][1], data={**client, **params})
    if not isinstance(row.get("access_token"), str) or not row["access_token"]:
        raise AccountError("The provider did not issue an access token.")
    return row


def identity(provider, token):
    headers = {"Authorization": "Bearer " + token}
    if provider == "spotify":
        row = api("GET", "https://api.spotify.com/v1/me", headers=headers)
        uid = clean(row.get("account_id") or row.get("id"))
        handle = clean(row.get("id"))
        name = clean(row.get("display_name") or handle)
    elif provider == "youtube":
        data = api("GET", "https://www.googleapis.com/youtube/v3/channels", headers=headers,
                   params={"mine": "true", "part": "snippet", "maxResults": 1})
        row = next(iter(data.get("items") or []), {})
        uid = handle = clean(row.get("id"))
        name = clean((row.get("snippet") or {}).get("title"))
    elif provider == "tiktok":
        data = api("GET", "https://open.tiktokapis.com/v2/user/info/", headers=headers,
                   params={"fields": "open_id,display_name"})
        row = (data.get("data") or {}).get("user") or {}
        uid, name, handle = clean(row.get("open_id")), clean(row.get("display_name")), ""
    else:
        row = api("GET", "https://musicbrainz.org/oauth2/userinfo", headers=headers)
        uid = clean(row.get("sub"))
        name = clean(row.get("preferred_username") or row.get("name") or uid)
        handle = uid
    if not uid or not name:
        raise AccountError("The provider could not confirm your account identity.")
    url = ""
    if handle:
        try:
            url = profile_url(provider, handle)
        except AccountError:
            pass
    return {"id": uid, "name": name, "url": url}


def listening(provider, account):
    if provider == "lastfm":
        data = last_request("user.getRecentTracks", user=account["id"], limit="10")
        rows = (data.get("recenttracks") or {}).get("track", [])
        return [clean(t.get("name")) + " · " + clean((t.get("artist") or {}).get("#text"))
                for t in rows if isinstance(t, dict)]
    headers = {"Authorization": "Bearer " + account["access_token"]}
    if provider == "spotify":
        data = api("GET", "https://api.spotify.com/v1/me/playlists", headers=headers, params={"limit": 20})
        return [clean(p.get("name")) for p in data.get("items", []) if isinstance(p, dict)]
    if provider == "youtube":
        data = api("GET", "https://www.googleapis.com/youtube/v3/playlists", headers=headers,
                   params={"mine": "true", "part": "snippet", "maxResults": 20})
        return [clean((p.get("snippet") or {}).get("title")) for p in data.get("items", []) if isinstance(p, dict)]
    raise AccountError("This service supports verified identity only.")
