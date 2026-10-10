from dataclasses import replace
from types import SimpleNamespace

import pytest

import main
from mariana.lyrics_presentation import LyricsPresentationService
from mariana.models import IdentityStatus, LyricsResult, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def lyrics_controls(monkeypatch):
    calls = []
    service = LyricsPresentationService(SimpleNamespace(
        lyrics=lambda *args, **kwargs: calls.append((args, kwargs)) or LyricsResult(
            IdentityStatus.IDENTIFIED, synced='[00:01.00]First line\n[00:03.00]Next line',
            provider='embedded',
        ),
    ))
    media = MediaRef(MediaSource.YOUTUBE, 'abcdefghijk', title='Example', duration=20)
    current = [PlaybackSnapshot(PlaybackState.PLAYING, media=media, position=2, session_id='occurrence-one')]
    monkeypatch.setattr(main, 'TIMED_LYRICS', service)
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: current[0])
    monkeypatch.setattr(main, '_ensure_media_playable', lambda _media: None)
    monkeypatch.setattr(main.DESKTOP_CONTROL, 'emit', lambda *_args: True)
    monkeypatch.setattr(main, 'IPrint', lambda *_args, **_kwargs: None)
    yield service, current, calls
    service.close()


def test_desktop_lyrics_request_is_explicit_and_bound_to_active_identity(lyrics_controls):
    service, current, calls = lyrics_controls
    assert main._desktop_control_request('lyrics.status', {}) == {'ok': True}
    assert calls == []
    assert not main._desktop_control_request('lyrics.request', {'media_id': 'stale', 'refresh': False})['ok']
    identity = current[0].media.stable_id
    assert main._desktop_control_request('lyrics.request', {'media_id': identity, 'refresh': False})['ok']
    assert service.wait_for_idle(timeout=2)
    assert service.projection()['active']['text'] == 'First line'
    assert len(calls) == 1
    assert current[0].position == 2
    assert current[0].state == PlaybackState.PLAYING


@pytest.mark.parametrize('value', [True, float('nan'), float('inf'), 60001, -60001, '20'])
def test_desktop_lyrics_offset_rejects_invalid_values(lyrics_controls, value):
    _, current, _ = lyrics_controls
    assert not main._desktop_control_request('lyrics.offset', {
        'media_id': current[0].media.stable_id, 'offset_ms': value,
    })['ok']


def test_cli_status_tracks_pause_seek_and_same_media_restart(lyrics_controls):
    service, current, calls = lyrics_controls
    main.timed_lyrics_command(['current'])
    assert service.wait_for_idle(timeout=2)
    assert main.timed_lyrics_command(['status'])['active']['text'] == 'First line'
    current[0] = replace(current[0], state=PlaybackState.PAUSED, position=4)
    assert main.timed_lyrics_command(['status'])['active']['text'] == 'Next line'
    assert main.timed_lyrics_command(['offset', '2000'])['active']['text'] == 'First line'
    assert len(calls) == 1
    current[0] = replace(current[0], session_id='occurrence-two', position=0)
    state = main.timed_lyrics_command(['status'])
    assert state['active'] is None and state['offset_ms'] == 0
    assert len(calls) == 1


def test_lyrics_controls_reject_unknown_fields_and_offsets_do_not_seek(lyrics_controls, monkeypatch):
    _, current, calls = lyrics_controls
    monkeypatch.setattr(main.vas.controller, 'seek', lambda *_args, **_kwargs: pytest.fail('lyrics must not seek'))
    identity = current[0].media.stable_id
    assert not main._desktop_control_request('lyrics.request', {
        'media_id': identity, 'refresh': False, 'url': 'https://example.invalid/private',
    })['ok']
    assert main._desktop_control_request('lyrics.offset', {'media_id': identity, 'offset_ms': -250})['ok']
    assert calls == []
