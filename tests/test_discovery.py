import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mariana.albums import AlbumCatalog, AlbumError, PlaybackCandidate
from mariana.discovery import STALE, DiscoverySelection
from mariana.models import AlbumRef, AlbumTrack, MediaRef, MediaSource

RELEASE = "12345678-1234-4234-8234-123456789012"
REQUEST = "a" * 32


def album():
    return AlbumRef(
        album_id="edition", title="A particular edition", album_artist="Artist",
        release_mbid=RELEASE,
        tracks=[AlbumTrack(title="Recording", artist="Artist", position=1, duration=180)],
    )


@pytest.fixture
def selection():
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", title="Actual video title")
    catalog = Mock(spec=AlbumCatalog)
    catalog.inspect_release.return_value = album()
    catalog.playback_candidates.return_value = [PlaybackCandidate(media, "provider-result")]
    source = Mock(return_value=(RELEASE, "card-version"))
    apply = Mock()
    unavailable = Mock(return_value=None)
    updates = []
    service = DiscoverySelection(
        catalog=catalog, source=source, apply=apply, unavailable=unavailable, on_update=updates.append,
    )
    yield service, catalog, source, apply, unavailable, updates
    service.close()


def find_choices(service):
    service.begin("release:one", REQUEST)
    assert service.wait()
    tracks = service.snapshot()
    service.choose(REQUEST, tracks["revision"], tracks["tracks"][0]["id"], "versions")
    assert service.wait()
    return service.snapshot()


@pytest.mark.parametrize("intent", ["play", "queue"])
def test_inspection_never_plays_and_explicit_choice_is_consumed_once(selection, intent):
    service, catalog, _, apply, _, _ = selection
    choices = find_choices(service)
    catalog.inspect_release.assert_called_once_with(RELEASE)
    assert choices["state"] == "choices"
    assert choices["candidates"][0]["title"] == "Actual video title"
    assert choices["candidates"][0]["match"] == "provider-result"
    apply.assert_not_called()
    choice = choices["candidates"][0]["id"]
    service.choose(REQUEST, choices["revision"], choice, intent)
    assert service.wait()
    apply.assert_called_once_with(catalog.playback_candidates.return_value[0].media, intent)
    assert service.snapshot()["state"] == "complete"
    with pytest.raises(ValueError, match="changed"):
        service.choose(REQUEST, choices["revision"], choice, intent)


@pytest.mark.parametrize("invalidate", ["card", "expiry", "cancel", "block"])
def test_current_binding_and_policy_are_rechecked_before_actions(selection, invalidate):
    service, _, source, apply, unavailable, _ = selection
    choices = find_choices(service)
    if invalidate == "card":
        source.return_value = None
    elif invalidate == "expiry":
        service.clock = lambda: 10**12
    elif invalidate == "cancel":
        service.cancel(REQUEST)
    else:
        unavailable.return_value = "Playback blocked"
    with pytest.raises(ValueError):
        service.choose(REQUEST, choices["revision"], choices["candidates"][0]["id"], "queue")
    apply.assert_not_called()


@pytest.mark.parametrize("reuse_request", [False, True])
def test_slow_lookup_does_not_block_new_request_or_publish_stale_choices(selection, reuse_request):
    service, catalog, _, apply, _, updates = selection
    started, release = threading.Event(), threading.Event()

    def slow(_identity):
        started.set()
        assert release.wait(2)
        result = album()
        result.title = "Old edition" if catalog.inspect_release.call_count == 1 else "Newest edition"
        return result

    catalog.inspect_release.side_effect = slow
    service.begin("release:one", REQUEST)
    assert started.wait(1)
    service.begin("release:two", REQUEST if reuse_request else "b" * 32)
    service.begin("release:three", REQUEST if reuse_request else "c" * 32)
    release.set()
    assert service.wait()
    assert catalog.inspect_release.call_count == 2  # Only the latest pending request.
    assert service.snapshot()["item_id"] == "release:three"
    assert not any(p["title"] == "Old edition" and p["state"] == "tracks" for p in updates)
    assert service.snapshot()["title"] == "Newest edition"
    apply.assert_not_called()


def test_close_cancels_publication_and_does_not_start_pending_work(selection):
    service, catalog, _, apply, _, updates = selection
    entered, release = threading.Event(), threading.Event()

    def slow(_identity):
        entered.set()
        assert release.wait(2)
        return album()

    catalog.inspect_release.side_effect = slow
    service.begin("release:one", REQUEST)
    assert entered.wait(1)
    service.begin("release:two", "b" * 32)
    service.close(timeout=0)
    count = len(updates)
    release.set()
    service.close()
    assert len(updates) == count
    assert catalog.inspect_release.call_count == 1
    apply.assert_not_called()


