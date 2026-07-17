import json
import time

from mariana.desktop_control import DesktopControl
from mariana.models import (
    MediaCapabilities,
    MediaChapter,
    MediaRef,
    MediaSource,
    PlaybackSnapshot,
    PlaybackState,
)
from mariana.playback_status import project_playback_status


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


def projected_status(
    *,
    source=MediaSource.LOCAL,
    state=PlaybackState.PLAYING,
    title="Track",
    position=3.0,
    duration=10.0,
    finite=True,
    live=False,
    seekable=True,
    error=None,
    library_index=None,
    queue_position=None,
    queue_count=0,
):
    media = None if state == PlaybackState.IDLE and title is None else MediaRef(
        source,
        "C:/private/track.flac" if source == MediaSource.LOCAL else "https://signed.example/media?token=secret",
        title=title,
        artist="Artist",
        stable_id="track-1",
        capabilities=MediaCapabilities(finite=finite, live=live, seekable=seekable),
    )
    if media is not None and library_index is not None and source == MediaSource.LOCAL:
        media.provenance = "library"
    return project_playback_status(
        PlaybackSnapshot(
            state,
            position=position,
            duration=duration,
            error=error,
            media=media,
            current_chapter=MediaChapter("Verse", 1, 5) if media else None,
        ),
        library_index=library_index,
        queue_position=queue_position,
        queue_count=queue_count,
    )


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
    status = projected_status(library_index=3, queue_position=2, queue_count=4)
    control.start_playback_monitor(lambda: status, interval=0.001)
    control.start_playback_monitor(lambda: status, interval=0.001)
    control.start_safety_monitor(lambda: (False, ["playback"]), interval=0.001)
    wait_for(lambda: {event for event, _ in events} >= {"playback", "loudness", "update-safe"})
    playback = next(payload for event, payload in events if event == "playback")
    assert playback == status.to_dict()
    assert playback["media_id"] == "track-1"
    assert playback["position_seconds"] == 3
    assert playback["duration_seconds"] == 10
    assert playback["percent"] == 30
    assert playback["library_index"] == 3
    assert playback["queue_position"] == 2
    assert playback["queue_count"] == 4
    assert playback["chapter"] == {"title": "Verse", "start_time": 1, "end_time": 5}
    assert next(payload for event, payload in events if event == "loudness")["replaygain_db"] == 0
    assert next(payload for event, payload in events if event == "update-safe")["reasons"] == ["playback"]
    control.close()
    assert control._monitor is None
    assert control._safety_monitor is None


def test_playback_monitor_emits_safe_live_unknown_and_idle_projections(monkeypatch):
    cases = [
        projected_status(
            source=MediaSource.RADIO,
            title="Station",
            position=12,
            duration=999,
            finite=False,
            live=True,
            seekable=False,
        ),
        projected_status(duration=None),
        projected_status(state=PlaybackState.IDLE, title=None, position=0, duration=None),
    ]

    for status in cases:
        events = []
        control = DesktopControl("pipe", "secret")
        monkeypatch.setattr(
            control,
            "emit",
            lambda event, payload=None, events=events: events.append((event, payload)) or True,
        )
        control.start_playback_monitor(lambda status=status: status, interval=0.001)
        wait_for(lambda events=events: any(event == "playback" for event, _ in events))
        payload = next(payload for event, payload in events if event == "playback")
        assert payload == status.to_dict()
        control.close()

    assert cases[0].live and cases[0].percent is None and not cases[0].seekable
    assert cases[1].duration_seconds is None and cases[1].percent is None
    assert cases[2].state == "idle" and cases[2].media_id is None and cases[2].title is None


def test_playback_monitor_never_emits_raw_resolver_or_private_fields(monkeypatch):
    status = projected_status(
        source=MediaSource.URL,
        title="https://private.example/song",
        state=PlaybackState.FAILED,
        error="ffmpeg -i https://signed.example/audio --header Cookie=secret",
    )
    events = []
    control = DesktopControl("pipe", "secret")
    monkeypatch.setattr(control, "emit", lambda event, payload=None: events.append((event, payload)) or True)
    control.start_playback_monitor(lambda: status, interval=0.001)
    wait_for(lambda: any(event == "playback" for event, _ in events))
    payload = next(payload for event, payload in events if event == "playback")
    serialized = json.dumps(payload)
    assert payload["title"] == "Online media"
    assert payload["safe_error"] == "Playback failed; see logs for details"
    assert not {"media", "position", "duration", "error", "output_device", "output_backend"} & payload.keys()
    assert "private.example" not in serialized
    assert "signed.example" not in serialized
    assert "Cookie" not in serialized
    control.close()


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
