import copy
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mariana.models import MediaCapabilities, MediaRef, MediaSource, canonical_uri
from mariana.recipe_playback import ExistingPlaybackRecipeHost
from mariana.recipe_sources import PreparedRecipeSource, prepare_online_recipe_source
from mariana.session_recipes import ReplayBlocked, canonical_media_reference, initial_state
from mariana.sources import ResolvedMedia


@pytest.fixture
def online():
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", title="Saved title", duration=60)
    expected = canonical_media_reference(media)
    resolutions = []

    def resolve(selected, *, force):
        assert force
        result = ResolvedMedia(
            selected, "https://cdn.example/media?token=SECRET", canonical_uri(selected.source, selected.original_uri),
            MediaCapabilities(), headers={"Authorization": "SECRET"}, expires_at=time.time() + 120,
            metadata={"title": "Fresh title", "duration": 60,
                      "provider_metadata": {"provider_media_id": "abcdefghijk"}},
        )
        resolutions.append(result)
        return result

    resolvers = Mock()
    resolvers.resolve.side_effect = resolve
    return media, expected, resolvers, resolutions


def test_fresh_provider_facts_and_exact_transport_without_mutating_catalog(online):
    media, expected, resolvers, resolutions = online
    original = copy.deepcopy(media.to_dict())
    # Stale catalog duration is not the freshly observed provider duration.
    media.duration = 90
    prepared, actual = prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: False)
    assert isinstance(prepared, PreparedRecipeSource)
    assert prepared.resolved is resolutions[0]
    assert prepared.resolved.media is prepared.media and prepared.media is not media
    assert prepared.media.title == "Fresh title" and prepared.media.duration == 60
    assert media.title == original["title"] and media.duration == 90
    assert actual == expected
    assert "SECRET" not in json.dumps(actual)
    assert "SECRET" not in json.dumps(prepared.media.to_dict())
    assert prepared.resolved.headers["Authorization"] == "SECRET"


@pytest.mark.parametrize("change,code", [
    (lambda result: result.metadata.update(duration=90), "changed_source"),
    (lambda result: result.metadata.update(duration=None), "unverified_online_source"),
    (lambda result: result.metadata.update(duration=float("nan")), "unverified_online_source"),
    (lambda result: result.metadata.update(duration=0), "unverified_online_source"),
    (lambda result: result.metadata.update(provider_metadata={"provider_media_id": "different00"}), "changed_source"),
    (lambda result: result.metadata.pop("provider_metadata"), "changed_source"),
    (lambda result: setattr(result, "canonical_uri", "https://www.youtube.com/watch?v=different00"), "changed_source"),
    (lambda result: setattr(result, "media", copy.deepcopy(result.media)), "changed_source"),
    (lambda result: setattr(result, "expires_at", time.time() - 1), "expired_source"),
    (lambda result: setattr(result.capabilities, "live", True), "live_source_requires_archive"),
    (lambda result: setattr(result.capabilities, "finite", False), "live_source_requires_archive"),
    (lambda result: setattr(result.capabilities, "seekable", False), "live_source_requires_archive"),
])
def test_provider_mismatch_missing_facts_and_unplayable_media_are_refused(online, change, code):
    media, expected, resolvers, _ = online
    original = resolvers.resolve.side_effect

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        change(result)
        return result

    resolvers.resolve.side_effect = changed
    with pytest.raises(ReplayBlocked) as error:
        prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: False)
    assert error.value.code == code
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("source", [MediaSource.URL, MediaSource.PODCAST, MediaSource.RADIO])
def test_catalog_only_sources_do_not_become_portable_online_references(online, source):
    _, _, resolvers, _ = online
    media = MediaRef(source, "https://cdn.example/media?token=SECRET", duration=60)
    with pytest.raises(ReplayBlocked, match="preflight unavailable"):
        prepare_online_recipe_source(media, canonical_media_reference(media), resolvers, cancelled=lambda: False)
    resolvers.resolve.assert_not_called()


def test_missing_saved_duration_refuses_preflight(online):
    media, expected, resolvers, _ = online
    expected["duration_ms"] = None
    with pytest.raises(ReplayBlocked, match="unverified online source"):
        prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: False)
    resolvers.resolve.assert_not_called()


@pytest.mark.parametrize("cancel_before", [True, False])
def test_cancelled_resolution_never_returns_playable_source(online, cancel_before):
    media, expected, resolvers, _ = online
    checks = iter([cancel_before, True])
    with pytest.raises(ReplayBlocked, match="replay cancelled"):
        prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: next(checks))
    assert resolvers.resolve.call_count == (0 if cancel_before else 1)


def test_wrong_catalog_identity_is_rejected_before_network(online):
    media, expected, resolvers, _ = online
    media.original_uri = "https://www.youtube.com/watch?v=different00"
    with pytest.raises(ReplayBlocked, match="changed source"):
        prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: False)
    resolvers.resolve.assert_not_called()


def test_signed_input_is_reduced_to_public_provider_identity(online):
    media, expected, resolvers, _ = online
    media.original_uri += "&token=CATALOG_SECRET"
    prepared, _ = prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: False)
    assert prepared.media.original_uri == "https://www.youtube.com/watch?v=abcdefghijk"
    assert "CATALOG_SECRET" not in resolvers.resolve.call_args.args[0].original_uri