def test_expired_response_and_private_provider_errors_are_safe(selection):
    service, catalog, source, apply, _, _ = selection
    catalog.inspect_release.side_effect = RuntimeError("https://private.example/?token=private")
    service.begin("release:one", REQUEST)
    assert service.wait()
    assert service.snapshot()["state"] == "error"
    assert "private" not in str(service.snapshot())

    def remove_card(_identity):
        source.return_value = None
        return album()

    catalog.inspect_release.side_effect = remove_card
    service.begin("release:one", REQUEST)
    assert service.wait()
    assert service.snapshot()["message"] == STALE
    apply.assert_not_called()


def test_empty_results_and_private_metadata_do_not_leak_or_execute(selection):
    service, catalog, _, apply, _, _ = selection
    catalog.inspect_release.return_value.title = "https://private.example/?token=private"
    catalog.playback_candidates.return_value = []
    result = find_choices(service)
    assert result["title"] == "Release edition"
    assert result["candidates"] == []
    assert "No playable versions" in result["message"]
    assert "https:" not in str(result)
    apply.assert_not_called()


def test_source_recheck_failure_revokes_selection_and_worker_recovers(selection):
    service, catalog, source, apply, _, _ = selection

    def lose_source(_identity):
        source.side_effect = OSError("Private source details")
        return album()

    catalog.inspect_release.side_effect = lose_source
    service.begin("release:one", REQUEST)
    assert service.wait()
    assert service.snapshot()["state"] == "error"
    assert service.snapshot()["message"] == STALE
    assert "Private" not in str(service.snapshot())
    apply.assert_not_called()

    source.side_effect = None
    catalog.inspect_release.side_effect = None
    assert find_choices(service)["state"] == "choices"


def test_late_version_results_are_revoked_after_the_source_card_changes(selection):
    service, catalog, source, apply, _, _ = selection
    entered, finish = threading.Event(), threading.Event()

    def versions(*_args, **_kwargs):
        entered.set()
        assert finish.wait(2)
        return catalog.playback_candidates.return_value

    catalog.playback_candidates.side_effect = versions
    service.begin("release:one", REQUEST)
    assert service.wait()
    state = service.snapshot()
    service.choose(REQUEST, state["revision"], state["tracks"][0]["id"], "versions")
    try:
        assert entered.wait(1)
        source.return_value = None
    finally:
        finish.set()
    assert service.wait()
    assert service.snapshot()["candidates"] == []
    assert service.snapshot()["message"] == STALE
    apply.assert_not_called()


def test_exact_release_inspection_does_not_mutate_search_state_or_resolve_sources():
    database = Mock()
    client = Mock()
    client.release.return_value = {
        "id": RELEASE, "title": "Edition", "media": [{"tracks": [{"title": "Track"}]}],
    }
    search = Mock()
    catalog = AlbumCatalog(database, musicbrainz=client, youtube_search=search)
    inspected = catalog.inspect_release(RELEASE)
    assert inspected.title == "Edition"
    assert inspected.tracks[0].title == "Track"
    assert inspected.tracks[0].media is None
    assert not database.mock_calls
    search.assert_not_called()
    client.release.return_value["id"] = "another-edition"
    with pytest.raises(AlbumError, match="unavailable"):
        catalog.inspect_release(RELEASE)


@pytest.mark.parametrize("tracks", [[], [{"title": "Recording"}] * 101])
def test_unsupported_editions_are_refused_before_resolution(tracks):
    client = Mock()
    client.release.return_value = {"id": RELEASE, "title": "Edition", "media": [{"tracks": tracks}]}
    catalog = AlbumCatalog(Mock(), musicbrainz=client)
    with pytest.raises(AlbumError, match="recording list"):
        catalog.inspect_release(RELEASE)
    with pytest.raises(AlbumError, match="identity"):
        catalog.inspect_release("ABCDEFAB-1234-4234-8234-123456789012")


@pytest.mark.parametrize("cancel_at", ["before-local", "before-search", "during-search"])
def test_cancelled_version_lookup_never_offers_partial_or_late_choices(cancel_at):
    cancelled = threading.Event()

    def search(*_args, **_kwargs):
        cancelled.set()
        return [{"id": "abcdefghijk"}]

    catalog = AlbumCatalog(Mock(), youtube_search=Mock(side_effect=search), youtube_info=Mock())
    catalog._local_rows = lambda: [({}, {}, None)] if cancel_at == "before-local" else []
    if cancel_at != "during-search":
        cancelled.set()
    assert catalog.playback_candidates(album(), album().tracks[0], cancelled=cancelled.is_set) == []
    catalog.youtube_info.assert_not_called()
    if cancel_at != "during-search":
        catalog.youtube_search.assert_not_called()


