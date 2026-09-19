import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.queueing import PersistentQueue
from mariana.recipe_queue import GroupIdentityMap, flat_tree
from mariana.session_recipes import RecipeError, default_settings, initial_state


@pytest.fixture
def session_cli(monkeypatch):
    service = Mock()
    service.status.return_value = {'state': 'idle', 'replay_active': False}
    service.start.return_value = {'state': 'preparing'}
    service.replay.return_value = {'state': 'replay_preparing'}
    monkeypatch.setattr(main, 'SESSIONS', service)
    monkeypatch.setattr(main, '_SESSION_REPLAY_ACTIVE', threading.Event())
    monkeypatch.setattr(main, '_SESSION_MEDIA', {})
    monkeypatch.setattr(main, '_SESSION_ACTIVE_ID', None)
    monkeypatch.setattr(main, '_SESSION_LAST_SETTINGS', None)
    monkeypatch.setattr(main, 'IPrint', Mock())
    monkeypatch.setattr(main.SLEEP_TIMER, 'status', lambda: SimpleNamespace(active=False))
    monkeypatch.setattr(main.STATION, 'session', lambda: None)
    monkeypatch.setattr(main, 'FOCUS_MODE', SimpleNamespace(recovery_required=False, state=SimpleNamespace(active=False), allows_command=lambda _: True), raising=False)
    monkeypatch.setattr(main, '_LOOP_OVERRIDE', {'mode': 'off'})
    monkeypatch.setattr(main, '_STEM_SELECTION', {'names': ()})
    monkeypatch.setattr(main, '_session_settings', lambda _: default_settings())
    monkeypatch.setattr(main.PLAY_REGIONS, 'get', lambda _: None)
    media = MediaRef(MediaSource.LOCAL, 'example.mp3', duration=60)
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: PlaybackSnapshot(
        PlaybackState.PAUSED, media=media, position=12, session_id='session-one',
    ))
    queue = {'items': [{'stable_id': media.stable_id}], 'groups': [],
             'state': {'current_position': 0, 'repeat_mode': 'off', 'shuffle_seed': None}}
    monkeypatch.setattr(main.QUEUE, 'export_snapshot', lambda: queue)
    return service, media, queue


@pytest.mark.parametrize('state', [PlaybackState.PAUSED, PlaybackState.PLAYING, PlaybackState.CROSSFADING])
def test_record_captures_current_position_and_occurrence_without_playback_mutation(session_cli, monkeypatch, state):
    service, media, queue = session_cli
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: PlaybackSnapshot(
        state, media=media, position=12, session_id='session-one',
    ))
    monkeypatch.setattr(main.vas.controller, 'play', Mock(side_effect=AssertionError('record must not play')))
    assert main.session_command(['record', 'example']) == {'state': 'preparing'}
    assert service.start.call_args.kwargs == {
        'initial_media_id': media.stable_id, 'initial_playback_session_id': 'session-one',
        'position_ms': 12000, 'playing': state != PlaybackState.PAUSED, 'queue_snapshot': queue,
        'settings': default_settings(),
    }


def test_play_requires_explicit_queue_replacement_consent(session_cli, monkeypatch):
    service, _, _ = session_cli
    monkeypatch.setattr(main, '_confirm_action', lambda _: False)
    assert main.session_command(['play', 'example']) is None
    service.replay.assert_not_called()
    main.session_command(['play', 'example', '--yes'])
    service.replay.assert_called_once_with('example')


def test_record_passes_whole_nested_snapshot_without_flattening(session_cli):
    service, _, queue = session_cli
    queue['groups'] = [{'group_id': 'album', 'kind': 'album', 'sibling_position': 0}]
    queue['items'][0].update(group_id='album', sibling_position=0)
    main.session_command(['record', 'example'])
    assert service.start.call_args.kwargs['queue_snapshot'] is queue
    assert 'queue_ids' not in service.start.call_args.kwargs


def test_seek_requires_active_recipe_without_implicitly_restarting_completed_playback(session_cli):
    service, _, _ = session_cli
    service.seek_replay.return_value = {'state': 'replay_preparing'}
    main.session_command(['seek', '01:30'])
    service.seek_replay.assert_called_once_with(90000, active_only=True)


