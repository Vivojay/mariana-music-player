from dataclasses import replace
from unittest.mock import Mock

import pytest

from beta.podcasts import vendors
from mariana.artwork import ArtworkCancelled, FetchedArtwork
from mariana.entertainment_catalog import BY_ID, ENTRIES, CatalogueReader, catalogue_details, search_catalogue
from mariana.homepage import HomepageService
from mariana.models import MediaRef, MediaSource
from mariana.podcast_feeds import MAX_PODCAST_BYTES, PodcastFeedError, episode_media, parse_podcast_feed


def feed(items=None):
    if items is None:
        items = """<item><guid>episode-one</guid><title>A real episode</title>
        <description><![CDATA[<p>Full episode description</p>]]></description>
        <pubDate>Tue, 09 Sep 2025 12:00:00 GMT</pubDate><itunes:duration>12:30</itunes:duration>
        <itunes:explicit>yes</itunes:explicit>
        <enclosure url="https://media.example/episode.mp3" type="audio/mpeg" />
        <psc:chapters><psc:chapter start="00:00:00" title="Intro" />
        <psc:chapter start="00:01:00" title="Discussion" /></psc:chapters></item>"""
    return (f'''<?xml version="1.0"?><rss version="2.0"
    xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
    xmlns:psc="http://podlove.org/simple-chapters"><channel><title>Programme</title>
    <language>de</language><itunes:author>Creator</itunes:author>
    <itunes:image href="https://images.example/cover.jpg" />{items}</channel></rss>''').encode()


def test_feed_preserves_identity_metadata_order_and_chapters():
    records = parse_podcast_feed(feed(), "https://publisher.example/feed")
    media = episode_media(records[0])
    assert media is not None
    assert (media.title, media.artist, media.album, media.duration) == ("A real episode", "Creator", "Programme", 750)
    assert media.source == MediaSource.PODCAST
    assert media.resolver_data["description"] == "Full episode description"
    assert media.resolver_data["explicit"] is True
    assert media.resolver_data["artwork"] == "https://images.example/cover.jpg"
    assert media.resolver_data["language"] == "de"
    assert [(c.title, c.start_time, c.end_time) for c in media.chapters] == [("Intro", 0, 60), ("Discussion", 60, 750)]
    restored = MediaRef.from_dict(media.to_dict())
    assert restored.to_dict() == media.to_dict()
    changed = parse_podcast_feed(feed().replace(b"episode.mp3", b"replacement.mp3"), "https://publisher.example/feed")
    assert episode_media(changed[0]).stable_id == media.stable_id
    assert episode_media(parse_podcast_feed(feed(), "https://different.example/feed")[0]).stable_id != media.stable_id


@pytest.mark.parametrize("payload", [
    feed('<item><title>Article</title><link>https://news.example/article</link></item>'),
    feed('<item><title>Live</title><enclosure url="https://media.example/live.m3u8" type="audio/mpeg" /></item>'),
    feed('<item><enclosure url="http://127.0.0.1/private.mp3" type="audio/mpeg" /></item>'),
    feed('<item><enclosure url="https://user:password@media.example/private.mp3" type="audio/mpeg" /></item>'),
    b'<!DOCTYPE rss [<!ENTITY x "x">]><rss/>',
    b'<rss><channel><item>',
])
def test_article_live_private_and_malformed_inputs_are_not_playable(payload):
    with pytest.raises(PodcastFeedError):
        parse_podcast_feed(payload, "https://publisher.example/feed")


def test_oversized_feed_is_rejected_before_parsing():
    with pytest.raises(PodcastFeedError, match="8 MiB"):
        parse_podcast_feed(b" " * (MAX_PODCAST_BYTES + 1), "https://publisher.example/feed")


def test_deduplication_is_feed_scoped_and_never_title_only():
    item = '<item><title>Same title</title><guid>{}</guid><enclosure url="https://media.example/{}.mp3" type="audio/mpeg" /></item>'
    records = parse_podcast_feed(feed(item.format("one", "one") + item.format("one", "rotated") + item.format("two", "two")), "https://publisher.example/feed")
    assert [r["episode_guid"] for r in records] == ["one", "two"]


def test_catalogue_reuses_radio_ids_and_shared_podcast_aliases():
    assert len({e.id for e in ENTRIES}) == len(ENTRIES)
    assert len({e.endpoint for e in ENTRIES if e.endpoint}) == sum(bool(e.endpoint) for e in ENTRIES)
    assert BY_ID["groove-salad"].station_id == "somafm-groove-salad"
    for key in ("live-on-kexp", "circle-round", "kulturfragen"):
        assert vendors[key.replace("-", "_")] == BY_ID[key].endpoint
    assert "record" not in catalogue_details("wfmu")["actions"]
    assert "download" not in catalogue_details("wfmu")["actions"]
    assert catalogue_details("circle-round")["command"] == "pod circle_round"


def test_index_search_is_offline_and_field_specific():
    assert [e.id for e in search_catalogue('provider:KEXP category:"Live Sessions"')] == ["live-on-kexp"]
    assert [e.id for e in search_catalogue('language:de')] == ["kulturfragen"]
    assert search_catalogue('after:2020-01-01') == []
    assert search_catalogue('unrelated') == []
    with pytest.raises(ValueError):
        search_catalogue('credentials:value')


def test_reader_cache_has_expiry_and_does_not_mask_failed_refresh():
    clock = [0]
    fetcher = Mock()
    fetcher.fetch.return_value = FetchedArtwork(feed(), "application/rss+xml")
    reader = CatalogueReader(fetcher=fetcher, now=lambda: clock[0])
    try:
        first = reader.episodes(BY_ID["circle-round"], lambda: False)
        first[0].title = "caller mutation"
        assert reader.episodes(BY_ID["circle-round"], lambda: False)[0].title == "A real episode"
        assert fetcher.fetch.call_count == 1
        clock[0] = 901
        fetcher.fetch.side_effect = OSError("provider unavailable")
        with pytest.raises(OSError):
            reader.episodes(BY_ID["circle-round"], lambda: False)
        with pytest.raises(ValueError):
            reader.episodes(replace(BY_ID["circle-round"], status="conditional"), lambda: False)
    finally:
        reader.close()
    fetcher.close.assert_called_once()


def test_cancellation_is_visible_during_fetch_and_prevents_stale_cache_write():
    stale = [False]
    fetcher = Mock()
    def fetch(*_, cancel, **_kwargs):
        assert not cancel.is_set()
        stale[0] = True
        assert cancel.is_set()
        return FetchedArtwork(feed(), "application/rss+xml")
    fetcher.fetch.side_effect = fetch
    reader = CatalogueReader(fetcher=fetcher)
    try:
        with pytest.raises(ArtworkCancelled):
            reader.episodes(BY_ID["circle-round"], lambda: stale[0])
        assert not reader.cache
    finally:
        reader.close()


def test_home_cards_are_offline_deduplicated_and_permission_bound():
    service = HomepageService()
    try:
        items = [item for section in service.snapshot()["sections"] for item in section["items"]]
        assert sum(item["link"] == BY_ID["live-on-kexp"].homepage for item in items) == 1
        assert service.release_target("catalogue:circle-round") is None
        service.configure(online_enabled=True)
        assert service.release_target("catalogue:circle-round") == BY_ID["circle-round"].binding()
        assert service.release_target("catalogue:netflix") is None
        service.configure(online_enabled=False)
        assert service.release_target("catalogue:circle-round") is None
    finally:
        service.close()
