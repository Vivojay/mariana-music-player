import json

import pytest

import lyrics_provider.get_lyrics as get_lyrics
from mariana.models import IdentityStatus, LyricsResult, TrackIdentity


@pytest.fixture
def lyrics_paths(monkeypatch, tmp_path):
    temp = tmp_path / "temp"
    res = tmp_path / "res"
    wallpapers = res / "lyrics-wallpapers"
    temp.mkdir()
    wallpapers.mkdir(parents=True)
    (res / "default.css").write_text("html { color: white; }\n", encoding="utf-8")
    (wallpapers / "1.DEFAULT.jpg").write_bytes(b"image")
    (wallpapers / "2.other.jpg").write_bytes(b"image")
    monkeypatch.setattr(get_lyrics, "TEMP_DIR", temp)
    monkeypatch.setattr(get_lyrics, "RES_DIR", res)
    monkeypatch.setattr(get_lyrics, "WALLPAPER_DIR", wallpapers)
    return temp, res, wallpapers


def test_natural_sort_helpers():
    names = ["10.jpg", "2.jpg", "1.jpg"]
    names.sort(key=get_lyrics.natural_keys)
    assert names == ["1.jpg", "2.jpg", "10.jpg"]


def test_open_identification_lyrics_flow(monkeypatch, tmp_path):
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")

    class Service:
        def identify(self, _media, pcm=None):
            assert pcm is None
            return TrackIdentity(
                IdentityStatus.IDENTIFIED, title="Track", artist="Artist", recording_mbid="mbid", confidence=0.9
            )

        def lyrics(self, _media, _identity):
            return LyricsResult(IdentityStatus.IDENTIFIED, plain="one\ntwo", provider="LRCLIB")

    monkeypatch.setattr(get_lyrics, "IDENTIFICATION_SERVICE", Service())
    monkeypatch.setattr(get_lyrics, "get_settings", lambda: ([".mp3"], {}))
    assert get_lyrics.get_lyrics(5, False, songfile=str(song)) == ("one\ntwo", "Artist — Track")


def test_create_lyrics_html_renders_cached_text(lyrics_paths):
    temp, _res, _wallpapers = lyrics_paths
    separator = "-" * 80
    (temp / "lyrics.txt").write_text(
        f"{separator}\nArtist\n{separator}\n\nline one\n\nline two\n", encoding="utf-8"
    )
    assert get_lyrics.create_lyrics_html() == 0
    html = (temp / "lyrics.html").read_text(encoding="utf-8")
    assert "<h1 class = 'main'>Artist</h1>" in html
    assert "<p>line one</p>" in html
    assert "<br>" in html


def test_create_lyrics_html_returns_failure_when_cache_missing(lyrics_paths):
    assert get_lyrics.create_lyrics_html() == 1


def test_show_window_writes_solid_color_assets(monkeypatch, lyrics_paths):
    temp, res, _wallpapers = lyrics_paths
    settings = {
        "use solid color bg": True,
        "solid color bg": {"color": "#123456"},
        "webview wallpaper": {"wallpaper folder": "", "wallpaper name or number": 1},
    }
    monkeypatch.setattr(get_lyrics, "get_settings", lambda: ([".mp3"], settings))
    monkeypatch.setattr(get_lyrics, "get_lyrics", lambda **_kwargs: ("line", "Artist"))
    assert get_lyrics.show_window(5, False, False) is None
    assert "background-color: #123456" in (res / "style.css").read_text(encoding="utf-8")
    assert "Artist" in (temp / "lyrics.txt").read_text(encoding="utf-8")


