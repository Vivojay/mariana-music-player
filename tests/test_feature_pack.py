from mariana.chunk_cache import ChunkCache, rank_prefetch_candidates
from mariana.commands import parse_search
from mariana.feature_pack import ascii_art_placeholder, parse_rate_filter
from mariana.netstatus import NetMonitor, offline_message, requires_network
from mariana.query import parse_query, split_bulk_selection


def test_net_monitor_flips_with_threshold():
    monitor = NetMonitor(flip_threshold=2)
    assert monitor.snapshot().online is True
    monitor._apply_result(False, None)
    assert monitor.snapshot().online is True
    flipped = monitor._apply_result(False, None)
    assert flipped is not None and flipped.online is False
    assert "Offline" in offline_message("play youtube media", status=monitor.snapshot())


def test_search_rate_and_tag_filters():
    request = parse_search(["find", "beatles", "--rate", "3-5", "--tag", "rock,live"])
    assert request.rate_range == (3, 5)
    assert "rock" in request.tags and "live" in request.tags
    only_rate = parse_search(["find", "--rate", "5"])
    assert only_rate.rate_range == (5, 5)


def test_query_parse_and_bulk_selection():
    request = parse_query(
        ["query", "library", "where", "rate>=3", "and", "tag=rock", "order", "by", "published", "desc", "limit", "20"]
    )
    assert request.scope == "library"
    assert len(request.predicates) == 2
    assert request.limit == 20 and request.order_desc
    assert split_bulk_selection("1,2,6", maximum=10) == [1, 2, 6]
    assert split_bulk_selection("3-5,9", maximum=10) == [3, 4, 5, 9]
    assert split_bulk_selection("all", maximum=3) == [1, 2, 3]


def test_chunk_cache_and_prefetch_ranking():
    cache = ChunkCache(limit_bytes=1024 * 1024)
    cache.put("media-1", 0, b"hello")
    assert cache.get("media-1", 0) == b"hello"
    assert cache.get("media-1", 9) is None
    assert cache.pin_span("media-1", 0, 2) >= 0
    candidates = rank_prefetch_candidates(queue_next=[("a", "A"), ("b", "B")], autoplay_next=("c", "C"))
    assert candidates[0].stable_id == "a"
    assert candidates[0].score == 1.0


def test_net_monitor_and_rate_filter():
    monitor = NetMonitor()
    snapshot = monitor.snapshot()
    assert isinstance(snapshot.online, bool)
    assert requires_network("youtube") and not requires_network("local")
    assert parse_rate_filter("3-5") == (3, 5)
    assert parse_rate_filter("5-3") == (3, 5)
    assert "Offline" in offline_message("play youtube media")


def test_prefetch_ranking_weights():
    candidates = rank_prefetch_candidates(
        queue_next=[("a", "A"), ("b", "B")],
        autoplay_next=("c", "C"),
        chapter_next=("d", "D"),
        hotspot_labels=[("e", "E", 1.0)],
        limit=5,
    )
    scores = {item.stable_id: item.score for item in candidates}
    assert scores["a"] == 1.0
    assert scores["c"] == 0.8
    assert scores["d"] == 0.6
    assert scores["e"] == 0.4


def test_ascii_placeholder_shape():
    art = ascii_art_placeholder(width=24, height=6)
    lines = art.splitlines()
    assert len(lines) == 8
    assert all(line.startswith(("+", "|")) for line in lines)


def test_chapter_favorites_roundtrip(tmp_path):
    from mariana.database import MarianaDatabase
    from mariana.favorite_chapters import ChapterFavoriteStore

    database = MarianaDatabase(tmp_path / "test.db")
    store = ChapterFavoriteStore(database)
    assert store.toggle("media-1", 2, title="Chapter 3") is True
    assert store.is_favorite("media-1", 2) is True
    assert store.toggle("media-1", 2) is False
    assert store.list("media-1") == []
    database.close()


def test_decoder_read_oom_guards():
    from mariana.models import MediaRef, MediaSource
    from mariana.playback import DecoderSession

    media = MediaRef(MediaSource.LOCAL, "/tmp/x.mp3")
    session = DecoderSession(media)
    session._buffer.extend(b"\x00" * 800)
    assert session.read(0) == b""
    assert session.read(-5) == b""
    assert session.read(10**9) is not None


def test_catalogue_link_entries_present():
    from mariana.entertainment_catalog import BY_ID, search_catalogue

    for entry_id in ("diary-of-a-ceo", "nbc-dateline", "kexp-live-radio", "triple-j-like-a-version", "comic-con-clips"):
        assert entry_id in BY_ID
        assert BY_ID[entry_id].native is False
        assert BY_ID[entry_id].actions == ("details", "official-link")
    assert search_catalogue("diary")
    assert search_catalogue("triple")


def test_command_completion_fuzzy_and_flags():
    from mariana.command_completion import command_completions

    exact = command_completions("net", 3)
    assert any(item.text.strip() == "net" for item in exact)
    fuzzy = command_completions("et st", 5)
    assert isinstance(fuzzy, tuple)
    flagged = command_completions("find", 4)
    assert any("--rate" in item.summary or "--tag" in item.summary for item in flagged)


def test_console_art_encodings():
    import io

    from PIL import Image

    from mariana.console_art import image_bytes_to_ascii, iterm_chunk, kitty_chunk, terminal_graphics

    image = Image.new("RGB", (32, 16), color=(255, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    art = image_bytes_to_ascii(data, width=24)
    assert "+" in art and "|" in art
    assert kitty_chunk(data).startswith("\x1b_G")
    assert iterm_chunk(data).startswith("\x1b]1337;File=")
    assert terminal_graphics() in {"kitty", "iterm", "sixel", "none"}


def test_sixel_chunk_and_detection(monkeypatch):
    import io

    from PIL import Image

    from mariana.console_art import sixel_chunk, terminal_graphics

    image = Image.new("RGB", (48, 24), color=(10, 200, 90))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    out = sixel_chunk(buffer.getvalue())
    assert out.startswith("\x1bPq") and out.endswith("\x1b\\")
    assert '"1;1;' in out
    monkeypatch.setenv("TERM", "foot")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.delenv("MARIANA_SIXEL", raising=False)
    assert terminal_graphics() == "sixel"
    monkeypatch.setenv("MARIANA_SIXEL", "0")
    assert terminal_graphics() == "none"


def test_warm_first_blocks_local(tmp_path):
    from mariana.chunk_cache import ChunkCache, warm_first_blocks

    target = tmp_path / "media.bin"
    target.write_bytes(b"A" * 600 * 1024)
    cache = ChunkCache(limit_bytes=4 * 1024 * 1024, block_bytes=256 * 1024)
    stored = warm_first_blocks(cache, stable_id="m1", source=str(target), blocks=2)
    assert stored == 2
    first = cache.get("m1", 0)
    assert first is not None and len(first) == 256 * 1024


def test_smart_suggest_local_only(tmp_path):
    from mariana.smart_suggest import SmartSuggester

    store = SmartSuggester(tmp_path / "suggest.json")
    assert store.score("net", match_rank=1) == 1.0
    store.set_enabled(True)
    store.record("net")
    store.record("net")
    assert store.score("net", match_rank=1) < 1.0
    assert store.score("query", match_rank=1) == 1.0
