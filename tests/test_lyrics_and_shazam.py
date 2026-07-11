import asyncio
import json
from pathlib import Path

import pytest

import lyrics_provider.detect_song as detect_song
import lyrics_provider.get_lyrics as get_lyrics
import lyrics_provider.get_related_music as related


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
    assert get_lyrics.atoi("12") == 12
    assert get_lyrics.atoi("x") == "x"


def test_get_lyrics_handles_local_web_and_unsupported_sources(monkeypatch):
    monkeypatch.setattr(get_lyrics, "get_settings", lambda: ([".mp3"], {}))
    monkeypatch.setattr(
        get_lyrics.lyrics_provider.detect_song,
        "get_weblink_audio_info",
        lambda **kwargs: {"display_name": kwargs["weblink"], "lyrics": ["a", "b"]},
    )
    assert get_lyrics.get_lyrics(5, False, weblink="stream", isYT=True) == ("a\nb", "stream")
    assert get_lyrics.get_lyrics(5, False, songfile="track.wav") == ("(Lyrics not available)", "Lyrics N/A")

    monkeypatch.setattr(
        get_lyrics.lyrics_provider.detect_song,
        "get_song_info",
        lambda *_a, **_k: {"display_name": "Artist", "lyrics": []},
    )
    assert get_lyrics.get_lyrics(5, True, songfile="track.mp3") == ("(Lyrics not available)", "Artist")


def test_create_lyrics_html_renders_cached_text(lyrics_paths):
    temp, _res, _wallpapers = lyrics_paths
    separator = "-" * 80
    (temp / "lyrics.txt").write_text(f"{separator}\nArtist\n{separator}\n\nline one\n\nline two\n", encoding="utf-8")

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
    assert (temp / "lyrics.html").is_file()


def test_show_window_invalid_wallpaper_falls_back_and_reports_range(monkeypatch, lyrics_paths):
    _temp, res, _wallpapers = lyrics_paths
    settings = {
        "use solid color bg": False,
        "solid color bg": {"color": "black"},
        "webview wallpaper": {"wallpaper folder": "", "wallpaper name or number": 99},
    }
    messages = []
    monkeypatch.setattr(get_lyrics, "get_settings", lambda: ([".mp3"], settings))
    monkeypatch.setattr(get_lyrics, "get_lyrics", lambda **_kwargs: ("line", "Artist"))
    monkeypatch.setattr(get_lyrics, "SAY", lambda **kwargs: messages.append(kwargs))

    get_lyrics.show_window(5, False, False)

    assert "between 1 and 2" in messages[0]["display_message"]
    assert "lyrics-wallpapers/1.DEFAULT.jpg" in (res / "style.css").read_text(encoding="utf-8")


def test_show_window_uses_cache_and_spawns_with_current_python(monkeypatch, lyrics_paths):
    temp, _res, _wallpapers = lyrics_paths
    separator = "-" * 80
    (temp / "lyrics.txt").write_text(f"{separator}\nCached Artist\n{separator}\nCached lyrics", encoding="utf-8")
    captured = {}
    monkeypatch.setattr(
        get_lyrics.subprocess,
        "Popen",
        lambda args, **kwargs: captured.update(args=args, kwargs=kwargs),
    )

    get_lyrics.show_window(5, True, False, refresh_lyrics=False)

    payload = json.loads(captured["args"][2])
    assert payload["head_text"] == "Cached Artist"
    assert payload["foot_text"] == "Lyrics Powered by ShazamIO"
    assert captured["args"][0] == get_lyrics.sys.executable
    assert captured["kwargs"]["shell"] is False


def test_normalize_song_info_empty_and_fallbacks(fixture_dir):
    response = json.loads((fixture_dir / "shazam_match.json").read_text(encoding="utf-8"))
    assert detect_song.normalize_song_info({}) == {}
    normalized = detect_song.normalize_song_info(response)
    assert normalized["display_name"] == "Artist - Track"
    assert normalized["lyrics"] == ["line one", "line two"]
    assert detect_song._section(response["track"], "MISSING") == {}


def test_weblink_audio_sampling_clamps_duration_and_cleans_up(monkeypatch, tmp_path):
    monkeypatch.setattr(detect_song, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(detect_song, "stream_url", lambda *_a, **_k: "direct-stream")
    monkeypatch.setattr(detect_song, "get_song_info", lambda path: {"path": path})
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        Path(args[-1]).write_bytes(b"sample")

    monkeypatch.setattr(detect_song.sp, "run", fake_run)
    result = detect_song.get_weblink_audio_info(100, "youtube", isYT=True)
    assert result["path"].endswith("song_detect.mp3")
    assert captured["args"][captured["args"].index("-t") + 1] == "20"
    assert "direct-stream" in captured["args"]
    assert not (tmp_path / "song_detect.mp3").exists()


def test_weblink_audio_sampling_handles_missing_ffmpeg(monkeypatch, tmp_path):
    monkeypatch.setattr(detect_song, "TEMP_DIR", tmp_path)
    monkeypatch.setattr(detect_song.sp, "run", lambda *_a, **_k: (_ for _ in ()).throw(FileNotFoundError()))
    assert detect_song.get_weblink_audio_info(None, "stream") == {}


def test_get_song_info_modes_and_related_spawn(monkeypatch, tmp_path, fixture_dir, capsys):
    song = tmp_path / "song.mp3"
    song.write_bytes(b"audio")
    response = json.loads((fixture_dir / "shazam_match.json").read_text(encoding="utf-8"))

    async def recognize(_song):
        return response

    spawned = {}
    monkeypatch.setattr(detect_song, "shazam_detect_song", recognize)
    monkeypatch.setattr(detect_song.sp, "Popen", lambda args, **kwargs: spawned.update(args=args, kwargs=kwargs))

    assert detect_song.get_song_info(str(song), get_title_only=True) == "Artist - Track"
    result = detect_song.get_song_info(str(song), display_shazam_id=True, get_related=True)
    assert result["shazam_id"] == "123"
    assert spawned["args"][0] == detect_song.sys.executable
    assert "Shazam ID: 123" in capsys.readouterr().out

    with pytest.raises(OSError):
        detect_song.get_song_info(str(tmp_path / "missing.mp3"))


def test_related_track_normalization_and_fetch(monkeypatch, fixture_dir):
    track = json.loads((fixture_dir / "shazam_match.json").read_text(encoding="utf-8"))["track"]
    normalized = related._normalize_related_track(track)
    assert normalized["youtube_url"].endswith("abc12345678")
    assert normalized["metadata"][0]["text"] == "Test Album"

    class FakeShazam:
        async def related_tracks(self, **kwargs):
            assert kwargs == {"track_id": 123, "limit": 2, "offset": 0}
            return {"data": [track]}

    monkeypatch.setattr(related, "Shazam", FakeShazam)
    assert asyncio.run(related._fetch_related(123, limit=2))[0]["display_name"] == "Artist - Track"


def test_get_related_music_persists_nonempty_results(monkeypatch, tmp_path):
    output = tmp_path / "nested" / "related.yml"
    monkeypatch.setattr(related, "RELATED_SONGS_PATH", output)

    async def fake_fetch(_song_id):
        return [{"display_name": "Related"}]

    monkeypatch.setattr(related, "_fetch_related", fake_fetch)
    assert related.get_related_music("123") == [{"display_name": "Related"}]
    assert "Related" in output.read_text(encoding="utf-8")