def test_version_results_are_bounded_distinct_and_require_a_real_title():
    info = Mock(side_effect=[{"title": "Actual version", "duration": 180}, {"duration": 180}])
    catalog = AlbumCatalog(Mock(), youtube_search=lambda *_, **__: [
        {"id": "abcdefghijk"}, {"id": "abcdefghijk"}, {"id": "bcdefghijkl"},
    ], youtube_info=info)
    catalog._local_rows = lambda: [
        ({"library_id": str(index), "canonical_path": f"/music/{index}.mp3", "content_signature": str(index), "fingerprint": None},
         {"title": "Different" if index == 0 else "Recording", "artist": "Artist"}, None)
        for index in range(13)
    ]
    results = catalog.playback_candidates(album(), album().tracks[0])
    assert [result.media.stable_id for result in results[:10]] == [str(index) for index in range(1, 11)]
    assert len(results) == 11
    assert results[-1].media.title == "Actual version"
    assert info.call_count == 2


@pytest.mark.parametrize("operation", ["begin", "choose", "cancel"])
def test_inflight_action_cannot_be_replaced_or_cancelled(selection, operation):
    service, _, _, apply, _, _ = selection
    entered, finish = threading.Event(), threading.Event()

    def applying(*_args):
        entered.set()
        assert finish.wait(2)

    apply.side_effect = applying
    choices = find_choices(service)
    service.choose(REQUEST, choices["revision"], choices["candidates"][0]["id"], "queue")
    try:
        assert entered.wait(1)
        with pytest.raises(ValueError):
            if operation == "begin":
                service.begin("release:two", "b" * 32)
            elif operation == "cancel":
                service.cancel(REQUEST)
            else:
                service.choose(REQUEST, service.snapshot()["revision"], "c" * 32, "versions")
    finally:
        finish.set()
    assert service.wait()
    apply.assert_called_once()
    assert service.snapshot()["state"] == "complete"


def test_invalid_selection_handles_and_missing_cards_do_not_start_work(selection):
    service, catalog, source, apply, _, _ = selection
    for item_id, request_id in [("article:one", REQUEST), ("release:one", "command\r"), ("release:" + "x" * 128, REQUEST)]:
        with pytest.raises(ValueError):
            service.begin(item_id, request_id)
    source.return_value = None
    with pytest.raises(ValueError):
        service.begin("release:one", REQUEST)
    catalog.inspect_release.assert_not_called()
    service.cancel("b" * 32)
    assert service.snapshot()["state"] == "closed"
    for revision, intent in [(True, "play"), (0, "play"), (1, "delete")]:
        with pytest.raises(ValueError):
            service.choose(REQUEST, revision, "c" * 32, intent)
    apply.assert_not_called()


def test_provider_candidates_preserve_actual_identity_and_ignore_unsafe_urls():
    catalog = AlbumCatalog(
        Mock(), youtube_search=Mock(return_value=[
            {"id": "abcdefghijk", "url": "https://private.example/?token=private", "title": "Actual version"},
            {"id": "invalid", "url": "file:///private"},
        ]), youtube_info=Mock(return_value={"title": "Live edition", "duration": 195, "artist": "Actual performer"}),
    )
    catalog._local_rows = list
    result = catalog.playback_candidates(album(), album().tracks[0])
    assert len(result) == 1
    media = result[0].media
    assert media.original_uri == "https://www.youtube.com/watch?v=abcdefghijk"
    assert media.title == "Live edition" and media.artist == "Actual performer"
    assert "recording_mbid" not in media.resolver_data
    assert media.album is None
    catalog.youtube_info.assert_called_once_with(media.original_uri, detailed=True, browser_profile=None)


@pytest.mark.parametrize("details", [{"is_live": True, "duration": 10}, {"duration": float("nan")}, {"duration": True}, {"duration": 10**400}])
def test_live_and_invalid_provider_results_are_not_offered(details):
    catalog = AlbumCatalog(Mock(), youtube_search=lambda *_, **__: [{"id": "abcdefghijk"}], youtube_info=lambda *_, **__: details)
    catalog._local_rows = list
    assert catalog.playback_candidates(album(), album().tracks[0]) == []


