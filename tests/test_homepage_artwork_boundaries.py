"""Application-level identity, consent, and lifecycle boundaries for Home/artwork."""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_homepage_artwork_cli import ArtworkStub, HomepageStub, _homepage_projection, _ready_artwork

import main
from mariana.artwork import ArtworkProjection, ArtworkState
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.presence import PresencePrivacyMode


@pytest.fixture(autouse=True)
def preserve_observer_revision(monkeypatch):
    monkeypatch.setattr(main, "_ARTWORK_OBSERVER_REVISION", main._ARTWORK_OBSERVER_REVISION)


@pytest.fixture
def artwork_scene(monkeypatch, tmp_path):
    projection, image = _ready_artwork(tmp_path / "cover.png")
    artwork = ArtworkStub(projection, image=image)
    active = {"media": MediaRef(MediaSource.LOCAL, str(tmp_path / "track.mp3"), stable_id="media-1")}
    opened = []
    monkeypatch.setattr(main, "ARTWORK", artwork)
    monkeypatch.setattr(main.vas.controller, "snapshot", lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=active["media"]))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(enabled=False, emit=Mock()))
    monkeypatch.setattr(main, "open_path", opened.append)
    monkeypatch.setattr(main, "IPrint", Mock())
    return SimpleNamespace(artwork=artwork, active=active, opened=opened, projection=projection)


def test_terminal_show_rejects_artwork_not_bound_to_active_media(artwork_scene):
    scene = artwork_scene
    scene.artwork.value = replace(scene.projection, media_id="stale-media")
    with pytest.raises(ValueError, match="Current media changed"):
        main.thumb_command(["show"])
    assert scene.opened == []


def test_explicit_terminal_fetch_is_bound_to_the_snapshotted_media(artwork_scene):
    scene = artwork_scene
    fetch = Mock(return_value=1)
    scene.artwork.fetch_current = fetch
    main.thumb_command(["show", "--fetch"])
    fetch.assert_called_once_with("media-1")
    assert len(scene.opened) == 1


def test_terminal_show_without_fetch_never_requests_online_artwork(artwork_scene):
    scene = artwork_scene
    fetch = Mock(side_effect=AssertionError("unexpected network consent"))
    scene.artwork.fetch_current = fetch
    main.thumb_command(["show"])
    fetch.assert_not_called()
    assert len(scene.opened) == 1


@pytest.mark.parametrize("projection_changes", [False, True])
def test_terminal_wait_cannot_open_artwork_after_active_media_changes(artwork_scene, projection_changes):
    scene = artwork_scene
    scene.artwork.value = replace(scene.projection, state=ArtworkState.LOADING)

    def wait(**_kwargs):
        scene.active["media"] = MediaRef(MediaSource.URL, "https://media.test/other", stable_id="media-2")
        scene.artwork.value = replace(
            scene.projection, media_id="media-2" if projection_changes else "media-1",
        )
        return scene.artwork.value

    scene.artwork.wait_for_idle = wait
    with pytest.raises(ValueError, match="Current media changed"):
        main.thumb_command(["show"])
    assert scene.opened == []


@pytest.mark.parametrize("setting", [[], {}])
def test_typed_homepage_setting_rejects_unhashable_values(setting):
    assert main._desktop_control_request("homepage.configure", {"setting": setting, "enabled": True}) == {
        "ok": False, "error": "Homepage setting is invalid",
    }


@pytest.mark.parametrize("same_controller", [False, True])
def test_replaced_observer_cannot_reactivate_artwork_from_late_callback(monkeypatch, same_controller):
    callbacks, removals, activations = [], [], []
    controller = SimpleNamespace(add_active_media_sink=lambda callback: callbacks.append(callback) or (lambda: removals.append("remove")))
    monkeypatch.setattr(main, "_ARTWORK_SINK_REMOVE", None)
    monkeypatch.setattr(main.vas, "controller", controller)
    monkeypatch.setattr(main, "_artwork_active_media_changed", lambda media, _resolved: activations.append(media))
    main._connect_artwork_controller()
    if not same_controller:
        monkeypatch.setattr(main.vas, "controller", SimpleNamespace(add_active_media_sink=controller.add_active_media_sink))
    main._connect_artwork_controller()
    media = MediaRef(MediaSource.URL, "https://media.test/current")
    callbacks[0](media, None)
    assert activations == []
    callbacks[1](media, None)
    assert activations == [media]
    assert removals == ["remove"]


def test_shutdown_detaches_observer_and_rejects_late_activation(monkeypatch):
    callbacks, events = [], []
    controller = SimpleNamespace(
        add_active_media_sink=lambda callback: callbacks.append(callback) or (lambda: events.append("detached")),
    )
    monkeypatch.setattr(main.vas, "controller", controller)
    monkeypatch.setattr(main, "_ARTWORK_SINK_REMOVE", None)
    monkeypatch.setattr(main, "ARTWORK", SimpleNamespace(close=lambda: events.append("closed")))
    monkeypatch.setattr(main, "_artwork_active_media_changed", lambda *_args: events.append("activated"))
    main._connect_artwork_controller()
    main._close_artwork_controller()
    callbacks[0](None, None)
    assert events == ["detached", "closed"]
    assert main._ARTWORK_SINK_REMOVE is None


