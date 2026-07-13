import json
import time
from types import SimpleNamespace

from mariana.desktop_control import DesktopControl
from mariana.models import MediaChapter


class MemoryStream:
    def __init__(self, *, fail=False):
        self.data = b""
        self.fail = fail
        self.closed = False

    def write(self, value):
        if self.fail:
            raise OSError("disconnected")
        self.data += value

    def close(self):
        self.closed = True


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("event monitor did not report before its deadline")


def test_desktop_events_are_authenticated_and_reconnect_once(monkeypatch):
    control = DesktopControl()
    assert not control.enabled
    assert control.emit("ready") is False

    broken = MemoryStream(fail=True)
    working = MemoryStream()
    streams = iter((broken, working))
    control = DesktopControl("pipe", "secret")
    monkeypatch.setattr(control, "_connect", lambda: next(streams))
    assert control.emit("ready", {"version": "test"})
    payload = json.loads(working.data)
    assert payload["token"] == "secret"
    assert payload["event"] == "ready"
    assert broken.closed
    control.close()
    assert working.closed


def test_playback_and_safety_monitors_emit_changes_and_close_cleanly(monkeypatch):
    control = DesktopControl("pipe", "secret")
    events = []
    monkeypatch.setattr(control, "emit", lambda event, payload=None: events.append((event, payload)) or True)
    snapshot = SimpleNamespace(
        state=SimpleNamespace(value="playing"), position=3.0, duration=10.0, volume=0.5,
        muted=False, error=None, media=SimpleNamespace(
            stable_id="track-1", source=SimpleNamespace(value="local"), title="Track", artist="Artist",
        ),
        current_chapter=MediaChapter("Verse", 10, 20),
    )
    control.start_playback_monitor(lambda: snapshot, interval=0.001)
    control.start_playback_monitor(lambda: snapshot, interval=0.001)
    control.start_safety_monitor(lambda: (False, ["playback"]), interval=0.001)
    wait_for(lambda: {event for event, _ in events} >= {"playback", "loudness", "update-safe"})
    playback = next(payload for event, payload in events if event == "playback")
    assert playback["media"]["id"] == "track-1"
    assert playback["chapter"] == {"title": "Verse", "start_time": 10, "end_time": 20}
    assert next(payload for event, payload in events if event == "loudness")["replaygain_db"] == 0
    assert next(payload for event, payload in events if event == "update-safe")["reasons"] == ["playback"]
    control.close()
    assert control._monitor is None
    assert control._safety_monitor is None


def test_monitor_failures_are_reported_without_escaping(monkeypatch):
    events = []
    control = DesktopControl("pipe", "secret")
    monkeypatch.setattr(control, "emit", lambda event, payload=None: events.append((event, payload)) or True)

    def fail():
        raise RuntimeError("boom")

    control.start_playback_monitor(fail, interval=0.001)
    wait_for(lambda: any(event == "fatal-error" for event, _ in events))
    assert "Playback monitor failed" in events[-1][1]["message"]
    control.close()

    events.clear()
    control = DesktopControl("pipe", "secret")
    monkeypatch.setattr(control, "emit", lambda event, payload=None: events.append((event, payload)) or True)
    control.start_safety_monitor(fail, interval=0.001)
    wait_for(lambda: any(event == "fatal-error" for event, _ in events))
    assert "Update-safety monitor failed" in events[-1][1]["message"]
    control.close()
