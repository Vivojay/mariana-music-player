import subprocess
import sys
from array import array
from types import SimpleNamespace

import pytest

from mariana import playback
from mariana.models import MediaCapabilities, MediaChapter, MediaRef, MediaSource, PlaybackState

RealDecoderSession = playback.DecoderSession


class Stream:
    instances = []

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.started = self.stopped = self.closed = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class Session:
    wait_result = True
    error = None
    created = []

    def __init__(self, media, **kwargs):
        self.media = media
        self.start_at = kwargs.get("start_at", 0)
        self.position = self.start_at
        self.buffered_seconds = 1.0
        self.fingerprint_pcm = b"fingerprint"
        self.eof = False
        self.started = self.stopped = self.reset = False
        self.on_metadata = None
        self.created.append(self)

    def start(self):
        self.started = True

    def wait_for_buffer(self, *args, **kwargs):
        return self.wait_result

    def read(self, frames):
        self.position += frames / playback.SAMPLE_RATE
        return array("f", [0.25] * frames * 2).tobytes()

    def stop(self):
        self.stopped = True

    def reset_fingerprint(self):
        self.reset = True


class ImmediateThread:
    def __init__(self, target, args=(), name="", **_kwargs):
        self.target = target
        self.args = args
        self.name = name

    def start(self):
        if getattr(self.target, "__name__", "") == "stop" or self.name == "mariana-playback-complete":
            self.target(*self.args)


class Resolvers:
    def resolve(self, media, **_kwargs):
        return playback.ResolvedMedia(
            media,
            media.original_uri,
            media.original_uri,
            media.capabilities,
        )

    def classify_failure(self, error, media):
        return playback.MediaFailure(playback.FailureCode.UNAVAILABLE, media.source, str(error))


@pytest.fixture
def controller(monkeypatch):
    Session.created.clear()
    Session.wait_result = True
    Session.error = None
    Stream.instances.clear()
    monkeypatch.setattr(playback, "DecoderSession", Session)
    monkeypatch.setattr(playback.threading, "Thread", ImmediateThread)
    return playback.PlaybackController(output_factory=Stream, crossfade_seconds=2, resolvers=Resolvers())


def finite(name="track", duration=10):
    return MediaRef(MediaSource.LOCAL, f"C:/{name}.flac", title=name, duration=duration)


def live():
    return MediaRef(
        MediaSource.RADIO,
        "https://example.test/live",
        capabilities=MediaCapabilities(finite=False, live=True, seekable=False),
    )


def test_prepare_success_failure_and_play_without_media(controller, monkeypatch):
    media = finite()
    assert controller.prepare(media, probe=False) is media
    assert controller.resolved_uri.endswith("track.flac")
    probed = finite("probed")
    monkeypatch.setattr(
        playback,
        "probe_media",
        lambda value, **_kwargs: value,
    )
    assert controller.prepare(probed, probe=True) is probed
    with pytest.raises(playback.PlaybackError, match="No media"):
        playback.PlaybackController(output_factory=Stream).play()
    monkeypatch.setattr(controller.resolvers, "resolve", lambda _media: (_ for _ in ()).throw(ValueError("bad")))
    with pytest.raises(ValueError, match="bad"):
        controller.prepare(finite("bad"), probe=False)
    assert controller.snapshot().state == PlaybackState.FAILED


def test_prepare_preserves_catalog_chapters_and_projects_position(controller):
    catalog_chapters = [
        MediaChapter("Local intro", 0, 10),
        MediaChapter("Local verse", 10, 20),
    ]
    media = MediaRef(
        MediaSource.LOCAL,
        "C:/chaptered.flac",
        title="Chaptered",
        duration=20,
        chapters=catalog_chapters,
    )

    class ResolverWithDifferentChapters(Resolvers):
        def resolve(self, source, **_kwargs):
            resolved = super().resolve(source)
            resolved.metadata["chapters"] = [
                {"title": "Resolver fallback", "start_time": 0, "end_time": 20}
            ]
            return resolved

    controller.resolvers = ResolverWithDifferentChapters()
    assert controller.prepare(media, probe=False).chapters == catalog_chapters
    active = Session(media)
    active.position = 12
    controller._active = active
    assert controller.snapshot().current_chapter == catalog_chapters[1]


