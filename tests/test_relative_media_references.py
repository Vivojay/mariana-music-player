"""Relative media targets share navigation order without navigating playback."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.navigation import (
    NavigationContext,
    NavigationEntry,
    NavigationScope,
    join_relative_references,
    parse_relative_reference,
)


@pytest.fixture
def library(monkeypatch):
    root = Path(main.__file__).parent / 'relative-reference-fixture'
    media = [MediaRef(MediaSource.LOCAL, str(root / f'{i}.mp3'), title=f'Track {i}') for i in range(3)]
    monkeypatch.setattr(main, '_sound_files', [item.original_uri for item in media])
    monkeypatch.setattr(main, '_library_media', lambda index: media[index - 1])
    monkeypatch.setattr(main, '_NAVIGATION_CONTEXT', None)
    monkeypatch.setattr(main, '_LAST_SEARCH_CONTEXT', None)
    controller = SimpleNamespace(
        snapshot=lambda: PlaybackSnapshot(state=PlaybackState.PAUSED, media=media[1], duration=90),
        play=Mock(), pause=Mock(), seek=Mock(),
    )
    monkeypatch.setattr(main, 'vas', SimpleNamespace(controller=controller))
    monkeypatch.setattr(main, 'QUEUE', SimpleNamespace(current=lambda: None, items=list))
    return media, controller


@pytest.mark.parametrize(('text', 'offset'), [('+2', 2), ('- 2', -2), ('+ 1', 1), ('-1', -1)])
def test_signed_reference_parser(text, offset):
    assert parse_relative_reference(text).offset == offset


@pytest.mark.parametrize('text', ['+0', '- 0'])
def test_zero_is_rejected(text):
    with pytest.raises(ValueError, match='positive'):
        parse_relative_reference(text)


@pytest.mark.parametrize('text', ['movie.mp3', '2', '-movie.mp3', 'https://example.test/+2', '-1.5'])
def test_other_references_are_not_reinterpreted(text):
    assert parse_relative_reference(text) is None


@pytest.mark.parametrize('command', ['path', 'open', 'play', 'block', 'unblock'])
def test_explicit_library_targets(command, library):
    media, controller = library
    assert main._expand_relative_library_target([command, '-', '1']) == [command, '1']
    assert main._expand_relative_library_target([command, '+1']) == [command, '3']
    assert main._media_from_argument('- 1') is media[0]
    controller.play.assert_not_called()
    controller.pause.assert_not_called()
    controller.seek.assert_not_called()


@pytest.mark.parametrize('tokens', [['seek', '-10'], ['volume', '-', '2'], ['fav', '+'], ['bl', '-'], ['eq', 'preamp', '-2'], ['rm', '-1']])
def test_unrelated_or_destructive_grammar_is_unchanged(tokens, library):
    assert main._expand_relative_library_target(tokens) == tokens


def test_bounds_and_missing_current(library, monkeypatch):
    _, controller = library
    with pytest.raises(ValueError, match='outside the library'):
        main._media_from_argument('+2')
    monkeypatch.setattr(controller, 'snapshot', lambda: PlaybackSnapshot(state=PlaybackState.IDLE))
    with pytest.raises(ValueError, match='currently active'):
        main._media_from_argument('-1')


def test_result_order_and_explicit_library_override(library, monkeypatch):
    media, _ = library
    context = NavigationContext(NavigationScope.RESULTS, tuple(
        NavigationEntry(item, item.stable_id, index + 1, item.title, NavigationScope.LIBRARY)
        for index, item in enumerate([media[1], media[0], media[2]])
    ), 0)
    monkeypatch.setattr(main, '_NAVIGATION_CONTEXT', context)
    assert main._media_from_argument('+1') is media[0]
    assert main._media_from_argument('+1 --in library') is media[2]
    assert main._NAVIGATION_CONTEXT is context
    assert context.cursor == 0


@pytest.mark.parametrize(('repeat', 'reference', 'expected'), [('off', '+1', 2), ('all', '+2', 0), ('one', '+1', 1)])
def test_queue_occurrence_and_repeat_policy(library, monkeypatch, repeat, reference, expected):
    media, _ = library
    items = [SimpleNamespace(queue_id=i, media=item) for i, item in enumerate(media)]
    queue = SimpleNamespace(current=lambda: items[1], items=lambda: items, state=lambda: {'repeat_mode': repeat}, jump=Mock())
    monkeypatch.setattr(main, 'QUEUE', queue)
    assert main._media_from_argument(reference) is media[expected]
    queue.jump.assert_not_called()


def test_online_relative_metadata_does_not_borrow_active_duration(library, monkeypatch):
    media, _ = library
    online = MediaRef(MediaSource.PODCAST, 'https://example.test/episode', title='Next episode')
    items = [SimpleNamespace(queue_id=1, media=media[1]), SimpleNamespace(queue_id=2, media=online)]
    monkeypatch.setattr(main, 'QUEUE', SimpleNamespace(current=lambda: items[0], items=lambda: items, state=dict))
    result, info = main._media_info(['+', '1'])
    assert result is online
    assert info['metadata']['title'] == 'Next episode'
    assert info['metadata']['duration'] is None
    assert info['state'] == 'inactive'
    with pytest.raises(ValueError, match='local library'):
        main._expand_relative_library_target(['path', '+1'])


def test_playlist_reference_list_accepts_spaced_offsets():
    assert join_relative_references(['+', '2', '-1', '4', 'a b.mp3']) == ['+2', '-1', '4', 'a b.mp3']


def test_path_dispatch_prints_target_without_playback(library, monkeypatch):
    media, controller = library
    output = []
    monkeypatch.setattr(main, 'IPrint', lambda value, **kwargs: output.append(value))
    monkeypatch.setattr(main, '_capture_session_queue', lambda: None)
    main.process('path - 1')
    assert media[0].original_uri in output
    controller.play.assert_not_called()


def test_queue_add_uses_selected_reference(library, monkeypatch):
    media, _ = library
    added = []
    def add(item, **kwargs):
        added.append(item)
        return SimpleNamespace(media=item)
    monkeypatch.setattr(main.QUEUE, 'add', add, raising=False)
    monkeypatch.setattr(main, 'RECOMMENDER', SimpleNamespace(record_event=Mock()))
    monkeypatch.setattr(main, 'IPrint', lambda *args, **kwargs: None)
    main.queue_command(['add', '-', '1'])
    assert added == [media[0]]
