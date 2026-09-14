"""Application boundaries for finite-media inspection and confirmed downloads."""

from types import SimpleNamespace

import pytest

import main
from mariana.command_catalog import COMMAND_CATALOG, CommandRisk
from mariana.database import MarianaDatabase
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import MediaPreferences
from recommendation_engine.engine import RecommendationEngine


def test_download_help_and_catalog_describe_confirmed_shortcut(monkeypatch):
    output = []
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))
    rows = main.help_command(["downloads"])
    assert isinstance(rows, tuple)
    assert rows[0][0] == "Downloads"
    assert "dl [y|yes|--yes]" in rows[0][1]
    assert "dl --yes" in "\n".join(output)
    spec = next(spec for spec in COMMAND_CATALOG if spec.canonical == "dl")
    assert spec.risk == CommandRisk.EXTERNAL_ACTION


@pytest.mark.parametrize("state", [
    PlaybackState.BUFFERING, PlaybackState.PLAYING, PlaybackState.PAUSED,
    PlaybackState.SEEKING, PlaybackState.CROSSFADING,
])
def test_default_download_uses_exact_active_identity_without_history(monkeypatch, state):
    media = MediaRef(MediaSource.URL, "https://media.test/track?token=private", title="Track")
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(state, media=media),
    ))
    monkeypatch.setattr(main, "DATABASE", SimpleNamespace(
        fetchone=lambda *_args: pytest.fail("Active media must not fall back to history"),
    ))
    selected, subject = main._default_download_media()
    assert selected is media and subject == "current media"


def test_default_download_restores_real_durable_successful_start(monkeypatch, tmp_path):
    with MarianaDatabase(tmp_path / "history.db") as database:
        preferences = MediaPreferences(database)
        recommender = RecommendationEngine(database)
        monkeypatch.setattr(main, "DATABASE", database)
        monkeypatch.setattr(main, "PREFERENCES", preferences)
        monkeypatch.setattr(main, "RECOMMENDER", recommender)
        monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
            snapshot=lambda: PlaybackSnapshot(PlaybackState.IDLE),
        ))
        old = MediaRef(MediaSource.URL, "https://media.test/old", title="Earlier")
        latest = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", title="Latest")
        main._record_successful_start(old)
        main._record_successful_start(latest)
        recommender.record_event(old, "complete")
        restored, subject = main._default_download_media()
        assert restored.source == latest.source and restored.stable_id == latest.stable_id
        assert restored.original_uri == latest.original_uri and restored.title == "Latest"
        assert subject == "most recently played media"


@pytest.mark.parametrize("source,capabilities", [
    (MediaSource.LOCAL, MediaCapabilities()),
    (MediaSource.RADIO, MediaCapabilities(live=True, finite=False)),
    (MediaSource.URL, MediaCapabilities(finite=False, downloadable=True)),
    (MediaSource.URL, MediaCapabilities(downloadable=False)),
])
def test_default_download_refusal_does_not_select_another_history_item(monkeypatch, source, capabilities):
    media = MediaRef(source, "https://media.test/current", capabilities=capabilities)
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    ))
    monkeypatch.setattr(main, "DATABASE", SimpleNamespace(
        fetchone=lambda *_args: pytest.fail("An unsupported active item cannot select a different download"),
    ))
    with pytest.raises(main.DownloadError):
        main.download_shortcut_command([])


def test_download_confirmation_keeps_bound_identity_when_playback_changes(monkeypatch, tmp_path):
    selected = MediaRef(MediaSource.URL, "https://media.test/selected?token=private", title="Selected")
    replacement = MediaRef(MediaSource.URL, "https://media.test/replacement", title="Replacement")
    active = [selected]
    calls = []
    monkeypatch.setitem(main.SETTINGS["download"], "downloads folder", str(tmp_path))
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=active[0]),
    ))
    def confirm(message, **_kwargs):
        assert "Selected" in message and "private" not in message
        active[0] = replacement
        return True
    def download(url, destination, **kwargs):
        calls.append((url, destination, kwargs["output_target"]))
        return destination
    monkeypatch.setattr(main, "_confirm_action", confirm)
    monkeypatch.setattr(main, "download_media", download)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    result = main.download_shortcut_command([])
    assert result == tmp_path / "Selected.mp3"
    assert len(calls) == 1 and calls[0][0] == selected.original_uri
    assert calls[0][1] == calls[0][2].path
    assert active[0] is replacement


def test_live_fingerprint_refusal_never_requests_audio_or_tool_setup(monkeypatch):
    media = MediaRef(MediaSource.RADIO, "https://radio.test/live", capabilities=MediaCapabilities(live=True, finite=False))
    output = []
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: output.append(str(value)))
    monkeypatch.setattr(main, "_prepare_fingerprint_tool", lambda: pytest.fail("Live audio cannot install a fingerprint tool"))
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        fingerprint_pcm=lambda **_kwargs: pytest.fail("Whole-media fingerprint cannot capture a live source"),
    ))
    assert main._media_fingerprint(media, {}) is None
    assert len(output) == 1 and output[0].startswith("Whole-media fingerprints require finite audio.")


@pytest.mark.parametrize("legacy_type", [0, None])
def test_open_recovered_youtube_identity_never_treats_tuple_as_local_path(monkeypatch, legacy_type):
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", title="Recovered")
    legacy = (media.title, media.original_uri, media.original_uri)
    opened, messages = [], []
    monkeypatch.setattr(main, "currentsong", legacy)
    monkeypatch.setattr(main, "current_media_type", legacy_type)
    monkeypatch.setattr(main, "get_current_progress", lambda: 12)
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    ))
    monkeypatch.setattr(main.webbrowser, "open", opened.append)
    monkeypatch.setattr(main.os, "system", lambda *_args: pytest.fail("Online identity cannot launch the file explorer"))
    monkeypatch.setattr(main, "SAY", lambda **kwargs: messages.append(kwargs))
    main.process("open")
    assert main.currentsong is legacy
    if legacy_type == 0:
        assert opened == [media.original_uri + "&t=12s"]
        assert not messages
    else:
        assert not opened
        assert messages[-1]["display_message"] == "No audio playing, no file selected to open"


def test_open_valid_local_string_preserves_existing_windows_selection(monkeypatch, tmp_path):
    path = tmp_path / "track.mp3"
    path.write_bytes(b"audio")
    media = MediaRef(MediaSource.LOCAL, str(path))
    opened = []
    monkeypatch.setattr(main, "currentsong", str(path))
    monkeypatch.setattr(main, "current_media_type", None)
    monkeypatch.setattr(main.sys, "platform", "win32")
    monkeypatch.setattr(main.vas, "controller", SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media),
    ))
    monkeypatch.setattr(main.os, "system", opened.append)
    monkeypatch.setattr(main.webbrowser, "open", lambda *_args: pytest.fail("Local file is not a web page"))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    main.process("open")
    assert opened == [f"explorer /select, {str(path).replace('/', chr(92))}"]