def test_play_prefetch_replace_and_failure(controller):
    media = controller.play(finite(), probe=False)
    assert media.title == "track"
    assert controller.snapshot().state == PlaybackState.PLAYING
    assert Stream.instances[0].started
    controller.prefetch(finite("next"), probe=False)
    first_next = controller._next
    controller.prefetch(finite("later"), probe=False)
    assert first_next.stopped
    Session.wait_result = False
    Session.error = "decode failed"
    with pytest.raises(playback.PlaybackError, match="decode failed"):
        controller.prefetch(finite("broken"), probe=False)
    assert Session.created[-1].stopped


def test_play_buffer_failure_is_typed(controller):
    Session.wait_result = False
    controller._prepared = finite()
    with pytest.raises(playback.PlaybackError, match="produced no playable"):
        controller.play()
    assert controller.snapshot().state == PlaybackState.FAILED
    assert Session.created[-1].stopped


def test_audio_callback_pause_normal_crossfade_and_promotion(controller):
    out = bytearray(8 * 4)
    controller._audio_callback(out, 4, None, "underflow")
    assert out == bytes(len(out))
    assert "underflow" in controller.snapshot().error

    active = Session(finite(duration=10))
    controller._active = active
    controller._state = PlaybackState.PAUSED
    controller._audio_callback(out, 4, None, None)
    assert out == bytes(len(out))

    controller._state = PlaybackState.PLAYING
    controller.set_volume(50)
    controller._audio_callback(out, 4, None, None)
    assert any(out)

    upcoming = Session(finite("next"))
    controller._next = upcoming
    active.position = 9
    controller._audio_callback(out, 4, None, None)
    assert controller.snapshot().state == PlaybackState.CROSSFADING
    assert upcoming.position > 0

    completed = controller._active
    completed.eof = True
    completed.buffered_seconds = 0
    seen = []
    controller.on_complete = lambda media: seen.append(media.title)
    controller._audio_callback(out, 4, None, None)
    assert controller._active is upcoming
    assert completed.stopped
    assert seen == ["track"]
    controller._promote_next(completed)
    assert controller._active is upcoming


def test_pause_resume_toggle_seek_restart_and_boundaries(controller, monkeypatch):
    with pytest.raises(playback.UnsupportedAction):
        controller.pause()
    with pytest.raises(playback.UnsupportedAction):
        controller.resume()
    controller._state = PlaybackState.PLAYING
    controller.toggle_pause()
    assert controller.snapshot().state == PlaybackState.PAUSED
    controller.toggle_pause()

    active = Session(finite(duration=5))
    controller._active = active
    controller._state = PlaybackState.PAUSED
    controller.seek(99)
    assert Session.created[-1].start_at == 5
    assert controller.snapshot().state == PlaybackState.PAUSED

    controller._active = None
    with pytest.raises(playback.UnsupportedAction, match="Nothing is loaded"):
        controller.seek(1)
    controller._active = Session(live())
    with pytest.raises(playback.UnsupportedAction, match="cannot be seeked"):
        controller.seek(1)

    calls = []
    monkeypatch.setattr(controller, "play", lambda media, probe=False: calls.append((media, probe)))
    controller.restart_live()
    assert calls[0][1] is False
    assert controller.notify_metadata_boundary("New title") == 1
    assert controller._active.reset
    controller._active = Session(finite())
    with pytest.raises(playback.UnsupportedAction):
        controller.restart_live()
    with pytest.raises(playback.UnsupportedAction):
        controller.notify_metadata_boundary()


def test_seek_clean_eof_at_safe_end_completes_without_false_failure(controller, monkeypatch):
    media = finite(duration=100)
    controller._active = Session(media)
    controller._state = PlaybackState.PLAYING
    replacement = Session(media)
    replacement.eof = True
    replacement.buffered_seconds = 0
    replacement.wait_for_buffer = lambda *_args, **_kwargs: False
    monkeypatch.setattr(controller, "_new_session", lambda *_args, **_kwargs: replacement)

    controller.seek(99.75)

    snapshot = controller.snapshot()
    assert snapshot.state == PlaybackState.IDLE
    assert snapshot.media is media
    assert snapshot.position == 100
    assert replacement.stopped


def test_seek_unbuffered_before_end_still_reports_decoder_failure(controller, monkeypatch):
    media = finite(duration=100)
    controller._active = Session(media)
    controller._state = PlaybackState.PLAYING
    replacement = Session(media)
    replacement.eof = True
    replacement.buffered_seconds = 0
    replacement.error = "seek failed"
    replacement.wait_for_buffer = lambda *_args, **_kwargs: False
    monkeypatch.setattr(controller, "_new_session", lambda *_args, **_kwargs: replacement)

    with pytest.raises(playback.PlaybackError, match="seek failed"):
        controller.seek(99.74)


