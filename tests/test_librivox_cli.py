from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.librivox import LibrivoxCatalog, LibrivoxError, parse_book
from mariana.models import MediaRef, PlaybackSnapshot, PlaybackState
from mariana.queueing import PersistentQueue
from tests.test_librivox import audiobook_payload


class CatalogClient:
    def __init__(self, book):
        self.book_result = book
        self.searches = []

    def search_title(self, query, *, limit, offset):
        options = {"limit": limit, "offset": offset}
        self.searches.append(("title", query, options))
        return [self.book_result]

    def search_author(self, surname, *, limit, offset):
        options = {"limit": limit, "offset": offset}
        self.searches.append(("author", surname, options))
        return [self.book_result]

    def search_genre(self, genre, *, limit, offset):
        options = {"limit": limit, "offset": offset}
        self.searches.append(("genre", genre, options))
        return [self.book_result]

    def recent(self, *, days, limit, offset):
        options = {"days": days, "limit": limit, "offset": offset}
        self.searches.append(("recent", "", options))
        return [self.book_result]

    def book(self, catalog_id):
        assert catalog_id == self.book_result.catalog_id
        return self.book_result


@pytest.fixture
def librivox_cli(monkeypatch):
    book = parse_book(audiobook_payload())
    assert book is not None
    client = CatalogClient(book)
    catalog = LibrivoxCatalog(client)
    database = MarianaDatabase(":memory:")
    queue = PersistentQueue(database)
    output = []
    events = []
    monkeypatch.setattr(main, "LIBRIVOX", catalog)
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: output.append(str(value)))
    monkeypatch.setattr(
        main,
        "RECOMMENDER",
        SimpleNamespace(record_event=lambda media, event, **_kwargs: events.append((media, event))),
    )
    monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
    monkeypatch.setattr(main.DESKTOP_CONTROL, "emit", lambda *_args, **_kwargs: None)
    yield book, client, catalog, queue, output, events
    database.close()


def test_librivox_search_recent_show_and_chapter_listing(librivox_cli):
    book, client, _catalog, _queue, output, _events = librivox_cli

    assert main.librivox_command(
        ["search", "Example", "Book", "--limit", "4", "--offset", "2"]
    ) == (book,)
    assert client.searches[-1] == ("title", "Example Book", {"limit": 4, "offset": 2})
    main.librivox_command(["show", "1"])
    main.librivox_command(["chapters", "id:123"])
    main.librivox_command(["recent", "14", "--limit", "3"])

    rendered = "\n".join(output)
    assert "Catalog ID" in rendered
    assert "The Example Book" in rendered
    assert "A carefully read example." in rendered
    assert "Rae Reader" in rendered
    assert client.searches[-1] == (
        "recent",
        "",
        {"days": 14, "limit": 3, "offset": 0},
    )


def test_librivox_play_uses_durable_media_and_prepares_complete_book_navigation(
    librivox_cli, monkeypatch
):
    book, _client, catalog, queue, _output, events = librivox_cli
    catalog.results = (book,)
    played = []
    monkeypatch.setattr(main, "_play_queue_item", lambda item: played.append(item))

    media = cast(MediaRef, main.librivox_command(["play", "1", "2"]))

    assert media.title == "The Example Book — Chapter Two"
    assert media.album == "The Example Book"
    assert media.artist == "Second Reader"
    assert played[0].media == media
    assert [item.media.title for item in queue.items()] == [
        "The Example Book — Chapter One",
        "The Example Book — Chapter Two",
    ]
    assert queue.current().media.stable_id == media.stable_id
    assert [event for _media, event in events] == ["manual_queue", "manual_queue"]


def test_librivox_current_and_book_navigation_use_persistent_queue(
    librivox_cli, monkeypatch
):
    book, _client, catalog, queue, output, _events = librivox_cli
    catalog.results = (book,)
    active_media: list[MediaRef | None] = [None]
    active_state = [PlaybackState.IDLE]
    played: list[MediaRef] = []

    def snapshot():
        media = active_media[0]
        return PlaybackSnapshot(
            state=active_state[0],
            position=25 if media is not None else 0,
            duration=media.duration if media is not None else None,
            media=media,
        )

    def play(item):
        played.append(item.media)
        active_media[0] = item.media
        active_state[0] = PlaybackState.PLAYING

    monkeypatch.setattr(main.vas.controller, "snapshot", snapshot)
    monkeypatch.setattr(main, "_play_queue_item", play)

    second = cast(MediaRef, main.librivox_command(["play", "1", "2"]))
    current = cast(dict[str, object], main.librivox_command(["current"]))
    assert main.librivox_command(["chapters", "current"]) == book
    assert current["chapter"] == 2
    assert current["chapter_count"] == 2
    assert current["book_id"] == "123"
    assert "2/2" in "\n".join(output)

    first = cast(MediaRef, main.librivox_command(["previous"]))
    assert first.resolver_data["librivox_section_number"] == 1
    queued = queue.current()
    assert queued is not None and queued.media.stable_id == first.stable_id

    assert cast(MediaRef, main.librivox_command(["next"])).stable_id == second.stable_id
    assert cast(MediaRef, main.librivox_command(["goto", "1"])).stable_id == first.stable_id
    assert cast(MediaRef, main.librivox_command(["last"])).stable_id == second.stable_id
    assert cast(MediaRef, main.librivox_command(["first"])).stable_id == first.stable_id
    with pytest.raises(LibrivoxError, match="does not wrap"):
        main.librivox_command(["previous"])
    assert [media.resolver_data["librivox_section_number"] for media in played] == [
        2,
        1,
        2,
        1,
        2,
        1,
    ]


