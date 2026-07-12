import threading
import time
from types import SimpleNamespace

import pytest

from mariana.models import PlaybackState
from mariana.sleep_timer import SleepAction, SleepStatus, SleepTimer, parse_duration


class Controller:
    def __init__(self, state=PlaybackState.PLAYING):
        self.state = state
        self.gains = []
        self.actions = []

    def snapshot(self):
        return SimpleNamespace(state=self.state)

    def pause(self):
        self.actions.append("pause")
        self.state = PlaybackState.PAUSED

    def stop(self):
        self.actions.append("stop")
        self.state = PlaybackState.IDLE

    def set_automation_gain(self, value):
        self.gains.append(value)


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("90s", 90), ("15m", 900), ("1h30m", 5400), ("01:02", 62), ("1:02:03", 3723)],
)
def test_parse_duration(value, seconds):
    assert parse_duration(value) == seconds


@pytest.mark.parametrize("value", ["", "0s", "1:60", "1:x", "1:2:3:4", "1m2m", "tomorrow", "1m 2s"])
def test_parse_duration_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        parse_duration(value)


def test_sleep_timer_fades_and_pauses_exactly_once():
    controller = Controller()
    finished = threading.Event()
    timer = SleepTimer(controller, on_update=lambda status: finished.set() if not status.active else None)
    timer.start(0.08, fade_seconds=0.08)
    assert finished.wait(1)
    assert controller.actions == ["pause"]
    assert controller.gains[0] == 1
    assert min(controller.gains) == 0
    assert controller.gains[-1] == 1
    assert not timer.status().active


def test_sleep_timer_can_stop_and_replacement_cancels_old_action():
    controller = Controller()
    timer = SleepTimer(controller)
    timer.start(0.03, action="pause", fade_seconds=0)
    timer.start(0.08, action=SleepAction.STOP, fade_seconds=0)
    time.sleep(0.15)
    assert controller.actions == ["stop"]


def test_cancel_restores_gain_and_inactive_expiry_is_harmless():
    controller = Controller(PlaybackState.IDLE)
    timer = SleepTimer(controller)
    timer.start(1)
    assert timer.cancel()
    assert not timer.cancel()
    assert controller.gains[-1] == 1
    timer.start(0.02)
    time.sleep(0.06)
    assert controller.actions == []


def test_perceptual_gain_curve():
    assert SleepTimer._gain(10, 10) == 1
    midpoint = SleepTimer._gain(5, 10)
    assert midpoint == pytest.approx(10 ** (-30 / 20))
    assert SleepTimer._gain(0, 10) == pytest.approx(0.001)


def test_sleep_status_and_start_validation():
    assert SleepStatus(True, action=SleepAction.STOP).to_dict()["action"] == "stop"
    timer = SleepTimer(Controller())
    with pytest.raises(ValueError, match="greater than zero"):
        timer.start(0)
    with pytest.raises(ValueError, match="negative"):
        timer.start(1, fade_seconds=-1)
    with pytest.raises(ValueError):
        timer.start(1, action="invalid")
    active = timer.start(1)
    assert active.active and timer.status().remaining_seconds > 0
    timer.cancel()

    idle = Controller(PlaybackState.IDLE)
    idle_timer = SleepTimer(idle)
    idle_timer._generation = 1
    idle_timer._expire(1, SleepAction.STOP)
    assert idle.actions == []


def test_stale_timer_work_cannot_change_playback():
    controller = Controller(PlaybackState.CROSSFADING)
    timer = SleepTimer(controller)
    timer._generation = 2
    timer._run(1, threading.Event(), time.monotonic() + 1, 1, 1, SleepAction.PAUSE)
    timer._expire(1, SleepAction.PAUSE)
    assert controller.actions == []

    timer._expire(2, SleepAction.PAUSE)
    assert controller.actions == ["pause"]


def test_generation_change_during_expiry_prevents_stale_completion():
    controller = Controller()
    timer = SleepTimer(controller)
    timer._generation = 1
    controller.stop = lambda: (controller.actions.append("stop"), setattr(timer, "_generation", 2))
    timer._expire(1, SleepAction.STOP)
    assert controller.actions == ["stop"]
    assert timer._generation == 2