def test_stop_close_recover_fingerprint_and_snapshot(controller):
    active, upcoming = Session(finite()), Session(finite("next"))
    controller._active, controller._next = active, upcoming
    assert controller.fingerprint_pcm() == b"fingerprint"
    controller._ensure_output()
    old_stream = controller._stream
    controller.recover_output()
    assert old_stream.stopped and old_stream.closed
    assert controller._stream is not old_stream
    controller.stop()
    assert active.stopped and upcoming.stopped
    assert controller.snapshot().state == PlaybackState.IDLE
    stream = controller._stream
    controller.close()
    assert stream.stopped and stream.closed
    assert controller.fingerprint_pcm() == b""


def test_natural_completion_retains_end_position_until_next_action(controller):
    completed = Session(finite("finished", duration=42))
    completed.position = 41.75
    controller._active = completed
    controller._state = PlaybackState.PLAYING

    controller._promote_next(completed)

    snapshot = controller.snapshot()
    assert snapshot.state == PlaybackState.IDLE
    assert snapshot.media.title == "finished"
    assert snapshot.position == snapshot.duration == 42

    controller.stop()
    snapshot = controller.snapshot()
    assert snapshot.position == 0
    assert snapshot.duration is None


def test_prefetched_promotion_does_not_retain_previous_end_position(controller):
    completed = Session(finite("finished", duration=42))
    upcoming = Session(finite("upcoming", duration=30))
    upcoming.position = 0.25
    controller._active = completed
    controller._next = upcoming
    controller._state = PlaybackState.PLAYING

    controller._promote_next(completed)

    snapshot = controller.snapshot()
    assert snapshot.media.title == "upcoming"
    assert snapshot.position == 0.25
    assert snapshot.duration == 30


def test_clear_prefetch_stops_only_the_upcoming_decoder(controller):
    active, upcoming = Session(finite()), Session(finite("next"))
    controller._active, controller._next = active, upcoming
    controller.clear_prefetch()
    assert controller._active is active
    assert controller._next is None
    assert upcoming.stopped and not active.stopped


