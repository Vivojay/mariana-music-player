from __future__ import annotations

import hashlib
import io
import json
import os
import threading
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace

import pytest
import requests
from PIL import Image

import mariana.homepage as homepage_module
from mariana.artwork import ArtworkCancelled, FetchedArtwork
from mariana.homepage import (
    BANDCAMP_DAILY_FEED_URL,
    LISTENBRAINZ_FRESH_RELEASES_URL,
    BandcampDailyProvider,
    HomepageArticle,
    HomepageConfiguration,
    HomepageImageCache,
    HomepageItemProjection,
    HomepageLocalContent,
    HomepageLocalItem,
    HomepageProjection,
    HomepageProviderError,
    HomepageSectionProjection,
    HomepageService,
    ListenBrainzFreshReleasesProvider,
)

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel><title>Bandcamp Updates</title>
    <item>
      <title>Scene report from Sao Paulo</title>
      <link>https://daily.bandcamp.com/scene-report/sao-paulo?tracking=drop-me</link>
      <description><![CDATA[<img src="https://f4.bcbits.com/img/0034567890_10.jpg"/><p>Independent artists reshape a local scene.</p><p>Read full story on the Bandcamp Daily.</p>]]></description>
      <category>Scene Report</category><pubDate>Fri, 04 Sep 2026 17:10:13 +0000</pubDate>
      <dc:creator>A Writer</dc:creator>
    </item>
    <item>
      <title>Earlier story</title>
      <link>https://daily.bandcamp.com/features/earlier</link>
      <description>An earlier independent release.</description>
      <pubDate>Thu, 03 Sep 2026 17:10:13 +0000</pubDate>
    </item>
  </channel>