def test_librivox_queue_cursor_restores_current_chapter_and_resume(
    librivox_cli, monkeypatch
):
    book, _client, catalog, queue, _output, _events = librivox_cli
    catalog.results = (book,)
    played = []
    monkeypatch.setattr(main, "_play_queue_item", lambda item: played.append(item.media))
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(PlaybackState.IDLE),
    )

    main.librivox_command(["play", "1", "2"])
    restored_queue = PersistentQueue(queue.database)
    monkeypatch.setattr(main, "QUEUE", restored_queue)

    current = cast(dict[str, object], main.librivox_command(["current"]))
    resumed = cast(MediaRef, main.librivox_command(["resume"]))
    assert current["chapter"] == 2
    assert current["chapter_count"] == 2
    assert resumed.resolver_data["librivox_section_number"] == 2
    selected = restored_queue.current()
    assert selected is not None and selected.media.stable_id == resumed.stable_id


def test_librivox_restart_and_resume_preserve_active_chapter_identity(
    librivox_cli, monkeypatch
):
    book, _client, catalog, _queue, output, _events = librivox_cli
    media = catalog.media(book, book.sections[0])
    state = {"value": PlaybackState.PAUSED}
    seeks = []
    resumes = []

    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            state=state["value"], position=42, duration=media.duration, media=media
        ),
    )
    monkeypatch.setattr(
        main.vas.controller,
        "seek",
        lambda value, **kwargs: seeks.append((value, kwargs)),
    )

    def resume(**kwargs):
        resumes.append(kwargs)
        state["value"] = PlaybackState.PLAYING

    monkeypatch.setattr(main.vas.controller, "resume", resume)
    monkeypatch.setattr(
        main,
        "_playback_status_projection",
        lambda: SimpleNamespace(to_dict=dict),
    )

    assert cast(MediaRef, main.librivox_command(["restart"])).stable_id == media.stable_id
    assert seeks == [(0, {"origin": "cli"})]
    assert cast(MediaRef, main.librivox_command(["resume"])).stable_id == media.stable_id
    assert resumes == [{"origin": "cli"}]
    assert "Restarted LibriVox chapter" in "\n".join(output)


def test_librivox_download_uses_existing_guarded_downloader_and_safe_section_names(
    librivox_cli, monkeypatch
):
    book, _client, catalog, _queue, _output, _events = librivox_cli
    catalog.results = (book,)
    calls = []
    monkeypatch.setattr(
        main,
        "_download_media_link",
        lambda media_url, **kwargs: calls.append((media_url, kwargs)) or kwargs["destination"],
    )

    destination = Path("C:/Mariana-Test-Downloads")
    completed = cast(
        tuple[Path, ...],
        main.librivox_command(
            [
                "download",
                "1",
                "all",
                "--format",
                "opus",
                "--to",
                str(destination),
                "--yes",
            ]
        ),
    )

    assert len(completed) == len(calls) == 2
    assert calls[0][0].endswith("01_chapter.mp3")
    assert calls[0][1]["bound_media"].title.endswith("Chapter One")
    assert calls[0][1]["output_format"] == "opus"
    assert calls[0][1]["destination"] == (
        destination / "The Example Book - 001 - Chapter One.opus"
    )
    assert calls[0][1]["assume_yes"] is True


def test_librivox_open_uses_only_catalog_supplied_official_links(librivox_cli, monkeypatch):
    book, _client, catalog, _queue, _output, _events = librivox_cli
    catalog.results = (book,)
    opened = []
    monkeypatch.setattr(main.webbrowser, "open", lambda value: opened.append(value) or True)

    assert main.librivox_command(["rss", "1"]) == book.rss_url
    assert main.librivox_command(["open", "id:123", "archive"]) == book.archive_url
    assert opened == [book.rss_url, book.archive_url]
    with pytest.raises(LibrivoxError, match="catalog, text, archive"):
        main.librivox_command(["open", "1", "unknown"])


def test_librivox_media_info_recovers_stable_provider_facts_after_persistence(
    librivox_cli, monkeypatch
):
    book, _client, catalog, queue, _output, _events = librivox_cli
    media = catalog.media(book, book.sections[0])
    queue.add(media)
    restored = queue.items()[0].media
    monkeypatch.setattr(
        main.vas.controller,
        "snapshot",
        lambda: PlaybackSnapshot(
            state=PlaybackState.PAUSED,
            position=12,
            duration=restored.duration,
            media=restored,
        ),
    )

    _media, info = main._media_info(["current"])

    assert info["metadata"]["provider"] == "LibriVox"
    assert info["metadata"]["provider_media_id"] == "901"
    assert info["metadata"]["publisher_id"] == "123"


def test_librivox_rejects_ambiguous_or_invalid_requests(librivox_cli):
    book, _client, catalog, _queue, _output, _events = librivox_cli
    catalog.results = (book,)
    with pytest.raises(LibrivoxError, match="complete audiobook"):
        main.librivox_command(["play", "1", "all"])
    with pytest.raises(LibrivoxError, match="between 1 and 50"):
        main.librivox_command(["search", "Example", "--limit", "0"])
    with pytest.raises(LibrivoxError, match="format must be one of"):
        main.librivox_command(["download", "1", "1", "--format", "exe", "--yes"])


def test_librivox_alias_routes_without_network_at_status(librivox_cli):
    _book, client, _catalog, _queue, output, _events = librivox_cli

    assert main.process("lv status") is None

    assert client.searches == []
    assert any("no account or API key required" in line for line in output)