def test_artwork_close_still_runs_when_observer_removal_fails(monkeypatch):
    closed = Mock()

    def fail():
        raise RuntimeError("detachment failed")

    monkeypatch.setattr(main, "_ARTWORK_SINK_REMOVE", fail)
    monkeypatch.setattr(main, "ARTWORK", SimpleNamespace(close=closed))
    with pytest.raises(RuntimeError, match="detachment failed"):
        main._close_artwork_controller()
    closed.assert_called_once_with()
    assert main._ARTWORK_SINK_REMOVE is None


def test_runtime_reconfiguration_rebinds_artwork_and_applies_independent_settings(monkeypatch):
    settings = deepcopy(main.SETTINGS)
    settings.update({
        "homepage": {"show on startup": False, "online content": True},
        "artwork": {"automatic online retrieval": True},
    })
    homepage = HomepageStub(_homepage_projection())
    artwork = ArtworkStub(ArtworkProjection(1, None, ArtworkState.IDLE, False))
    order = []
    replacement = SimpleNamespace(
        equalizer=SimpleNamespace(prepare=lambda value: value, submit=lambda _value: order.append("equalizer")),
        add_active_media_sink=lambda _callback: order.append("attached") or (lambda: None),
    )
    monkeypatch.setattr(main, "SETTINGS", main.SETTINGS)
    monkeypatch.setattr(main, "load_user_settings", lambda: settings)
    monkeypatch.setattr(main, "HOMEPAGE", homepage)
    monkeypatch.setattr(main, "ARTWORK", artwork)
    monkeypatch.setattr(main, "_ARTWORK_SINK_REMOVE", lambda: order.append("detached"))
    monkeypatch.setattr(main, "EQUALIZER", SimpleNamespace(settings=object()))
    monkeypatch.setattr(main.vas, "controller", main.vas.controller)
    monkeypatch.setattr(main.vas, "configure", lambda **_kwargs: setattr(main.vas, "controller", replacement))
    monkeypatch.setattr(main.YT_query, "configure", lambda **_kwargs: None)
    monkeypatch.setattr(main, "IDENTITY", SimpleNamespace(fpcalc_bin=None))
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(ffmpeg_bin=None, fpcalc_bin=None, rsgain=None))
    monkeypatch.setattr(main, "check_runtime", lambda *_args: SimpleNamespace(errors=[]))
    for name in ("MEDIA_TOOLS", "RUNTIME_REPORT", "FATAL_ERROR_INFO", "AUTOPLAY_ENABLED", "visible", "loglevel", "DEFAULT_EDITOR"):
        monkeypatch.setattr(main, name, getattr(main, name))

    main.refresh_runtime_configuration()
    assert order == ["equalizer", "detached", "attached"]
    assert artwork.clear_calls == 1 and artwork.enabled_calls == [True]
    assert homepage.configure_calls == [(False, True)]
    assert homepage.refresh_calls == 0


@pytest.mark.parametrize("startup", [False, True])
@pytest.mark.parametrize("online", [False, True])
@pytest.mark.parametrize("desktop_enabled", [False, True])
@pytest.mark.parametrize("visible", [False, True])
def test_startup_visibility_never_implies_network_consent(monkeypatch, startup, online, desktop_enabled, visible):
    homepage = HomepageStub(_homepage_projection(startup=startup, online=online))
    projection = ArtworkProjection(1, None, ArtworkState.IDLE, False)
    emitted, printed = [], []
    desktop = SimpleNamespace(
        enabled=desktop_enabled,
        start_request_listener=lambda _callback: None,
        start_playback_monitor=lambda _callback: None,
        start_safety_monitor=lambda _callback: None,
        emit=lambda event, payload=None: emitted.append((event, payload)),
    )
    monkeypatch.setattr(main, "HOMEPAGE", homepage)
    monkeypatch.setattr(main, "ARTWORK", ArtworkStub(projection))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", desktop)
    monkeypatch.setattr(main, "PRESENCE", SimpleNamespace(mode=PresencePrivacyMode.OFF))
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(main, "visible", visible)
    monkeypatch.setattr(main, "initialize_audio_output", lambda: None)
    monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
    monkeypatch.setattr(main, "DOWNLOADS", SimpleNamespace(status=list))
    monkeypatch.setattr(main, "LIBRARY_SERVICE", SimpleNamespace(start=lambda **_kwargs: None))
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "mainprompt", lambda: None)
    monkeypatch.setattr(main, "showbanner", lambda: None)
    monkeypatch.setattr(main, "_print_homepage", printed.append)
    monkeypatch.setattr(main, "USER_DATA", {"default_user_data": {"stats": {"log_ins": 0}}})

    main.run()
    assert homepage.refresh_calls == int(online)
    assert len(printed) == int(startup and visible and not desktop_enabled)
    assert ("homepage", homepage.snapshot()) in emitted
    assert ("artwork", projection.to_dict()) in emitted
