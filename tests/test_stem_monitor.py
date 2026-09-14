import struct
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import mariana.playback as playback
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackState
from mariana.sources import ResolvedMedia


class FakeDecoder:
    def __init__(self, media, *, start_at=0, input_sources=(), program_gain_db=0, **_kwargs):
        self.media = media
        self.start_at = float(start_at)
        self.frames_emitted = 0
        self.input_sources = tuple(input_sources)
        self.program_gain_db = program_gain_db
        self.program_gain = 10 ** (program_gain_db / 20)
        self.buffered_seconds = 8.0
        self.eof = False
        self.stopped = False
        self.value = 0.75 if input_sources else 0.25

    @property
    def position(self):
        return self.start_at + self.frames_emitted / playback.SAMPLE_RATE

    @property
    def error(self):
        return None

    def start(self):
        return None

    def wait_for_buffer(self, **_kwargs):
        return True

    def read(self, frames):
        self.frames_emitted += frames
        return np.full((frames, playback.CHANNELS), self.value, dtype=np.float32).tobytes()

    def stop(self):
        self.stopped = True


@pytest.fixture
def monitor(monkeypatch, tmp_path):
    monkeypatch.setattr(playback, "DecoderSession", FakeDecoder)
    controller = playback.PlaybackController(output_factory=lambda **_: None)
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "song.wav"), duration=60)
    controller._active = FakeDecoder(media, start_at=12)
    controller._state = PlaybackState.PLAYING
    stem = tmp_path / "vocals.wav"
    stem.write_bytes(b"prepared")
    yield controller, media, stem
    controller.stop()


def test_stem_analysis_uses_private_current_transport_without_relabeling_identity(monitor):
    controller, media, _ = monitor
    assert controller.stem_analysis_source(media.stable_id) == (media.original_uri, {})
    media.source = MediaSource.YOUTUBE
    controller._resolved = ResolvedMedia(media=media, canonical_uri=media.original_uri,
                                         playback_uri='https://example.test/private?token=secret',
                                         capabilities=media.capabilities,
                                         headers={'Authorization': 'Bearer secret'})
    source, headers = controller.stem_analysis_source(media.stable_id)
    assert source.endswith('token=secret')
    headers.clear()
    assert controller._resolved.headers == {'Authorization': 'Bearer secret'}
    assert controller.snapshot().media is media


@pytest.mark.parametrize('case', ['changed', 'idle', 'live', 'unbounded', 'unresolved-online'])
def test_stem_analysis_refuses_unavailable_or_unbounded_inputs_without_playback_mutation(monitor, case):
    controller, media, _ = monitor
    identifier = media.stable_id
    if case == 'changed':
        identifier = 'another-item'
    elif case == 'idle':
        controller._active = None
    elif case == 'live':
        media.capabilities = MediaCapabilities(finite=False, live=True)
    elif case == 'unbounded':
        media.capabilities = MediaCapabilities(finite=False, live=False)
    else:
        media.source = MediaSource.YOUTUBE
    active = controller._active
    with pytest.raises(playback.UnsupportedAction):
        controller.stem_analysis_source(identifier)
    assert controller._active is active


@pytest.mark.parametrize('case', ['duplicate', 'directory', 'changed', 'no-active', 'buffering', 'live', 'unbounded'])
def test_stem_monitor_rejects_invalid_selection_before_starting_replacement(monitor, case, monkeypatch):
    controller, media, stem = monitor
    sources = [stem]
    identifier = media.stable_id
    if case == 'duplicate':
        sources.append(stem)
    elif case == 'directory':
        sources = [stem.parent]
    elif case == 'changed':
        identifier = 'another-item'
    elif case == 'no-active':
        controller._active = None
    elif case == 'buffering':
        controller._state = PlaybackState.BUFFERING
    elif case == 'live':
        media.capabilities = MediaCapabilities(live=True, finite=False)
    else:
        media.capabilities = MediaCapabilities(finite=False)
    monkeypatch.setattr(playback, 'DecoderSession', lambda *_args, **_kwargs: pytest.fail('unexpected decoder'))
    active = controller._active
    with pytest.raises(playback.UnsupportedAction):
        controller.configure_stem_monitor(identifier, sources)
    assert controller._active is active
    assert not controller.stem_monitor_status()['active']


def test_repeated_stem_selection_is_idempotent_and_paused_original_restores_without_pcm(monitor):
    controller, media, stem = monitor
    controller._state = PlaybackState.PAUSED
    controller.configure_stem_monitor(media.stable_id, [stem])
    prepared = controller._stem_session
    controller.configure_stem_monitor(media.stable_id, [stem])
    assert controller._stem_session is prepared
    controller.configure_stem_monitor(media.stable_id, [])
    assert controller._stem_session is None and controller._stem_previous is None
    assert controller.snapshot().state is PlaybackState.PAUSED
    assert controller.snapshot().position == 12
    output = np.ones((1024, playback.CHANNELS), dtype=np.float32)
    controller._audio_callback(output, 1024, None, None)
    assert not output.any()


