"""Recoverable transport errors must leave a working command prompt."""
from types import SimpleNamespace

import pytest

import main
from mariana.models import PlaybackSnapshot, PlaybackState
from mariana.playback import PlaybackError, UnsupportedAction


@pytest.mark.parametrize('error', [
    UnsupportedAction('Adjust speed on a playing or paused recording'),
    PlaybackError('Could not buffer the requested speed'),
])
def test_speed_rejection_leaves_next_command_available(monkeypatch, error):
    def reject(_rate):
        raise error

    snapshot = PlaybackSnapshot(PlaybackState.IDLE)
    controller = SimpleNamespace(snapshot=lambda: snapshot, set_playback_rate=reject)
    messages = []
    monkeypatch.setattr(main.vas, 'controller', controller)
    monkeypatch.setattr(main, 'IPrint', lambda message, **kw: messages.append(message))
    monkeypatch.setattr(main, 'SAY', lambda **kw: messages.append(kw['display_message']))
    assert main.process('speed 1.25') is None
    assert str(error) in messages[-1]
    assert main.process('speed status') is None
    assert 'Playback speed: 1×' in messages[-1]
