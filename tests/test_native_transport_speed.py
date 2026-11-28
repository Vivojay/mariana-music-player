import shutil
import wave

import numpy as np
import pytest

from mariana.models import MediaRef, MediaSource, PlaybackState, PlayRegion
from mariana.playback import SAMPLE_RATE, PlaybackController, PlaybackError, UnsupportedAction


class Output:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


@pytest.fixture
def session(tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg required")
    path = tmp_path / "A4.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setparams((1, 2, SAMPLE_RATE, 0, "NONE", ""))
        pcm = (np.sin(np.arange(SAMPLE_RATE * 5) * (2 * np.pi * 440 / SAMPLE_RATE)) * 8000).astype("<i2")
        wav.writeframes(pcm.tobytes())
    controller = PlaybackController(output_factory=Output)
    media = MediaRef(MediaSource.LOCAL, str(path))
    controller.play(media, start_at=.25, start_paused=True)
    try:
        yield controller, media
    finally:
        controller.close()


def render(controller, seconds):
    count = round(seconds * SAMPLE_RATE)
    samples = np.zeros((count, 2), dtype=np.float32)
    controller._audio_callback(samples, count, None, None)
    return samples


@pytest.mark.parametrize("rate", [.8, 1.25, 2.0])
def test_rate_changes_wall_duration_and_preserves_pitch_and_identity(session, rate):
    ctl, media = session
    original = ctl.snapshot()
    ctl.set_playback_rate(rate)
    assert ctl.snapshot().state == PlaybackState.PAUSED and ctl.snapshot().position == original.position
    assert not render(ctl, .1).any()
    ctl.seek(1.0)
    assert ctl.snapshot().playback_rate == rate and ctl.snapshot().position == 1.0
    assert ctl._active.wait_for_buffer(minimum_seconds=.6)
    ctl.resume()
    data = render(ctl, .5)[:, 0]
    spectrum = np.abs(np.fft.rfft(data * np.hanning(len(data))))
    assert np.argmax(spectrum) * SAMPLE_RATE / len(data) == pytest.approx(440, abs=3)
    assert ctl.snapshot().position == pytest.approx(1 + .5 * rate, abs=.001)
    assert ctl.snapshot().session_id == original.session_id
    assert ctl.snapshot().media.stable_id == media.stable_id
    ctl.set_playback_rate(1.0)
    assert ctl.snapshot().session_id == original.session_id
    assert ctl.snapshot().playback_rate == 1.0


def test_rejected_rate_and_decoder_failure_leave_current_audio_intact(session, monkeypatch):
    ctl, _ = session
    before = ctl.snapshot()
    for rate in [0.25, 2.5, float("nan")]:
        with pytest.raises(ValueError):
            ctl.set_playback_rate(rate)
    def sink(event):
        return True
    ctl.begin_recipe_capture(sink, lambda event: None)
    with pytest.raises(UnsupportedAction, match="recipe"):
        ctl.set_playback_rate(1.5)
    ctl.end_recipe_capture(sink)
    monkeypatch.setattr("mariana.playback.DecoderSession.wait_for_buffer", lambda self, **kwargs: False)
    with pytest.raises(PlaybackError, match="buffer"):
        ctl.set_playback_rate(1.5)
    assert before.session_id == ctl.snapshot().session_id and ctl.snapshot().playback_rate == 1
    ctl.resume()
    assert render(ctl, .05).any()


def test_prefetch_promotes_next_item_at_normal_speed(session):
    ctl, media = session
    ctl.set_playback_rate(2.0)
    ctl.seek(4.0)
    ctl.set_crossfade_seconds(.5)
    ctl.prefetch(MediaRef(MediaSource.LOCAL, media.original_uri, title="Next"))
    ctl.resume()
    assert ctl._active.wait_for_buffer(minimum_seconds=.6)
    for _ in range(16):
        render(ctl, .05)
    assert ctl.snapshot().playback_rate == 1.0
    assert .35 < ctl.snapshot().position < 1.1


def test_region_endpoint_uses_media_seconds(session):
    ctl, _ = session
    ctl.set_playback_rate(2.0)
    ctl._active_region = PlayRegion(ctl.snapshot().media.stable_id, start_seconds=.25, end_seconds=.55)
    ctl.resume()
    assert ctl._active.wait_for_buffer(minimum_seconds=.6)
    samples = render(ctl, .25)
    assert samples[:7000].any() and not samples[7201:].any()
    assert ctl.snapshot().position == pytest.approx(.55)


def test_intervening_seek_supersedes_blocked_speed_change(session, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from mariana.playback import DecoderSession

    ctl, _ = session
    prepared, proceed = threading.Event(), threading.Event()
    wait_for_buffer = DecoderSession.wait_for_buffer
    def wait(decoder, *args, **kwargs):
        result = wait_for_buffer(decoder, *args, **kwargs)
        if decoder.rate == 1.5:
            prepared.set()
            assert proceed.wait(5)
        return result
    monkeypatch.setattr(DecoderSession, "wait_for_buffer", wait)
    with ThreadPoolExecutor(max_workers=1) as pool:
        preparing = pool.submit(ctl.set_playback_rate, 1.5)
        assert prepared.wait(5)
        try:
            ctl.seek(2.0)
        finally:
            proceed.set()
        with pytest.raises(UnsupportedAction, match="changed"):
            preparing.result()
    assert ctl.snapshot().position == 2.0 and ctl.snapshot().playback_rate == 1.0
