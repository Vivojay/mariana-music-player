import hashlib
import json

import pytest

from beta import podcasts


@pytest.mark.parametrize("feed", tuple(podcasts.vendors.values()))
def test_catalogue_cache_binding_preserves_existing_digest(feed):
    assert podcasts._feed_cache_identity(feed) == hashlib.sha256(feed.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("feed", [
    "https://example.test/custom.rss",
    "https://user:secret@example.test/custom.rss",
    "https://example.test/custom.rss?token=secret",
    podcasts.vendors["podnews"] + "?token=secret",
])
def test_custom_feed_credentials_do_not_become_cache_bindings(feed):
    assert podcasts._feed_cache_identity(feed) is None


def test_custom_feed_refresh_keeps_cache_data_without_url_binding(monkeypatch, tmp_path, fixture_dir):
    from tests.test_podcasts_and_downloads import Response

    payload = (fixture_dir / "podcast_feed.xml").read_bytes()
    response = Response(payload)
    monkeypatch.setattr(podcasts.requests, "get", lambda *_args, **_kwargs: response)
    output = tmp_path / "custom.json"
    uri = "https://example.test/custom.rss?token=secret"

    episodes = podcasts.refresh_podcast_data(uri, output)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["podcasts_raw"] == episodes
    assert saved["feed_identity"] is None
    assert "secret" not in output.read_text(encoding="utf-8")
    assert response.closed
