"""Damaged saved restrictions must not become an implicit unlock or startup crash."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from mariana.focus_mode import (
    COUNTDOWN_SECONDS,
    RECOVERY_MESSAGE,
    FocusModeError,
    FocusModeService,
    FocusState,
    FocusStateStore,
    PairedFocusDevice,
)
from mariana.models import MediaRef, MediaSource
from tests.test_focus_mode import Clock, Credentials, Transport


def active_state():
    return FocusState(
        active=True, activated_at=1_000.0, active_media_id='abcdefghijk',
        paired_devices=[PairedFocusDevice('phone-device-0001', 'Phone', 1_000.0)],
    )


def service_at(path):
    clock = Clock()
    transport = Transport(clock)
    service = FocusModeService(
        FocusStateStore(path), credentials=Credentials(), transport=transport,
        clock=clock, approved_youtube_ids=['abcdefghijk'],
    )
    return service, transport


@pytest.mark.parametrize('payload', [
    b'', b'{', b'null', b'[]', b'\xff', b'{}', b'{"schema_version":1,"schema_version":1}',
    b'[' * 2_000, b' ' * 65_537,
], ids=['empty', 'truncated', 'null', 'array', 'encoding', 'missing-fields', 'duplicate-keys', 'deep', 'oversized'])
def test_corrupt_payload_opens_locked_and_preserves_original(tmp_path, payload):
    path = tmp_path / 'focus-state.json'
    path.write_bytes(payload)
    service, transport = service_at(path)
    assert service.recovery_required and service.state.active
    assert service.status()['recovery_message'] == RECOVERY_MESSAGE
    assert service.recovery_status() == {'required': True, 'message': RECOVERY_MESSAGE}
    assert path.read_bytes() == payload
    assert transport.calls == []
    restored, _ = service_at(path)
    assert restored.recovery_required


@pytest.mark.parametrize(('field', 'value'), [
    ('schema_version', True), ('schema_version', 2), ('desktop_instance_id', None),
    ('desktop_instance_id', 'bad'), ('active', 'false'), ('active', 0),
    ('activated_at', True), ('activated_at', float('nan')), ('activated_at', float('inf')),
    ('active_media_id', 'https://private.invalid/?secret=value'), ('active_media_id', None),
    ('paired_devices', None), ('paired_devices', {}), ('paired_devices', [None]), ('paired_devices', []),
    ('failed_attempts', '2'), ('failed_attempts', -1), ('failed_attempts', 6),
    ('unlock_stage', []), ('unlock_stage', 'unknown'), ('unlock_stage', 'countdown'),
    ('pairing_request_id', 'pairing-request-1'), ('pairing_expires_at', 1_200.0),
    ('unlock_device_id', True), ('unlock_request_id', []),
    ('countdown_started_at', 1_000.0), ('passcode_blocked_until', '1001'),
    ('unexpected', 'private-data'),
])
def test_invalid_fields_fail_closed_without_coercion(tmp_path, field, value):
    path = tmp_path / 'focus-state.json'
    payload = {**asdict(active_state()), field: value}
    path.write_text(json.dumps(payload), encoding='utf-8')
    before = path.read_bytes()
    service, _ = service_at(path)
    assert service.recovery_required
    assert path.read_bytes() == before
    assert 'private.invalid' not in json.dumps(service.status())


def test_first_run_differs_from_deleted_existing_state(tmp_path):
    path = tmp_path / 'focus-state.json'
    service, _ = service_at(path)
    assert not service.state.active and not service.recovery_required
    assert not service.store.guard_path.exists()
    service.store.save(active_state())
    path.unlink()
    restored, _ = service_at(path)
    assert restored.recovery_required
    assert not path.exists()


def test_existing_valid_install_gains_presence_guard_without_state_rewrite(tmp_path):
    path = tmp_path / 'focus-state.json'
    path.write_text(json.dumps(asdict(active_state())), encoding='utf-8')
    before = path.read_bytes()
    service, _ = service_at(path)
    assert not service.recovery_required and service.state.active
    assert service.store.guard_path.is_file()
    assert path.read_bytes() == before


def test_restore_requires_explicit_retry_and_an_active_backup(tmp_path):
    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    path.write_text(json.dumps(asdict(FocusState())), encoding='utf-8')
    with pytest.raises(FocusModeError, match='Playback is locked'):
        service.recover_saved_state()
    assert service.recovery_required
    path.write_text(json.dumps(asdict(active_state())), encoding='utf-8')
    restarted, _ = service_at(path)
    assert restarted.recovery_required
    assert restarted.recover_saved_state() == {'required': False, 'message': None}
    assert restarted.state.active and restarted.state.active_media_id == 'abcdefghijk'
    loaded, _ = service_at(path)
    assert loaded.state.active and not loaded.recovery_required


def test_recovered_countdown_cannot_unlock_without_new_handshake(tmp_path, monkeypatch):
    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    backup = active_state()
    backup.unlock_stage = 'countdown'
    backup.unlock_request_id = 'unlock-request-1'
    backup.unlock_device_id = 'phone-device-0001'
    backup.unlock_expires_at = 1_100.0
    backup.countdown_started_at = 1_000.0
    monkeypatch.setattr('mariana.focus_mode._now', lambda: 1_000.0)
    path.write_text(json.dumps(asdict(backup)), encoding='utf-8')
    service.recover_saved_state()
    assert service.state.unlock_stage is None
    service.clock.value += COUNTDOWN_SECONDS + 1
    assert not service.poll_unlock()
    assert service.state.active


@pytest.mark.parametrize('operation', [
    lambda s: s.setup_passcode('new-passcode', 'new-passcode'), lambda s: s.activate(),
    lambda s: s.begin_pairing(), lambda s: s.refresh_pairing(),
    lambda s: s.revoke_device('phone-device-0001'), lambda s: s.rollback_activation('abcdefghijk'),
    lambda s: s.begin_unlock('some-passcode'), lambda s: s.submit_phone_code('ABCDEFGH23'),
    lambda s: s.poll_unlock(), lambda s: s.cancel_pending_unlock(),
    lambda s: s.assert_media_allowed(MediaRef(MediaSource.YOUTUBE, 'https://youtu.be/abcdefghijk')),
])
def test_recovery_rejects_mutations_without_credentials_transport_or_saved_data_changes(tmp_path, operation):
    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, transport = service_at(path)
    with pytest.raises(FocusModeError, match='Playback is locked'):
        operation(service)
    assert path.read_bytes() == b'broken'
    assert service.credentials.values == {} and transport.calls == []


@pytest.mark.parametrize('command', ['p', 'pause', 'resume', '/ys', 'session', 'eq', 'volume', 'download-ml', 'home'])
def test_recovery_cli_rejects_playback_or_settings_changes(tmp_path, command):
    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    assert not service.allows_command([command])
    for allowed in ('focus', 'help', 'now', 'exit', 'quit', 's', 'stop'):
        assert service.allows_command([allowed])


def test_failed_unlock_persistence_locks_instead_of_leaving_memory_unlocked(tmp_path, monkeypatch):
    path = tmp_path / 'focus-state.json'
    service, _ = service_at(path)
    service.state = active_state()
    service.store.save(service.state)
    before = path.read_bytes()
    service.state.unlock_stage = 'countdown'
    service.state.countdown_started_at = service.clock() - COUNTDOWN_SECONDS
    monkeypatch.setattr(service.store, 'save', lambda _state: (_ for _ in ()).throw(OSError('disk unavailable')))
    with pytest.raises(FocusModeError, match='Playback is locked'):
        service.poll_unlock()
    assert service.state.active and service.recovery_required
    assert path.read_bytes() == before
    assert service.status()['recovery_required']


def test_corrupt_guard_stays_locked_even_if_primary_file_is_missing(tmp_path):
    path = tmp_path / 'focus-state.json'
    path.with_name(path.name + '.guard').write_text('{', encoding='utf-8')
    service, _ = service_at(path)
    assert service.recovery_required and not path.exists()
    assert service.store.guard_path.read_text(encoding='utf-8') == '{'


def test_recovery_status_does_not_need_working_credentials(tmp_path, monkeypatch):
    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    monkeypatch.setattr(service.credentials, 'get', lambda _key: pytest.fail('credential lookup during recovery'))
    assert service.status()['recovery_required']


@pytest.mark.parametrize('action', [
    'playback.play', 'playback.pause', 'playback.seek', 'playback.next', 'equalizer.configure',
    'homepage.refresh', 'discovery.choose', 'strudel.preview', 'video.configure', 'download.current',
])
def test_desktop_recovery_gate_rejects_before_control_dispatch(tmp_path, monkeypatch, action):
    from types import SimpleNamespace

    import main

    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    events = []
    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, 'DESKTOP_CONTROL', SimpleNamespace(emit=lambda *values: events.append(values)))
    monkeypatch.setattr(main, '_apply_desktop_control_request', lambda *_args: pytest.fail('control mutation'))
    result = main._desktop_control_request(action, {'media_id': 'track'})
    assert result == {'ok': False, 'error': RECOVERY_MESSAGE}
    assert events == [('focus-recovery', {'required': True, 'message': RECOVERY_MESSAGE})]


def test_cli_and_typed_retry_restore_the_same_active_lock_without_terminal_injection(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import main

    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, transport = service_at(path)
    events, messages = [], []
    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, 'DESKTOP_CONTROL', SimpleNamespace(emit=lambda *values: events.append(values)))
    monkeypatch.setattr(main, 'IPrint', lambda text, **_kwargs: messages.append(text))
    monkeypatch.setattr(main, '_apply_desktop_control_request', lambda *_args: pytest.fail('normal control dispatch'))
    assert main.focus_command(['status'])['recovery_required']
    with pytest.raises(FocusModeError, match='Playback is locked'):
        main.focus_command(['setup'])
    result = main._desktop_control_request('focus.recovery.retry', {})
    assert not result['ok'] and service.recovery_required
    assert not main._desktop_control_request('focus.recovery.retry', {'path': 'untrusted'})['ok']
    path.write_text(json.dumps(asdict(active_state())), encoding='utf-8')
    assert main.focus_command(['recover']) == {'required': False, 'message': None}
    assert service.state.active
    assert events[-1] == ('focus-recovery', {'required': False, 'message': None})
    assert transport.calls == []
    assert main._desktop_control_request('focus.recovery.status', {}) == {'ok': True}


@pytest.mark.parametrize('first_boot', [False, True])
def test_recovery_startup_skips_onboarding_and_playback_prerequisites(tmp_path, monkeypatch, first_boot):
    import main
    from runtime_check import PLAYBACK_PREREQUISITE_ERRORS, RuntimeReport

    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    errors = tuple(sorted(PLAYBACK_PREREQUISITE_ERRORS))
    calls = []
    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, 'FIRST_BOOT', first_boot)
    monkeypatch.setattr(main, 'SOFT_FATAL_ERROR_INFO', None)
    monkeypatch.setattr(main, 'RUNTIME_REPORT', RuntimeReport(errors, (), {}))
    monkeypatch.setattr(main, 'FATAL_ERROR_INFO', '; '.join(errors))
    monkeypatch.setattr(main, 'first_startup_greet', lambda *_: pytest.fail('onboarding during recovery'))
    monkeypatch.setattr(main, 'ensure_managed_tool_migration', lambda: pytest.fail('tool setup during recovery'))
    monkeypatch.setattr(main, 'run', lambda: calls.append('locked-shell'))
    main.startup()
    assert calls == ['locked-shell']
    assert service.recovery_required and path.read_bytes() == b'broken'


def test_recovery_keeps_nonplayback_fatal_errors_and_explicit_abort(tmp_path, monkeypatch):
    import main
    from runtime_check import RuntimeReport

    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, 'SOFT_FATAL_ERROR_INFO', None)
    monkeypatch.setattr(main, 'RUNTIME_REPORT', RuntimeReport(('unsupported runtime',), (), {}))
    monkeypatch.setattr(main, 'FATAL_ERROR_INFO', 'unsupported runtime')
    monkeypatch.setattr(main, 'run', lambda: pytest.fail('incompatible runtime'))
    monkeypatch.setattr(main, 'IPrint', lambda *_args, **_kwargs: None)
    with pytest.raises(SystemExit) as error:
        main.startup()
    assert error.value.code == 1
    monkeypatch.setattr(main, 'SOFT_FATAL_ERROR_INFO', 'explicit abort')
    main.startup()


def test_runtime_persistence_failure_schedules_one_stop_and_persistent_notice(tmp_path, monkeypatch):
    import threading
    from types import SimpleNamespace

    import main

    service, _ = service_at(tmp_path / 'focus-state.json')
    service.state = active_state()
    service.store.save(service.state)
    service.state.unlock_stage = 'countdown'
    service.state.countdown_started_at = service.clock() - COUNTDOWN_SECONDS
    service._on_recovery = main._notify_focus_recovery
    entered, release = threading.Event(), threading.Event()
    stops, notices = [], []

    def stop():
        stops.append(threading.get_ident())
        # Acquiring the state lock here proves output work does not hold it.
        assert service.recovery_status()['required']
        entered.set()
        assert release.wait(2)

    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, '_FOCUS_RECOVERY_THREAD', None)
    monkeypatch.setattr(main, 'vas', SimpleNamespace(supervisor=SimpleNamespace(stop=stop)))
    monkeypatch.setattr(main, 'DESKTOP_CONTROL', SimpleNamespace(emit=lambda *values: notices.append(values)))
    monkeypatch.setattr(service.store, 'save', lambda _state: (_ for _ in ()).throw(OSError('unavailable')))
    try:
        with pytest.raises(FocusModeError, match='Playback is locked'):
            service.poll_unlock()
        assert entered.wait(2)
        worker = main._FOCUS_RECOVERY_THREAD
        assert main._schedule_focus_recovery() is worker
        assert stops == [worker.ident] and worker.ident != threading.get_ident()
        assert notices == [('focus-recovery', {'required': True, 'message': RECOVERY_MESSAGE})]
    finally:
        release.set()
        main._close_focus_recovery()
    assert not worker.is_alive()
    assert service.state.active and service.recovery_required


def test_recovery_callback_failure_cannot_unlock_saved_restrictions(tmp_path, monkeypatch):
    service, _ = service_at(tmp_path / 'focus-state.json')
    service.state = active_state()
    service._on_recovery = lambda: (_ for _ in ()).throw(RuntimeError('worker unavailable'))
    monkeypatch.setattr(service.store, 'save', lambda _state: (_ for _ in ()).throw(OSError('unavailable')))
    with pytest.raises(FocusModeError, match='Playback is locked'):
        service.cancel_pending_unlock()
    assert service.recovery_required and service.state.active


@pytest.mark.parametrize('nested', [False, True])
def test_worker_start_failure_stops_outside_state_and_scheduler_locks(tmp_path, monkeypatch, nested):
    import threading
    from contextlib import nullcontext
    from types import SimpleNamespace

    import main

    real_thread = threading.Thread
    service, _ = service_at(tmp_path / 'focus-state.json')
    service.state = active_state()
    service.store.save(service.state)
    service.state.unlock_stage = 'countdown'
    service.state.countdown_started_at = service.clock() - COUNTDOWN_SECONDS
    service._on_recovery = main._notify_focus_recovery
    notices, stops, unlocked, readers = [], [], [], []

    class UnstartedThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError('cannot start another thread')

        def join(self, **_kwargs):
            pytest.fail('shutdown must not join an unstarted worker')

    def stop():
        stops.append(threading.get_ident())
        finished = threading.Event()

        def read_recovery():
            # Another thread must acquire both locks while synchronous stop is
            # running; same-thread RLock reentry would not prove this invariant.
            with main._FOCUS_RECOVERY_LOCK:
                assert service.recovery_status()['required']
            finished.set()

        reader = real_thread(target=read_recovery, daemon=True)
        readers.append(reader)
        reader.start()
        unlocked.append(finished.wait(2))

    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, '_FOCUS_RECOVERY_THREAD', None)
    monkeypatch.setattr(main, 'vas', SimpleNamespace(supervisor=SimpleNamespace(stop=stop)))
    monkeypatch.setattr(main, 'DESKTOP_CONTROL', SimpleNamespace(emit=lambda *values: notices.append(values)))
    monkeypatch.setattr(main.threading, 'Thread', UnstartedThread)
    monkeypatch.setattr(service.store, 'save', lambda _state: (_ for _ in ()).throw(OSError('unavailable')))
    try:
        with service._state_lock() if nested else nullcontext():
            with pytest.raises(FocusModeError, match='Playback is locked'):
                service.poll_unlock()
            if nested:
                assert stops == [] and notices == []
        assert stops == [threading.get_ident()]
        assert unlocked == [True]
        assert notices == [('focus-recovery', {'required': True, 'message': RECOVERY_MESSAGE})]
        assert main._FOCUS_RECOVERY_THREAD is None
        main._close_focus_recovery()
    finally:
        for reader in readers:
            reader.join(timeout=2)
    assert service.recovery_required and service.state.active


def test_worker_start_fallback_still_stops_if_notice_transport_is_unavailable(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import main

    service, _ = service_at(tmp_path / 'focus-state.json')
    service.state = active_state()
    service._on_recovery = main._notify_focus_recovery
    stops = []

    class UnstartedThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError('cannot start another thread')

    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, '_FOCUS_RECOVERY_THREAD', None)
    monkeypatch.setattr(main, 'vas', SimpleNamespace(supervisor=SimpleNamespace(stop=lambda: stops.append('stopped'))))
    monkeypatch.setattr(main, 'DESKTOP_CONTROL', SimpleNamespace(
        emit=lambda *_args: (_ for _ in ()).throw(OSError('transport unavailable')),
    ))
    monkeypatch.setattr(main.threading, 'Thread', UnstartedThread)
    monkeypatch.setattr(service.store, 'save', lambda _state: (_ for _ in ()).throw(OSError('unavailable')))
    with pytest.raises(FocusModeError, match='Playback is locked'):
        service.cancel_pending_unlock()
    assert stops == ['stopped']
    assert service.recovery_required and service.state.active
    assert main._FOCUS_RECOVERY_THREAD is None


def test_actual_command_router_preserves_safe_stop_but_rejects_resume_toggles(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import main
    from mariana.models import PlaybackState

    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, _ = service_at(path)
    stops, messages = [], []
    monkeypatch.setattr(main, 'FOCUS_MODE', service)
    monkeypatch.setattr(main, '_SESSION_REPLAY_ACTIVE', SimpleNamespace(is_set=lambda: False))
    monkeypatch.setattr(main, 'isplaying', False)
    monkeypatch.setattr(main, 'vas', SimpleNamespace(
        controller=SimpleNamespace(snapshot=lambda: SimpleNamespace(state=PlaybackState.IDLE)),
    ))
    monkeypatch.setattr(main, 'stopsong', lambda: stops.append('stopped'))
    monkeypatch.setattr(main, 'IPrint', lambda message, **_kwargs: messages.append(message))
    for command in ('s', 'stop'):
        main._process_command(command)
    assert stops == ['stopped', 'stopped'] and messages == []
    for command in ('p', 'pause', 'resume'):
        main._process_command(command)
    assert stops == ['stopped', 'stopped']
    assert messages == [RECOVERY_MESSAGE] * 3
    assert service.recovery_required and service.state.active


def test_directory_in_place_of_saved_state_is_not_read_or_overwritten(tmp_path):
    path = tmp_path / 'focus-state.json'
    path.mkdir()
    marker = path / 'preserved.txt'
    marker.write_text('preserved', encoding='utf-8')
    service, _ = service_at(path)
    assert service.recovery_required and marker.read_text(encoding='utf-8') == 'preserved'
    with pytest.raises(FocusModeError, match='Playback is locked'):
        FocusStateStore._write(path, asdict(active_state()))
    assert path.is_dir() and list(tmp_path.glob('.focus-state-*.tmp')) == []


def test_saved_state_replaced_between_path_check_and_open_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import mariana.focus_mode as focus

    path = tmp_path / 'focus-state.json'
    path.write_text(json.dumps(asdict(active_state())), encoding='utf-8')
    original_fstat = focus.os.fstat

    def replaced(descriptor):
        details = original_fstat(descriptor)
        return SimpleNamespace(st_dev=details.st_dev, st_ino=details.st_ino + 1)

    monkeypatch.setattr(focus.os, 'fstat', replaced)
    service, _ = service_at(path)
    assert service.recovery_required
    assert json.loads(path.read_text(encoding='utf-8'))['active'] is True


def test_duplicate_paired_device_identity_cannot_restore_restrictions(tmp_path):
    path = tmp_path / 'focus-state.json'
    backup = active_state()
    backup.paired_devices.append(backup.paired_devices[0])
    path.write_text(json.dumps(asdict(backup)), encoding='utf-8')
    service, _ = service_at(path)
    assert service.recovery_required
    with pytest.raises(FocusModeError, match='Playback is locked'):
        service.recover_saved_state()
    assert service.recovery_required


def test_expired_saved_challenges_are_cleared_without_unlocking(tmp_path, monkeypatch):
    path = tmp_path / 'focus-state.json'
    backup = active_state()
    backup.pairing_request_id = 'pairing-request-1'
    backup.pairing_expires_at = 1_001.0
    backup.unlock_request_id = 'unlock-request-1'
    backup.unlock_device_id = backup.paired_devices[0].device_id
    backup.unlock_stage = 'awaiting_phone_code'
    backup.unlock_expires_at = 1_001.0
    path.write_text(json.dumps(asdict(backup)), encoding='utf-8')
    monkeypatch.setattr('mariana.focus_mode._now', lambda: 1_002.0)
    service, _ = service_at(path)
    assert not service.recovery_required and service.state.active
    assert service.state.pairing_request_id is None and service.state.pairing_expires_at is None
    assert service.state.unlock_request_id is None and service.state.unlock_stage is None


def test_recovery_guard_write_failure_remains_locked_across_restart(tmp_path, monkeypatch):
    path = tmp_path / 'focus-state.json'
    path.write_bytes(b'broken')
    service, transport = service_at(path)
    path.write_text(json.dumps(asdict(active_state())), encoding='utf-8')
    monkeypatch.setattr(service.store, '_guard', lambda _required: (_ for _ in ()).throw(OSError('read-only guard')))
    with pytest.raises(FocusModeError, match='Playback is locked'):
        service.recover_saved_state()
    assert service.recovery_required and service.state.active
    with pytest.raises(FocusModeError, match='Playback is locked'):
        service.store.save(active_state())
    restored, _ = service_at(path)
    assert restored.recovery_required and transport.calls == []
    assert list(tmp_path.glob('.focus-state-*.tmp')) == []
