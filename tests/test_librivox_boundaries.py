"""Provider failure, exact chapter selection, and durable audiobook boundaries."""

from __future__ import annotations

from dataclasses import replace

import pytest
import requests

from mariana.database import MarianaDatabase
from mariana.librivox import (
    MAX_DESCRIPTION_LENGTH,
    LibrivoxCatalog,
    LibrivoxClient,
    LibrivoxError,
    parse_book,
)
from mariana.models import MediaSource
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.queueing import PersistentQueue
from tests.test_librivox import FakeResponse, FakeSession, audiobook_payload


@pytest.fixture
def book():
    result = parse_book(audiobook_payload())
    assert result is not None
    return result


class BrokenResponse(FakeResponse):
    def __init__(self, failure, phase):
        super().__init__({"books": []})
        self.failure, self.phase = failure, phase
        self.close_count = 0

    def raise_for_status(self):
        if self.phase == "status":
            raise self.failure

    def iter_content(self, chunk_size):
        yield b'{"books": ['
        raise self.failure

    def close(self):
        self.close_count += 1
        super().close()


@pytest.mark.parametrize("phase", ["connect", "status", "body"])
@pytest.mark.parametrize("error_type", [requests.Timeout, requests.ConnectionError, requests.HTTPError])
def test_catalog_io_failures_are_sanitized_and_release_open_response(phase, error_type):
    error = error_type("private credential and transport diagnostics")
    response = BrokenResponse(error, phase)

    class Session(FakeSession):
        def get(self, url, **kwargs):
            if phase == "connect":
                raise error
            return super().get(url, **kwargs)

    client = LibrivoxClient(Session(response))
    with pytest.raises(LibrivoxError) as caught:
        client.search_title("Example")
    assert "private" not in str(caught.value)
    assert "timeout" in str(caught.value) if error_type is requests.Timeout else "unavailable" in str(caught.value)
    assert response.close_count == (0 if phase == "connect" else 1)


@pytest.mark.parametrize("payload", [b"\xff", b'{"books":', b"not JSON"])
def test_invalid_document_encoding_or_json_is_closed_before_safe_error(payload):
    response = FakeResponse({})
    response.content = payload
    with pytest.raises(LibrivoxError, match="invalid catalog data"):
        LibrivoxClient(FakeSession(response)).search_title("Example")
    assert response.closed


@pytest.mark.parametrize("payload", [None, False, [], {}, {"books": None}, {"books": {"id": "123"}}])
def test_empty_provider_results_are_not_fabricated(payload):
    response = FakeResponse(payload)
    assert LibrivoxClient(FakeSession(response)).search_title("Example") == []
    assert response.closed


@pytest.mark.parametrize("size", [1024, 1025])
def test_catalog_payload_budget_accepts_exact_limit_and_stops_at_first_excess(size):
    prefix = b'{"books": [], "padding": "'
    payload = prefix + b"x" * (size - len(prefix) - 2) + b'"}'
    assert len(payload) == size

    class Response(FakeResponse):
        def __init__(self):
            super().__init__({})
            self.reads = 0

        def iter_content(self, chunk_size):
            assert chunk_size == 64 * 1024
            yield b""
            self.reads += 1
            yield payload
            if size > 1024:
                pytest.fail("An oversized response must not be drained")

    response = Response()
    client = LibrivoxClient(FakeSession(response), max_response_bytes=1024)
    if size == 1024:
        assert client.search_title("Example") == []
    else:
        with pytest.raises(LibrivoxError, match="safety limit"):
            client.search_title("Example")
    assert response.closed and response.reads == 1


@pytest.mark.parametrize("url", [
    "file:///private/catalog", "https://person:password@librivox.org/catalog",
    "http://127.0.0.1/catalog", "https://librivox.org.attacker.example/catalog",
    "http://librivox.org/catalog", "https://librivox.org:8443/catalog",
])
def test_invalid_final_catalog_authority_is_rejected_before_consuming_body(url):
    class Response(FakeResponse):
        def iter_content(self, chunk_size):
            pytest.fail("Rejected catalog response must not be consumed")

    response = Response({}, url=url)
    with pytest.raises(LibrivoxError, match="official catalog host"):
        LibrivoxClient(FakeSession(response)).search_title("Example")
    assert response.closed


