import os
from pathlib import Path

import pytest
import requests

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource
from mariana.playlists import (
    MAX_PLAYLIST_IMPORT_BYTES,
    MAX_PLAYLIST_IMPORT_ITEMS,
    MAX_PLAYLIST_IMPORT_LINE_BYTES,
    PlaylistError,
    PlaylistStore,
)


def import_items(tmp_path: Path, text: str) -> list[MediaRef]:
    source = tmp_path / "source.m3u8"
    source.write_text(text, encoding="utf-8")
    with MarianaDatabase(tmp_path / "collections.db") as database:
        store = PlaylistStore(database)
        return store.flattened_media(store.import_m3u("Imported", source).tree)


@pytest.mark.parametrize(
    "uri",
    [
        "https://youtube.com/watch?v=abcdefghijk",
        "https://www.youtube.com/watch?v=abcdefghijk&list=example",
        "https://m.youtube.com/watch?v=abcdefghijk",
        "https://music.youtube.com/watch?v=abcdefghijk",
        "https://youtu.be/abcdefghijk?t=10",
        "https://www.youtu.be/abcdefghijk",
        "https://youtube.com/embed/abcdefghijk",
        "https://youtube.com/v/abcdefghijk",
        "https://youtube.com/shorts/abcdefghijk",
        "https://youtube.com/live/abcdefghijk",
        "https://youtube-nocookie.com/embed/abcdefghijk",
        "https://www.youtube-nocookie.com/embed/abcdefghijk",
        "https://youtube.com/redirect?url=https%3A%2F%2Fyoutu.be%2Fabcdefghijk",
        "https://youtube.com/attribution_link?u=%2Fwatch%3Fv%3Dabcdefghijk",
        "http://WWW.YOUTUBE.COM/watch?v=abcdefghijk",
        "https://youtu.be/abc123",
    ],
)
def test_supported_youtube_references_reuse_identity_parser_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, uri: str,
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Playlist import must not contact a provider")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    items = import_items(tmp_path, f"#EXTINF:-1,Chosen recording\n{uri}\n")

    assert len(items) == 1
    assert items[0].source == MediaSource.YOUTUBE
    assert items[0].original_uri == uri
    assert items[0].title == "Chosen recording"


@pytest.mark.parametrize(
    "uri",
    [
        "https://notyoutube.example/watch?v=abcdefghijk",
        "https://youtube.com.example/watch?v=abcdefghijk",
        "https://youtu.be.example/abcdefghijk",
        "https://www.youtube.example/watch?v=abcdefghijk",
        "https://youtube.com@external.example/watch?v=abcdefghijk",
        "https://external.example/audio.mp3?source=youtube.com",
        "https://youtube.com%2F@external.example/watch?v=abcdefghijk",
        "https://youtube.com%2f/watch?v=abcdefghijk",
        "https:///watch?v=abcdefghijk",
        "https://youtube.com/",
        "https://youtube.com/@creator",
        "https://www.youtube.com/watch?v=one&v=two",
        "https://www.youtube.com/watch?v=",
        "https://example.test/private.mp3?signature=private-value",
        "http://127.0.0.1:8080/local-stream",
    ],
)
def test_non_youtube_references_keep_generic_policy_and_original_destination(tmp_path: Path, uri: str):
    items = import_items(tmp_path, uri + "\n")

    assert len(items) == 1
    assert items[0].source == MediaSource.URL
    assert items[0].original_uri == uri


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_bom_unicode_titles_tabs_and_local_references_remain_compatible(tmp_path: Path, newline: str):
    lines = ["\ufeff#EXTM3U", "#EXTINF:-1,أغنية\tगीत", "\tmissing song.wav\t", "", "# comment", "other.wav"]
    items = import_items(tmp_path, newline.join(lines))

    assert [item.title for item in items] == ["أغنية\tगीत", None]
    assert [item.source for item in items] == [MediaSource.LOCAL, MediaSource.LOCAL]
    assert items[0].original_uri == str(tmp_path / "missing song.wav")
    assert items[1].original_uri == str(tmp_path / "other.wav")
    assert not (tmp_path / "missing song.wav").exists()
    assert not (tmp_path / "other.wav").exists()


@pytest.mark.parametrize("payload", [b"good.wav\n\xffbad.wav\n", b"good.wav\n\xc3", b"\xff\xfeg\x00o\x00"])
def test_malformed_utf8_never_creates_partial_playlist(tmp_path: Path, payload: bytes):
    source = tmp_path / "invalid.m3u8"
    source.write_bytes(payload)
    with MarianaDatabase(tmp_path / "collections.db") as database:
        store = PlaylistStore(database)
        preserved = store.create("Existing")

        with pytest.raises(PlaylistError, match="readable UTF-8"):
            store.import_m3u("Imported", source)

        assert store.list() == [preserved]
        assert store.revisions("Existing") == [1]


