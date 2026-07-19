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
        def __init__(self):
            self.duration = 120.0
            self.seeks = []
            self.seek_error = False

        def snapshot(self):
            return PlaybackSnapshot(state['value'], duration=self.duration, media=media)

        def seek(self, target):
            if self.seek_error:
                raise RuntimeError('private transport details')
            self.seeks.append(target)

    def toggle(*, softtoggle):
        assert softtoggle is False
        state['value'] = (
            PlaybackState.PLAYING
            if state['value'] == PlaybackState.PAUSED
            else PlaybackState.PAUSED
        )

    controller = Controller()
    monkeypatch.setattr(main.vas, 'controller', controller)
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
    return media, state, emitted, controller


def test_desktop_play_and_pause_are_state_and_identity_bound(desktop_playback):
    _media, state, emitted, _controller = desktop_playback

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
    _media, _state, _emitted, _controller = desktop_playback
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
    media, state, _emitted, _controller = desktop_playback

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


def test_desktop_seek_is_identity_bound_clamped_and_republishes(desktop_playback):
    _media, state, emitted, controller = desktop_playback

    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 45.5}
    ) == {'ok': True}
    state['value'] = PlaybackState.PAUSED
    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 999}
    ) == {'ok': True}

    assert controller.seeks == [45.5, 120.0]
    assert [event for event, _payload in emitted] == ['playback', 'playback']


@pytest.mark.parametrize('target', [True, '10', -1, float('nan'), float('inf')])
def test_desktop_seek_refuses_invalid_targets(desktop_playback, target):
    _media, _state, _emitted, controller = desktop_playback

    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': target}
    ) == {'ok': False, 'error': 'Seek target is invalid'}
    assert controller.seeks == []


def test_desktop_seek_refuses_stale_blocked_and_ineligible_media(desktop_playback, monkeypatch):
    media, state, _emitted, controller = desktop_playback

    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'stale', 'target_seconds': 10}
    ) == {'ok': False, 'error': 'Current media changed; try again'}
    monkeypatch.setattr(main, '_is_media_blocked', lambda selected: selected is media)
    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 10}
    ) == {'ok': False, 'error': 'Playback is blocked for this media'}
    monkeypatch.setattr(main, '_is_media_blocked', lambda _media: False)
    state['value'] = PlaybackState.BUFFERING
    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 10}
    ) == {'ok': False, 'error': 'Seek is unavailable in the current state'}
    state['value'] = PlaybackState.PLAYING
    media.capabilities.seekable = False
    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 10}
    ) == {'ok': False, 'error': 'Current media is not seekable'}
    assert controller.seeks == []


def test_desktop_seek_refuses_missing_duration_and_live_media(desktop_playback):
    media, _state, _emitted, controller = desktop_playback

    controller.duration = None
    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 10}
    ) == {'ok': False, 'error': 'Current media is not seekable'}
    controller.duration = 120
    media.capabilities.live = True
    media.capabilities.finite = False
    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 10}
    ) == {'ok': False, 'error': 'Current media is not seekable'}
    assert controller.seeks == []


def test_desktop_seek_sanitizes_controller_failures(desktop_playback):
    _media, _state, _emitted, controller = desktop_playback
    controller.seek_error = True

    assert main._desktop_control_request(
        'playback.seek', {'media_id': 'track-1', 'target_seconds': 10}
    ) == {'ok': False, 'error': 'Could not seek playback'}
