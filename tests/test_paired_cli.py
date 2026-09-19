from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.command_catalog import CommandRisk, serialize_command_catalog
from mariana.paired_trust import PairingError


@pytest.fixture
def companion(monkeypatch):
    service = Mock()
    service.status.return_value = {
        'listener_running': False, 'read_only': True, 'state': 'idle',
        'operation': None, 'result': None, 'error': None,
    }
    service.submit.side_effect = lambda operation, *_: {'state': 'pending', 'operation': operation}
    monkeypatch.setattr(main, 'PAIRED_COMPANION', service)
    monkeypatch.setattr(main, 'IPrint', Mock())
    return service


def test_room_status_is_cached_and_does_not_start_or_poll_network(companion):
    assert main.room_command([])['state'] == 'idle'
    main.room_command(['status'])
    assert companion.status.call_count == 2
    companion.submit.assert_not_called()


@pytest.mark.parametrize(('command', 'expected'), [
    (['host', '192.168.1.10'], ('host', '192.168.1.10', 0)),
    (['host', '192.168.1.10', '8765'], ('host', '192.168.1.10', 8765)),
    (['connect', 'invitation.json', 'a' * 64], ('connect', 'invitation.json', 'a' * 64, 'Mariana desktop')),
    (['connect', 'invitation.json', 'a' * 64, 'Music desktop'],
     ('connect', 'invitation.json', 'a' * 64, 'Music desktop')),
    (['approve', 'b' * 32, 'c' * 16], ('approve', 'b' * 32, 'c' * 16)),
    (['reject', 'b' * 32], ('reject', 'b' * 32)),
    (['invite', 'new-invitation.json'], ('invite', 'new-invitation.json')),
    (['devices'], ('devices',)), (['requests'], ('requests',)),
    (['revoke', 'd' * 32], ('revoke', 'd' * 32)),
    (['now'], ('now',)), (['poll'], ('poll',)), (['stop'], ('stop',)),
    (['cancel'], ('cancel',)), (['disconnect'], ('disconnect',)),
])
def test_room_commands_schedule_explicit_operations_without_blocking(companion, command, expected):
    result = main.room_command(command)
    assert result['state'] == 'pending'
    companion.submit.assert_called_once_with(*expected)
    assert 'room status' in main.IPrint.call_args.args[0]


@pytest.mark.parametrize('arguments', [
    ['status', 'extra'], ['host'], ['host', '192.168.1.10', 'nan'],
    ['host', '192.168.1.10', '-1'], ['host', '192.168.1.10', '65536'],
    ['connect', 'file.json'], ['approve', 'id'], ['stop', 'extra'],
    ['delete'], ['publish', 'anything'], ['now', 'extra'],
])
def test_invalid_room_grammar_does_not_schedule_work(companion, arguments):
    with pytest.raises(ValueError):
        main.room_command(arguments)
    companion.submit.assert_not_called()


def test_pairing_refusal_uses_existing_command_error_boundary(companion):
    companion.submit.side_effect = PairingError('Pairing requires protected credential storage')
    with pytest.raises(ValueError, match='protected credential storage'):
        main.room_command(['host', '127.0.0.1'])


def test_room_shutdown_does_not_construct_service_when_unused(monkeypatch):
    monkeypatch.setattr(main, 'PAIRED_COMPANION', None)
    monkeypatch.setattr(main, '_paired_companion', Mock(side_effect=AssertionError('must stay lazy')))
    assert main._close_paired_companion()


def test_room_initialization_uses_runtime_state_without_starting_listener(tmp_path, monkeypatch):
    from mariana import paired_companion

    factory = Mock(return_value=object())
    monkeypatch.setattr(paired_companion, 'PairedCompanion', factory)
    monkeypatch.setattr(main, 'PAIRED_COMPANION', None)
    monkeypatch.setattr(main, 'RUNTIME_PATHS', SimpleNamespace(state=lambda name: tmp_path / name))
    service = main._paired_companion()
    assert service is main._paired_companion()
    factory.assert_called_once()
    assert factory.call_args.args == (tmp_path / 'paired-desktops',)
    assert callable(factory.call_args.kwargs['snapshot'])


def test_room_help_documents_read_only_permissions_and_explicit_external_operations(companion):
    rows = {row['canonical']: row for row in serialize_command_catalog()}
    assert rows['room']['risk'] == CommandRisk.READ_ONLY
    for command in ('host', 'connect', 'now', 'poll', 'invite'):
        assert rows[f'room {command}']['risk'] == CommandRisk.EXTERNAL_ACTION
    assert 'read-only' in rows['room devices']['summary']
    assert main.room_command(['help'])
    companion.submit.assert_not_called()


def test_room_routes_through_existing_command_loop(companion, monkeypatch):
    monkeypatch.setattr(main, '_SESSION_REPLAY_ACTIVE', SimpleNamespace(is_set=lambda: False))
    monkeypatch.setattr(
        main, 'FOCUS_MODE',
        SimpleNamespace(recovery_required=False, allows_command=lambda _: True), raising=False,
    )
    main.process('room status')
    companion.status.assert_called_once()
    companion.submit.assert_not_called()
