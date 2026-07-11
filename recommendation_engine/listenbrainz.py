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
