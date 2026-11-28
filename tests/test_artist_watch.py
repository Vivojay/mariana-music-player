import json
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest

from mariana.artist_watch import _mentions, following, run_artist_command
from mariana.database import MarianaDatabase

A = "85c95c6a-31e0-40de-b7b7-9685ac70866b"
B = "eb000cc5-c089-473e-b3f8-a1015f3c232b"
R = "09982041-fe14-47a1-b551-251a78fd1201"
TODAY = date(2026, 11, 24)
ARTISTS = [{"id": A, "name": "River Above", "country": "IN"}, {"id": B, "name": "Arc"}]


def test_discover_credit_deduplication_and_dynamic_query():
    client = Mock()
    row = {"id": R, "title": "A new EP", "artist-credit": [{"artist": a} for a in ARTISTS]}
    client.artist_catalogue_search.return_value = [row, row]
    lines = run_artist_command(["discover", "electronic"], None, client, today=TODAY)
    assert len(lines) == 2
    assert A in lines[0] and B in lines[1]
    entity, query = client.artist_catalogue_search.call_args.args
    assert entity == "release-group" and 'tag:"electronic"' in query and "2027-02-22" in query


def test_dynamic_search_and_recent_groups_are_distinct():
    client = Mock()
    client.artist_catalogue_search.return_value = ARTISTS
    lines = run_artist_command(["emerging", "indie"], None, client, today=TODAY)
    assert len(lines) == 2
    assert client.artist_catalogue_search.call_args.args[1] == 'type:group AND begin:[2024-01-01 TO 2026-11-24] AND tag:"indie"'
    run_artist_command(["search", 'A "band"'], None, client)
    assert client.artist_catalogue_search.call_args.args[1] == 'artist:"A \\"band\\""'


def test_follows_persist_across_connections_and_releases_are_artist_scoped(tmp_path):
    db_file = tmp_path / "artists.db"
    db = MarianaDatabase(db_file)
    client = Mock()
    client.artist_catalogue_search.return_value = ARTISTS
    run_artist_command(["follow", A], db, client)
    run_artist_command(["follow", A], db, client)
    run_artist_command(["follow", B], db, client)
    assert following(MarianaDatabase(db_file)) == {A: "River Above", B: "Arc"}
    run_artist_command(["unfollow", B], db, client)
    row = {"id": R, "title": "Evenings", "first-release-date": "2026-12-01"}
    client.artist_catalogue_search.return_value = [
        {**row, "artist-credit": [{"artist": ARTISTS[1]}]},
        {**row, "artist-credit": [{"artist": ARTISTS[0]}]},
    ]
    for command, entity in (("releases", "release-group"), ("tracks", "recording")):
        lines = run_artist_command([command], db, client, today=TODAY)
        assert len(lines) == 1 and f"https://musicbrainz.org/{entity}/{R}" in lines[0]
        assert client.artist_catalogue_search.call_args.args[0] == entity
        assert f"arid:{A}" in client.artist_catalogue_search.call_args.args[1]
    with pytest.raises(ValueError, match="followed MBID"):
        run_artist_command(["news", B], db, client)


def test_input_errors_and_empty_watchlist_skip_network(tmp_path):
    db = MarianaDatabase(tmp_path / "artists.db")
    client = Mock()
    for args in (["tracks"], ["news"], ["releases"]):
        assert "Follow an artist" in run_artist_command(args, db, client)[0]
    with pytest.raises(ValueError):
        run_artist_command(["follow", "123"], db, client)
    with pytest.raises(ValueError):
        run_artist_command(["search"], db, client)
    client.artist_catalogue_search.assert_not_called()


