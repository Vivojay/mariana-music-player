from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState


@pytest.fixture
def desktop_playback(monkeypatch):
    media = MediaRef(MediaSource.YOUTUBE, 'youtube:test', stable_id='track-1', title='Track')
    state = {'value': PlaybackState.PLAYING}
    emitted = []

    class Controller:
        def snapshot(self):
            return PlaybackSnapshot(state['value'], media=media)

    def toggle(*, softtoggle):
        assert softtoggle is False
        state['value'] = (
            PlaybackState.PLAYING
            if state['value'] == PlaybackState.PAUSED
            else PlaybackState.PAUSED
        )

    monkeypatch.setattr(main.vas, 'controller', Controller())
    monkeypatch.setattr(main, 'playpausetoggle', toggle)
    monkeypatch.setattr(main, '_is_media_blocked', lambda _media: False)
    monkeypatch.setattr(
        main,
        '_playback_status_projection',
        lambda: SimpleNamespace(to_dict=lambda: {'state': state['value'].value}),
    )
    monkeypatch.setattr(
        main,
        'DESKTOP_CONTROL',
        SimpleNamespace(emit=lambda event, payload=None: emitted.append((event, payload)) or True),
    )
    return media, state, emitted


def test_desktop_play_and_pause_are_state_and_identity_bound(desktop_playback):
    _media, state, emitted = desktop_playback

    assert main._desktop_control_request('playback.pause', {'media_id': 'track-1'}) == {'ok': True}
    assert state['value'] == PlaybackState.PAUSED
    assert main._desktop_control_request('playback.play', {'media_id': 'track-1'}) == {'ok': True}
    assert state['value'] == PlaybackState.PLAYING
    assert [event for event, _payload in emitted] == ['playback', 'playback']

    assert main._desktop_control_request('playback.play', {'media_id': 'track-1'}) == {
        'ok': False,
        'error': 'Play is unavailable in the current state',
    }
    assert main._desktop_control_request('playback.pause', {'media_id': 'stale'}) == {
        'ok': False,
        'error': 'Current media changed; try again',
    }


def test_desktop_previous_and_next_use_the_shared_queue_step(desktop_playback, monkeypatch):
    operations = []
    monkeypatch.setattr(
        main,
        '_step_queue_playback',
        lambda operation: operations.append(operation) or SimpleNamespace(queue_id=1),
    )

    assert main._desktop_control_request('playback.previous', {'media_id': 'track-1'}) == {'ok': True}
    assert main._desktop_control_request('playback.next', {'media_id': 'track-1'}) == {'ok': True}
    assert operations == ['previous', 'next']


def test_desktop_playback_controls_refuse_invalid_blocked_and_unavailable_targets(
    desktop_playback,
    monkeypatch,
):
    media, state, _emitted = desktop_playback

    assert main._desktop_control_request('playback.next', {}) == {
        'ok': False,
        'error': 'Playback target is unavailable',
    }
    monkeypatch.setattr(main, '_is_media_blocked', lambda selected: selected is media)
    assert main._desktop_control_request('playback.next', {'media_id': 'track-1'}) == {
        'ok': False,
        'error': 'Playback is blocked for this media',
    }
    monkeypatch.setattr(main, '_is_media_blocked', lambda _media: False)
    monkeypatch.setattr(main, '_step_queue_playback', lambda _operation: None)
    assert main._desktop_control_request('playback.next', {'media_id': 'track-1'}) == {
        'ok': False,
        'error': 'No next queue item is available',
    }
    state['value'] = PlaybackState.BUFFERING
    assert main._desktop_control_request('playback.pause', {'media_id': 'track-1'}) == {
        'ok': False,
        'error': 'Pause is unavailable in the current state',
    }
