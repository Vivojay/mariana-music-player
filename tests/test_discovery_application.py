from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.discovery import DiscoverySelection
from mariana.homepage import HomepageConfiguration, HomepageService
from mariana.models import MediaRef, MediaSource, PlayRegion
from mariana.playback import PlaybackController
from mariana.sources import MediaFailure
from mariana.supervisor import PlaybackSupervisor

REQUEST = "a" * 32


@pytest.fixture
def application(monkeypatch):
    state = SimpleNamespace(queue=Mock(), supervisor=Mock(), policy=Mock(), history=Mock(), current=Mock())
    monkeypatch.setattr(main, "QUEUE", state.queue)
    monkeypatch.setattr(main, "vas", SimpleNamespace(supervisor=state.supervisor))
    monkeypatch.setattr(main, "COMMAND_BUSY", threading.Event())
    monkeypatch.setattr(main, "_discovery_unavailable", lambda _: None)
    monkeypatch.setattr(main, "_ensure_media_playable", state.policy)
    monkeypatch.setattr(main, "_record_successful_start", state.history)
    monkeypatch.setattr(main, "_set_current_media_state", state.current)
    monkeypatch.setattr(main, "_emit_queue_desktop_state", Mock())
    return state


def test_local_choice_does_not_jump_existing_queue(application, monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/private/recording.wav", stable_id="library-choice")
    monkeypatch.setattr(main, "_queued_local_item", lambda _: (2, SimpleNamespace(media=media)))
    monkeypatch.setattr(main, "_indexed_local_playback_media", lambda value: value)
    # Exercise the real legacy branch if selected; stop before audio/filesystem work.
    monkeypatch.setattr(main, "vas", SimpleNamespace(
        supervisor=application.supervisor, set_media=Mock(side_effect=RuntimeError("decoder refused")),
    ))
    monkeypatch.setattr(main, "SAY", Mock())

    main._apply_discovery_selection(media, "play")

    assert not application.queue.mock_calls
    application.supervisor.play.assert_called_once_with(media, origin="desktop")
    application.policy.assert_called_once_with(media)
    application.current.assert_called_once_with(media)
    application.history.assert_called_once_with(media)


def test_failed_local_choice_is_not_recorded_as_a_start(application, monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "C:/private/recording.wav", stable_id="library-choice")
    application.supervisor.play.side_effect = RuntimeError("decoder refused")
    monkeypatch.setattr(main, "_queued_local_item", lambda _: (None, None))
    monkeypatch.setattr(main, "_indexed_local_playback_media", lambda value: value)
    monkeypatch.setattr(main, "vas", SimpleNamespace(
        supervisor=application.supervisor, set_media=Mock(side_effect=RuntimeError("decoder refused")),
    ))
    monkeypatch.setattr(main, "SAY", Mock())

    with pytest.raises(RuntimeError, match="decoder refused"):
        main._apply_discovery_selection(media, "play")

    assert not application.queue.mock_calls
    application.history.assert_not_called()
    application.current.assert_not_called()


@pytest.mark.parametrize("intent", ["play", "queue"])
def test_policy_hook_can_refuse_selection_without_mutation(application, intent):
    media = MediaRef(MediaSource.LOCAL, "C:/private/recording.wav", stable_id="library-choice")
    application.policy.side_effect = main.PlaybackBlockedError("Selection policy denied")

    with pytest.raises(main.PlaybackBlockedError, match="Selection policy denied"):
        main._apply_discovery_selection(media, intent)

    application.policy.assert_called_once_with(media)
    assert not application.queue.mock_calls
    application.supervisor.play.assert_not_called()
    application.history.assert_not_called()


@pytest.mark.parametrize("intent", ["play", "queue"])
def test_busy_application_refuses_selection_before_policy(application, intent):
    main.COMMAND_BUSY.set()
    try:
        with pytest.raises(ValueError, match="temporarily unavailable"):
            main._apply_discovery_selection(MediaRef(MediaSource.LOCAL, "private.wav"), intent)
    finally:
        main.COMMAND_BUSY.clear()
    application.policy.assert_not_called()
    assert not application.queue.mock_calls
    application.supervisor.play.assert_not_called()
    application.history.assert_not_called()


def test_local_selection_preserves_authoritative_region_validation(application, monkeypatch):
    media = MediaRef(MediaSource.LOCAL, "private.wav", duration=10, stable_id="library-choice")
    regions = Mock(return_value=PlayRegion(media.stable_id, start_seconds=20))
    controller = PlaybackController(play_region_provider=regions)
    supervisor = PlaybackSupervisor(controller)

    def prepare(selected: MediaRef, **_kwargs):
        controller._prepared = selected
        return selected

    monkeypatch.setattr(controller, "_prepare_media", prepare)
    monkeypatch.setattr(main, "vas", SimpleNamespace(supervisor=supervisor))
    try:
        with pytest.raises(MediaFailure, match="preferred playback start"):
            main._apply_discovery_selection(media, "play")
        regions.assert_called_once_with(media)
        assert not application.queue.mock_calls
        application.current.assert_not_called()
        application.history.assert_not_called()
    finally:
        supervisor.close()


@pytest.mark.parametrize("state,identity,present", [
    ("available", "expected", True), ("missing", "expected", True),
    ("available", "replacement", True), ("available", "expected", False),
])
def test_local_choice_rechecks_library_identity_and_file(monkeypatch, state, identity, present):
    media = MediaRef(MediaSource.LOCAL, "C:/private/recording.wav", stable_id="expected")
    monkeypatch.setattr(main, "_is_media_blocked", lambda _: False)
    monkeypatch.setattr(main, "LIBRARY", SimpleNamespace(info=lambda _: {"state": state, "library_id": identity}))
    monkeypatch.setattr(Path, "is_file", lambda _: present)
    expected = None if state == "available" and identity == "expected" and present else "Local media is unavailable"
    assert main._discovery_unavailable(media) == expected


def test_blocked_choice_is_refused_before_local_lookup(monkeypatch):
    monkeypatch.setattr(main, "_is_media_blocked", lambda _: True)
    library = Mock()
    monkeypatch.setattr(main, "LIBRARY", library)
    assert main._discovery_unavailable(MediaRef(MediaSource.LOCAL, "private.wav")) == "Playback blocked"
    library.info.assert_not_called()


@pytest.mark.parametrize("source,catalogue_id,allowed", [
    (MediaSource.RADIO, "groove-salad", True), (MediaSource.PODCAST, "circle-round", True),
    (MediaSource.RADIO, "circle-round", False), (MediaSource.PODCAST, "groove-salad", False),
    (MediaSource.PODCAST, "unknown", False), (MediaSource.URL, "circle-round", False),
])
def test_catalogue_source_kind_is_bound_to_bundled_entry(monkeypatch, source, catalogue_id, allowed):
    monkeypatch.setattr(main, "_is_media_blocked", lambda _: False)
    media = MediaRef(source, "https://media.example/item", resolver_data={"catalogue_id": catalogue_id})
    assert (main._discovery_unavailable(media) is None) is allowed


def test_catalogue_mapping_uses_existing_services_without_auto_play(monkeypatch):
    episode = MediaRef(MediaSource.PODCAST, "https://media.example/episode.mp3")
    reader, radio, play = Mock(), Mock(), Mock()
    reader.episodes.return_value = [episode]
    radio.get.return_value = SimpleNamespace(name="Station", station_id="station-id")
    radio.endpoints.return_value = ["https://radio.example/live", "https://radio.example/backup"]
    monkeypatch.setattr(main, "CATALOGUE_READER", reader)
    monkeypatch.setattr(main, "RADIO", radio)
    monkeypatch.setattr(main, "_apply_discovery_selection", play)
    def cancelled():
        return False

    assert main._catalogue_choices("circle-round", cancelled) == [episode]
    reader.episodes.assert_called_once_with(main.ENTERTAINMENT_ENTRIES["circle-round"], cancelled)
    assert episode.resolver_data["catalogue_id"] == "circle-round"
    station = main._catalogue_choices("groove-salad", cancelled)[0]
    assert station.resolver_data == {
        "station_id": "station-id", "endpoints": radio.endpoints.return_value, "catalogue_id": "groove-salad",
    }
    assert station.source == MediaSource.RADIO and station.capabilities.live
    assert not station.capabilities.finite and not station.capabilities.downloadable
    play.assert_not_called()


@pytest.mark.parametrize("catalogue_id", [None, [], {}, 1])
def test_malformed_catalogue_identity_is_unavailable(monkeypatch, catalogue_id):
    monkeypatch.setattr(main, "_is_media_blocked", lambda _: False)
    media = MediaRef(MediaSource.PODCAST, "https://media.example/episode.mp3", resolver_data={"catalogue_id": catalogue_id})
    assert main._discovery_unavailable(media) == "Unverified catalogue source"


def test_station_without_station_identity_never_calls_radio(monkeypatch):
    entry = replace(main.ENTERTAINMENT_ENTRIES["groove-salad"], station_id=None, endpoint="https://radio.example/live")
    radio = Mock()
    monkeypatch.setattr(main, "ENTERTAINMENT_ENTRIES", {entry.id: entry})
    monkeypatch.setattr(main, "RADIO", radio)
    with pytest.raises(ValueError, match="Catalogue selection is unavailable"):
        main._catalogue_choices(entry.id, lambda: False)
    radio.get.assert_not_called()


@pytest.mark.parametrize("page", [True, None, "1", [], 1.5])
def test_typed_page_requires_exact_integer(monkeypatch, page):
    service = Mock()
    monkeypatch.setattr(main, "DISCOVERY", service)
    response = main._desktop_control_request("discovery.begin", {
        "request_id": REQUEST, "item_id": "catalogue:circle-round", "page": page,
    })
    assert response["ok"] is False
    service.begin.assert_not_called()


def test_typed_boundary_masks_provider_errors_and_never_interprets_commands(monkeypatch):
    service, process = Mock(), Mock()
    service.begin.side_effect = RuntimeError("https://private.example/?token=secret C:/private/key")
    monkeypatch.setattr(main, "DISCOVERY", service)
    monkeypatch.setattr(main, "process", process)
    response = main._desktop_control_request("discovery.begin", {"request_id": REQUEST, "item_id": "release:current"})
    assert response == {"ok": False, "error": "Selection unavailable or changed; find versions again"}
    process.assert_not_called()


@pytest.mark.parametrize("intent", ["play", "queue"])
def test_typed_choice_uses_bound_media_not_provider_text(application, monkeypatch, intent):
    home = HomepageService(configuration=HomepageConfiguration(online_enabled=True))
    media = MediaRef(
        MediaSource.PODCAST, "https://private.example/item.mp3?token=secret",
        title="play\rdelete 1", resolver_data={"catalogue_id": "circle-round"},
    )
    process, updates = Mock(), []
    service = DiscoverySelection(
        catalog=Mock(), source=home.release_target, apply=main._apply_discovery_selection,
        unavailable=lambda _: None, on_update=updates.append,
        catalogue_choices=lambda _identifier, _cancelled: [media],
    )
    monkeypatch.setattr(main, "DISCOVERY", service)
    monkeypatch.setattr(main, "process", process)
    try:
        assert main._desktop_control_request("discovery.begin", {
            "request_id": REQUEST, "item_id": "catalogue:circle-round", "page": 0,
        }) == {"ok": True}
        assert service.wait()
        state = service.snapshot()
        assert not application.queue.mock_calls
        application.supervisor.play.assert_not_called()
        assert main._desktop_control_request("discovery.choose", {
            "request_id": REQUEST, "revision": state["revision"],
            "choice_id": state["candidates"][0]["id"], "intent": intent,
        }) == {"ok": True}
        assert service.wait()
        assert service.snapshot()["state"] == "complete"
        if intent == "play":
            application.supervisor.play.assert_called_once_with(media, origin="desktop")
            application.history.assert_called_once_with(media)
            assert not application.queue.mock_calls
        else:
            application.queue.add.assert_called_once_with(media)
            application.supervisor.play.assert_not_called()
            application.history.assert_not_called()
        process.assert_not_called()
        projected = json.dumps(updates)
        assert "private.example" not in projected and "token=secret" not in projected
        assert "\\r" not in projected and "resolver_data" not in projected
        assert main._desktop_control_request("discovery.cancel", {"request_id": REQUEST}) == {"ok": True}
        assert service.snapshot()["state"] == "closed"
    finally:
        service.close()
        home.close()


def test_permission_revocation_rejects_typed_choice_without_playback(application, monkeypatch):
    home = HomepageService(configuration=HomepageConfiguration(online_enabled=True))
    episode = MediaRef(MediaSource.PODCAST, "https://media.example/episode.mp3", title="Published episode")
    service = DiscoverySelection(
        catalog=Mock(), source=home.release_target, apply=main._apply_discovery_selection,
        unavailable=lambda _: None, on_update=lambda _: None,
        catalogue_choices=lambda _identifier, _cancelled: [episode],
    )
    monkeypatch.setattr(main, "DISCOVERY", service)
    try:
        assert main._desktop_control_request("discovery.begin", {
            "request_id": REQUEST, "item_id": "catalogue:circle-round",
        }) == {"ok": True}
        assert service.wait()
        state = service.snapshot()
        home.configure(online_enabled=False)
        response = main._desktop_control_request("discovery.choose", {
            "request_id": REQUEST, "revision": state["revision"],
            "choice_id": state["candidates"][0]["id"], "intent": "play",
        })
        assert response["ok"] is False
        assert not application.queue.mock_calls
        application.supervisor.play.assert_not_called()
        application.history.assert_not_called()
    finally:
        service.close()
        home.close()