@pytest.mark.parametrize("url", [
    "file:///private/audio.mp3", "https://person:password@archive.org/audio.mp3",
    "http://localhost/audio.mp3", "http://speaker.local/audio.mp3",
    "http://192.168.1.2/audio.mp3", "http://[::1]/audio.mp3", "javascript:play()",
])
def test_unsafe_section_reference_is_omitted_without_losing_safe_sibling(url):
    payload = audiobook_payload(listen_url=url)
    parsed = parse_book(payload)
    assert parsed is not None
    assert [section.section_id for section in parsed.sections] == ["902"]
    selected = LibrivoxCatalog.select_sections(parsed, "1")
    assert selected == (parsed.sections[0],) and selected[0].number == 2
    media = LibrivoxCatalog.media(parsed, selected[0])
    assert media.original_uri == payload["sections"][1]["listen_url"]
    assert media.capabilities.finite and media.capabilities.downloadable and not media.capabilities.live


@pytest.mark.parametrize("duration", [None, True, -1, 10**400, "NaN", "Infinity", "-01:05", "a:b", "1:2:3:4"])
def test_missing_or_invalid_duration_does_not_invent_a_source_position(duration):
    payload = audiobook_payload()
    payload["sections"][0]["playtime"] = duration
    parsed = parse_book(payload)
    assert parsed is not None
    media = LibrivoxCatalog.media(parsed, parsed.sections[0])
    assert media.duration is None
    assert media.capabilities.finite and not media.capabilities.live
    assert media.source is MediaSource.PODCAST


def test_provider_display_fields_are_bounded_without_dropping_valid_chapters():
    payload = audiobook_payload()
    payload.update(title="<b>Known book</b>\n\x1b" + "x" * 400,
                   description="<p>" + "detail " * 3_000 + "</p>", private_token="not retained")
    payload["sections"].insert(0, None)
    payload["sections"].append({"id": "903", "listen_url": "https://archive.org/third.mp3",
                                "section_number": False, "title": "", "readers": [None, {}]})
    payload["authors"] = [None, {}, {"first_name": "Ada", "last_name": "Author"},
                          {"first_name": "Ada", "last_name": "Author"}]
    parsed = parse_book(payload)
    assert parsed is not None
    assert len(parsed.title) <= 300 and len(parsed.description) <= MAX_DESCRIPTION_LENGTH
    assert "<" not in parsed.title and "\x1b" not in parsed.title and "\n" not in parsed.title
    assert parsed.authors == ("Ada Author",)
    assert [(item.number, item.section_id) for item in parsed.sections] == [(1, "901"), (2, "902"), (4, "903")]
    assert parsed.sections[-1].title == "Section 4"
    projected = LibrivoxCatalog.media(parsed, parsed.sections[-1])
    assert projected.artist == "Ada Author" and "private_token" not in projected.resolver_data


class CatalogClient:
    def __init__(self, books):
        self.books = {book.catalog_id: book for book in books}
        self.results = list(books)
        self.error: LibrivoxError | None = None
        self.requests = []

    def search_title(self, _query, **_options):
        if self.error is not None:
            raise self.error
        return self.results

    def book(self, identifier):
        self.requests.append(identifier)
        if self.error is not None:
            raise self.error
        return self.books[identifier]


def test_new_result_scope_rejects_outdated_index_but_explicit_identity_still_resolves(book):
    second = replace(book, catalog_id="456", title="Different recording")
    client = CatalogClient([book, second])
    catalog = LibrivoxCatalog(client)  # type: ignore[arg-type]
    catalog.search("title", "First")
    assert catalog.resolve("2") is second
    client.results = [book]
    catalog.search("title", "Changed")
    with pytest.raises(LibrivoxError, match="result number is unavailable"):
        catalog.resolve("2")
    assert catalog.resolve("id:456") is second
    assert client.requests == ["456"]
    client.results = []
    catalog.search("title", "Empty")
    assert catalog.result_count == 0
    with pytest.raises(LibrivoxError, match="result number is unavailable"):
        catalog.resolve("1")