@pytest.mark.parametrize("control", ["\0", "\x1b", "\x0b", "\x7f"])
def test_unsafe_control_characters_are_rejected_atomically(tmp_path: Path, control: str):
    source = tmp_path / "invalid.m3u"
    source.write_text(f"good.wav\n#EXTINF:-1,unsafe{control}title\nother.wav\n", encoding="utf-8")
    with MarianaDatabase(tmp_path / "collections.db") as database:
        store = PlaylistStore(database)
        with pytest.raises(PlaylistError, match="unsupported control characters"):
            store.import_m3u("Imported", source)
        assert store.list() == []


def test_oversized_file_is_refused_before_reading_payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "oversized.m3u8"
    with source.open("wb") as stream:
        stream.truncate(MAX_PLAYLIST_IMPORT_BYTES + 1)
    original_open = Path.open

    class SizeGuard:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, *_args):
            raise AssertionError("Oversized payload must not be read")

    def opened(path: Path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return SizeGuard(stream) if path == source and args == ("rb",) else stream

    with MarianaDatabase(tmp_path / "collections.db") as database:
        monkeypatch.setattr(Path, "open", opened)
        store = PlaylistStore(database)
        with pytest.raises(PlaylistError, match="8 MiB"):
            store.import_m3u("Imported", source)
        assert store.list() == []


def test_file_growth_after_size_check_is_still_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "growing.m3u8"
    source.write_bytes(b"#EXTM3U\n")
    original_fstat = os.fstat
    expanded = False

    def growing(descriptor):
        nonlocal expanded
        details = original_fstat(descriptor)
        if not expanded:
            expanded = True
            with source.open("ab") as stream:
                stream.truncate(MAX_PLAYLIST_IMPORT_BYTES + 1)
        return details

    with MarianaDatabase(tmp_path / "collections.db") as database:
        with monkeypatch.context() as patch:
            patch.setattr(os, "fstat", growing)
            with pytest.raises(PlaylistError, match="8 MiB"):
                PlaylistStore(database).import_m3u("Imported", source)
        assert expanded
        assert PlaylistStore(database).list() == []


@pytest.mark.parametrize("prefix", ["# comment ", "#EXTINF:-1,", "https://example.test/"])
def test_overlong_lines_are_rejected_including_comments(tmp_path: Path, prefix: str):
    source = tmp_path / "overlong.m3u8"
    source.write_text("good.wav\n" + prefix + "x" * MAX_PLAYLIST_IMPORT_LINE_BYTES + "\n", encoding="utf-8")
    with MarianaDatabase(tmp_path / "collections.db") as database:
        store = PlaylistStore(database)
        with pytest.raises(PlaylistError, match="64 KiB"):
            store.import_m3u("Imported", source)
        assert store.list() == []


def test_line_byte_limit_counts_multibyte_text_not_characters(tmp_path: Path):
    with pytest.raises(PlaylistError, match="64 KiB"):
        import_items(tmp_path, "#" + "界" * (MAX_PLAYLIST_IMPORT_LINE_BYTES // 3 + 1))


def test_exact_line_byte_limit_is_accepted(tmp_path: Path):
    items = import_items(tmp_path, "#" + "x" * (MAX_PLAYLIST_IMPORT_LINE_BYTES - 1) + "\nmissing.wav\n")
    assert len(items) == 1
    assert items[0].original_uri == str(tmp_path / "missing.wav")


@pytest.mark.parametrize("count", [MAX_PLAYLIST_IMPORT_ITEMS, MAX_PLAYLIST_IMPORT_ITEMS + 1])
def test_entry_limit_accepts_boundary_and_rejects_overflow_without_partial_import(tmp_path: Path, count: int):
    source = tmp_path / "entries.m3u8"
    source.write_text("#EXTM3U\n" + "https://example.test/audio.mp3\n" * count, encoding="utf-8")
    with MarianaDatabase(tmp_path / "collections.db") as database:
        store = PlaylistStore(database)
        if count > MAX_PLAYLIST_IMPORT_ITEMS:
            with pytest.raises(PlaylistError, match="5000 media entries"):
                store.import_m3u("Imported", source)
            assert store.list() == []
        else:
            playlist = store.import_m3u("Imported", source)
            assert len(store.flattened_media(playlist.tree)) == count
            assert store.revisions("Imported") == [1]


@pytest.mark.parametrize("text", ["", "#EXTM3U\n\n\t\n# comment\n"])
def test_empty_import_remains_a_valid_empty_playlist(tmp_path: Path, text: str):
    assert import_items(tmp_path, text) == []


def test_invalid_url_reports_line_without_revealing_private_reference(tmp_path: Path):
    secret = "https://[invalid-host]/audio?token=do-not-display"
    source = tmp_path / "invalid.m3u8"
    source.write_text(f"good.wav\n{secret}\n", encoding="utf-8")
    with MarianaDatabase(tmp_path / "collections.db") as database:
        with pytest.raises(PlaylistError, match="invalid media reference on line 2") as caught:
            PlaylistStore(database).import_m3u("Imported", source)
        assert "do-not-display" not in str(caught.value)
        assert "invalid-host" not in str(caught.value)
        assert PlaylistStore(database).list() == []
