"""Capture consent, live composition, and trusted control-origin boundaries."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana import playback
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, PlaybackState
from mariana.playback_events import LocalPlaybackEvents
from mariana.sources import ResolverRegistry
from tests.test_playback_state_machine import Resolvers, Session, Stream


@pytest.mark.parametrize("previous", [None, False, "invalid", {"enabled": False, "custom": "retained"}])
@pytest.mark.parametrize("present", [False, True])
def test_failed_settings_write_restores_exact_section_without_live_consent(monkeypatch, tmp_path, previous, present):
    settings = {"unrelated": {"retained": True}}
    if present:
        settings["playback events"] = previous
    before = deepcopy(settings)
    service = SimpleNamespace(configure=Mock(), status=Mock())
    save = Mock(side_effect=OSError("private settings path"))
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "PLAYBACK_EVENTS", service)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    monkeypatch.setattr(main, "save_user_settings", save)

    with pytest.raises(OSError):
        main._persist_playback_event_configuration(enabled=True, retention_days=30, forward_to_log=True)

    assert settings == before
    if present:
        assert settings["playback events"] is previous
    service.configure.assert_not_called()
    service.status.assert_not_called()
    save.assert_called_once()


@pytest.mark.parametrize("field,value", [
    ("enabled", 1), ("enabled", "yes"), ("forward_to_log", 0),
    ("retention_days", True), ("retention_days", 0), ("retention_days", 3651),
    ("retention_days", 1.5), ("retention_days", float("inf")),
])
def test_invalid_capture_settings_never_write_or_reconfigure(monkeypatch, field, value):
    settings = {"playback events": {"enabled": False}}
    before = deepcopy(settings)
    service = SimpleNamespace(configure=Mock(), status=Mock())
    save = Mock()
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "PLAYBACK_EVENTS", service)
    monkeypatch.setattr(main, "save_user_settings", save)
    with pytest.raises(ValueError):
        main._persist_playback_event_configuration(**{field: value})
    assert settings == before
    save.assert_not_called()
    service.configure.assert_not_called()


def test_capture_settings_commit_before_live_change_and_retain_other_keys(monkeypatch, tmp_path):
    settings = {"playback events": {"custom": "retained", "enabled": False}, "loglevel": 0}
    order = []
    service = SimpleNamespace(
        configure=lambda **values: order.append(("live", values)), status=lambda: {"enabled": True},
    )
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "PLAYBACK_EVENTS", service)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    monkeypatch.setattr(main, "save_user_settings", lambda value, path: order.append(("save", deepcopy(value))))
    assert main._persist_playback_event_configuration(enabled=True) == {"enabled": True}
    assert [item[0] for item in order] == ["save", "live"]
    assert settings == {"playback events": {"custom": "retained", "enabled": True}, "loglevel": 0}


def test_startup_capture_sink_is_the_authoritative_controller_only():
    assert main.vas.controller._playback_event_sink == main.PLAYBACK_EVENTS.capture


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_refresh_reuses_capture_worker_and_rebinds_replacement_controller(monkeypatch, enabled):
    settings = deepcopy(main.SETTINGS)
    settings.update({"playback events": {"enabled": enabled, "retention days": 7, "forward to log": False}, "loglevel": 0})
    service = SimpleNamespace(capture=Mock(), configure=Mock())
    controllers = []

    def configure(**kwargs):
        controllers.append(SimpleNamespace(sink=kwargs["playback_event_sink"]))

    monkeypatch.setattr(main, "SETTINGS", {})
    monkeypatch.setattr(main, "load_user_settings", lambda: settings)
    monkeypatch.setattr(main, "PLAYBACK_EVENTS", service)
    monkeypatch.setattr(main, "LocalPlaybackEvents", Mock(side_effect=AssertionError("must reuse worker")))
    monkeypatch.setattr(main, "vas", SimpleNamespace(
        configure=configure,
        controller=SimpleNamespace(add_active_media_sink=Mock(return_value=lambda: None)),
    ))
    monkeypatch.setattr(main, "YT_query", SimpleNamespace(configure=Mock()))
    monkeypatch.setattr(main, "IDENTITY", SimpleNamespace(fpcalc_bin=None))
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(ffmpeg_bin=None, fpcalc_bin=None, rsgain=None))
    monkeypatch.setattr(main, "check_runtime", lambda *_args: SimpleNamespace(errors=[]))
    monkeypatch.setattr(main, "RSGainAnalyzer", Mock())
    for name in ("EQUALIZER", "ARTWORK", "HOMEPAGE"):
        monkeypatch.setattr(main, name, None)
    for name in ("MEDIA_TOOLS", "RUNTIME_REPORT", "FATAL_ERROR_INFO", "AUTOPLAY_ENABLED", "visible", "loglevel", "DEFAULT_EDITOR"):
        monkeypatch.setattr(main, name, getattr(main, name))
    main.refresh_runtime_configuration()
    main.refresh_runtime_configuration()
    assert len(controllers) == 2
    assert all(controller.sink is service.capture for controller in controllers)
    service.configure.assert_called_with(enabled=enabled, retention_days=7, forward_to_log=False)
    assert service.configure.call_count == 2
    service.capture.assert_not_called()


@pytest.fixture
def capture_scene(monkeypatch, tmp_path):
    monkeypatch.setattr(playback, "DecoderSession", Session)
    monkeypatch.setattr(Session, "wait_result", True)
    monkeypatch.setattr(Session, "error", None)
    monkeypatch.setattr(Session, "created", [])
    monkeypatch.setattr(Stream, "instances", [])
    with MarianaDatabase(tmp_path / "capture.db") as database:
        logs = []
        service = LocalPlaybackEvents(database, enabled=True, log_sink=logs.append)
        resolvers = ResolverRegistry()
        monkeypatch.setattr(resolvers, "resolve", Resolvers().resolve)
        controller = playback.PlaybackController(output_factory=Stream, resolvers=resolvers, playback_event_sink=service.capture)
        media = MediaRef(MediaSource.LOCAL, str(tmp_path / "private title.flac"), stable_id="opaque-media", duration=60)
        controller.play(media, probe=False, origin="automatic")
        facade = SimpleNamespace(
            controller=controller,
            player=SimpleNamespace(audio_set_volume=Mock()),
            media_player=lambda *, action, origin: (
                controller.pause(origin=origin) if controller.snapshot().state == PlaybackState.PLAYING
                else controller.resume(origin=origin)
            ),
        )
        monkeypatch.setattr(main, "vas", facade)
        monkeypatch.setattr(main, "PLAYBACK_EVENTS", service)
        monkeypatch.setattr(main, "_is_media_blocked", lambda _media: False)
        monkeypatch.setattr(main, "_playback_status_projection", lambda: SimpleNamespace(to_dict=dict))
        monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=Mock()))
        monkeypatch.setattr(main, "currentsong", media.original_uri)
        monkeypatch.setattr(main, "isplaying", True)
        monkeypatch.setattr(main, "cached_volume", 0.5)
        monkeypatch.setattr(main, "visible", False)
        monkeypatch.setattr(main, "voltransition", Mock())
        monkeypatch.setattr(main, "IPrint", Mock())
        try:
            yield controller, service, database, logs
        finally:
            controller.close()
            assert service.close()


@pytest.mark.parametrize("origin", [None, "desktop", "mini-player"])
def test_typed_user_actions_capture_once_with_host_origin_and_exclude_automatic_start(capture_scene, origin):
    _controller, service, database, logs = capture_scene
    payload: dict[str, object] = {"media_id": "opaque-media"}
    if origin is not None:
        payload["origin"] = origin
    for action in ("pause", "play", "seek"):
        request = {**payload, **({"target_seconds": 12} if action == "seek" else {})}
        assert main._desktop_control_request(f"playback.{action}", request) == {"ok": True}
    assert service.flush()
    rows = database.fetchall("SELECT action,origin FROM playback_events ORDER BY rowid")
    assert [(row["action"], row["origin"]) for row in rows] == [
        ("play", "automatic"), ("pause", origin or "desktop"),
        ("play", origin or "desktop"), ("seek", origin or "desktop"),
    ]
    assert sum(row["total"] for row in service.aggregate("opaque-media")) == 3
    assert logs == []


@pytest.mark.parametrize("action", ["play", "pause", "seek"])
@pytest.mark.parametrize("origin", ["system", "automatic", "recovery", ["desktop"], None, 1])
def test_typed_control_rejects_untrusted_origins_before_any_action(monkeypatch, action, origin):
    controller = SimpleNamespace(snapshot=Mock(side_effect=AssertionError("must reject before playback")))
    monkeypatch.setattr(main, "vas", SimpleNamespace(controller=controller))
    payload: dict[str, object] = {"media_id": "opaque-media", "target_seconds": 12, "origin": origin}
    assert main._desktop_control_request(f"playback.{action}", payload) == {
        "ok": False, "error": "Playback action origin is invalid",
    }
    controller.snapshot.assert_not_called()


def test_cli_seek_origin_is_supported_without_changing_play_pause_contract(capture_scene):
    _controller, service, database, _logs = capture_scene
    payload: dict[str, object] = {"media_id": "opaque-media", "origin": "cli", "target_seconds": 12}
    assert main._desktop_control_request("playback.seek", payload) == {"ok": True}
    assert main._desktop_control_request("playback.pause", payload) == {"ok": False, "error": "Playback action origin is invalid"}
    assert service.flush()
    row = database.fetchone("SELECT origin FROM playback_events WHERE action='seek'")
    assert row is not None and row["origin"] == "cli"


def test_failed_typed_seek_and_blocked_controls_do_not_capture(capture_scene, monkeypatch):
    controller, service, _database, _logs = capture_scene
    payload: dict[str, object] = {"media_id": "opaque-media", "origin": "desktop", "target_seconds": 12}
    monkeypatch.setattr(controller, "seek", Mock(side_effect=RuntimeError("private path")))
    assert main._desktop_control_request("playback.seek", payload) == {"ok": False, "error": "Could not seek playback"}
    monkeypatch.setattr(main, "_is_media_blocked", lambda _media: True)
    assert main._desktop_control_request("playback.pause", payload)["ok"] is False
    assert service.aggregate("opaque-media") == []


@pytest.mark.parametrize("width", ["0", "-1", "nan", "inf"])
def test_current_hotspots_reject_invalid_bins_without_exposing_media(capture_scene, width):
    with pytest.raises(ValueError, match="positive finite"):
        main.hotspots_command(["current", width])
    main.IPrint.assert_not_called()


@pytest.mark.parametrize("scaling", ["linear", "log1p"])
def test_unrepresentable_bin_index_is_a_validation_error_without_changing_history(capture_scene, scaling):
    _controller, service, database, _logs = capture_scene
    assert main._desktop_control_request("playback.seek", {
        "media_id": "opaque-media", "origin": "desktop", "target_seconds": 12,
    }) == {"ok": True}
    assert service.flush()
    before = [dict(row) for row in database.fetchall("SELECT * FROM playback_events ORDER BY rowid")]
    with pytest.raises(ValueError, match=r"bin width.*stored positions"):
        main.hotspots_command(["current", "1e-320", scaling])
    assert [dict(row) for row in database.fetchall("SELECT * FROM playback_events ORDER BY rowid")] == before
    assert service.aggregate("opaque-media", bin_seconds=5, scaling=scaling)[0]["seek_destinations"] == 1
    main.IPrint.assert_not_called()


def test_hotspot_command_routing_catches_validation_errors_and_keeps_help_explicit(monkeypatch):
    printed = Mock()
    handler = Mock(side_effect=ValueError("Hotspot bin width is too small for stored positions"))
    monkeypatch.setattr(main, "hotspots_command", handler)
    monkeypatch.setattr(main, "IPrint", printed)
    main.process("hotspots current 1e-320")
    handler.assert_called_once_with(["current", "1e-320"])
    printed.assert_called_with("Hotspot bin width is too small for stored positions", visible=main.visible)
    help_rows = main.help_command(["hotspots"])
    assert isinstance(help_rows, tuple) and help_rows[0][0] == "Settings"
    from mariana.command_catalog import COMMAND_CATALOG, CommandRisk
    clear = next(spec for spec in COMMAND_CATALOG if spec.canonical == "hotspots clear")
    assert clear.risk is CommandRisk.DESTRUCTIVE
    assert clear.forms[0].flags == ("--yes",)
