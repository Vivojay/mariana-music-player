import json

import pytest

from mariana.database import MarianaDatabase
from mariana.librivox import LibrivoxCatalog, LibrivoxClient, LibrivoxError, parse_book
from mariana.models import has_durable_podcast_identity
from mariana.preferences import MediaPreferences, PreferenceState
from mariana.sources import sanitized_resolver_data


def audiobook_payload(*, listen_url="https://archive.org/download/book/01_chapter.mp3"):
    return {
        "id": "123",
        "title": "The Example Book",
        "description": "<p>A <strong>carefully read</strong> example.</p>",
        "language": "English",
        "copyright_year": "1901",
        "num_sections": "2",
        "totaltime": "1:02:03",
        "totaltimesecs": "3723",
        "url_rss": "https://librivox.org/rss/123",
        "url_zip_file": "https://archive.org/download/book/book_64kb_mp3.zip",
        "url_librivox": "https://librivox.org/the-example-book-by-author/",
        "url_text_source": "https://www.gutenberg.org/ebooks/123",
        "url_iarchive": "https://archive.org/details/book",
        "coverart_jpg": "https://archive.org/download/book/cover.jpg",
        "authors": [{"first_name": "Ada", "last_name": "Author"}],
        "translators": [{"first_name": "Tara", "last_name": "Translator"}],
        "genres": [{"name": "Fiction"}, {"name": "Adventure"}],
        "sections": [
            {
                "id": "901",
                "section_number": "1",
                "title": "Chapter One",
                "listen_url": listen_url,
                "playtime": "10:05",
                "language": "English",
                "readers": [{"display_name": "Rae Reader"}],
            },
            {
                "id": "902",
                "section_number": "2",
                "title": "Chapter Two",
                "listen_url": "https://archive.org/download/book/02_chapter.mp3",
                "playtime": "11:06",
                "readers": [{"display_name": "Second Reader"}],
            },
        ],
    }


class FakeResponse:
    def __init__(self, payload, *, url="https://librivox.org/api/feed/audiobooks"):
        self.content = json.dumps(payload).encode()
        self.url = url
        self.closed = False
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.max_redirects = 0

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_parse_book_retains_allowlisted_catalog_sections_and_cleans_html():
    book = parse_book(audiobook_payload())

    assert book is not None
    assert book.catalog_id == "123"
    assert book.title == "The Example Book"
    assert book.description == "A carefully read example."
    assert book.authors == ("Ada Author",)
    assert book.translators == ("Tara Translator",)
    assert book.genres == ("Fiction", "Adventure")
    assert book.total_seconds == 3723
    assert book.sections[0].readers == ("Rae Reader",)
    assert book.sections[0].duration_seconds == 605
    assert book.sections[0].listen_url.endswith("01_chapter.mp3")


def test_client_uses_released_catalog_parameters_and_bounded_result_count():
    session = FakeSession(FakeResponse({"books": [audiobook_payload()]}))
    client = LibrivoxClient(session)

    books = client.search_title("Example", limit=4, offset=8)

    assert books[0].catalog_id == "123"
    url, request = session.calls[0]
    assert url == "https://librivox.org/api/feed/audiobooks"
    assert request["params"] == {
        "title": "^Example",
        "limit": 4,
        "offset": 8,
        "coverart": 1,
        "format": "json",
    }
    assert request["timeout"] == (5, 20)
    assert request["stream"] is True
    assert session.response.closed is True
    with pytest.raises(LibrivoxError, match="between 1 and 50"):
        client.search_title("Example", limit=51)
    with pytest.raises(LibrivoxError, match="non-negative whole number"):
        client.search_title("Example", offset=-1)


def test_client_maps_author_genre_recent_and_detail_to_documented_api_fields(monkeypatch):
    session = FakeSession(FakeResponse({"books": [audiobook_payload()]}))
    client = LibrivoxClient(session)
    monkeypatch.setattr("mariana.librivox.time.time", lambda: 2_000_000)

    client.search_author("Wells", limit=2, offset=1)
    assert session.calls[-1][1]["params"]["author"] == "Wells"
    client.search_genre("Poetry", limit=3, offset=2)
    assert session.calls[-1][1]["params"]["genre"] == "Poetry"
    client.recent(days=10, limit=4, offset=3)
    assert session.calls[-1][1]["params"]["since"] == 1_136_000
    client.book("123")
    assert session.calls[-1][1]["params"] == {
        "id": "123",
        "extended": 1,
        "coverart": 1,
        "limit": 1,
        "format": "json",
    }


def test_client_rejects_external_redirects_and_oversized_or_invalid_documents():
    redirected = LibrivoxClient(
        FakeSession(FakeResponse({"books": []}, url="https://example.test/catalog"))
    )
    with pytest.raises(LibrivoxError, match="outside its official catalog host"):
        redirected.book("123")

    malformed = LibrivoxClient(FakeSession(FakeResponse(["unexpected"])))
    with pytest.raises(LibrivoxError, match="unexpected catalog response"):
        malformed.book("123")

    oversized_response = FakeResponse({"books": []})
    oversized_response.content = b"x" * 1025
    oversized = LibrivoxClient(FakeSession(oversized_response), max_response_bytes=1024)
    with pytest.raises(LibrivoxError, match="safety limit"):
        oversized.book("123")


def test_catalog_uses_result_numbers_and_explicit_catalog_ids():
    book = parse_book(audiobook_payload())
    assert book is not None

    class Client:
        def search_title(self, *_args, **_kwargs):
            return [book]

        def book(self, catalog_id):
            assert catalog_id == "123"
            return book

    catalog = LibrivoxCatalog(Client())  # type: ignore[arg-type]
    assert catalog.search("title", "Example") == (book,)
    assert catalog.resolve("1") == book
    assert catalog.resolve("id:123") == book
    assert catalog.select_sections(book, "2") == (book.sections[1],)
    with pytest.raises(LibrivoxError, match="result number"):
        LibrivoxCatalog(Client()).resolve("123")  # type: ignore[arg-type]


def test_chapter_identity_survives_transport_changes_and_distinguishes_sections():
    original = parse_book(audiobook_payload())
    moved = parse_book(audiobook_payload(listen_url="https://archive.org/download/book/new-01.mp3"))
    assert original is not None and moved is not None
    catalog = LibrivoxCatalog()

    first = catalog.media(original, original.sections[0])
    changed_transport = catalog.media(moved, moved.sections[0])
    second = catalog.media(original, original.sections[1])

    assert first.stable_id == changed_transport.stable_id
    assert first.original_uri != changed_transport.original_uri
    assert first.stable_id != second.stable_id
    assert has_durable_podcast_identity(first)
    assert first.capabilities.downloadable and first.capabilities.seekable
    assert sanitized_resolver_data(first.resolver_data) == {
        "librivox_book_id": "123",
        "librivox_section_id": "901",
        "librivox_section_number": 1,
        "librivox_section_count": 2,
        "podcast_identity_kind": "guid",
    }

    database = MarianaDatabase(":memory:")
    try:
        preferences = MediaPreferences(database)
        assert preferences.toggle(first, PreferenceState.FAVORITE) == PreferenceState.FAVORITE
        restored = MediaPreferences(database).media(first.stable_id)
        assert restored is not None
        assert restored.resolver_data["librivox_book_id"] == "123"
        assert restored.resolver_data["librivox_section_number"] == 1
        assert restored.resolver_data["librivox_section_count"] == 2
        assert MediaPreferences(database).is_favorite(changed_transport)
    finally:
        database.close()