@pytest.mark.parametrize('reason', ['no-audio', 'changed-media', 'too-far-behind'])
def test_unsuccessful_stem_preparation_closes_candidate_and_preserves_original(monitor, monkeypatch, reason):
    controller, media, stem = monitor
    active = controller._active
    candidates = []

    class Candidate(FakeDecoder):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            candidates.append(self)
            if reason == 'too-far-behind':
                self.buffered_seconds = 0

        def wait_for_buffer(self, **_kwargs):
            if reason == 'changed-media':
                controller._active = FakeDecoder(MediaRef(MediaSource.LOCAL, 'other.wav', duration=30))
            return reason != 'no-audio'

    monkeypatch.setattr(playback, 'DecoderSession', Candidate)
    if reason == 'too-far-behind':
        ticks = iter([0.0, 6.0])
        monkeypatch.setattr(playback.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(playback.PlaybackError):
        controller.configure_stem_monitor(media.stable_id, [stem])
    assert len(candidates) == 1 and candidates[0].stopped
    assert not controller.stem_monitor_status()['active']
    if reason != 'changed-media':
        assert controller._active is active
        assert controller.snapshot().position == 12


def test_replacing_stems_retires_old_transition_without_stopping_program(monitor, monkeypatch, tmp_path):
    controller, media, first = monitor
    second = tmp_path / 'drums.wav'
    third = tmp_path / 'bass.wav'
    second.write_bytes(b'prepared')
    third.write_bytes(b'prepared')
    retired = []
    monkeypatch.setattr(controller, '_stop_stem_sessions_async', lambda *values: retired.extend(values))
    controller.configure_stem_monitor(media.stable_id, [first])
    original_stems = controller._stem_session
    controller.configure_stem_monitor(media.stable_id, [second])
    next_stems = controller._stem_session
    controller.configure_stem_monitor(media.stable_id, [])
    assert controller._stem_previous is next_stems
    assert original_stems in retired
    controller.configure_stem_monitor(media.stable_id, [third])
    assert controller.snapshot().media is media
    assert controller.snapshot().position == 12


def test_exhausted_stem_monitor_falls_back_to_original_without_changing_program_position(monitor, monkeypatch):
    controller, media, stem = monitor
    controller.configure_stem_monitor(media.stable_id, [stem])
    current = controller._stem_session
    monkeypatch.setattr(current, 'read', lambda _frames: b'')
    retired = []
    monkeypatch.setattr(controller, '_stop_stem_sessions_async', lambda *values: retired.extend(values))
    original = np.full((1024, playback.CHANNELS), .25, dtype=np.float32)
    output = controller._apply_stem_monitor(original, 1024, current, None, 0)
    assert np.array_equal(output, original)
    assert current in retired
    assert controller.stem_monitor_status()['active'] is False
    assert controller.snapshot().position == 12


def test_retired_underflow_cannot_clear_a_newly_selected_stem_monitor(monitor, monkeypatch):
    controller, media, stem = monitor
    controller.configure_stem_monitor(media.stable_id, [stem])
    old = controller._stem_session
    new = FakeDecoder(media, start_at=12, input_sources=[str(stem)])

    def retiring_read(_frames):
        controller._stem_session = new
        return b''

    monkeypatch.setattr(old, 'read', retiring_read)
    original = np.full((1024, playback.CHANNELS), .25, dtype=np.float32)
    output = controller._apply_stem_monitor(original, 1024, old, None, 0)
    assert np.array_equal(output, original)
    assert controller._stem_session is new and not new.stopped
    assert controller.stem_monitor_status()['active'] is True
    assert controller.snapshot().position == 12


def test_exhausted_previous_stem_uses_original_during_smooth_new_selection(monitor, monkeypatch):
    controller, media, _ = monitor
    current = FakeDecoder(media, input_sources=['new'])
    previous = FakeDecoder(media, input_sources=['old'])
    monkeypatch.setattr(previous, 'read', lambda _frames: b'')
    controller._stem_session = current
    controller._stem_previous = previous
    frames = controller._stem_transition_total
    original = np.full((frames, playback.CHANNELS), .25, dtype=np.float32)
    output = controller._apply_stem_monitor(original, frames, current, previous, frames)
    assert np.allclose(output[0], .25)
    assert np.allclose(output[-1], .75, atol=.001)
    assert controller._stem_session is current and controller._stem_previous is None
    assert controller.snapshot().position == 12


def test_stem_monitor_changes_only_local_pcm_and_preserves_program_feed(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(playback, "DecoderSession", FakeDecoder)
    controller = playback.PlaybackController(output_factory=lambda **_kwargs: None)
    media = MediaRef(
        MediaSource.LOCAL,
        str(tmp_path / "song.wav"),
        stable_id="track-1",
        duration=60,
        capabilities=MediaCapabilities(finite=True, live=False, seekable=True, downloadable=False),
    )
    original = FakeDecoder(media)
    controller._active = original
    controller._state = PlaybackState.PLAYING
    controller._volume = 1.0
    captured = []
    controller.add_program_sink(lambda samples, _frames: captured.append(np.array(samples, copy=True)))
    stem = tmp_path / "vocals.wav"
    stem.write_bytes(b"prepared")

    controller.configure_stem_monitor(media.stable_id, [stem])
    output = np.zeros((1024, playback.CHANNELS), dtype=np.float32)
    controller._audio_callback(output, 1024, None, None)
    assert np.allclose(output[0], 0.25)
    for _ in range(4):
        controller._audio_callback(output, 1024, None, None)

    assert np.allclose(captured[-1], 0.25)
    assert np.allclose(output, 0.75)
    assert controller.snapshot().media == media
    assert controller.snapshot().state == PlaybackState.PLAYING
    assert controller.stem_monitor_status() == {
        "active": True,
        "transitioning": False,
        "media_id": media.stable_id,
        "source_count": 1,
    }

    controller.configure_stem_monitor(media.stable_id, [])
    controller._audio_callback(output, 1024, None, None)
    assert np.allclose(output[0], 0.75)
    for _ in range(4):
        controller._audio_callback(output, 1024, None, None)
    assert np.allclose(output, 0.25)
    assert controller.stem_monitor_status()["active"] is False


def test_stem_monitor_is_restarted_at_an_authoritative_seek_and_closed_on_stop(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(playback, "DecoderSession", FakeDecoder)
    controller = playback.PlaybackController(output_factory=lambda **_kwargs: None)
    media = MediaRef(
        MediaSource.LOCAL,
        str(tmp_path / "song.wav"),
        stable_id="track-1",
        duration=60,
        capabilities=MediaCapabilities(finite=True, live=False, seekable=True, downloadable=False),
    )
    controller._active = FakeDecoder(media)
    controller._state = PlaybackState.PLAYING
    stem = tmp_path / "drums.wav"
    stem.write_bytes(b"prepared")
    controller.configure_stem_monitor(media.stable_id, [stem])

    controller.seek(12, origin="cli")

    assert controller.snapshot().position == 12
    assert controller.stem_monitor_status() == {
        "active": True,
        "transitioning": False,
        "media_id": media.stable_id,
        "source_count": 1,
    }
    restarted_stem = controller._stem_session
    assert restarted_stem is not None and restarted_stem.start_at == 12
    controller.stop()
    assert restarted_stem.stopped
    assert controller.stem_monitor_status()["active"] is False


def test_decoder_builds_a_local_multi_stem_mix_without_resolving_original(monkeypatch, tmp_path: Path):
    commands = []

    class Process:
        stdout = SimpleNamespace(read=lambda _size: b"")
        stderr = SimpleNamespace(readline=lambda: b"")
        pid = 1

        def poll(self):
            return 0

    monkeypatch.setattr(playback, "find_executable", lambda *_args: "ffmpeg")
    monkeypatch.setattr(playback.subprocess, "Popen", lambda command, **_kwargs: commands.append(command) or Process())
    monkeypatch.setattr(playback, "WindowsJob", lambda _process: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(playback, "resolve_input", lambda _media: (_ for _ in ()).throw(AssertionError("resolved original")))
    media = MediaRef(MediaSource.YOUTUBE, "https://private.test/watch", duration=10)
    vocals = tmp_path / "vocals.wav"
    drums = tmp_path / "drums.wav"
    vocals.write_bytes(b"v")
    drums.write_bytes(b"d")

    session = playback.DecoderSession(media, input_sources=[vocals, drums], start_at=3)
    session.start()

    command = commands[0]
    assert command.count("-i") == 2
    assert str(vocals.resolve()) in command and str(drums.resolve()) in command
    assert any(
        "amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[stem]" in value
        for value in command
    )
    assert "https://private.test/watch" not in command


def test_decoder_mixes_real_local_stem_pcm_with_ffmpeg(tmp_path: Path):
    try:
        ffmpeg = playback.find_executable("ffmpeg")
    except playback.PlaybackError:
        pytest.skip("FFmpeg is not available")

    def write_constant(path: Path, value: float) -> None:
        sample = max(-32768, min(32767, round(value * 32767)))
        frame = struct.pack("<hh", sample, sample)
        with wave.open(str(path), "wb") as output:
            output.setnchannels(playback.CHANNELS)
            output.setsampwidth(2)
            output.setframerate(playback.SAMPLE_RATE)
            output.writeframes(frame * playback.SAMPLE_RATE)

    vocals = tmp_path / "vocals.wav"
    drums = tmp_path / "drums.wav"
    write_constant(vocals, 0.1)
    write_constant(drums, 0.2)
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "unused.wav"), duration=1)
    session = playback.DecoderSession(media, ffmpeg_bin=ffmpeg, input_sources=[vocals, drums])
    try:
        session.start()
        assert session.wait_for_buffer(minimum_seconds=0.1, timeout=5)
        samples = np.frombuffer(session.read(2048), dtype=np.float32)
        assert samples.size == 2048 * playback.CHANNELS
        assert np.allclose(samples, 0.3, atol=2e-4)
    finally:
        session.stop()
