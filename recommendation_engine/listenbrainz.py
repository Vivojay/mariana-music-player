"""Optional ListenBrainz candidate source; disabled until a user token is supplied."""

from __future__ import annotations

import requests

from mariana.identity import USER_AGENT


class ListenBrainzClient:
    def __init__(self, token: str | None = None, *, session=None, timeout: float = 15):
        self.token = token
        self.session = session or requests.Session()
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    def recommendations(self, user_name: str, count: int = 25) -> list[dict]:
        if not self.token:
            return []
        response = self.session.get(
            f"https://api.listenbrainz.org/1/cf/recommendation/user/{user_name}/recording",
            params={"count": min(max(count, 1), 100)},
            headers={"Authorization": f"Token {self.token}", "User-Agent": USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json().get("payload", {}).get("mbids", [])

    def artist_radio(self, artist_mbid: str, *, count: int = 25, mode: str = "medium") -> list[dict]:
        """Return public LB Radio recording candidates for a MusicBrainz artist."""
        if not artist_mbid or mode not in {"easy", "medium", "hard"}:
            return []
        response = self.session.get(
            f"https://api.listenbrainz.org/1/lb-radio/artist/{artist_mbid}",
            params={"mode": mode},
            headers={"User-Agent": USER_AGENT},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json().get("payload", {})
        values = payload.get("recordings") or payload.get("mbids") or []
        normalized = []
        for item in values:
            if isinstance(item, str):
                normalized.append({"recording_mbid": item})
            elif isinstance(item, dict):
                normalized.append(dict(item))
        return normalized[: min(max(count, 1), 100)]