def test_host_reuses_verified_transport_for_play_and_seek_but_not_queue_persistence(online):
    media, expected, resolvers, _ = online
    prepared, _ = prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: False)
    playback, queues = Mock(), []
    host = ExistingPlaybackRecipeHost(
        lambda: playback, resolve=Mock(), restore_queue=lambda state, items: queues.append(items),
        configure_queue=Mock(), set_replay_active=Mock(),
    )
    state = initial_state()
    state.update(media="item", queue=["item"], current_index=0, position_ms=1234, playing=False)
    host.restore(state, {"item": prepared})
    assert queues == [{"item": prepared.media}]
    playback.play.assert_called_once_with(
        prepared.media, start_at=1.234, probe=False, origin="recovery", start_paused=True, resolved=prepared.resolved,
    )
    host.apply({"kind": "seek", "data": {"position_ms": 4321}}, state, {"item": prepared})
    playback.seek.assert_called_once_with(4.321, origin="recovery", resolved=prepared.resolved)
    assert resolvers.resolve.call_count == 1


def test_service_online_preflight_uses_current_controller_and_cancellation(online, tmp_path):
    from mariana.session_service import SessionRecipeService

    media, expected, resolvers, _ = online
    controller = SimpleNamespace(resolvers=resolvers)
    service = SessionRecipeService(
        tmp_path / "recipes", playback=lambda: controller, lookup_media=lambda _: media,
        restore_queue=Mock(), configure_queue=Mock(), set_replay_active=Mock(),
    )
    try:
        result = service._resolve(expected)
        assert result.reference == expected and isinstance(result.media, PreparedRecipeSource)
        service._operation_deadline = time.monotonic() - 1
        with pytest.raises(ReplayBlocked, match="source preflight timeout"):
            service._resolve(expected)
        assert resolvers.resolve.call_count == 1
    finally:
        service.close()


def test_worker_replay_and_recipe_seek_reresolve_without_serializing_transport(online, tmp_path):
    from mariana.session_service import SessionRecipeService

    media, _, resolvers, resolutions = online
    clock = [0.0]
    playback = Mock()
    playback.resolvers = resolvers
    playback.snapshot.return_value = SimpleNamespace(state="paused")
    queues = []
    service = SessionRecipeService(
        tmp_path / "recipes", playback=lambda: playback, lookup_media=lambda _: media,
        restore_queue=lambda state, items: queues.append(items), configure_queue=Mock(),
        set_replay_active=Mock(), clock=lambda: clock[0],
    )

    def wait_for(predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.005)
        assert predicate(), service.status()

    try:
        service.start("online", initial_media_id=media.stable_id, queue_ids=[media.stable_id], current_index=0)
        wait_for(lambda: service.status()["state"] == "recording")
        clock[0] = 2
        assert service.stop()
        service.replay("online")
        wait_for(lambda: playback.play.call_count == 1)
        assert playback.play.call_args.kwargs["resolved"] is resolutions[0]
        service.seek_replay(1000)
        wait_for(lambda: playback.play.call_count == 2)
        assert playback.play.call_args.kwargs["resolved"] is resolutions[1]
        assert resolutions[0] is not resolutions[1]
        assert resolvers.resolve.call_count == 2
        assert all(isinstance(value, MediaRef) for items in queues for value in items.values())
        assert "SECRET" not in (service.directory / "online.jsonl").read_text()
        assert "cdn.example" not in (service.directory / "online.jsonl").read_text()
    finally:
        service.close()


def test_worker_cancellation_during_provider_io_cannot_start_late_audio(online, tmp_path):
    from mariana.session_service import SessionRecipeService

    media, _, resolvers, _ = online
    entered, release = threading.Event(), threading.Event()
    resolve = resolvers.resolve.side_effect

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return resolve(*args, **kwargs)

    resolvers.resolve.side_effect = blocked
    playback = Mock()
    playback.resolvers = resolvers
    playback.snapshot.return_value = SimpleNamespace(state="paused")
    service = SessionRecipeService(
        tmp_path / "recipes", playback=lambda: playback, lookup_media=lambda _: media,
        restore_queue=Mock(), configure_queue=Mock(), set_replay_active=Mock(),
    )
    try:
        service.start("cancel", initial_media_id=media.stable_id)
        assert service.stop()
        service.replay("cancel")
        assert entered.wait(1)
        assert not service.stop_replay(timeout=.01)
        release.set()
        deadline = time.monotonic() + 2
        while service.status()["replay_active"] and time.monotonic() < deadline:
            time.sleep(.005)
        assert not service.status()["replay_active"]
        playback.play.assert_not_called()
    finally:
        release.set()
        service.close()


def test_decoder_failure_stops_recipe_before_subsequent_actions(online):
    from mariana.session_recipes import RecipeReplayEngine, ResolvedRecipeMedia, new_recipe

    media, expected, resolvers, _ = online
    prepared, actual = prepare_online_recipe_source(media, expected, resolvers, cancelled=lambda: False)
    playback = Mock()
    playback.snapshot.return_value = SimpleNamespace(state="failed")
    host = ExistingPlaybackRecipeHost(
        lambda: playback, resolve=lambda _: ResolvedRecipeMedia(prepared, actual),
        restore_queue=Mock(), configure_queue=Mock(), set_replay_active=Mock(),
    )
    recipe = new_recipe(media={"item": expected})
    replay = RecipeReplayEngine(recipe, host)
    replay.start()
    with pytest.raises(ReplayBlocked, match="playback failed"):
        replay.tick()
    assert replay.status == "paused" and replay.error_code == "playback_failed"
    playback.play.assert_not_called()
    assert playback.stop.call_count == 2
