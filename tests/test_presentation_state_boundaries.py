"""Presentation failures must preserve preferences and current-media ownership."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.artwork import ArtworkProjection, ArtworkState
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def presentation(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, 'C:/fixture/song.flac', stable_id='current')
    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=12)
    emitted, opened, printed = Mock(), Mock(), Mock()
    monkeypatch.setattr(main.vas, 'controller', SimpleNamespace(snapshot=lambda: snapshot))
    monkeypatch.setattr(main, 'DESKTOP_CONTROL', SimpleNamespace(emit=emitted))
    monkeypatch.setattr(main, 'open_path', opened)
    monkeypatch.setattr(main, 'IPrint', printed)
    return snapshot, emitted, opened, printed


@pytest.mark.parametrize('original', [{}, {'desktop': 'invalid'}, {'desktop': {'extra': True}},
                                      {'desktop': {'close button': 'tray', 'extra': True}}])
def test_close_preference_failed_save_restores_exact_existing_configuration(presentation, monkeypatch, original):
    settings = deepcopy(original)
    monkeypatch.setattr(main, 'SETTINGS', settings)
    monkeypatch.setattr(main, 'save_user_settings', Mock(side_effect=OSError('read only')))
    with pytest.raises(OSError, match='read only'):
        main.desktop_command(['close', 'quit'])
    assert settings == original
    presentation[1].assert_not_called()


@pytest.mark.parametrize('arguments', [[], ['close'], ['close', 'current']])
def test_close_preference_inspection_does_not_write_settings(presentation, monkeypatch, arguments):
    save = Mock()
    monkeypatch.setattr(main, 'SETTINGS', {'desktop': {'close button': 'quit'}})
    monkeypatch.setattr(main, 'save_user_settings', save)
    assert main.desktop_command(arguments) == 'quit'
    save.assert_not_called()
    presentation[1].assert_not_called()


@pytest.mark.parametrize('arguments', [['quit'], ['close', 'quit', 'extra']])
def test_close_preference_invalid_shape_has_no_effect(presentation, monkeypatch, arguments):
    save = Mock()
    monkeypatch.setattr(main, 'save_user_settings', save)
    with pytest.raises(ValueError, match='Usage'):
        main.desktop_command(arguments)
    save.assert_not_called()
    presentation[1].assert_not_called()


def test_new_banner_preference_is_not_kept_after_failed_persistence(presentation, monkeypatch):
    settings = {'show banner': False}
    monkeypatch.setattr(main, 'SETTINGS', settings)
    monkeypatch.setattr(main, 'save_user_settings', Mock(side_effect=OSError('read only')))
    with pytest.raises(OSError):
        main.banner_command(['occasions', 'on'])
    assert settings == {'show banner': False}


@pytest.mark.parametrize('arguments', [['help'], ['show'], ['country', 'detect', '--unexpected'], ['unknown']])
def test_banner_help_and_invalid_controls_never_fetch_location_or_persist(presentation, monkeypatch, arguments):
    detect, save, show = Mock(), Mock(), Mock()
    monkeypatch.setattr(main, 'detect_country', detect)
    monkeypatch.setattr(main, 'save_user_settings', save)
    monkeypatch.setattr(main, 'showbanner', show)
    if arguments[0] in {'help', 'show'}:
        main.banner_command(arguments)
        assert show.call_count == int(arguments == ['show'])
    else:
        with pytest.raises(ValueError, match='Usage'):
            main.banner_command(arguments)
        show.assert_not_called()
    detect.assert_not_called()
    save.assert_not_called()


@pytest.mark.parametrize('moment', ['no-media', 'before-fetch', 'after-fetch'])
def test_artwork_refuses_missing_media_and_stale_results_without_display(presentation, monkeypatch, moment):
    snapshot, emitted, opened, _printed = presentation
    current = ArtworkProjection(1, 'current', ArtworkState.READY, False)
    stale = replace(current, media_id='previous')
    artwork = SimpleNamespace(projection=Mock(side_effect=[stale, current] if moment == 'before-fetch'
                                             else [current, stale]), fetch_current=Mock(return_value=1))
    monkeypatch.setattr(main, 'ARTWORK', artwork)
    if moment == 'no-media':
        monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: replace(snapshot, media=None))
    with pytest.raises(ValueError, match=r'No media|Current media changed'):
        main._show_current_artwork(fetch=True, desktop=True, expected_media_id='current')
    assert artwork.fetch_current.call_count == int(moment == 'after-fetch')
    emitted.assert_not_called()
    opened.assert_not_called()


@pytest.mark.parametrize('fetch', [False, True])
@pytest.mark.parametrize('state', [ArtworkState.LOADING, ArtworkState.UNAVAILABLE])
def test_cli_artwork_wait_is_bounded_and_never_opens_an_unavailable_image(presentation, monkeypatch, fetch, state):
    projection = ArtworkProjection(1, 'current', ArtworkState.LOADING, False)
    finished = replace(projection, state=state)
    artwork = SimpleNamespace(projection=Mock(return_value=projection), fetch_current=Mock(return_value=1),
                              wait_for_idle=Mock(return_value=finished), current_image=Mock(return_value=None))
    monkeypatch.setattr(main, 'ARTWORK', artwork)
    if state == ArtworkState.LOADING:
        assert main._show_current_artwork(fetch=fetch, desktop=False) is finished
        assert 'still loading' in presentation[3].call_args.args[0]
    else:
        with pytest.raises(ValueError, match='No supported artwork'):
            main._show_current_artwork(fetch=fetch, desktop=False)
    artwork.wait_for_idle.assert_called_once_with(timeout=12.0 if fetch else 2.0)
    assert artwork.fetch_current.call_count == int(fetch)
    presentation[1].assert_not_called()
    presentation[2].assert_not_called()
    assert presentation[0].position == 12 and presentation[0].state == PlaybackState.PAUSED