@pytest.mark.parametrize('action', [
    'lyrics.status', 'equalizer.status', 'download.status', 'video.status',
    'homepage.open', 'autocomplete.catalog',
])
def test_replay_guard_keeps_read_only_desktop_surfaces_available(session_cli, monkeypatch, action):
    main._SESSION_REPLAY_ACTIVE.set()
    apply = Mock(return_value={'ok': True})
    monkeypatch.setattr(main, '_apply_desktop_control_request', apply)
    assert main._desktop_control_request(action, {}) == {'ok': True}
    apply.assert_called_once_with(action, {})


@pytest.mark.parametrize('command', ['pause', 'seek 5', 'queue clear', '/ys example', 'crossfade 2'])
def test_replay_guard_rejects_competing_cli_and_typed_controls(session_cli, monkeypatch, command):
    main._SESSION_REPLAY_ACTIVE.set()
    apply = Mock(side_effect=AssertionError('guard must reject'))
    monkeypatch.setattr(main, '_apply_desktop_control_request', apply)
    main.process(command)
    assert 'session stop' in main.IPrint.call_args.args[0]
    result = main._desktop_control_request('playback.seek', {'media_id': 'x', 'position': 4})
    assert not result['ok'] and 'Session replay' in result['error']
    apply.assert_not_called()


def test_recipe_ownership_suppresses_independent_prefetch_and_queue_completion(session_cli, monkeypatch):
    main._SESSION_REPLAY_ACTIVE.set()
    monkeypatch.setattr(main.QUEUE, 'items', Mock(side_effect=AssertionError('must not advance')))
    monkeypatch.setattr(main.RECOMMENDER, 'record_event', Mock(side_effect=AssertionError('must not advance')))
    main._prefetch_after(None)
    main._on_queue_item_complete(None)


def test_committed_event_fanout_is_once_and_independent_of_capture_failure(session_cli, monkeypatch):
    service, media, _ = session_cli
    capture = Mock(side_effect=RuntimeError('optional persistence is unavailable'))
    monkeypatch.setattr(main.PLAYBACK_EVENTS, 'capture', capture)
    service.capture_playback_event.return_value = True
    event = {'stable_id': media.stable_id, 'session_id': 'session-one', 'action': 'seek',
             'origin': 'cli', 'position_seconds': 12, 'seek_from_seconds': 3, 'seek_to_seconds': 12}
    assert main._capture_committed_playback_event(**event)
    capture.assert_called_once_with(**event)
    service.capture_playback_event.assert_called_once_with(**event)


def test_active_media_clear_records_one_stop_not_repeated_idle_notifications(session_cli):
    service, media, _ = session_cli
    main._remember_session_media(media)
    main._remember_session_media(None)
    main._remember_session_media(None)
    service.capture_stop.assert_called_once_with(reason='automatic')
    assert main._SESSION_MEDIA[media.stable_id].stable_id == media.stable_id


def test_committed_queue_hook_records_hierarchy_and_deduplicates_settings(session_cli, monkeypatch):
    service, _, queue = session_cli
    service.status.return_value = {'state': 'recording'}
    main._capture_session_queue()
    service.capture_queue_snapshot.assert_called_with(queue)
    service.capture_settings.assert_not_called()
    main._capture_session_queue()
    service.capture_settings.assert_not_called()
    queue['groups'] = [{'group_id': 'album', 'kind': 'album', 'sibling_position': 0}]
    queue['items'][0].update(group_id='album', sibling_position=0)
    main._capture_session_queue()
    service.capture_queue_snapshot.assert_called_with(queue)
    service.mark_unsupported.assert_not_called()
    monkeypatch.setattr(main, '_LOOP_OVERRIDE', {'mode': 'all'})
    main._capture_session_queue()
    service.mark_unsupported.assert_called_once()


def test_effective_queue_restore_preserves_duplicate_occurrences_and_cursor(tmp_path, monkeypatch):
    database = MarianaDatabase(tmp_path / 'test.db')
    queue = PersistentQueue(database)
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / 'song.wav'), duration=30)
    state = initial_state()
    state.update(queue=[media.stable_id, media.stable_id], current_index=1)
    state['queue_tree'] = flat_tree(state['queue'])
    monkeypatch.setattr(main, 'QUEUE', queue)
    monkeypatch.setattr(main, '_ensure_media_playable', lambda _: None)
    monkeypatch.setattr(main, '_emit_queue_desktop_state', lambda: None)
    main._session_restore_queue(state, {media.stable_id: media})
    snapshot = queue.export_snapshot()
    assert [item['stable_id'] for item in snapshot['items']] == state['queue']
    assert snapshot['state']['current_position'] == 1
    assert snapshot['groups'] == []