def test_news_only_matches_complete_names_and_keeps_original_publisher_links():
    xml = b"""<rss version="2.0"><channel>
      <item><title>Arc in London</title><link>https://louderthanwar.com/review?tracking=1</link></item>
      <item><title>Archers at the hall</title><link>https://louderthanwar.com/archers</link></item>
      <item><title>ARC new music</title><link>https://other.invalid/a</link></item>
      </channel></rss>"""
    assert [item.display() for item in _mentions(xml, "https://louderthanwar.com/feed/", ["Arc"], "LTW")] == [
        "LTW · Arc in London · https://louderthanwar.com/review"
    ]
    with pytest.raises(ValueError):
        _mentions(b"<!DOCTYPE rss><rss/>", "https://louderthanwar.com/feed/", ["Arc"], "LTW")


def test_new_destinations_are_unique_and_open_on_desktop():
    root = Path(__file__).resolve().parents[1]
    rows = json.loads((root / "desktop/culture_sources.json").read_bytes())
    links = [row["url"] for row in rows]
    assert len(links) == len(set(links)) == 78
    assert {row["id"] for row in rows} >= {"panic-room", "sxsw", "comic-con", "sigil-radio"}


def test_artist_inbox_survives_restarts_partial_failure_and_refreshes(tmp_path, monkeypatch):
    from mariana.artist_watch import ArtistUpdate
    path = tmp_path / "artists.db"
    db = MarianaDatabase(path)
    client = Mock()
    client.artist_catalogue_search.return_value = ARTISTS
    run_artist_command(["follow", A], db, client)
    def fake_news(tracked, messages):
        messages.append("Example unavailable.")
        return [ArtistUpdate("BrooklynVegan · River Above", "https://www.brooklynvegan.com/ra/")]
    monkeypatch.setattr("mariana.artist_watch._news", fake_news)
    def fake_search(entity, _query):
        if entity == "release-group":
            raise ValueError("Offline")
        return [{"id": R, "title": "Evenings", "first-release-date": "2026-12-01",
                 "artist-credit": [{"artist": ARTISTS[0]}]}]
    client.artist_catalogue_search.side_effect = fake_search
    first = run_artist_command(["refresh"], db, client, today=TODAY)
    assert "2 new" in first[0]
    assert any("release-group search unavailable" in item for item in first)
    assert "Example unavailable." in first
    second_db = MarianaDatabase(path)
    assert "0 new" in run_artist_command(["refresh"], second_db, client, today=TODAY)[0]
    inbox = run_artist_command(["inbox"], db, client)
    assert len(inbox) == 2 and all(line.startswith("New · ") for line in inbox)
    item_id = inbox[0].split(" · ")[1]
    assert "1 update" in run_artist_command(["read", item_id], db, client)[0]
    assert len(run_artist_command(["inbox"], second_db, client)) == 1
    run_artist_command(["read", "all"], db, client)
    assert "no matching" in run_artist_command(["inbox"], db, client)[0]
    assert len(run_artist_command(["inbox", "all"], db, client)) == 2


def test_live_news_partial_provider_failure_keeps_other_matches(monkeypatch):
    from types import SimpleNamespace

    from mariana.artist_watch import _news
    from mariana.artwork import ArtworkFetchError
    xml = b'<rss version="2.0"><channel><item><title>Arc plays live</title><link>https://www.brooklynvegan.com/arc/</link></item></channel></rss>'
    fetcher = Mock()
    fetcher.fetch.side_effect = [SimpleNamespace(data=xml), ArtworkFetchError("missing"), SimpleNamespace(data=b"invalid")]
    monkeypatch.setattr("mariana.artwork.SafeArtworkFetcher", lambda **_: fetcher)
    messages = []
    hits = _news({B: "Arc"}, messages)
    assert [hit.url for hit in hits] == ["https://www.brooklynvegan.com/arc/"]
    assert messages == ["Louder Than War · Feed unavailable.", "GoldFlakePaint · Feed unavailable."]
    assert all(call.kwargs["max_bytes"] == 2_000_000 for call in fetcher.fetch.call_args_list)
    fetcher.close.assert_called_once()


APPLE_ARTIST = {"wrapperType": "artist", "artistId": 27, "artistName": "The River"}


