"""Standalone CLI video window: spawn, follow, pause/seek/stop linkage."""

from mariana.cli_video import CliVideoWindow
from mariana.models import MediaRef, MediaSource


def test_video_resolver_import_surface():
    """Regression: the video-URI helpers live in two homes; importing either
    from the wrong place silently drops to the audio-only fallback."""
    from beta.youtube_media import resolve_stream
    from mariana.sources import is_extractor_page_url

    assert callable(resolve_stream)
    assert callable(is_extractor_page_url)
    assert is_extractor_page_url("https://www.youtube.com/watch?v=aqz-KE-bpKQ")


class FakeProcess:
    live = True

    def __init__(self, command):
        self.command = command
        self.terminated = False
        FakeProcess.live = True

    def poll(self):
        return None if FakeProcess.live else 0

    def terminate(self):
        self.terminated = True
        FakeProcess.live = False

    def wait(self, timeout=None):
        return 0

    def kill(self):
        FakeProcess.live = False


def local_media(name="clip"):
    return MediaRef(MediaSource.LOCAL, f"C:/{name}.mp4", title=name, duration=120)


def make_window(resolver=None):
    window = CliVideoWindow()
    opened = {}

    def snapshot():
        return opened.get("snapshot")

    def resolve(media):
        if resolver is not None:
            return resolver(media)
        return (f"C:/{media.title}.mp4", {})

    announced = []
    window.configure(
        snapshot_fn=snapshot,
        resolve_fn=resolve,
        ffplay_fn=lambda: "ffplay",
        announce_fn=announced.append,
    )
    return window, opened, announced


def test_open_spawns_video_only_window(monkeypatch):
    import mariana.cli_video as module

    spawned = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: spawned.append((a, k)) or FakeProcess(a[0]))

    window, opened, _announced = make_window()
    media = local_media()
    opened["snapshot"] = type("Snap", (), {"media": media, "position": 12.0, "state": "PLAYING"})()
    status = window.open()

    assert status.open is True
    assert status.follow is True
    command = spawned[0][0][0]
    assert command[0] == "ffplay"
    assert "-an" in command
    assert "-ss" in command
    window.close()


def test_close_stops_following(monkeypatch):
    import mariana.cli_video as module

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: FakeProcess(a[0]))
    window, opened, _announced = make_window()
    media = local_media()
    opened["snapshot"] = type("Snap", (), {"media": media, "position": 0.0, "state": "PLAYING"})()
    window.open()
    status = window.close()
    assert status.open is False
    assert status.follow is False
    # Follow-up commits are ignored once closed.
    window.follow(local_media("other"))
    assert window.status().follow is False


def test_audio_only_has_no_picture(monkeypatch):
    import mariana.cli_video as module

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: FakeProcess(a[0]))
    window, opened, _announced = make_window(resolver=lambda _media: (None, {}))
    media = local_media()
    opened["snapshot"] = type("Snap", (), {"media": media, "position": 0.0, "state": "PLAYING"})()
    try:
        window.open()
    except ValueError as error:
        assert "no video picture" in str(error).casefold()
    else:
        raise AssertionError("audio-only media must refuse a video window")
    assert window.status().open is False


def test_open_requires_current_media():
    window, opened, _announced = make_window()
    opened["snapshot"] = type("Snap", (), {"media": None, "position": 0.0, "state": "STOPPED"})()
    try:
        window.open()
    except ValueError as error:
        assert "no current media" in str(error).casefold()
    else:
        raise AssertionError("video open without media must fail")


def test_hidden_window_fetches_no_video_bytes(monkeypatch):
    import mariana.cli_video as module

    spawns = []
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: spawns.append(a[0]) or FakeProcess(a[0]))
    window, opened, _announced = make_window()
    first = local_media("one")
    opened["snapshot"] = type("Snap", (), {"media": first, "position": 0.0, "state": "PLAYING"})()
    window.open()
    assert len(spawns) == 1
    # Hiding terminates the process and drops follow: no purely-video bytes.
    window.close()
    assert window.status().open is False
    assert window.status().follow is False
    # Later commits must not resolve or spawn anything while hidden.
    window.follow(local_media("two"))
    assert len(spawns) == 1
    assert window.status().open is False


def test_immediate_exit_reports_ffplay_reason(monkeypatch):
    import io

    import mariana.cli_video as module

    class DeadProcess(FakeProcess):
        def __init__(self, command):
            super().__init__(command)
            self.stderr = io.BytesIO(b"Server returned 403 Forbidden (denied by filter)")

        def poll(self):
            return 1

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: DeadProcess(a[0]))
    window, opened, _announced = make_window()
    media = local_media()
    opened["snapshot"] = type("Snap", (), {"media": media, "position": 0.0, "state": "PLAYING"})()
    try:
        window.open()
    except ValueError as error:
        assert "exited immediately" in str(error).casefold()
        assert "403" in str(error)
    else:
        raise AssertionError("a dead ffplay must not report success")
    assert window.status().open is False
    assert window.last_error() is not None


def test_canonical_view_model_matches_app_surface():
    from mariana.video_view import MAX_ZOOM, MIN_ZOOM, ViewTransform, clamp_pan, crop_filter, zoom_step

    assert (MIN_ZOOM, MAX_ZOOM) == (1.0, 4.0)
    assert zoom_step(1.0, 1) == 1.25
    assert zoom_step(4.0, 1) == 4.0
    assert zoom_step(1.0, -1) == 1.0
    # Same clamp math as MiniPlayerVideo.clampPan on a unit stage.
    assert clamp_pan(10.0, 1.0, 1.0) == 0.0
    assert clamp_pan(10.0, 1.0, 2.0) == 0.5
    assert clamp_pan(-10.0, 1.0, 2.0) == -0.5
    assert crop_filter(1.0, 0.0, 0.0) is None
    assert "scale=" in (crop_filter(2.0, 0.0, 0.0) or "")
    view = ViewTransform(media_id="m", x=1.0, y=1.0, zoom=2.0)
    view.reset("n")
    assert (view.media_id, view.x, view.y, view.zoom) == ("n", 0.0, 0.0, 1.0)


def test_view_commands_reopen_anchored(monkeypatch):
    import mariana.cli_video as module

    spawns = []
    monkeypatch.setattr(
        module.subprocess, "Popen", lambda *a, **k: spawns.append(a[0]) or FakeProcess(a[0])
    )
    window, opened, _announced = make_window()
    media = local_media("zoomable")
    opened["snapshot"] = type("Snap", (), {"media": media, "position": 5.0, "state": "PLAYING"})()
    window.open()
    assert len(spawns) == 1
    state = window.set_zoom("in")
    assert state.zoom == 1.25
    assert len(spawns) == 2
    assert "-vf" in spawns[1]
    state = window.reset_view()
    assert state.zoom == 1.0
    assert "-vf" not in spawns[2]
    window.close()