def test_nested_recipe_restore_validates_every_source_before_queue_mutation(tmp_path, monkeypatch):
    queue = PersistentQueue(MarianaDatabase(tmp_path / 'queue.db'))
    first = MediaRef(MediaSource.LOCAL, str(tmp_path / 'first.wav'), duration=30)
    blocked = MediaRef(MediaSource.LOCAL, str(tmp_path / 'blocked.wav'), duration=30)
    queue.extend([first])
    before = queue.export_snapshot()
    state = initial_state()
    projected = GroupIdentityMap().project({
        'groups': [{'group_id': 'album', 'kind': 'album', 'sibling_position': 0}],
        'items': [{'stable_id': media.stable_id, 'group_id': 'album', 'sibling_position': index}
                  for index, media in enumerate([first, blocked, first])],
        'state': {'current_position': 2},
    })
    state.update({key: projected[key] for key in ('queue', 'current_index', 'queue_tree')})
    monkeypatch.setattr(main, 'QUEUE', queue)
    monkeypatch.setattr(main, '_emit_queue_desktop_state', Mock())

    def ensure(media):
        if media is blocked:
            raise ValueError('Media is blocked')

    monkeypatch.setattr(main, '_ensure_media_playable', ensure)
    resolved = {first.stable_id: first, blocked.stable_id: blocked}
    with pytest.raises(ValueError, match='blocked'):
        main._session_restore_queue(state, resolved)
    assert queue.export_snapshot() == before
    main._emit_queue_desktop_state.assert_not_called()
    monkeypatch.setattr(main, '_ensure_media_playable', lambda _: None)
    main._session_restore_queue(state, resolved)
    snapshot = queue.export_snapshot()
    assert [item['stable_id'] for item in snapshot['items']] == state['queue']
    assert snapshot['state']['current_position'] == 2
    assert len(snapshot['groups']) == 1 and snapshot['groups'][0]['kind'] == 'album'
    assert snapshot['groups'][0]['source_ref'] is None


def test_session_status_list_inspect_and_stop_report_service_state(session_cli, tmp_path, monkeypatch):
    service, _, _ = session_cli
    service.inspect.return_value = {'name': 'example', 'valid': True}
    service.stop.return_value = True
    assert main.session_command(['status']) == {'state': 'idle', 'replay_active': False}
    assert main.session_command(['inspect', 'example']) == {'name': 'example', 'valid': True}
    assert main.session_command(['stop'])['state'] == 'idle'
    monkeypatch.setattr(main, 'RUNTIME_PATHS', SimpleNamespace(state=lambda *parts: tmp_path))
    assert main.session_command(['list']) == []
    with pytest.raises(RecipeError, match='Usage'):
        main.session_command(['bogus'])
    with pytest.raises(RecipeError, match='Usage'):
        main.session_command(['record'])
    with pytest.raises(RecipeError, match='Usage'):
        main.session_command(['seek', '01:30', 'extra'])


def test_session_record_guards_require_ready_idle_services(session_cli, monkeypatch):
    service, _, _ = session_cli
    monkeypatch.setattr(main.SLEEP_TIMER, 'status', lambda: SimpleNamespace(active=True))
    with pytest.raises(RecipeError, match='Stop the sleep timer'):
        main.session_command(['record', 'example'])
    monkeypatch.setattr(main.SLEEP_TIMER, 'status', lambda: SimpleNamespace(active=False))
    monkeypatch.setattr(main, '_LOOP_OVERRIDE', {'mode': 'infinite'})
    with pytest.raises(RecipeError, match='Disable loop'):
        main.session_command(['record', 'example'])
    monkeypatch.setattr(main, '_LOOP_OVERRIDE', {'mode': 'off'})
    service.status.return_value = {'state': 'idle', 'replay_active': False}
    monkeypatch.setattr(
        main.vas.controller, 'snapshot',
        lambda: PlaybackSnapshot(PlaybackState.FAILED, media=None, position=0),
    )
    with pytest.raises(RecipeError, match='ready before starting'):
        main.session_command(['record', 'example'])


def test_session_seek_reports_replay_position(session_cli):
    service, _, _ = session_cli
    service.seek_replay.return_value = {'state': 'replaying', 'position_ms': 90000}
    assert main.session_command(['seek', '01:30']) == {'state': 'replaying', 'position_ms': 90000}
    service.seek_replay.assert_called_once_with(90000, active_only=True)


