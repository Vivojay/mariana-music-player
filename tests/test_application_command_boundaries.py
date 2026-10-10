"""User command errors must not trigger unrelated playback, storage or network work."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.librivox import LibrivoxError
from mariana.models import PlaybackSnapshot, PlaybackState
from mariana.session_recipes import RecipeError
from tests.test_librivox_cli import librivox_cli as librivox_cli
from tests.test_session_cli import session_cli as session_cli


@pytest.mark.parametrize('arguments', [
    ['help', 'extra'], ['status', 'extra'], ['show'], ['show', '1', 'extra'],
    ['chapters'], ['play'], ['play', '1', '2', 'extra'], ['queue'],
    ['queue', '1', '2', 'extra'], ['current', 'extra'], ['goto'], ['goto', '1', 'extra'],
    ['next', '1', 'extra'], ['previous', '1', 'extra'], ['first', 'extra'], ['last', 'extra'],
    ['restart', 'extra'], ['download', '1', '--yes', '--yes'], ['download'],
    ['rss'], ['open'], ['open', '1', 'text', 'extra'], ['unknown'],
])
def test_audiobook_invalid_command_arity_has_no_catalog_or_playback_side_effects(librivox_cli, monkeypatch, arguments):
    _book, client, _catalog, queue, _output, events = librivox_cli
    lookup, play = Mock(), Mock()
    monkeypatch.setattr(main, '_resolve_librivox_reference', lookup)
    monkeypatch.setattr(main, '_play_librivox_book_section', play)
    with pytest.raises(LibrivoxError):
        main.librivox_command(arguments)
    lookup.assert_not_called()
    play.assert_not_called()
    assert not client.searches and not queue.items() and not events


@pytest.mark.parametrize('arguments', [[], ['help'], ['?']])
def test_audiobook_help_is_available_without_network(librivox_cli, arguments):
    _book, client, _catalog, _queue, output, _events = librivox_cli
    assert main.librivox_command(arguments) is None
    assert 'librivox play' in '\n'.join(output)
    assert not client.searches


def test_audiobook_play_all_points_to_explicit_queue_operation(librivox_cli):
    book, _client, catalog, queue, _output, _events = librivox_cli
    catalog.results = (book,)
    with pytest.raises(LibrivoxError, match='librivox queue'):
        main.librivox_command(['play', '1', 'all'])
    assert not queue.items()


@pytest.mark.parametrize('case', ['unknown-target', 'missing-link', 'browser-refused'])
def test_audiobook_provider_links_report_missing_or_unopenable_destinations(librivox_cli, monkeypatch, case):
    book, client, catalog, _queue, _output, _events = librivox_cli
    selected = replace(book, text_url=None) if case == 'missing-link' else book
    catalog.results = (selected,)
    client.book_result = selected
    browser = Mock(return_value=False)
    monkeypatch.setattr(main.webbrowser, 'open', browser)
    target = 'untrusted' if case == 'unknown-target' else 'text'
    with pytest.raises(LibrivoxError, match=r'link must|has no|Could not open'):
        main.librivox_command(['open', '1', target])
    if case != 'browser-refused':
        browser.assert_not_called()
    else:
        browser.assert_called_once_with(book.text_url)


@pytest.mark.parametrize('case', ['seek-failed', 'queued', 'removed'])
def test_audiobook_restart_respects_actual_active_or_queued_source(librivox_cli, monkeypatch, case):
    book, _client, catalog, queue, _output, _events = librivox_cli
    media = catalog.media(book, book.sections[0])
    if case == 'queued':
        queue.add(media)
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media if case == 'seek-failed' else None)
    monkeypatch.setattr(main, '_current_librivox_media', lambda: (media, snapshot))
    seek, play = Mock(side_effect=RuntimeError('decoder unavailable')), Mock(return_value=media)
    monkeypatch.setattr(main.vas.controller, 'seek', seek)
    monkeypatch.setattr(main, '_play_librivox_queue_item', play)
    if case == 'queued':
        assert main.librivox_command(['restart']) is media
        play.assert_called_once_with(queue.items()[0])
        seek.assert_not_called()
    else:
        with pytest.raises(LibrivoxError, match=r'Could not restart|no longer queued'):
            main.librivox_command(['restart'])
        play.assert_not_called()


@pytest.mark.parametrize('arguments', [
    ['record'], ['record', 'one', 'two'], ['record', 'one', '--yes'], ['play'], ['unknown'],
])
def test_recipe_command_shape_is_checked_before_starting_service(session_cli, arguments):
    service, _media, _queue = session_cli
    with pytest.raises(RecipeError, match='Usage'):
        main.session_command(arguments)
    service.start.assert_not_called()
    service.replay.assert_not_called()


@pytest.mark.parametrize('owner', ['sleep', 'station', 'focus', 'loop', 'stems'])
@pytest.mark.parametrize('operation', ['record', 'play'])
def test_recipe_refuses_competing_owners_before_touching_queue_or_playback(session_cli, monkeypatch, owner, operation):
    service, _media, _queue = session_cli
    if owner == 'sleep':
        monkeypatch.setattr(main.SLEEP_TIMER, 'status', lambda: SimpleNamespace(active=True))
    elif owner == 'station':
        monkeypatch.setattr(main.STATION, 'session', lambda: object())
    elif owner == 'focus':
        main.FOCUS_MODE.state.active = True
    elif owner == 'loop':
        main._LOOP_OVERRIDE['mode'] = 'once'
    else:
        main._STEM_SELECTION['names'] = ('vocals',)
    with pytest.raises(RecipeError, match=r'Stop|Disable'):
        main.session_command([operation, 'evening'])
    service.start.assert_not_called()
    service.replay.assert_not_called()


@pytest.mark.parametrize('state', [PlaybackState.BUFFERING, PlaybackState.FAILED])
def test_recipe_record_waits_for_authoritative_ready_state(session_cli, monkeypatch, state):
    service, media, _queue = session_cli
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: PlaybackSnapshot(state, media=media))
    with pytest.raises(RecipeError, match='Wait until playback is ready'):
        main.session_command(['record', 'evening'])
    service.start.assert_not_called()


@pytest.mark.parametrize('replaying', [False, True])
def test_recipe_stop_routes_to_the_current_owner_and_reports_flush(session_cli, replaying):
    service, _media, _queue = session_cli
    service.status.return_value = {'state': 'recording', 'replay_active': replaying}
    service.stop.return_value = False
    service.stop_replay.return_value = True
    result = main.session_command(['stop'])
    assert result['flushed'] is replaying
    (service.stop_replay if replaying else service.stop).assert_called_once_with()
    (service.stop if replaying else service.stop_replay).assert_not_called()


def test_recipe_inspection_is_read_only(session_cli):
    service, _media, _queue = session_cli
    service.inspect.return_value = {'complete': False}
    assert main.session_command(['inspect', 'evening']) == {'complete': False}
    service.inspect.assert_called_once_with('evening')
    service.start.assert_not_called()
    service.replay.assert_not_called()