def test_launch_ffplay_success_and_failure(monkeypatch):
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffplay")
    process = object()
    captured = {}
    monkeypatch.setattr(
        playback.subprocess,
        "Popen",
        lambda command, **kwargs: captured.update(command=command, kwargs=kwargs) or process,
    )
    assert playback.launch_ffplay(finite()) is process
    assert "-autoexit" in captured["command"]
    monkeypatch.setattr(playback.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(playback.PlaybackError, match="could not start"):
        playback.launch_ffplay(finite())


def test_decoder_start_http_command_errors_and_forced_kill(monkeypatch):
    commands = []
    monkeypatch.setattr(
        playback,
        "_ffmpeg_http_options",
        lambda _executable: {"reconnect_max_retries", "reconnect_delay_total_max", "respect_retry_after"},
    )

    class Pipe:
        def read(self, _size=-1):
            return b""

        def readline(self):
            return b""

    class Process:
        _handle = 1
        pid = 42

        def __init__(self):
            self.stdout = Pipe()
            self.stderr = Pipe()
            self.killed = self.terminated = False
            self.waits = 0

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

        def kill(self):
            self.killed = True

    process = Process()
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr(playback, "WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(playback.threading, "Thread", lambda **_kwargs: SimpleNamespace(start=lambda: None, is_alive=lambda: False))
    monkeypatch.setattr(
        playback.subprocess,
        "Popen",
        lambda command, **_kwargs: commands.append(command) or process,
    )
    media = MediaRef(MediaSource.URL, "https://example.test/audio", duration=10)
    session = playback.DecoderSession(media, start_at=2)
    session.start()
    assert "-reconnect" in commands[0] and "-ss" in commands[0]
    assert "-reconnect_max_retries" in commands[0] and "-respect_retry_after" in commands[0]
    session.start()
    session.stop()
    assert process.terminated and process.killed

    monkeypatch.setattr(playback.subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bad")))
    with pytest.raises(playback.PlaybackError, match="could not start"):
        playback.DecoderSession(media).start()

    process = Process()
    monkeypatch.setattr(playback.subprocess, "Popen", lambda command, **_kwargs: commands.append(command) or process)
    playback.DecoderSession(live()).start()
    assert "-icy" in commands[-1]


def test_decoder_parses_unique_icy_title_updates(monkeypatch):
    class Lines:
        def __init__(self):
            self.values = iter([b"StreamTitle: Artist - Song\n", b"icy-title='Artist - Song'\n", b""])

        def readline(self):
            return next(self.values)

    session = object.__new__(playback.DecoderSession)
    session.process = SimpleNamespace(stderr=Lines())
    session._stderr = []
    session._last_stream_title = None
    titles = []
    session.on_metadata = titles.append
    session._stderr_loop()
    assert titles == ["Artist - Song"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("StreamTitle='Artist - Song';StreamUrl='';", "Artist - Song"),
        (b"icy-title: Caf\xe9 del Mar", "Caf\u00e9 del Mar"),
        ("unrelated metadata", None),
        ("StreamTitle='';", None),
    ],
)
def test_icy_title_parser_tolerates_encodings_and_malformed_fields(value, expected):
    assert playback.parse_icy_title(value) == expected


def test_stale_prefetch_metadata_cannot_reset_active_fingerprint(controller):
    active = Session(live())
    stale = Session(live())
    controller._active = active
    controller._handle_stream_metadata(stale, "Wrong")
    assert not active.reset
    controller._handle_stream_metadata(active, "Artist - Current")
    assert active.reset
    assert active.media.title == "Artist - Current"


def test_executable_resolution_youtube_input_and_invalid_probe_metadata(monkeypatch):
    monkeypatch.setattr("mariana.toolchain.find_managed_executable", lambda name: f"managed/{name}")
    assert playback.find_executable("ffmpeg") == "managed/ffmpeg"
    monkeypatch.setattr("beta.youtube_media.stream_url", lambda url, **_kwargs: f"resolved:{url}")
    youtube = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch?v=x")
    assert playback.resolve_input(youtube).startswith("resolved:")

    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffprobe")
    captured = {}

    def run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(stdout='{"format":{"duration":"bad"},"streams":[]}')

    monkeypatch.setattr(playback.subprocess, "run", run)
    media = MediaRef(MediaSource.URL, "https://example.test/audio")
    playback.probe_media(media, source="https://cdn.test/audio", headers={"Referer": "safe"})
    assert media.duration is None and "-headers" in captured["command"]


def test_decoder_properties_timeout_filter_and_private_tunnel(monkeypatch):
    media = MediaRef(
        MediaSource.URL,
        "https://example.test/private",
        capabilities=MediaCapabilities(finite=True, seekable=True),
    )
    resolved = playback.ResolvedMedia(
        media,
        media.original_uri,
        media.original_uri,
        media.capabilities,
        headers={"Referer": "safe"},
        metadata={"credential_ref": "radio", "credential_username": "listener"},
    )
    commands = []

    class Tunnel:
        def __init__(self, *args):
            commands.append(("tunnel", args))

        def start(self):
            return "http://127.0.0.1:1234/stream"

        def close(self):
            commands.append(("closed",))

    class Pipe:
        def read(self, _size=-1):
            return b""

        def readline(self):
            return b""

    class Process:
        stdout = Pipe()
        stderr = Pipe()
        pid = 1

        def poll(self):
            return 0

    monkeypatch.setattr("mariana.credentials.ListenerAuthTunnel", Tunnel)
    monkeypatch.setattr(playback.subprocess, "Popen", lambda command, **_kwargs: commands.append(command) or Process())
    monkeypatch.setattr(playback, "_ffmpeg_http_options", lambda _executable: frozenset())
    monkeypatch.setattr(playback, "WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))

    class NoThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def is_alive(self):
            return False

    monkeypatch.setattr(playback.threading, "Thread", NoThread)
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    session = playback.DecoderSession(
        media,
        ffmpeg_bin="ffmpeg",
        resolved=resolved,
        start_at=1,
        audio_filter="volume=1",
    )
    assert session.fingerprint_pcm == b"" and session.error is None and not session.failed
    session.start()
    command = next(item for item in commands if isinstance(item, list))
    assert "-headers" in command and "-af" in command and "-ss" in command
    assert not session.wait_for_buffer(minimum_seconds=1, timeout=0)
    session.reset_fingerprint()
    session.stop()
    assert ("closed",) in commands


def test_decoder_buffer_reads_complete_frames_and_reports_position(monkeypatch):
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    session = playback.DecoderSession(finite("buffer"), start_at=2)
    session._buffer.extend(b"\x00" * (playback.BYTES_PER_FRAME * 3 + 1))

    assert session.wait_for_buffer(
        minimum_seconds=1 / playback.SAMPLE_RATE,
        timeout=0,
    )
    payload = session.read(2)
    assert len(payload) == playback.BYTES_PER_FRAME * 2
    assert session.frames_emitted == 2
    assert session.position == pytest.approx(2 + 2 / playback.SAMPLE_RATE)
    assert len(session._buffer) == playback.BYTES_PER_FRAME + 1


def test_windows_job_close_tolerates_host_api_failure(monkeypatch):
    job = object.__new__(playback.WindowsJob)
    job.handle = 123
    monkeypatch.setitem(
        sys.modules,
        "win32api",
        SimpleNamespace(CloseHandle=lambda _handle: (_ for _ in ()).throw(OSError("closed"))),
    )
    job.close()
    assert job.handle is None


def test_failed_completion_sink_isolation_and_replaygain_branches(controller, monkeypatch):
    media = finite("failed")
    failed = Session(media)
    failed.failed = True
    failed.error = "decoder broke"
    controller._active = failed
    controller._state = PlaybackState.PLAYING
    failures = []
    controller.on_failure = lambda source, error: failures.append((source, error))
    monkeypatch.setattr(playback.threading, "Thread", ImmediateThread)
    controller._finish_active(failed)
    assert controller.snapshot().state == PlaybackState.FAILED

    good = Session(finite("gain"))
    controller._active = good
    controller._next = Session(finite("next"))
    controller.configure_replaygain(enabled=True, mode="track", preamp_db=2, prevent_clipping=False)
    assert controller.replaygain_enabled and controller.replaygain_preamp_db == 2
    with pytest.raises(ValueError, match="preamp"):
        controller.configure_replaygain(preamp_db=16)

    calls = []
    remove_program = controller.add_program_sink(lambda *_args: (_ for _ in ()).throw(RuntimeError("sink")))
    remove_metadata = controller.add_metadata_sink(lambda title: calls.append(title))
    controller.add_metadata_sink(lambda _title: (_ for _ in ()).throw(RuntimeError("sink")))
    controller._publish_program(b"", 0)
    controller._publish_metadata("Title")
    remove_program()
    remove_program()
    remove_metadata()
    remove_metadata()
    assert calls == ["Title"]


def test_numpy_crossfade_empty_next_and_output_recovery(controller):
    active = Session(finite("active", duration=1))
    active.position = 0.9
    next_session = Session(finite("next"))
    next_session.read = lambda _frames: b""
    controller._active = active
    controller._next = next_session
    controller._state = PlaybackState.PLAYING
    output = __import__("numpy").zeros((8, 2), dtype="float32")
    controller._audio_callback(output, 8, None, "underflow")
    assert controller.snapshot().error.startswith("Audio output")

    stream = Stream(callback=lambda *_args: None)
    controller._stream = stream
    controller.recover_output()
    assert stream.stopped and stream.closed and controller._stream is not stream


def test_remaining_playback_branches(controller, monkeypatch, tmp_path):
    monkeypatch.setattr("mariana.toolchain.find_tool_executable", lambda name, _configured=None: f"PATH/{name}")
    assert playback.find_executable("ffmpeg", str(tmp_path / "missing")) == "PATH/ffmpeg"

    with monkeypatch.context() as scoped:
        scoped.setattr(playback.os, "name", "posix")
        job = playback.WindowsJob(SimpleNamespace())
        assert job.handle is None
        job.close()

    media = finite("metadata")

    class MetadataResolvers(Resolvers):
        def resolve(self, source, **_kwargs):
            return playback.ResolvedMedia(
                source,
                source.original_uri,
                source.original_uri,
                source.capabilities,
                metadata={"title": "Resolved title"},
            )

    controller.resolvers = MetadataResolvers()
    assert controller.prepare(media, probe=False).title == "metadata"
    untitled = MediaRef(MediaSource.LOCAL, "C:/untitled.flac", duration=1)
    assert controller.prepare(untitled, probe=False).title == "Resolved title"

    class ChapterResolvers(Resolvers):
        def resolve(self, source, **_kwargs):
            return playback.ResolvedMedia(
                source,
                source.original_uri,
                source.original_uri,
                source.capabilities,
                metadata={
                    "title": "Chaptered",
                    "artist": "Artist",
                    "categories": ["Music"],
                    "track": "Chaptered",
                    "chapters": [
                        {"title": "Intro", "start_time": 0, "end_time": 10},
                        {"title": "Verse", "start_time": 10, "end_time": 20},
                    ],
                },
            )

    controller.resolvers = ChapterResolvers()
    chaptered = MediaRef(MediaSource.YOUTUBE, "https://youtube.test/watch?v=chaptered", duration=20)
    controller.prepare(chaptered, probe=False)
    active = Session(chaptered)
    controller._active = active
    active.position = 10
    snapshot = controller.snapshot()
    assert snapshot.current_chapter == MediaChapter("Verse", 10, 20)
    assert chaptered.resolver_data["is_music"] is True

    controller._ensure_output()
    existing = controller._stream
    controller._ensure_output()
    assert controller._stream is existing

    empty = Session(finite("empty", duration=1))
    empty.read = lambda _frames: b""
    empty.position = 0.9
    controller._active = empty
    controller._next = Session(finite("next"))
    controller._state = PlaybackState.PLAYING
    output = __import__("numpy").zeros((4, 2), dtype="float32")
    controller._audio_callback(output, 4, None, None)

    stale = Session(finite("stale"))
    stale.failed = True
    controller._active = Session(finite("current"))
    controller._finish_active(stale)
    assert controller._active.media.title == "current"

    failed = Session(finite("failed-again"))
    failed.failed = True
    failed.error = None
    controller._active = failed
    controller.on_failure = None
    controller._finish_active(failed)
    assert controller.snapshot().state == PlaybackState.FAILED

    controller._active = None
    controller._watch_stop.clear()
    controller._watch_completion()
    controller.set_volume(0.5)
    controller.configure_replaygain(enabled=False)

    live_session = Session(live())
    controller._active = live_session
    controller._state = PlaybackState.PLAYING
    generation = controller.notify_metadata_boundary(None)
    assert generation > 0 and live_session.media.title is None

    controller._stream = None
    controller.recover_output()
    assert controller._stream is not None


def test_decoder_posix_shutdown_and_seek_failure(controller, monkeypatch):
    class Reader:
        def __init__(self):
            self.joined = False

        def is_alive(self):
            return True

        def join(self, timeout=None):
            self.joined = timeout == 2

    class Process:
        pid = 42

        def __init__(self):
            self.waits = 0
            self.terminated = self.killed = False

        def poll(self):
            return None

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("ffmpeg", timeout)

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    session = RealDecoderSession(finite(), ffmpeg_bin="ffmpeg")
    replacement = Session(finite("replacement", duration=None))
    active = Session(finite("seek-source", duration=None))
    signals = []
    session.process = Process()
    session._reader = Reader()
    session.job = SimpleNamespace(close=lambda: signals.append(("job", "closed")))
    with monkeypatch.context() as scoped:
        scoped.setattr(playback.os, "name", "posix")
        scoped.setattr(playback.os, "killpg", lambda pid, sig: signals.append((pid, sig)), raising=False)
        scoped.setattr(playback.signal, "SIGKILL", 9, raising=False)
        session.stop()
    assert len(signals) >= 3 and session.process is None

    replacement.wait_for_buffer = lambda *_args, **_kwargs: False
    replacement.error = "seek failed"
    controller._active = active
    controller._state = PlaybackState.PLAYING
    monkeypatch.setattr(controller, "_new_session", lambda *_args, **_kwargs: replacement)
    with pytest.raises(playback.PlaybackError, match="seek failed"):
        controller.seek(20)


def test_windows_job_none_handle_and_legacy_tool_lookup(monkeypatch, tmp_path):
    legacy = tmp_path / ".tools"
    legacy.mkdir()
    executable = legacy / ("ffmpeg.exe" if playback.os.name == "nt" else "ffmpeg")
    executable.write_bytes(b"tool")
    monkeypatch.setattr("mariana.toolchain.find_managed_executable", lambda _name: None)
    monkeypatch.setattr("mariana.paths.runtime_paths", lambda: SimpleNamespace(resource=lambda _name: legacy))
    monkeypatch.setattr("mariana.toolchain.shutil.which", lambda _name: None)
    monkeypatch.setattr("mariana.toolchain.common_tool_locations", lambda _name: ())
    assert playback.find_executable("ffmpeg") == str(executable.resolve())

    fake_job = SimpleNamespace(
        CreateJobObject=lambda *_args: None,
        JobObjectExtendedLimitInformation=1,
    )
    monkeypatch.setattr(playback, "_is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32job", fake_job)
    job = playback.WindowsJob(SimpleNamespace(_handle=1))
    assert job.handle is None


def test_windows_job_assigns_and_closes_handle_on_every_test_platform(monkeypatch):
    calls = []
    information = {"BasicLimitInformation": {"LimitFlags": 0}}
    fake_job = SimpleNamespace(
        CreateJobObject=lambda *_args: "job-handle",
        QueryInformationJobObject=lambda *_args: information,
        SetInformationJobObject=lambda *args: calls.append(("set", args)),
        AssignProcessToJobObject=lambda *args: calls.append(("assign", args)),
        JobObjectExtendedLimitInformation=1,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE=2,
    )
    fake_api = SimpleNamespace(CloseHandle=lambda handle: calls.append(("close", handle)))
    monkeypatch.setattr(playback, "_is_windows", lambda: True)
    monkeypatch.setitem(sys.modules, "win32job", fake_job)
    monkeypatch.setitem(sys.modules, "win32api", fake_api)

    job = playback.WindowsJob(SimpleNamespace(_handle=7))
    assert job.handle == "job-handle"
    assert information["BasicLimitInformation"]["LimitFlags"] == 2
    assert calls[:2] == [
        ("set", ("job-handle", 1, information)),
        ("assign", ("job-handle", 7)),
    ]

    job.close()
    assert calls[-1] == ("close", "job-handle")
    assert job.handle is None


def test_decoder_read_loop_backpressure_fingerprint_and_metadata_without_callback(monkeypatch):
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    media = finite("reader")

    class Stdout:
        def __init__(self, values):
            self.values = iter(values)

        def read(self, _size):
            return next(self.values, b"")

    session = RealDecoderSession(media, ffmpeg_bin="ffmpeg")
    session.process = SimpleNamespace(stdout=Stdout([b"\0" * playback.BYTES_PER_FRAME, b""]))
    session._read_loop()
    assert session.eof and session.buffered_seconds > 0 and session.fingerprint_pcm

    stopped = RealDecoderSession(media, ffmpeg_bin="ffmpeg", max_buffer_seconds=0)
    stopped.process = SimpleNamespace(stdout=Stdout([b"data"]))

    class Condition:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def wait(self, _timeout):
            stopped._stop.set()

        def notify_all(self):
            pass

    stopped._condition = Condition()
    stopped._read_loop()
    assert stopped.eof

    stopped._last_stream_title = None
    stopped.on_metadata = None
    stopped.process = SimpleNamespace(
        stderr=SimpleNamespace(readline=iter([b"StreamTitle='No callback';", b""]).__next__)
    )
    stopped._stderr_loop()
    assert stopped._last_stream_title == "No callback"


def test_controller_gain_filter_pause_promotion_and_leveling_branches(controller, monkeypatch):
    profile = SimpleNamespace(
        track_gain_db=-3.0,
        album_gain_db=None,
        track_peak=0.8,
        album_peak=None,
        complete_album=False,
    )
    controller.loudness_repository = SimpleNamespace(get=lambda _stable_id: profile)
    controller.replaygain_enabled = True
    assert controller._program_gain_db(finite("gain-enabled")) == pytest.approx(-3)
    controller.live_leveling = True
    assert controller._live_filter(live()).startswith("loudnorm=")

    paused = Session(finite("paused"))
    controller._active = paused
    controller._state = PlaybackState.PAUSED
    output = __import__("numpy").ones((4, 2), dtype="float32")
    controller._audio_callback(output, 4, None, None)
    assert not output.any()

    controller._active = paused
    controller._next = None
    controller.on_complete = None
    controller._promote_next(paused)
    assert controller.snapshot().state == PlaybackState.IDLE

    with pytest.raises(ValueError, match="Automation"):
        controller.set_automation_gain(-0.1)
    controller.set_automation_gain(0.5)
    assert controller.snapshot().volume == 1.0

    restarts = []
    controller._active = Session(live())
    monkeypatch.setattr(controller, "restart_live", lambda: restarts.append(True))
    controller.live_leveling = False
    controller.set_live_leveling(False)
    controller.set_live_leveling(True)
    assert restarts == [True]