@pytest.mark.parametrize("mb_error", [None, "MusicBrainz returned HTTP 503 (service unavailable). Try again later."])
def test_name_search_uses_independent_catalogue_on_miss_or_outage(monkeypatch, mb_error):
    client = Mock()
    client.artist_catalogue_search.return_value = []
    if mb_error:
        client.artist_catalogue_search.side_effect = ValueError(mb_error)
    apple = Mock(return_value=[APPLE_ARTIST, APPLE_ARTIST, {**APPLE_ARTIST, "wrapperType": "track"}])
    monkeypatch.setattr("mariana.artist_watch.apple_rows", apple)
    lines = run_artist_command(["search", "The", "River"], None, client)
    assert lines == ["The River · Apple Music (US) · apple:27"] + ([mb_error] if mb_error else [])
    apple.assert_called_once_with("search", term="The River", media="music", entity="musicArtist", limit=25)


def test_no_match_versus_outage_and_offline_follows(tmp_path, monkeypatch):
    db = MarianaDatabase(tmp_path / "artists.db")
    db.set_state("artist.follow." + A, "The River")
    client = Mock()
    client.artist_catalogue_search.return_value = []
    apple = Mock(return_value=[])
    monkeypatch.setattr("mariana.artist_watch.apple_rows", apple)
    assert "another spelling" in run_artist_command(["search", "Other"], db, client)[0]
    apple.side_effect = ValueError("Apple Music timed out.")
    client.artist_catalogue_search.side_effect = ValueError("MusicBrainz returned HTTP 403.")
    lines = run_artist_command(["search", "Other"], db, client)
    assert lines == ["Both online catalogues are unavailable. Try artist list for saved follows.",
                     "Search Bandcamp · https://bandcamp.com/search?q=Other&item_type=b",
                     "MusicBrainz returned HTTP 403.", "Apple Music timed out."]
    assert run_artist_command(["search", "river"], db, client)[0] == f"The River · Saved follow · {A}"


def test_apple_follows_verify_persist_and_scope_new_music(tmp_path, monkeypatch):
    path = tmp_path / "artists.db"
    db = MarianaDatabase(path)
    client = Mock()
    apple = Mock(return_value=[{**APPLE_ARTIST, "artistId": 99}])
    monkeypatch.setattr("mariana.artist_watch.apple_rows", apple)
    with pytest.raises(ValueError, match="confirm"):
        run_artist_command(["follow", "apple:27"], db, client)
    assert following(db) == {}
    apple.return_value = [APPLE_ARTIST]
    assert "Following The River" in run_artist_command(["follow", "apple:27"], db, client)[0]
    apple.assert_called_with("lookup", id="27")
    assert following(MarianaDatabase(path)) == {"apple:27": "The River"}
    album = {"wrapperType": "collection", "collectionId": 52, "collectionName": "Test album"}
    song = {"wrapperType": "track", "kind": "song", "trackId": 53, "trackName": "Test song"}
    common = {"artistId": 27, "releaseDate": "2026-12-05T12:00:00Z"}
    apple.return_value = [APPLE_ARTIST, {**album, **common}, {**song, **common},
                          {**song, **common, "trackId": 54, "artistId": 545},
                          {**song, **common, "trackId": 55, "releaseDate": "2020-12-05T12:00:00Z"}]
    for action, entity, number in (("releases", "album", 52), ("tracks", "song", 53)):
        result = run_artist_command([action, "apple:27"], db, client, today=TODAY)
        assert len(result) == 1 and f"The River · https://music.apple.com/us/{entity}/{number}" in result[0]
        apple.assert_called_with("lookup", id="27", entity=entity, sort="recent", limit=100)
    monkeypatch.setattr("mariana.artist_watch._news", lambda *_: [])
    for added in (2, 0):
        assert f"{added} new" in run_artist_command(["refresh", "apple:27"], db, client, today=TODAY)[0]
    assert len(run_artist_command(["inbox"], db, client)) == 2
    run_artist_command(["unfollow", "apple:27"], db, client)
    assert following(db) == {}
    client.artist_catalogue_search.assert_not_called()