def test_failed_refresh_keeps_displayed_results_and_does_not_poison_detail_retry(book):
    client = CatalogClient([book])
    catalog = LibrivoxCatalog(client)  # type: ignore[arg-type]
    catalog.search("title", "Initial")
    client.error = LibrivoxError("Catalog unavailable")
    with pytest.raises(LibrivoxError):
        catalog.search("title", "Refresh")
    assert catalog.results == (book,)
    with pytest.raises(LibrivoxError):
        catalog.resolve("1")
    client.error = None
    assert catalog.resolve("1") is book and client.requests == ["123", "123"]


def test_detail_cache_reuses_recent_identity_and_evicts_only_oldest(book):
    books = [replace(book, catalog_id=str(identifier)) for identifier in range(1, 4)]
    client = CatalogClient(books)
    catalog = LibrivoxCatalog(client, detail_cache_size=2)  # type: ignore[arg-type]
    catalog.resolve("id:1")
    catalog.resolve("id:2")
    assert catalog.resolve("id:1") is books[0]
    catalog.resolve("id:3")
    assert catalog.resolve("id:1") is books[0]
    catalog.resolve("id:2")
    assert client.requests == ["1", "2", "3", "2"]


@pytest.mark.parametrize("selector", ["0", "3", "-1", "1.0", "1-2", "first", ""])
def test_invalid_chapter_selection_never_falls_back_to_whole_book(book, selector):
    with pytest.raises(LibrivoxError, match="Chapter must"):
        LibrivoxCatalog.select_sections(book, selector)


def test_unplayable_catalog_record_cannot_be_selected_or_downloaded(book):
    for selector in (None, "all", "1"):
        with pytest.raises(LibrivoxError, match="no playable sections"):
            LibrivoxCatalog.select_sections(replace(book, sections=()), selector)


def test_same_title_chapters_and_cursor_survive_real_database_reopen(tmp_path, book):
    second = replace(book.sections[1], title=book.sections[0].title)
    book = replace(book, sections=(book.sections[0], second))
    media = [LibrivoxCatalog.media(book, section) for section in book.sections]
    path = tmp_path / "library.sqlite3"
    database = MarianaDatabase(path)
    try:
        queue = PersistentQueue(database)
        for item in media:
            queue.add(item)
        queue.jump(1)
        MediaPreferences(database).toggle(media[0], PreferenceState.FAVORITE)
    finally:
        database.close()
    reopened = MarianaDatabase(path)
    try:
        queue = PersistentQueue(reopened)
        assert [item.media.stable_id for item in queue.items()] == [item.stable_id for item in media]
        selected = queue.current()
        assert selected is not None and selected.media.stable_id == media[1].stable_id
        assert selected.media.title == media[0].title
        assert selected.media.duration == media[1].duration
        assert selected.media.resolver_data["librivox_section_id"] == "902"
        preferences = MediaPreferences(reopened)
        moved = LibrivoxCatalog.media(book, replace(book.sections[0], listen_url="https://archive.org/moved.mp3"))
        assert preferences.is_favorite(moved) and not preferences.is_favorite(media[1])
        assert preferences.toggle(moved, PreferenceState.FAVORITE) is PreferenceState.NEUTRAL
    finally:
        reopened.close()



@pytest.mark.parametrize("field", ["sections", "genres"])
@pytest.mark.parametrize("value", [42, True, "not a list", {"id": "unexpected"}])
def test_malformed_optional_collections_do_not_abort_other_catalog_records(field, value):
    malformed = audiobook_payload()
    malformed[field] = value
    valid = audiobook_payload()
    valid["id"] = "456"
    response = FakeResponse({"books": [malformed, valid]})
    books = LibrivoxClient(FakeSession(response)).search_title("Example")
    assert [item.catalog_id for item in books] == ["123", "456"]
    assert getattr(books[0], field) == ()
    assert len(books[1].sections) == 2