def test_show_window_uses_cache_and_open_attribution(monkeypatch, lyrics_paths):
    temp, _res, _wallpapers = lyrics_paths
    separator = "-" * 80
    (temp / "lyrics.txt").write_text(
        f"{separator}\nCached Artist\n{separator}\nCached lyrics", encoding="utf-8"
    )
    captured = {}
    monkeypatch.setattr(
        get_lyrics.subprocess,
        "Popen",
        lambda args, **kwargs: captured.update(args=args, kwargs=kwargs),
    )
    get_lyrics.show_window(5, True, False, refresh_lyrics=False)
    payload = json.loads(captured["args"][2])
    assert payload["head_text"] == "Cached Artist"
    assert "LRCLIB" in payload["foot_text"]
    assert "Chromaprint" in payload["foot_text"]
    assert captured["kwargs"]["shell"] is False


def test_show_window_uses_custom_wallpaper_and_reports_missing_file(monkeypatch, lyrics_paths):
    _temp, res, _wallpapers = lyrics_paths
    custom = res.parent / "custom"
    custom.mkdir()
    (custom / "wall.jpg").write_bytes(b"image")
    settings = {
        "use solid color bg": False,
        "solid color bg": {"color": "#000"},
        "webview wallpaper": {"wallpaper folder": str(custom), "wallpaper name or number": "wall"},
    }
    messages = []
    monkeypatch.setattr(get_lyrics, "get_settings", lambda: ([".mp3"], settings))
    monkeypatch.setattr(get_lyrics, "get_lyrics", lambda **_kwargs: ("line", "Artist"))
    monkeypatch.setattr(get_lyrics, "SAY", lambda **kwargs: messages.append(kwargs))
    get_lyrics.show_window(5, False, False)
    css = (res / "style.css").read_text(encoding="utf-8")
    assert str((custom / "wall.jpg").resolve()).replace("\\", "/") in css

    settings["webview wallpaper"]["wallpaper name or number"] = "missing"
    get_lyrics.show_window(5, False, False)
    assert any("invalid wallpaper" in message["display_message"] for message in messages)


@pytest.mark.parametrize(("selection", "expected"), [(2, "2.other.jpg"), ("2.other", "2.other.jpg")])
def test_show_window_selects_bundled_wallpaper(monkeypatch, lyrics_paths, selection, expected):
    _temp, res, _wallpapers = lyrics_paths
    settings = {
        "use solid color bg": False,
        "solid color bg": {"color": "#000"},
        "webview wallpaper": {"wallpaper folder": "", "wallpaper name or number": selection},
    }
    monkeypatch.setattr(get_lyrics, "get_settings", lambda: ([".mp3"], settings))
    monkeypatch.setattr(get_lyrics, "get_lyrics", lambda **_kwargs: ("line", "Artist"))
    get_lyrics.show_window(5, False, False)
    assert expected in (res / "style.css").read_text(encoding="utf-8")


def test_show_window_handles_invalid_wallpaper_index_and_missing_cache(monkeypatch, lyrics_paths):
    temp, _res, _wallpapers = lyrics_paths
    settings = {
        "use solid color bg": False,
        "solid color bg": {"color": "#000"},
        "webview wallpaper": {"wallpaper folder": "", "wallpaper name or number": 99},
    }
    messages = []
    spawned = {}
    monkeypatch.setattr(get_lyrics, "get_settings", lambda: ([".mp3"], settings))
    monkeypatch.setattr(get_lyrics, "get_lyrics", lambda **_kwargs: ("line", "Artist"))
    monkeypatch.setattr(get_lyrics, "SAY", lambda **kwargs: messages.append(kwargs))
    get_lyrics.show_window(5, False, False)
    assert any("between 1 and" in message["display_message"] for message in messages)
    (temp / "lyrics.txt").unlink()

    monkeypatch.setattr(
        get_lyrics.subprocess,
        "Popen",
        lambda args, **kwargs: spawned.update(args=args, kwargs=kwargs),
    )
    get_lyrics.show_window(5, True, False, refresh_lyrics=False)
    payload = json.loads(spawned["args"][2])
    assert payload["head_text"] == "Lyrics N/A"
    assert payload["text_to_be_displayed"] == "(Lyrics not available)"