def test_capture_marks_unsupported_sessions_without_recording(session_cli, monkeypatch):
    service, _, _ = session_cli
    service.status.return_value = {'state': 'preparing'}
    monkeypatch.setattr(main, '_LOOP_OVERRIDE', {'mode': 'infinite'})
    main._capture_session_queue()
    service.mark_unsupported.assert_called_once_with()
    service.capture_queue_snapshot.assert_not_called()
    monkeypatch.setattr(main, '_LOOP_OVERRIDE', {'mode': 'off'})
    monkeypatch.setattr(main, '_STEM_SELECTION', {'names': ('vocals',)})
    main._capture_session_queue()
    assert service.mark_unsupported.call_count == 2
    monkeypatch.setattr(main, '_STEM_SELECTION', {'names': ()})
    monkeypatch.setattr(main.STATION, 'session', lambda: SimpleNamespace())
    main._capture_session_queue()
    assert service.mark_unsupported.call_count == 3
    monkeypatch.setattr(main.STATION, 'session', lambda: None)
    monkeypatch.setattr(main.QUEUE, 'export_snapshot', Mock(side_effect=RuntimeError('unavailable')))
    main._capture_session_queue()
    assert service.mark_unsupported.call_count == 4


def test_replay_ownership_freezes_independent_advancement(session_cli, monkeypatch):
    service, media, _ = session_cli
    main._SESSION_REPLAY_ACTIVE.set()
    try:
        main._remember_session_media(media)
        assert media.stable_id == main._SESSION_ACTIVE_ID
        main._on_queue_item_complete(media)
        service.capture_queue_snapshot.assert_not_called()
    finally:
        main._SESSION_REPLAY_ACTIVE.clear()
        main._SESSION_ACTIVE_ID = None


def test_session_stop_seek_and_usage_errors_report_without_side_effects(session_cli, monkeypatch, tmp_path):
    service, _, _ = session_cli
    service.stop_replay.return_value = True
    service.status.return_value = {'state': 'replaying', 'replay_active': True}
    stopped = main.session_command(['stop'])
    assert stopped['flushed'] is True
    service.stop_replay.assert_called_once_with()
    monkeypatch.setattr(main, 'RUNTIME_PATHS', SimpleNamespace(state=lambda *parts: tmp_path))
    (tmp_path / 'evening.jsonl').write_text('{}\n', encoding='utf-8')
    assert main.session_command(['list']) == ['evening']
    with pytest.raises(RecipeError, match='Usage'):
        main.session_command(['bogus'])
    with pytest.raises(RecipeError, match='Usage'):
        main.session_command(['record'])
    with pytest.raises(RecipeError, match='Usage'):
        main.session_command(['status', 'extra'])
    with pytest.raises(RecipeError, match='Stop the sleep timer'):
        monkeypatch.setattr(main.STATION, 'session', lambda: SimpleNamespace())
        try:
            main.session_command(['record', 'example'])
        finally:
            monkeypatch.setattr(main.STATION, 'session', lambda: None)
    monkeypatch.setattr(
        main, 'FOCUS_MODE',
        SimpleNamespace(state=SimpleNamespace(active=True)), raising=False,
    )
    try:
        with pytest.raises(RecipeError, match='Focus session'):
            main.session_command(['record', 'example'])
    finally:
        delattr(main, 'FOCUS_MODE')


def test_capture_records_settings_changes_only(session_cli, monkeypatch):
    from mariana.session_recipes import default_settings as _defaults
    service, _, _ = session_cli
    service.status.return_value = {'state': 'preparing'}
    changed = _defaults()
    changed['repeat'] = 'one'
    monkeypatch.setattr(main, '_SESSION_LAST_SETTINGS', changed)
    main._capture_session_queue()
    service.capture_settings.assert_called_once()
    service.capture_settings.reset_mock()
    monkeypatch.setattr(main, '_SESSION_LAST_SETTINGS', _defaults())
    main._capture_session_queue()
    service.capture_settings.assert_not_called()


def test_idle_media_clear_stops_capture_worker(session_cli):
    service, _, _ = session_cli
    main._SESSION_ACTIVE_ID = 'previous-media'
    try:
        main._remember_session_media(None)
        assert main._SESSION_ACTIVE_ID is None
        service.capture_stop.assert_called_once_with(reason='automatic')
    finally:
        main._SESSION_ACTIVE_ID = None