def test_oversized_release_duration_does_not_discard_known_recording(selection):
    service, catalog, _, apply, _, _ = selection
    catalog.inspect_release.return_value.tracks[0].duration = 10**400
    service.begin("release:one", REQUEST)
    assert service.wait()
    state = service.snapshot()
    assert state["state"] == "tracks"
    assert state["tracks"][0]["title"] == "Recording"
    assert state["tracks"][0]["duration"] is None
    apply.assert_not_called()


@pytest.mark.parametrize("explicit", [[], {}, ["yes"]])
def test_malformed_optional_catalogue_label_does_not_discard_known_media(selection, explicit):
    service, catalog, _, apply, _, _ = selection
    item = catalog.playback_candidates.return_value[0].media
    item.resolver_data["explicit"] = explicit
    service.catalogue_choices = lambda *_args: [item]
    service.begin("catalogue:one", REQUEST)
    assert service.wait()
    state = service.snapshot()
    assert state["state"] == "choices"
    assert state["candidates"][0]["title"] == "Actual video title"
    assert state["candidates"][0]["explicit"] is False
    apply.assert_not_called()


@pytest.mark.parametrize("invalidate", ["card", "shutdown"])
def test_action_rechecks_binding_after_policy_validation(selection, invalidate):
    service, _, source, apply, unavailable, _ = selection
    choices = find_choices(service)

    def revoke():
        if invalidate == "card":
            source.return_value = None
        else:
            service.close(timeout=0)
        return None

    # The first policy check accepts submission; the worker's check revokes it.
    unavailable.side_effect = lambda *_args: (
        None if unavailable.call_count == 2 else revoke()
    )
    service.choose(REQUEST, choices["revision"], choices["candidates"][0]["id"], "queue")
    assert service.wait()
    apply.assert_not_called()


def test_duplicate_local_recordings_remain_explicit_choices_when_network_fails():
    catalog = AlbumCatalog(Mock(), youtube_search=Mock(side_effect=OSError("offline")))
    catalog._local_rows = lambda: [
        ({"library_id": key, "canonical_path": f"C:/music/{key}.mp3", "content_signature": key, "fingerprint": None},
         {"title": "Recording", "artist": "Artist", "duration": 180}, "recording-id")
        for key in ("one", "two")
    ]
    track = album().tracks[0]
    track.recording_mbid = "recording-id"
    results = catalog.playback_candidates(album(), track)
    assert [row.media.stable_id for row in results] == ["one", "two"]
    assert all(row.match == "recording-id" for row in results)

    catalog._local_rows = list
    with pytest.raises(OSError, match="offline"):
        catalog.playback_candidates(album(), track)


def test_desktop_boundary_rejects_injection_and_uses_typed_selection(monkeypatch):
    import main

    service = Mock()
    monkeypatch.setattr(main, "DISCOVERY", service)
    assert main._desktop_control_request("discovery.begin", {"item_id": "release:one", "request_id": REQUEST}) == {"ok": True}
    service.begin.assert_called_once_with("release:one", REQUEST)
    invalid_payloads: tuple[dict[str, object], ...] = (
        {"request_id": REQUEST, "command": "delete 1"},
        {"request_id": "play\r", "item_id": "release:one"},
        {"request_id": REQUEST, "revision": True, "choice_id": "b" * 32, "intent": "queue"},
    )
    for payload in invalid_payloads:
        assert not main._desktop_control_request("discovery.choose", payload)["ok"]
    service.choose.assert_not_called()


def test_queue_action_only_appends_and_play_does_not_replace_queue(monkeypatch):
    import main

    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", title="Version")
    queue = Mock()
    supervisor = Mock()
    monkeypatch.setattr(main, "QUEUE", queue)
    monkeypatch.setattr(main, "vas", SimpleNamespace(supervisor=supervisor))
    monkeypatch.setattr(main, "COMMAND_BUSY", threading.Event())
    monkeypatch.setattr(main, "_discovery_unavailable", lambda _: None)
    monkeypatch.setattr(main, "_ensure_media_playable", lambda value: value)
    monkeypatch.setattr(main, "_emit_queue_desktop_state", Mock())
    monkeypatch.setattr(main, "_set_current_media_state", Mock())
    monkeypatch.setattr(main, "RECOMMENDER", Mock())
    main._apply_discovery_selection(media, "queue")
    assert queue.mock_calls == [("add", (media,), {})]
    supervisor.play.assert_not_called()
    queue.reset_mock()
    main._apply_discovery_selection(media, "play")
    supervisor.play.assert_called_once_with(media, origin="desktop")
    assert not queue.mock_calls