def test_artist_search_caches_fresh_results_and_preserves_query_in_browser_link(tmp_path, monkeypatch):
    path = tmp_path / "artists.db"
    client = Mock()
    client.artist_catalogue_search.return_value = [ARTISTS[0]]
    apple = Mock(side_effect=ValueError("Apple Music timed out."))
    monkeypatch.setattr("mariana.artist_watch.apple_rows", apple)
    args = ["search", "A&B", "live"]
    run_artist_command(args, MarianaDatabase(path), client)
    apple.assert_not_called()
    client.artist_catalogue_search.side_effect = ValueError("MusicBrainz timed out.")
    lines = run_artist_command(args, MarianaDatabase(path), client)
    assert any("Previous search" in line and A in line for line in lines)
    assert "Search Bandcamp · https://bandcamp.com/search?q=A%26B+live&item_type=b" in lines


def test_apple_storefront_and_transport_use_official_endpoint(monkeypatch):
    from mariana import artist_catalogues
    monkeypatch.setenv("MARIANA_APPLE_COUNTRY", "in")
    monkeypatch.setattr(artist_catalogues, "_last_apple_request", float("-inf"))
    response = Mock()
    response.json.return_value = {"results": [APPLE_ARTIST]}
    get = Mock(return_value=response)
    monkeypatch.setattr(artist_catalogues.requests, "get", get)
    client = Mock()
    client.artist_catalogue_search.return_value = []
    assert run_artist_command(["search", "A&B"], None, client) == ["The River · Apple Music (IN) · apple:27"]
    assert get.call_args.args == ("https://itunes.apple.com/search",)
    assert get.call_args.kwargs["params"] == {"term": "A&B", "media": "music", "entity": "musicArtist", "limit": 25,
                                            "country": "IN"}
    monkeypatch.setenv("MARIANA_APPLE_COUNTRY", "not a country")
    assert any("two-letter" in line for line in run_artist_command(["search", "A&B"], None, client))
    assert get.call_count == 1


def test_name_search_bounds_history_and_preserves_followed_artists(tmp_path):
    db = MarianaDatabase(tmp_path / "artists.db")
    db.set_state("artist.follow." + A, "River Above")
    client = Mock()
    client.artist_catalogue_search.return_value = ARTISTS
    for i in range(70):
        run_artist_command(["search", f"Artist {i}"], db, client)
    assert len(db.fetchall("SELECT key FROM app_state WHERE key GLOB 'artist.search.*'")) == 64
    assert following(db) == {A: "River Above"}


def test_follow_official_urls_verify_the_id_and_ignore_display_slug(tmp_path, monkeypatch):
    db = MarianaDatabase(tmp_path / "artists.db")
    client = Mock()
    client.artist_catalogue_search.return_value = ARTISTS
    apple = Mock(return_value=[APPLE_ARTIST])
    monkeypatch.setattr("mariana.artist_watch.apple_rows", apple)
    run_artist_command(["follow", "https://music.apple.com/in/artist/display-slug/27?l=en"], db, client)
    run_artist_command(["follow", f"https://musicbrainz.org/artist/{A}"], db, client)
    assert following(db) == {A: "River Above", "apple:27": "The River"}
    for invalid in ("https://elsewhere.example/us/artist/example/27",
                    "https://music.apple.com@elsewhere.example/us/artist/example/27",
                    "https://music.apple.com/us/album/example/27", "http://music.apple.com/us/artist/27"):
        with pytest.raises(ValueError, match="Usage"):
            run_artist_command(["follow", invalid], db, client)
    apple.assert_called_once_with("lookup", id="27")
    client.artist_catalogue_search.assert_called_once_with("artist", "arid:" + A)
