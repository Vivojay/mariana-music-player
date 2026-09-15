"""Chapter inspection and navigation through existing playback boundaries."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

import main
from mariana.command_catalog import serialize_command_catalog
from mariana.models import MediaCapabilities, MediaChapter, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback_status import PlaybackRegionProjection, project_playback_status


@pytest.mark.parametrize('command', ['chapters', 'chapters current'])
@pytest.mark.parametrize('state', [PlaybackState.PLAYING, PlaybackState.PAUSED])
def test_chapters_lists_the_complete_timeline_without_mutating_playback(monkeypatch, command, state):
    media = MediaRef(
        MediaSource.YOUTUBE,
        'https://private.test/playback?token=secret',
        title='Full album',
        chapters=[MediaChapter(f'Complete chapter {index}', index * 60, (index + 1) * 60) for index in range(8)],
    )
    snapshot = PlaybackSnapshot(state, media=media, position=125, duration=480)
    projection = project_playback_status(snapshot)
    printed = []
    tables = []
    real_table = main.tbl
    seek = Mock()

    def table(rows, **kwargs):
        tables.append(rows)
        return real_table(rows, **kwargs)

    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: snapshot)
    monkeypatch.setattr(main, '_playback_status_projection', lambda: projection)
    monkeypatch.setattr(main, 'IPrint', lambda value='', **kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, 'tbl', table)
    monkeypatch.setattr(main.vas.controller, 'seek', seek)
    monkeypatch.setattr(main, 'song_seek', seek)

    main.process(command)

    assert len(tables) == 1
    rows = tables[0]
    assert len(rows) == 8
    assert rows[2] == (3, '*', '02:00', '03:00', '01:00', 'Complete chapter 2')
    assert [row[0] for row in rows if row[1] == '*'] == [3]
    output = '\n'.join(printed)
    assert 'Full album [Youtube]' in output
    assert all(f'Complete chapter {index}' in output for index in range(8))
    assert 'private.test' not in output and 'token=' not in output
    seek.assert_not_called()
    assert snapshot.position == 125 and snapshot.state == state


@pytest.mark.parametrize('kind', ['idle', 'no-chapters', 'live'])
def test_chapters_explains_unavailable_timelines(monkeypatch, kind):
    media = None if kind == 'idle' else MediaRef(MediaSource.RADIO if kind == 'live' else MediaSource.LOCAL, 'unused')
    if kind == 'live' and media is not None:
        media.capabilities = MediaCapabilities(finite=False, live=True, seekable=False)
    snapshot = PlaybackSnapshot(PlaybackState.IDLE if kind == 'idle' else PlaybackState.PLAYING, media=media)
    monkeypatch.setattr(main, '_playback_status_projection', lambda: project_playback_status(snapshot))
    printed = []
    monkeypatch.setattr(main, 'IPrint', lambda value='', **kwargs: printed.append(str(value)))

    main.chapters_command([])

    assert printed == ['No active media.' if kind == 'idle' else 'No chapter timeline is available for the current media.']


@pytest.mark.parametrize('arguments', [['nonsense'], ['0'], ['+0'], ['goto'], ['next', '2'], ['+9999999']])
def test_chapters_rejects_arguments_instead_of_silently_seeking(monkeypatch, arguments):
    projection = Mock(side_effect=AssertionError('Invalid syntax must not inspect playback'))
    printed = []
    monkeypatch.setattr(main, '_playback_status_projection', projection)
    monkeypatch.setattr(main, 'IPrint', lambda value='', **kwargs: printed.append(str(value)))

    main.chapters_command(arguments)

    assert len(printed) == 1 and printed[0].startswith('Usage: chapters ')
    projection.assert_not_called()


def test_chapters_catalog_discloses_navigation_risk():
    command = next(row for row in serialize_command_catalog() if row['canonical'] == 'chapters')
    assert command['risk'] == 'state-changing'
    assert ('next',) in [form['tokens'] for form in command['forms']]


@pytest.fixture
def chapter_session(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, 'test-album', title='Album', chapters=[
        MediaChapter(f'Part {index + 1}', index * 60, (index + 1) * 60) for index in range(8)
    ])
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=125, duration=480)
    projection = project_playback_status(snapshot)
    printed = []
    seek = Mock()
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: snapshot)
    monkeypatch.setattr(main.vas.controller, 'seek', seek)
    monkeypatch.setattr(main, '_playback_status_projection', lambda: projection)
    monkeypatch.setattr(main, '_is_media_blocked', lambda media: False)
    monkeypatch.setattr(main.DESKTOP_CONTROL, 'emit', Mock())
    monkeypatch.setattr(main, 'IPrint', lambda value='', **kwargs: printed.append(str(value)))
    return snapshot, projection, seek, printed


@pytest.mark.parametrize(('arguments', 'target'), [
    ('next', 180), ('prev', 60), ('previous', 60), ('+', 180), ('-', 60),
    ('+3', 300), ('+ 3', 300), ('-2', 0), ('- 2', 0), ('restart', 120),
    ('first', 0), ('last', 420), ('5', 240), ('goto 5', 240),
])
@pytest.mark.parametrize('prefix', ['chapters', 'chapter', '.chapters', '.chapter'])
def test_chapter_navigation_uses_backend_seek(chapter_session, prefix, arguments, target):
    snapshot, _, seek, printed = chapter_session
    main.process(f'{prefix} {arguments}')
    seek.assert_called_once_with(float(target), origin='cli')
    assert snapshot.state == PlaybackState.PAUSED
    assert 'seeking to' in printed[-1]


@pytest.mark.parametrize('arguments', ['list', 'current', 'show', 'show 5', 'find Part 5', 'find absent', 'help'])
def test_chapter_inspection_does_not_seek(chapter_session, arguments):
    _, _, seek, printed = chapter_session
    main.chapters_command(arguments.split())
    seek.assert_not_called()
    output = '\n'.join(printed)
    if arguments in {'show 5', 'find Part 5'}:
        assert 'Part 5' in output and 'Part 4' not in output
    elif arguments == 'show':
        assert 'Part 3' in output and 'Part 4' not in output
    elif arguments == 'find absent':
        assert output == 'No matching chapters.'


@pytest.mark.parametrize('arguments', ['+6', '-3', '9', 'goto 9'])
def test_chapter_navigation_does_not_wrap(chapter_session, arguments):
    _, _, seek, printed = chapter_session
    main.chapters_command(arguments.split())
    seek.assert_not_called()
    assert 'do not wrap' in printed[-1]


def test_chapter_seek_rejects_changed_media(chapter_session, monkeypatch):
    snapshot, _, seek, printed = chapter_session
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: replace(snapshot, media=MediaRef(MediaSource.LOCAL, 'other')))
    main.chapters_command(['next'])
    seek.assert_not_called()
    assert printed == ['Current media changed; try again']


@pytest.mark.parametrize(('number', 'target'), [('1', None), ('3', 150), ('4', 180), ('5', None)])
def test_chapter_seek_respects_preferred_region(chapter_session, monkeypatch, number, target):
    _, projection, seek, printed = chapter_session
    projection = replace(projection, region=PlaybackRegionProjection(start_seconds=150, end_seconds=240))
    monkeypatch.setattr(main, '_playback_status_projection', lambda: projection)
    main.chapters_command([number])
    if target is None:
        seek.assert_not_called()
        assert printed == ['That chapter is outside the preferred play region.']
    else:
        seek.assert_called_once_with(float(target), origin='cli')


@pytest.mark.parametrize('reason', ['blocked', 'live', 'stopped', 'decoder-error'])
def test_chapter_seek_reuses_backend_refusals(chapter_session, monkeypatch, reason):
    snapshot, _, seek, printed = chapter_session
    if reason == 'blocked':
        monkeypatch.setattr(main, '_is_media_blocked', lambda media: True)
    elif reason == 'live':
        snapshot.media.capabilities.live = True
    elif reason == 'stopped':
        monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: replace(snapshot, state=PlaybackState.IDLE))
    else:
        seek.side_effect = RuntimeError('private decoder details')
    main.chapters_command(['next'])
    if reason != 'decoder-error':
        seek.assert_not_called()
    assert len(printed) == 1 and 'seeking to' not in printed[0]
    assert 'private decoder details' not in printed[0]


@pytest.mark.parametrize(('position', 'command', 'target'), [
    (0, 'prev', None), (479, 'next', None), (120, 'next', 180),
    (120, 'prev', 60), (120, 'restart', 120),
])
def test_chapter_edges_are_deterministic(chapter_session, monkeypatch, position, command, target):
    snapshot, _, seek, _ = chapter_session
    snapshot = replace(snapshot, position=position)
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: snapshot)
    monkeypatch.setattr(main, '_playback_status_projection', lambda: project_playback_status(snapshot))
    main.chapters_command([command])
    if target is None:
        seek.assert_not_called()
    else:
        seek.assert_called_once_with(float(target), origin='cli')


def test_chapter_help_works_without_active_media(monkeypatch):
    projection = Mock(side_effect=AssertionError('Help must not require active media'))
    printed = []
    monkeypatch.setattr(main, '_playback_status_projection', projection)
    monkeypatch.setattr(main, 'IPrint', lambda value='', **kwargs: printed.append(str(value)))
    main.chapters_command(['help'])
    assert any('Numbers are 1-based' in line for line in printed)
    projection.assert_not_called()