</rss>"""


class Response:
    def __init__(
        self,
        content: bytes = FEED,
        *,
        url: str = BANDCAMP_DAILY_FEED_URL,
        status_code: int = 200,
    ) -> None:
        self.content = content
        self.url = url
        self.status_code = status_code
        self.headers = {"Content-Length": str(len(content))}
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield from (
            self.content[index : index + chunk_size]
            for index in range(0, len(self.content), chunk_size)
        )

    def close(self) -> None:
        self.closed = True


def article(
    title: str = "Fresh story",
    *,
    link: str = "https://daily.bandcamp.com/features/fresh",
) -> HomepageArticle:
    return HomepageArticle(
        hashlib.sha256(link.encode("utf-8")).hexdigest()[:20],
        title,
        "A short attributed excerpt.",
        "Bandcamp Daily",
        link,
        "2026-09-04T17:10:13+00:00",
        "Bandcamp Daily Staff",
        "Features",
    )


class Provider:
    source_name = "Bandcamp Daily"

    def __init__(self, callback: Callable[[threading.Event], tuple[HomepageArticle, ...]]) -> None:
        self.callback = callback

    def fetch(self, cancelled: threading.Event) -> tuple[HomepageArticle, ...]:
        return self.callback(cancelled)


class NamedProvider(Provider):
    def __init__(self, source_name, callback):
        super().__init__(callback)
        self.source_name = source_name


def cache_payload(*, fetched_at: float, item: HomepageArticle | None = None):
    return {
        "schema_version": 2,
        "sources": ["Bandcamp Daily"],
        "fetched_at": fetched_at,
        "items": [(item or article()).to_cache_dict()],
    }


def section(projection: HomepageProjection, key: str) -> HomepageSectionProjection:
    return next(value for value in projection["sections"] if value["key"] == key)


def projection_items(projection: HomepageProjection, key: str) -> list[HomepageItemProjection]:
    return list(section(projection, key)["items"])


def test_configuration_defaults_and_keeps_startup_and_network_independent():
    assert HomepageConfiguration.from_mapping(None) == HomepageConfiguration(True, False)
    assert HomepageConfiguration.from_mapping(
        {"show on startup": False, "online content": True}
    ) == HomepageConfiguration(False, True)
    assert HomepageConfiguration.from_mapping(
        {"show on startup": "no", "online content": "yes"}
    ) == HomepageConfiguration(True, False)


def test_official_destinations_work_offline_without_fetching_or_inventing_rankings():
    calls = []
    service = HomepageService(provider=Provider(lambda _cancelled: calls.append(True) or ()))
    projection = service.snapshot()
    assert not service.refresh_async()
    assert calls == []
    charts = projection_items(projection, "chart-links")
    assert [item["source"] for item in charts] == ["Billboard", "Official Charts Company", "IFPI"]
    assert "not imported" in str(charts[0]["summary"])
    destinations = [
        item for group in projection["sections"] if group["key"].endswith("-links")
        for item in group["items"]
    ]
    assert len(destinations) == 20
    # KEXP is now a single native podcast card, not a second external-link record.
    all_items = [item for group in projection['sections'] for item in group['items']]
    assert [item['id'] for item in all_items if item['link'] == 'https://www.kexp.org/podcasts/live-on-kexp/'] == ['catalogue:live-on-kexp']
    assert any(item['link'] == 'https://www.abc.net.au/triplej/programs/like-a-version' for item in destinations)
    assert any(item['link'] == 'https://linktr.ee/elevatormusiclive' for item in destinations)
    shows = projection_items(projection, "show-links")
    assert [item["title"] for item in shows] == ["Vanderpump Rules", "BravoTV", "Hayu"]
    assert "authorised provider" in str(shows[0]["summary"])
    assert "Subscription" in str(shows[2]["summary"])
    assert len({item["id"] for item in destinations}) == len(destinations)
    assert all(item["published_at"] is None and item["image_key"] is None for item in destinations)
    assert all(str(item["link"]).startswith("https://") for item in destinations)
    assert all("rank" not in item and "playback_uri" not in item for item in destinations)
    charts[0]["title"] = "Changed by a consumer"
    assert projection_items(service.snapshot(), "chart-links")[0]["title"] == "Billboard charts"
    service.close()


def test_text_link_and_count_sanitizers_cover_malformed_boundaries(monkeypatch):
    def reject_markup(_self, _value):
        raise ValueError("malformed markup")

    monkeypatch.setattr(homepage_module._TextExtractor, "feed", reject_markup)
    assert homepage_module._plain_text("<b>  fallback text </b>", maximum=20) == "fallback text"
    monkeypatch.undo()

    assert homepage_module._plain_text("123456", maximum=5) == "1234…"
    assert homepage_module._official_bandcamp_link(None) is None
    assert homepage_module._official_bandcamp_link("x" * 2_049) is None
    assert homepage_module._official_bandcamp_link("https://daily.bandcamp.com:bad/story") is None
    assert homepage_module._bounded_count("not-a-count") == 0
    assert replace(article(), attribution=None).to_projection_item()["source"] == "Bandcamp Daily"
    credited = replace(article(), attribution="A long collaborative artist credit " * 4)
    assert len(credited.to_projection_item()["source"]) == 80
    assert credited.to_projection_item()["source"].startswith("Bandcamp Daily · ")


def test_local_projection_is_immediate_bounded_json_safe_and_private():
    values = [
        HomepageLocalItem("favorite", "A safe favourite", "Artist"),
        HomepageLocalItem("recent", "https://private.test/song", "must disappear"),
        HomepageLocalItem("queue", "Queued song", "C:\\Users\\person\\secret.mp3"),
        HomepageLocalItem("queue", "Linux path", "/mnt/music/private.flac"),
        HomepageLocalItem("unsupported", "Ignored", None),
    ]
    values.extend(HomepageLocalItem("library", f"Song {index}") for index in range(20))
    service = HomepageService(
        local_loader=lambda: HomepageLocalContent(-1, 10**20, 2, 3, tuple(values)),
    )

    projection = service.snapshot()

    assert set(projection) == {
        "schema_version",
        "show_on_startup",
        "online_enabled",
        "state",
        "refreshed_at",
        "safe_message",
        "sections",
    }
    assert projection["schema_version"] == 2
    assert projection["show_on_startup"] is True
    assert projection["online_enabled"] is False
    assert projection["state"] == "offline"
    assert projection["refreshed_at"] is None
    local_items = projection_items(projection, "local")
    assert len(local_items) == 12
    assert local_items[0] == {
        "id": "local-summary:favorites",
        "title": "Rated media",
        "summary": "10000000 one-to-five-star ratings",
        "source": "Mariana",
        "published_at": None,
        "link": None,
        "image_key": None,
        "image_mime": None,
    }
    assert json.loads(json.dumps(projection)) == projection
    assert "private.test" not in str(projection)
    assert "secret.mp3" not in str(projection)
    assert "/mnt/" not in str(projection)


def test_local_projection_accepts_mapping_items_and_ignores_bad_shapes():
    service = HomepageService(
        local_loader=lambda: {
            "library_count": "invalid",
            "items": [
                {"kind": "queue", "title": "<b>Mapped title</b>", "subtitle": None},
                object(),
                {"kind": "queue", "title": None, "subtitle": "ignored"},
            ],
        }
    )

    items = projection_items(service.snapshot(), "local")

    assert [(item["title"], item["summary"]) for item in items] == [("Mapped title", None)]
    assert HomepageService(local_loader=lambda: None).snapshot()["sections"][0]["items"] == []
    assert (
        HomepageService(local_loader=lambda: {"items": object()})
        .snapshot()["sections"][0]["items"]
        == []
    )


def test_duplicate_safe_local_labels_keep_unique_projection_ids():
    duplicate = HomepageLocalItem("favorite", "Same title", "Same artist")
    service = HomepageService(local_loader=lambda: HomepageLocalContent(items=(duplicate, duplicate)))

    items = projection_items(service.snapshot(), "local")

    assert [item["title"] for item in items] == ["Same title", "Same title"]
    assert len({item["id"] for item in items}) == 2
    assert items[1]["id"] == f'{items[0]["id"]}:2'


def test_local_failure_is_nonfatal_and_does_not_hide_cached_online_content():
    service = HomepageService(
        configuration=HomepageConfiguration(False, True),
        local_loader=lambda: (_ for _ in ()).throw(OSError("C:/private/library")),
        cache_load=lambda: cache_payload(fetched_at=950),
        now=lambda: 1_000,
    )

    projection = service.snapshot()

    assert projection["state"] == "partial"
    assert projection["safe_message"] == "Local homepage information is temporarily unavailable"
    assert projection_items(projection, "local") == []
    assert projection_items(projection, "culture")[0]["title"] == "Fresh story"
    assert "private" not in str(projection).casefold()


def test_local_failure_without_online_content_has_a_safe_error_state():
    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        local_loader=lambda: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    projection = service.snapshot()

    assert projection["state"] == "error"
    assert projection["safe_message"] == "Local homepage information is temporarily unavailable"
    assert "private detail" not in str(projection)


def test_cached_content_renders_when_offline_and_reports_fresh_or_stale_state():
    disabled = HomepageService(
        cache_load=lambda: cache_payload(fetched_at=950), now=lambda: 1_000
    ).snapshot()
    fresh = HomepageService(
        configuration=HomepageConfiguration(True, True),
        cache_load=lambda: cache_payload(fetched_at=950),
        now=lambda: 1_000,
        cache_ttl_seconds=100,
    ).snapshot()
    stale = HomepageService(
        configuration=HomepageConfiguration(True, True),
        cache_load=lambda: cache_payload(fetched_at=800),
        now=lambda: 1_000,
        cache_ttl_seconds=100,
    ).snapshot()

    assert disabled["state"] == "offline"
    assert projection_items(disabled, "culture")
    assert fresh["state"] == "ready"
    assert fresh["refreshed_at"] == 950
    assert stale["state"] == "stale"


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2, "sources": ["Bandcamp Daily"], "fetched_at": 1_000, "items": []},
        cache_payload(fetched_at=-1),
        cache_payload(
            fetched_at=1_000,
            item=article(link="https://evil.test/stolen?token=secret"),
        ),
        {**cache_payload(fetched_at=1_000), "private": "secret"},
    ],
)
def test_invalid_empty_or_private_cache_is_ignored(payload):
    projection = HomepageService(
        configuration=HomepageConfiguration(True, True),
        cache_load=lambda: payload,
        now=lambda: 1_000,
    ).snapshot()
    assert projection["state"] == "offline"
    assert projection_items(projection, "culture") == []


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"schema_version": 2, "sources": ["Bandcamp Daily"], "fetched_at": 1_000},
        {**cache_payload(fetched_at=1_000), "items": ()},
        cache_payload(fetched_at=float("nan")),
        cache_payload(fetched_at=10**400),
        cache_payload(fetched_at=1_301),
        cache_payload(fetched_at=0),
        {
            **cache_payload(fetched_at=1_000),
            "items": [{**article().to_cache_dict(), "title": "x" * 65_000}],
        },
    ],
)
def test_cache_shape_age_and_size_boundaries_degrade_to_empty(payload):
    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        cache_load=lambda: payload,
        now=lambda: 1_000,
        cache_max_age_seconds=100,
    )

    assert service.snapshot()["state"] == "offline"
    assert projection_items(service.snapshot(), "culture") == []


def test_cache_loader_callback_exception_never_blocks_startup():
    def fail_cache_load():
        raise RuntimeError("state backend is temporarily unavailable")

    service = HomepageService(
        local_loader=lambda: {"library_count": 2},
        cache_load=fail_cache_load,
    )

    projection = service.snapshot()

    assert projection["state"] == "offline"
    assert projection_items(projection, "local")[0]["summary"] == "2 media items"
    assert projection_items(projection, "culture") == []


def test_cache_ignores_nonmapping_items_but_keeps_valid_articles():
    payload = cache_payload(fetched_at=1_000)
    payload["items"] = [None, article().to_cache_dict()]

    projection = HomepageService(
        configuration=HomepageConfiguration(True, True),
        cache_load=lambda: payload,
        now=lambda: 1_000,
    ).snapshot()

    assert projection["state"] == "ready"
    assert [item["title"] for item in projection_items(projection, "culture")] == ["Fresh story"]


def test_default_provider_uses_an_isolated_owned_session_and_closes_it(monkeypatch):
    class OwnedSession:
        def __init__(self):
            self.trust_env = True
            self.close_calls = 0

        def get(self, *_args, **_kwargs):
            raise AssertionError("network should not be used")

        def close(self):
            self.close_calls += 1

    owned = OwnedSession()
    monkeypatch.setattr(homepage_module.requests, "Session", lambda: owned)
    provider = BandcampDailyProvider()
    service = HomepageService(provider=provider)

    assert owned.trust_env is False
    service.close()
    service.close()
    assert owned.close_calls == 1

    class InjectedGet:
        def __init__(self):
            self.close_calls = 0

        def __call__(self, *_args, **_kwargs):
            return Response()

        def close(self):
            self.close_calls += 1

    injected = InjectedGet()
    BandcampDailyProvider(request_get=injected).close()
    assert injected.close_calls == 0


def test_bandcamp_provider_uses_official_bounded_feed_and_short_attributed_entries():
    response = Response()
    requests_seen = []

    def get(url, **kwargs):
        requests_seen.append((url, kwargs))
        return response

    results = BandcampDailyProvider(request_get=get).fetch(threading.Event())

    assert requests_seen[0][0] == BANDCAMP_DAILY_FEED_URL
    assert requests_seen[0][1]["stream"] is True
    assert requests_seen[0][1]["timeout"] == (4, 12)
    assert requests_seen[0][1]["allow_redirects"] is False
    assert response.closed is True
    assert [item.title for item in results] == ["Scene report from Sao Paulo", "Earlier story"]
    assert results[0].excerpt == "Independent artists reshape a local scene."
    assert results[0].attribution == "A Writer"
    assert results[0].category == "Scene Report"
    assert results[0].link == "https://daily.bandcamp.com/scene-report/sao-paulo"
    assert results[0].published_at == "2026-09-04T17:10:13+00:00"
    assert results[0].image_url == "https://f4.bcbits.com/img/0034567890_10.jpg"


def test_bandcamp_dates_fall_back_safely_for_naive_and_invalid_values():
    timestamp, published = BandcampDailyProvider._published(
        {"published_parsed": object(), "published": "Fri, 04 Sep 2026 17:10:13"}
    )
    assert timestamp > 0
    assert published == "2026-09-04T17:10:13+00:00"
    assert BandcampDailyProvider._published({"published": "not a date"}) == (0.0, None)
    assert BandcampDailyProvider._published({}) == (0.0, None)


def test_bandcamp_response_stream_handles_unknown_sizes_empty_chunks_and_cancellation():
    class MixedChunkResponse(Response):
        def iter_content(self, chunk_size: int):
            del chunk_size
            yield b""
            yield b"payload"

    response = MixedChunkResponse(b"payload")
    response.headers = {"Content-Length": "unknown"}
    provider = BandcampDailyProvider(request_get=lambda *_args, **_kwargs: response)
    assert provider._response_bytes(threading.Event()) == b"payload"
    assert response.closed is True

    oversized = Response(b"123456789")
    oversized.headers = {"Content-Length": "unknown"}
    with pytest.raises(HomepageProviderError, match="size limit"):
        BandcampDailyProvider(
            request_get=lambda *_args, **_kwargs: oversized,
            max_bytes=8,
        )._response_bytes(threading.Event())

    cancelled = threading.Event()
    class CancellingResponse(Response):
        def iter_content(self, chunk_size: int):
            del chunk_size
            cancelled.set()
            yield b"payload"

    interrupted = CancellingResponse(b"payload")
    with pytest.raises(RuntimeError):
        BandcampDailyProvider(
            request_get=lambda *_args, **_kwargs: interrupted
        )._response_bytes(cancelled)
    assert interrupted.closed is True


def test_bandcamp_fetch_rechecks_cancellation_and_skips_bad_or_duplicate_entries(monkeypatch):
    cancelled_after_download = threading.Event()
    provider = BandcampDailyProvider(request_get=lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        provider,
        "_response_bytes",
        lambda _cancelled: cancelled_after_download.set() or FEED,
    )
    with pytest.raises(RuntimeError):
        provider.fetch(cancelled_after_download)

    entries = [
        object(),
        {"title": "Missing description", "link": "https://daily.bandcamp.com/features/bad"},
        {
            "title": "Valid",
            "link": "https://daily.bandcamp.com/features/valid",
            "summary": "A useful excerpt.",
            "tags": ["not-a-mapping"],
            "category": "Fallback category",
        },
        {
            "title": "Duplicate",
            "link": "https://daily.bandcamp.com/features/valid",
            "summary": "Must be ignored.",
        },
    ]
    monkeypatch.setattr(
        homepage_module.feedparser,
        "parse",
        lambda _payload: SimpleNamespace(bozo=False, entries=entries),
    )

    results = BandcampDailyProvider(
        request_get=lambda *_args, **_kwargs: Response(b"ignored")
    ).fetch(threading.Event())

    assert [(item.title, item.category) for item in results] == [("Valid", "Fallback category")]


def test_bandcamp_provider_rejects_redirect_and_oversized_or_invalid_feeds():
    with pytest.raises(HomepageProviderError, match="redirects are not followed"):
        BandcampDailyProvider(
            request_get=lambda *_args, **_kwargs: Response(status_code=302)
        ).fetch(threading.Event())
    with pytest.raises(HomepageProviderError, match="redirected"):
        BandcampDailyProvider(
            request_get=lambda *_args, **_kwargs: Response(url="https://elsewhere.test/feed")
        ).fetch(threading.Event())
    with pytest.raises(HomepageProviderError, match="size limit"):
        BandcampDailyProvider(
            request_get=lambda *_args, **_kwargs: Response(b"x" * 9), max_bytes=8
        ).fetch(threading.Event())
    with pytest.raises(HomepageProviderError, match="invalid feed"):
        BandcampDailyProvider(request_get=lambda *_args, **_kwargs: Response(b"not xml")).fetch(
            threading.Event()
        )


def test_bandcamp_provider_enforces_an_overall_refresh_deadline():
    times = iter((0.0, 0.0, 2.0))
    response = Response()
    provider = BandcampDailyProvider(
        request_get=lambda *_args, **_kwargs: response,
        total_timeout=1,
        monotonic=lambda: next(times),
    )

    with pytest.raises(HomepageProviderError, match="time limit"):
        provider.fetch(threading.Event())

    assert response.closed is True


def test_cancelled_bandcamp_refresh_never_starts_a_network_request():
    requests_seen = []
    cancelled = threading.Event()
    cancelled.set()
    provider = BandcampDailyProvider(
        request_get=lambda *_args, **_kwargs: requests_seen.append(True) or Response()
    )

    with pytest.raises(RuntimeError):
        provider.fetch(cancelled)

    assert requests_seen == []


def test_refresh_is_nonblocking_publishes_loading_and_persists_sanitized_cache():
    release = threading.Event()
    stored = []
    updates = []

    def fetch(_cancelled):
        release.wait(1)
        return (article(),)

    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(fetch),
        cache_save=stored.append,
        on_update=updates.append,
        now=lambda: 1_000,
    )

    assert service.refresh_async() is True
    assert service.snapshot()["state"] == "loading"
    release.set()
    assert service.wait()

    assert service.snapshot()["state"] == "ready"
    assert stored == [cache_payload(fetched_at=1_000)]
    assert [projection["state"] for projection in updates] == ["loading", "ready"]


def test_network_failure_has_offline_state_without_cache_and_partial_with_cache():
    def fail(_cancelled):
        raise requests.ConnectionError("https://private.test/?token=secret")

    empty = HomepageService(
        configuration=HomepageConfiguration(True, True), provider=Provider(fail)
    )
    assert empty.refresh_async()
    assert empty.wait()
    empty_projection = empty.snapshot()
    assert empty_projection["state"] == "offline"
    assert empty_projection["safe_message"] == "Online discovery is temporarily unavailable"
    assert "private.test" not in str(empty_projection)

    cached = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(fail),
        cache_load=lambda: cache_payload(fetched_at=900),
        now=lambda: 1_000,
    )
    assert cached.refresh_async()
    assert cached.wait()
    cached_projection = cached.snapshot()
    assert cached_projection["state"] == "partial"
    assert projection_items(cached_projection, "culture")[0]["title"] == "Fresh story"


def test_provider_and_cache_failures_are_distinct_safe_states():
    invalid = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(lambda _cancelled: ()),
    )
    assert invalid.refresh_async()
    assert invalid.wait()
    assert invalid.snapshot()["state"] == "error"
    assert invalid.snapshot()["safe_message"] == "Online discovery could not be refreshed"

    uncached = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(lambda _cancelled: (article(),)),
        cache_save=lambda _value: (_ for _ in ()).throw(OSError("private path")),
    )
    assert uncached.refresh_async()
    assert uncached.wait()
    assert uncached.snapshot()["state"] == "partial"
    assert uncached.snapshot()["safe_message"] == "Fresh discovery is shown but could not be cached"


def test_service_revalidates_provider_items_before_cache_or_projection():
    unsafe = replace(
        article(),
        title="Bearer token=private",
        link="https://daily.bandcamp.com/features/fresh?secret=drop-me",
    )
    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(lambda _cancelled: (unsafe, article("Safe story"))),
    )

    assert service.refresh_async()
    assert service.wait()
    projection = service.snapshot()

    assert projection["state"] == "ready"
    assert [item["title"] for item in projection_items(projection, "culture")] == ["Safe story"]
    assert "private" not in str(projection).casefold()


def test_refresh_is_coalesced_while_a_bounded_worker_is_running():
    first_started = threading.Event()
    release_first = threading.Event()
    calls = 0
    stored = []

    def fetch(cancelled):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            release_first.wait(1)
            # Ignore cancellation deliberately to prove generation binding.
            return (article("Old story", link="https://daily.bandcamp.com/features/old"),)
        return (article("New story", link="https://daily.bandcamp.com/features/new"),)

    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(fetch),
        cache_save=stored.append,
        now=lambda: 1_000,
    )
    assert service.refresh_async() is True
    assert first_started.wait(1)
    assert service.refresh_async() is False
    release_first.set()
    assert service.wait()

    assert projection_items(service.snapshot(), "culture")[0]["title"] == "Old story"
    assert len(stored) == 1
    assert calls == 1

    assert service.refresh_async() is True
    assert service.wait()
    assert projection_items(service.snapshot(), "culture")[0]["title"] == "New story"
    assert calls == 2


def test_disabling_online_before_provider_io_prevents_the_request():
    provider_started = threading.Event()
    release_provider = threading.Event()
    requests_seen = []
    bandcamp = BandcampDailyProvider(
        request_get=lambda *_args, **_kwargs: requests_seen.append(True) or Response()
    )

    class GatedProvider:
        source_name = "Bandcamp Daily"

        def fetch(self, cancelled):
            provider_started.set()
            assert release_provider.wait(1)
            return bandcamp.fetch(cancelled)

    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=GatedProvider(),
    )
    assert service.refresh_async() is True
    assert provider_started.wait(1)
    service.configure(online_enabled=False)
    release_provider.set()
    assert service.wait()

    assert requests_seen == []
    assert service.snapshot()["online_enabled"] is False


def test_disabling_online_cancels_pending_refresh_but_keeps_cache_displayable():
    started = threading.Event()
    release = threading.Event()
    stored = []

    def fetch(_cancelled):
        started.set()
        release.wait(1)
        return (article("Late story"),)

    service = HomepageService(
        configuration=HomepageConfiguration(False, True),
        provider=Provider(fetch),
        cache_load=lambda: cache_payload(fetched_at=900),
        cache_save=stored.append,
        now=lambda: 1_000,
    )
    assert service.refresh_async()
    assert started.wait(1)
    projection = service.configure(show_on_startup=True, online_enabled=False)
    release.set()
    assert service.wait()

    assert projection["show_on_startup"] is True
    final = service.snapshot()
    assert final["online_enabled"] is False
    assert final["state"] == "offline"
    assert projection_items(final, "culture")[0]["title"] == "Fresh story"
    assert stored == []
    assert service.refresh_async() is False


def test_close_is_idempotent_bounded_and_late_worker_cannot_publish():
    started = threading.Event()
    release = threading.Event()
    updates = []
    stored = []

    def fetch(_cancelled):
        started.set()
        release.wait(1)
        return (article("Too late"),)

    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(fetch),
        cache_save=stored.append,
        on_update=updates.append,
    )
    assert service.refresh_async()
    assert started.wait(1)
    service.close(timeout=0)
    service.close(timeout=0)
    release.set()
    assert service.wait()

    assert stored == []
    assert [projection["state"] for projection in updates] == ["loading"]
    assert service.refresh_async() is False


def test_configure_rejects_non_boolean_values():
    service = HomepageService()
    with pytest.raises(ValueError, match="startup"):
        service.configure(show_on_startup=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="online"):
        service.configure(online_enabled="yes")  # type: ignore[arg-type]


def test_configure_recomputes_cache_freshness_and_closed_service_is_stable():
    fresh = HomepageService(
        cache_load=lambda: cache_payload(fetched_at=950),
        now=lambda: 1_000,
        cache_ttl_seconds=100,
    )
    assert fresh.configure(online_enabled=True)["state"] == "ready"

    stale = HomepageService(
        cache_load=lambda: cache_payload(fetched_at=800),
        now=lambda: 1_000,
        cache_ttl_seconds=100,
    )
    assert stale.configure(online_enabled=True)["state"] == "stale"

    no_cache = HomepageService()
    assert no_cache.configure(online_enabled=True)["state"] == "offline"
    no_cache.close()
    assert no_cache.configure(show_on_startup=False)["show_on_startup"] is True


def test_update_callback_failures_and_wait_timeout_are_nonfatal():
    started = threading.Event()
    release = threading.Event()

    def fetch(_cancelled):
        started.set()
        release.wait(1)
        return (article(),)

    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(fetch),
        on_update=lambda _projection: (_ for _ in ()).throw(RuntimeError("UI gone")),
    )

    assert service.refresh_async()
    assert started.wait(1)
    assert service.wait(timeout=0) is False
    release.set()
    assert service.wait()
    assert service.snapshot()["state"] == "ready"


def test_article_cache_and_public_projection_shapes_remain_stable():
    original = article()
    changed = replace(original, title="Changed")
    assert changed.to_cache_dict() == {**original.to_cache_dict(), "title": "Changed"}
    assert set(changed.to_projection_item()) == {
        "id",
        "title",
        "summary",
        "source",
        "published_at",
        "link",
        "image_key",
        "image_mime",
    }


def _still_image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (16, 12), "purple").save(output, format="PNG")
    return output.getvalue()


class ImageFetcher:
    def __init__(self, payload: bytes | None = None) -> None:
        self.payload = payload or _still_image_bytes()
        self.calls: list[str] = []

    def fetch(self, url, *, cancel, max_bytes):
        assert not cancel.is_set()
        assert len(self.payload) <= max_bytes
        self.calls.append(url)
        return FetchedArtwork(self.payload, "image/png")


@pytest.mark.parametrize("end_refresh", ["complete", "disable", "close"])
def test_ready_cover_is_published_before_slow_images_and_late_updates_are_cancelled(
    tmp_path, end_refresh,
):
    second_started = threading.Event()
    release_second = threading.Event()
    updates = []

    class DelayedFetcher(ImageFetcher):
        def fetch(self, url, *, cancel, max_bytes):
            if url.endswith("second.png"):
                second_started.set()
                assert release_second.wait(5)
                # Model a transport which finishes after cancellation; the cache
                # and service must still reject its result.
                return FetchedArtwork(self.payload, "image/png")
            return super().fetch(url, cancel=cancel, max_bytes=max_bytes)

    entries = tuple(
        replace(
            article(name, link=f"https://daily.bandcamp.com/features/{name}"),
            image_url=f"https://f4.bcbits.com/img/{name}.png",
        ) for name in ("first", "second")
    )
    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(lambda _cancelled: entries),
        image_cache=HomepageImageCache(tmp_path / "images", fetcher=DelayedFetcher()),
        on_update=updates.append,
    )
    try:
        assert service.refresh_async()
        assert second_started.wait(5)
        first, second = projection_items(updates[-1], "culture")
        assert first["image_key"] is not None
        assert second["image_key"] is None
        if end_refresh == "disable":
            service.configure(online_enabled=False)
        elif end_refresh == "close":
            service.close(timeout=0)
        release_second.set()
        assert service.wait(5)
        first, second = projection_items(service.snapshot(), "culture")
        assert first["image_key"] is not None
        assert (second["image_key"] is not None) == (end_refresh == "complete")
    finally:
        release_second.set()
        service.close()


def test_provider_images_are_validated_cached_and_projected_without_remote_urls(tmp_path):
    remote = "https://f4.bcbits.com/img/0034567890_10.jpg?tracking=discarded"
    enriched = replace(article(), image_url=remote)
    fetcher = ImageFetcher()
    image_cache = HomepageImageCache(tmp_path / "homepage", fetcher=fetcher)
    stored = []
    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(lambda _cancelled: (enriched,)),
        image_cache=image_cache,
        cache_save=stored.append,
        now=lambda: 1_000,
    )

    assert service.refresh_async()
    assert service.wait()
    item = projection_items(service.snapshot(), "culture")[0]

    assert fetcher.calls == ["https://f4.bcbits.com/img/0034567890_10.jpg"]
    assert item["image_mime"] == "image/png"
    assert homepage_module._IMAGE_CACHE_NAME.fullmatch(str(item["image_key"]))
    assert remote not in json.dumps(service.snapshot())
    assert remote not in json.dumps(stored)
    assert (tmp_path / "homepage" / str(item["image_key"])).is_file()

    offline_fetcher = ImageFetcher()
    restarted_cache = HomepageImageCache(tmp_path / "homepage", fetcher=offline_fetcher)
    cached = restarted_cache.resolve(enriched.article_id, remote, threading.Event())
    assert cached.cache_key == item["image_key"]
    assert offline_fetcher.calls == []


def test_invalid_or_untrusted_feed_images_degrade_to_visual_placeholders(tmp_path, monkeypatch):
    entries = [{
        "title": "Safe story",
        "link": "https://daily.bandcamp.com/features/safe",
        "summary": (
            '<img src="https://private.invalid/cover.jpg">'
            '<img src="https://f4.bcbits.com/not-img/cover.jpg">A safe excerpt.'
        ),
    }]
    monkeypatch.setattr(
        homepage_module.feedparser,
        "parse",
        lambda _payload: SimpleNamespace(bozo=False, entries=entries),
    )
    provider = BandcampDailyProvider(request_get=lambda *_args, **_kwargs: Response(b"ignored"))
    result = provider.fetch(threading.Event())[0]
    assert result.image_url is None

    malformed = ImageFetcher(b"not an image")
    image_cache = HomepageImageCache(tmp_path / "homepage", fetcher=malformed)
    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(
            lambda _cancelled: (
                replace(article(), image_url="https://f4.bcbits.com/img/invalid.jpg"),
            )
        ),
        image_cache=image_cache,
    )
    assert service.refresh_async()
    assert service.wait()
    item = projection_items(service.snapshot(), "culture")[0]
    assert item["image_key"] is None
    assert item["image_mime"] is None
    assert item["title"] == "Fresh story"


def test_listenbrainz_fresh_releases_use_stable_musicbrainz_identity_and_cover_art():
    first = "1f1db316-8361-4a40-9633-550b259642f5"
    cover = "9432fb06-bd84-4f2e-9386-b2f14e0de54d"
    payload = json.dumps({
        "payload": {
            "releases": [
                {
                    "artist_credit_name": "Röyksopp",
                    "release_date": "2026-09-05",
                    "release_group_primary_type": "Album",
                    "release_mbid": first,
                    "caa_release_mbid": cover,
                    "release_name": "Profound Mysteries",
                },
                {
                    "artist_credit_name": "Duplicate",
                    "release_date": "2026-09-05",
                    "release_mbid": first,
                    "release_name": "Must not duplicate",
                },
                {"release_mbid": "not-an-mbid", "release_name": "Unsafe"},
            ]
        }
    }).encode()
    response = Response(payload, url=LISTENBRAINZ_FRESH_RELEASES_URL)
    calls = []
    provider = ListenBrainzFreshReleasesProvider(
        request_get=lambda url, **kwargs: calls.append((url, kwargs)) or response
    )

    releases = provider.fetch(threading.Event())

    assert calls == [(LISTENBRAINZ_FRESH_RELEASES_URL, {
        "params": {"days": 14},
        "headers": {"User-Agent": "Mariana/0.7 (+https://github.com/Vivojay/mariana-music-player)"},
        "timeout": (4, 12),
        "stream": True,
        "allow_redirects": False,
    })]
    assert len(releases) == 1
    assert releases[0].title == "Profound Mysteries"
    assert releases[0].attribution == "Röyksopp"
    assert releases[0].section == "releases"
    assert releases[0].link == f"https://musicbrainz.org/release/{first}"
    assert releases[0].image_url == f"https://coverartarchive.org/release/{cover}/front-500"
    assert releases[0].to_projection_item()["summary"] == (
        f"Album · Released 2026-09-05 · Inspect this edition: album search reid:{first} --scope online"
    )
    assert response.closed is True


def test_multiple_discovery_sources_project_separate_sections_and_partial_failures():
    release = HomepageArticle(
        article_id="unused-provider-id",
        title="A new album",
        excerpt="Album · Released 2026-09-05",
        source=ListenBrainzFreshReleasesProvider.source_name,
        link="https://musicbrainz.org/release/1f1db316-8361-4a40-9633-550b259642f5",
        published_at="2026-09-05",
        attribution="An artist",
        section="releases",
    )
    service = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(lambda _cancelled: (article(),)),
        additional_providers=(NamedProvider(
            ListenBrainzFreshReleasesProvider.source_name,
            lambda _cancelled: (release,),
        ),),
        now=lambda: 1_000,
    )
    assert service.refresh_async()
    assert service.wait()
    projection = service.snapshot()
    assert projection["state"] == "ready"
    assert [item["title"] for item in projection_items(projection, "culture")] == ["Fresh story"]
    assert [item["title"] for item in projection_items(projection, "releases")] == ["A new album"]

    partial = HomepageService(
        configuration=HomepageConfiguration(True, True),
        provider=Provider(lambda _cancelled: (article(),)),
        additional_providers=(NamedProvider(
            ListenBrainzFreshReleasesProvider.source_name,
            lambda _cancelled: (_ for _ in ()).throw(requests.ConnectionError("offline")),
        ),),
    )
    assert partial.refresh_async()
    assert partial.wait()
    assert partial.snapshot()["state"] == "partial"
    assert partial.snapshot()["safe_message"] == "Some discovery sources are temporarily unavailable"


@pytest.mark.parametrize("setting", [
    {"max_encoded_bytes": 0}, {"max_cache_bytes": 0}, {"max_cache_entries": 0}, {"cache_ttl_seconds": 0},
])
def test_homepage_image_cache_requires_finite_storage_limits(tmp_path, setting):
    with pytest.raises(ValueError):
        HomepageImageCache(tmp_path / "covers", fetcher=ImageFetcher(), **setting)


@pytest.mark.parametrize("corruption", ["empty", "oversized", "wrong-format", "expired"])
def test_homepage_corrupt_or_expired_cover_is_replaced_not_displayed(tmp_path, corruption):
    fetcher = ImageFetcher()
    cache = HomepageImageCache(tmp_path / "covers", fetcher=fetcher, max_encoded_bytes=1024)
    url = "https://f4.bcbits.com/img/cover.png"
    entry = cache.resolve("story", url, threading.Event())
    path = cache.cache_dir / entry.cache_key
    if corruption == "empty":
        path.write_bytes(b"")
    elif corruption == "oversized":
        path.write_bytes(b"x" * 1025)
    elif corruption == "wrong-format":
        output = io.BytesIO()
        Image.new("RGB", (8, 8)).save(output, format="JPEG")
        path.write_bytes(output.getvalue())
    else:
        os.utime(path, (0, 0))
    replacement = cache.resolve("story", url, threading.Event())
    assert replacement.cache_key == entry.cache_key
    assert fetcher.calls == [url, url]
    assert path.read_bytes() == fetcher.payload
    cache.close()


def test_homepage_cover_cache_evicts_oldest_and_cancels_without_fetch(tmp_path):
    fetcher = ImageFetcher()
    cache = HomepageImageCache(tmp_path / "covers", fetcher=fetcher, max_cache_entries=1)
    url = "https://f4.bcbits.com/img/cover.png"
    first = cache.resolve("first", url, threading.Event())
    second = cache.resolve("second", url, threading.Event())
    assert not (cache.cache_dir / first.cache_key).exists()
    assert (cache.cache_dir / second.cache_key).is_file()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ArtworkCancelled):
        cache.resolve("third", url, cancelled)
    with pytest.raises(ValueError):
        cache.resolve(" ", url, threading.Event())
    cache.close()
    cache.close()
    with pytest.raises(ArtworkCancelled):
        cache.resolve("third", url, threading.Event())
    assert len(fetcher.calls) == 2


def test_homepage_cache_startup_removes_only_expired_images_and_interrupted_writes(tmp_path):
    directory = tmp_path / "covers"
    directory.mkdir()
    expired = directory / ("a" * 64 + ".png")
    current = directory / ("b" * 64 + ".png")
    temporary = directory / ".interrupted.tmp"
    unrelated = directory / "keep.txt"
    for path in (expired, current, temporary, unrelated):
        path.write_bytes(_still_image_bytes())
    os.utime(expired, (0, 0))
    os.utime(current, (100, 100))
    cache = HomepageImageCache(directory, fetcher=ImageFetcher(), now=lambda: 100, cache_ttl_seconds=10)
    try:
        assert not expired.exists() and not temporary.exists()
        assert current.is_file() and unrelated.is_file()
    finally:
        cache.close()


def test_homepage_cache_closes_its_owned_transport_once_even_if_cleanup_errors(tmp_path, monkeypatch):
    closed = []

    class OwnedFetcher(ImageFetcher):
        def close(self):
            closed.append(True)
            raise OSError("Transport already closed")

    monkeypatch.setattr(homepage_module, "SafeArtworkFetcher", lambda **_kwargs: OwnedFetcher())
    cache = HomepageImageCache(tmp_path / "covers")
    cache.close()
    cache.close()
    assert closed == [True]
    with pytest.raises(ArtworkCancelled):
        cache.resolve("story", "https://f4.bcbits.com/img/cover.png", threading.Event())


@pytest.mark.parametrize("patch", [
    {"section": "private"}, {"source": "Untrusted provider"},
    {"image_key": "../private.png", "image_mime": "image/png"},
    {"image_mime": "image/svg+xml"},
    {"image_key": "a" * 64 + ".png", "image_mime": None},
    {"image_key": "a" * 64 + ".png", "image_mime": "image/jpeg"},
])
def test_tampered_cached_article_is_rejected_as_a_whole(patch):
    cached = cache_payload(fetched_at=1000)
    cached["items"][0].update(patch)
    service = HomepageService(provider=Provider(lambda _cancelled: ()), cache_load=lambda: cached, now=lambda: 1000)
    assert projection_items(service.snapshot(), "culture") == []
    service.close()


@pytest.mark.parametrize("reference", [None, "x" * 2049, "https://musicbrainz.org:bad/release/none", "https://elsewhere.example/release/none"])
def test_release_and_cover_links_reject_malformed_or_untrusted_references(reference):
    assert homepage_module._official_musicbrainz_link(reference) is None
    assert homepage_module._official_cover_art_image(reference) is None


def test_feed_thumbnail_fallback_uses_only_validated_provider_images():
    expected = "https://f4.bcbits.com/img/cover.png"
    assert homepage_module._bandcamp_entry_image({"media_thumbnail": [None, {"url": expected + "?tracking=removed"}]}) == expected
    assert homepage_module._bandcamp_entry_image({"media_content": [None, {"url": "https://private.invalid/cover"}]}) is None


@pytest.mark.parametrize("problem", ["redirect", "wrong-host", "declared-size", "stream-size", "invalid-json", "wrong-shape", "cancelled-stream"])
def test_release_provider_closes_response_on_failure_or_cancellation(problem):
    cancelled = threading.Event()
    response = Response(b'{"payload":{"releases":[]}}', url=LISTENBRAINZ_FRESH_RELEASES_URL)
    limit = 128
    if problem == "redirect":
        response.status_code = 302
    elif problem == "wrong-host":
        response.url = "https://private.invalid/releases"
    elif problem == "declared-size":
        response.headers["Content-Length"] = "129"
    elif problem == "stream-size":
        response.headers = {}
        response.content = b"x" * 129
    elif problem == "invalid-json":
        response.content = b"{"
    elif problem == "wrong-shape":
        response.content = b"[]"
    else:
        def stream(_chunk_size=None, **_kwargs):
            cancelled.set()
            yield b"{}"
        response.iter_content = stream
    provider = ListenBrainzFreshReleasesProvider(request_get=lambda *_args, **_kwargs: response, max_bytes=limit)
    with pytest.raises((HomepageProviderError, homepage_module._RefreshCancelled)):
        provider.fetch(cancelled)
    assert response.closed


def test_release_provider_cancellation_prevents_io_and_owns_session_cleanup(monkeypatch):
    calls = []
    session = SimpleNamespace(trust_env=True, get=lambda *_args, **_kwargs: calls.append("request"), close=lambda: calls.append("close"))
    monkeypatch.setattr(homepage_module.requests, "Session", lambda: session)
    provider = ListenBrainzFreshReleasesProvider()
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(homepage_module._RefreshCancelled):
        provider.fetch(cancelled)
    provider.close()
    provider.close()
    assert calls == ["close"]
    assert not session.trust_env


def test_release_provider_ignores_incomplete_items_and_empty_stream_chunks():
    identity = "1f1db316-8361-4a40-9633-550b259642f5"
    valid = {
        "release_mbid": identity, "release_name": "Recording", "artist_credit_name": "Artist",
        "release_date": "2026-09-08", "caa_release_mbid": "unsupported-image-identity",
    }
    payload = json.dumps({"payload": {"releases": [
        None, {**valid, "release_name": ""}, {**valid, "release_date": "unknown"}, valid,
    ]}}).encode()
    response = Response(payload, url=LISTENBRAINZ_FRESH_RELEASES_URL)
    response.headers["Content-Length"] = "unknown"
    response.iter_content = lambda **_kwargs: iter([b"", None, payload])
    provider = ListenBrainzFreshReleasesProvider(request_get=lambda *_args, **_kwargs: response)
    results = provider.fetch(threading.Event())
    assert len(results) == 1
    assert results[0].title == "Recording" and results[0].image_url is None
    assert response.closed


def test_release_provider_cancellation_after_download_discards_results():
    identity = "1f1db316-8361-4a40-9633-550b259642f5"
    payload = json.dumps({"payload": {"releases": [{"release_mbid": identity}]}}).encode()
    response = Response(payload, url=LISTENBRAINZ_FRESH_RELEASES_URL)
    cancelled = threading.Event()
    response.close = cancelled.set
    provider = ListenBrainzFreshReleasesProvider(request_get=lambda *_args, **_kwargs: response)
    with pytest.raises(homepage_module._RefreshCancelled):
        provider.fetch(cancelled)


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_release_provider_applies_a_refresh_deadline_and_closes_slow_responses(phase):
    clock = [0.0]
    response = Response(b'{"payload":{"releases":[]}}', url=LISTENBRAINZ_FRESH_RELEASES_URL)

    def get(*_args, **_kwargs):
        if phase == "headers":
            clock[0] = 2.0
        return response

    def chunks(**_kwargs):
        clock[0] = 2.0
        yield response.content

    response.iter_content = chunks
    provider = ListenBrainzFreshReleasesProvider(request_get=get, total_timeout=1, monotonic=lambda: clock[0])
    with pytest.raises(HomepageProviderError, match="time limit"):
        provider.fetch(threading.Event())
    assert response.closed


@pytest.mark.parametrize(("extension", "mime"), [("jpg", "image/jpeg"), ("webp", "image/webp")])
def test_cached_image_metadata_round_trips_supported_formats_without_remote_paths(extension, mime):
    key = "a" * 64 + "." + extension
    cached = cache_payload(fetched_at=1000, item=replace(article(), image_key=key, image_mime=mime))
    service = HomepageService(provider=Provider(lambda _cancelled: ()), cache_load=lambda: cached, now=lambda: 1000)
    try:
        item = projection_items(service.snapshot(), "culture")[0]
        assert item["image_key"] == key and item["image_mime"] == mime
        assert "image_url" not in item
    finally:
        service.close()


def test_canonical_cover_reference_drops_tracking_without_changing_release_identity():
    identity = "1f1db316-8361-4a40-9633-550b259642f5"
    canonical = f"https://coverartarchive.org/release/{identity}/front-500"
    assert homepage_module._official_cover_art_image(canonical + "?tracking=removed#fragment") == canonical


def test_release_card_binding_requires_current_identity_and_permission():
    identity = "1f1db316-8361-4a40-9633-550b259642f5"
    release = replace(article(), source=ListenBrainzFreshReleasesProvider.source_name,
                      link=f"https://musicbrainz.org/release/{identity}", section="releases")
    provider = NamedProvider(ListenBrainzFreshReleasesProvider.source_name, lambda _cancelled: (release,))
    service = HomepageService(configuration=HomepageConfiguration(True, True), provider=provider)
    try:
        assert service.refresh_async() and service.wait()
        card = projection_items(service.snapshot(), "releases")[0]
        binding = service.release_target(card["id"])
        assert binding and binding[0] == identity
        assert service.release_target("release:missing") is None
        service.configure(online_enabled=False)
        assert service.release_target(card["id"]) is None
        service.configure(online_enabled=True)
        assert service.release_target(card["id"]) == binding
    finally:
        service.close()
    assert service.release_target(card["id"]) is None
