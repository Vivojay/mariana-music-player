"""The paired homepage shares display-safe current choices, not host paths."""

import http.client
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from mariana.homepage import HomepageArticle, HomepageConfiguration, HomepageImageCache, HomepageService
from mariana.web_home import browser_homepage
from mariana.web_session import NativeSession, make_server


def test_paired_home_is_read_only_by_default_and_hides_local_content():
    local_calls = []
    home = HomepageService(local_loader=lambda: local_calls.append(True) or {
        "library_count": 30,
        "items": [{"kind": "current", "title": "Local recording", "subtitle": "Local artist"}],
    })
    fallback = browser_homepage(home)

    assert local_calls == []
    assert fallback["onlineEnabled"] is False
    assert [section["key"] for section in fallback["sections"]][:2] == ["culture", "releases"]
    assert any(section["key"] == "press-links" and section["items"] for section in fallback["sections"])
    assert all(not item["selectable"] for section in fallback["sections"] for item in section["items"])
    assert fallback["discovery"] is None
    with_library = browser_homepage(home, share_library=True)
    assert local_calls == [True]
    assert "Local recording" in [item["title"] for item in with_library["sections"][0]["items"]]
    assert home.snapshot()["online_enabled"] is False


def test_paired_home_canonicalizes_links_and_preserves_native_row_numbering():
    home = HomepageService(configuration=HomepageConfiguration(online_enabled=True))
    podcast = next(item for section in home.snapshot()["sections"] for item in section["items"]
                   if item["id"].startswith("catalogue:") and home.release_target(item["id"]))
    picker = SimpleNamespace(snapshot=lambda: {
        "item_id": podcast["id"], "revision": 34, "state": "choices",
        "title": "Selection", "page": 1, "has_more": True,
        "request_id": "a" * 32,
        "candidates": [
            {"title":"Private file", "playable": True, "source": "local"},
            {"title":"Sunny podcast", "playable": True, "source": "rss", "artist": "KEXP"},
            {"title":"/path/to/private/file", "playable": True, "source": "rss"},
        ],
    })
    original = home.snapshot
    def snapshot(**options):
        result = original(**options)
        result["sections"][0]["items"].extend((
            {"id": "culture:1", "title": "New music", "link": "https://daily.bandcamp.com/classical/?token=secret", "image_key": "private"},
            {"id": "culture:2", "title": "Invalid", "link": "https://evil.example/secret"},
        ))
        return result

    projection = browser_homepage(SimpleNamespace(snapshot=snapshot, release_target=home.release_target), picker=picker)
    release, rejected = projection["sections"][0]["items"]
    assert release["link"] == "https://daily.bandcamp.com/classical/"
    assert "image_key" not in release
    assert rejected["link"] is None
    assert projection["discovery"]["revision"] == 34
    rows = projection["discovery"]["rows"]
    assert [row["number"] for row in rows] == [2, 3]
    assert rows[0]["title"] == "Sunny podcast"
    assert rows[1]["title"] == "Version"
    assert "request_id" not in projection["discovery"]


def test_paired_home_artwork_reads_only_current_validated_public_cache_entries(tmp_path):
    cache = HomepageImageCache(tmp_path, fetcher=SimpleNamespace())
    home = HomepageService(image_cache=cache)
    key = "a" * 64 + ".png"
    published = tmp_path / key
    unlisted = "b" * 64 + ".png"
    image = io.BytesIO()
    Image.new("RGB", (48, 24), "aquamarine").save(image, format="PNG")
    png = image.getvalue()
    published.write_bytes(png)
    (tmp_path / unlisted).write_bytes(png)
    home._articles = (HomepageArticle("fixture", "Culture", "Editorial", "Bandcamp Daily",
                                      "https://daily.bandcamp.com/features/fixture",
                                      image_key=key, image_mime="image/png"),)
    session = NativeSession()
    session.homepage = lambda share: browser_homepage(home, share)
    session.homepage_image = home.cached_image

    with make_server(session, Path(__file__).resolve().parents[1] / "web/player", []) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def request(route, bearer, data=None, origin=None, method="POST"):
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                connection.request(method, f"/api/{route}", json.dumps(data or {}), {
                    "Origin": origin or f"http://127.0.0.1:{server.server_port}",
                    "Content-Type": "application/json", "Authorization": f"Bearer {bearer}",
                })
                response = connection.getresponse()
                return response.status, response.getheader("Content-Type"), response.read()
            finally:
                connection.close()

        try:
            invite = session.invite
            assert request("homepage-image", invite, {"key": key})[0] == 403
            status, _, paired = request("pair", invite)
            assert status == 200
            token = json.loads(paired)["token"]
            status, _, snapshot = request("homepage", token)
            assert status == 200
            assert json.loads(snapshot)["sections"][0]["items"][0]["artwork"] == key
            assert str(tmp_path) not in snapshot.decode()
            assert request("homepage-image", token, {"key": key}) == (200, "image/png", png)
            assert request("homepage-image", token, {"key": key}, origin="https://elsewhere.invalid")[0] == 403
            assert request("homepage-image", token, {"key": key}, method="GET")[0] == 404
            assert request("homepage-image", token, {"key": unlisted})[0] == 404
            assert request("homepage-image", token, {"key": "../outside.png"})[0] == 404
            published.write_bytes(b"Not the published PNG")
            assert request("homepage-image", token, {"key": key})[0] == 404
        finally:
            server.shutdown()
            thread.join(2)
            home.close()