@pytest.mark.parametrize("url", [
    "https://[broken", "https://archive.org:not-a-port/audio", "https://archive.org:65536/audio",
    "https://archive.org/track\nInjected: value", "https://archive.org\x7f/audio",
])
def test_malformed_optional_urls_are_dropped_without_poisoning_valid_record(url):
    payload = audiobook_payload(listen_url=url)
    payload["url_rss"] = payload["coverart_jpg"] = url
    parsed = parse_book(payload)
    assert parsed is not None and parsed.rss_url is None and parsed.artwork_url is None
    assert [section.section_id for section in parsed.sections] == ["902"]
    assert LibrivoxCatalog.media(parsed, parsed.sections[0]).capabilities.downloadable


@pytest.mark.parametrize("extra_match", [False, True])
def test_detail_lookup_rejects_wrong_or_ambiguous_recording(extra_match):
    wrong = audiobook_payload()
    books = [wrong]
    if extra_match:
        matching = audiobook_payload()
        matching["id"] = "999"
        books.append(matching)
    response = FakeResponse({"books": books})
    with pytest.raises(LibrivoxError, match="requested catalog ID"):
        LibrivoxClient(FakeSession(response)).book("999")
    assert response.closed


def test_catalog_rejects_substituted_detail_without_caching_it(book):
    class Client:
        def __init__(self, result):
            self.result = result

        def book(self, _identifier):
            return self.result

    client = Client(replace(book, catalog_id="456"))
    catalog = LibrivoxCatalog(client)  # type: ignore[arg-type]
    catalog.results = (book,)
    with pytest.raises(LibrivoxError, match="requested catalog ID"):
        catalog.resolve("1")
    client.result = book
    assert catalog.resolve("1") is book



@pytest.mark.parametrize("location", [
    "https://outside.example/catalog", "http://librivox.org/catalog",
    "https://127.0.0.1/private", "https://user:secret@librivox.org/catalog", "",
])
def test_catalog_redirects_are_checked_before_any_followup_request(location):
    response = FakeResponse({})
    response.status_code = 302
    response.headers = {"Location": location}

    class Session(FakeSession):
        def get(self, url, **kwargs):
            assert kwargs.get("allow_redirects") is False
            assert not self.calls, "Rejected destination must not be contacted"
            return super().get(url, **kwargs)

    session = Session(response)
    with pytest.raises(LibrivoxError, match="redirect"):
        LibrivoxClient(session).search_title("Example")
    assert response.closed and len(session.calls) == 1


def test_official_https_redirect_is_bounded_and_releases_each_response():
    redirect = FakeResponse({})
    redirect.status_code = 302
    redirect.headers = {"Location": "/api/feed/updated?format=json"}
    result = FakeResponse({"books": [audiobook_payload()]}, url="https://librivox.org/api/feed/updated?format=json")

    class Session(FakeSession):
        def get(self, url, **kwargs):
            assert kwargs.get("allow_redirects") is False
            self.response = redirect if not self.calls else result
            return super().get(url, **kwargs)

    session = Session(redirect)
    assert LibrivoxClient(session).search_title("Example")[0].catalog_id == "123"
    assert len(session.calls) == 2
    assert session.calls[1][0] == result.url
    assert session.calls[1][1]["params"] is None
    assert redirect.closed and result.closed


def test_official_redirect_loop_stops_without_consuming_bodies():
    responses = []

    class Session(FakeSession):
        def get(self, url, **kwargs):
            assert kwargs.get("allow_redirects") is False
            assert len(responses) < 6
            response = FakeResponse({})
            response.status_code = 302
            response.headers = {"Location": "/api/feed/audiobooks"}
            responses.append(response)
            return response

    with pytest.raises(LibrivoxError, match="redirect"):
        LibrivoxClient(Session(FakeResponse({}))).search_title("Example")
    assert len(responses) == 6 and all(response.closed for response in responses)


def test_zero_padded_explicit_id_resolves_same_book_and_cache(book):
    response = FakeResponse({"books": [audiobook_payload()]})
    session = FakeSession(response)
    catalog = LibrivoxCatalog(LibrivoxClient(session))
    assert catalog.resolve("id:00123") == book
    assert catalog.resolve("id:123") == book
    assert len(session.calls) == 1
    assert session.calls[0][1]["params"]["id"] == "123"
