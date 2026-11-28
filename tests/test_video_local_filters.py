import shutil
import subprocess
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.playback import DecoderSession, probe_media
from mariana.video import LocalVideo, default_presentation
from mariana.video_detection import YoloDetector
from mariana.video_filters import filter_image, parse_filter


def test_fixed_filter_presets_on_decoded_rgb():
    red = Image.new("RGB", (1, 1), "red")
    assert filter_image(red, parse_filter("grayscale")).getpixel((0, 0)) == (54, 54, 54)
    assert filter_image(red, parse_filter("threshold", "22")).getpixel((0, 0)) == (0, 0, 0)
    assert filter_image(red, parse_filter("threshold", "20")).getpixel((0, 0)) == (255, 255, 255)
    assert filter_image(red, parse_filter("protanopia")).getpixel((0, 0)) == (109, 95, 0)
    assert filter_image(red, parse_filter("off")) is red
    with pytest.raises(ValueError):
        parse_filter("threshold", 101)
    with pytest.raises(ValueError):
        parse_filter("sepia", 45)


def test_native_silent_picture_has_a_clock_and_default_video(tmp_path):
    executable = shutil.which("ffmpeg")
    if not executable or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and FFprobe are required for the real video fixture")
    source = tmp_path / "silent.mp4"
    subprocess.run([executable, "-nostdin", "-v", "error", "-f", "lavfi",
                    "-i", "testsrc2=size=160x90:rate=12", "-t", "2", "-c:v", "mpeg4", str(source)],
                   check=True, capture_output=True, timeout=10)
    media = probe_media(MediaRef(MediaSource.LOCAL, str(source)))
    assert media.resolver_data["has_video_track"] and media.resolver_data["video_clock_only"]
    assert default_presentation(media) == "auto" and not media.capabilities.fingerprintable
    decoder = DecoderSession(media, ffmpeg_bin=executable, start_at=.5)
    try:
        decoder.start()
        assert decoder.wait_for_buffer(timeout=5), decoder.error
        samples = decoder.read(4800)
        assert samples and not any(samples)
        assert decoder.position > .5
    finally:
        decoder.stop()

    snapshot = PlaybackSnapshot(PlaybackState.PAUSED, media=media, position=.5)
    service = LocalVideo(tmp_path / "cache", lambda: snapshot, lambda _status: None, enabled=lambda: True)
    try:
        service.expect(media, "audio")
        assert not service.auto_open_local(media)
        service.activate(media, None)
        assert service.status()["state"] == "off"
        service.expect(media, None)
        assert service.auto_open_local(media)
        service.request("auto", expected_media=media)
        cutoff = time.monotonic() + 6
        while service.status()["state"] == "preparing" and time.monotonic() < cutoff:
            time.sleep(.025)
        assert service.status()["state"] == "ready", service.status()
        handle = service.status()["handle"]
        projected = service.configure_filter("threshold", 43, expected_media=media)
        assert projected["handle"] == handle, "filtering must not replace the decoder resource"
        assert projected["filter"] == {"preset": "threshold", "threshold": 43}
    finally:
        service.close()


def test_yolo_raw_boxes_are_letterbox_correct_and_class_aware():
    class Session:
        def get_inputs(self):
            return [SimpleNamespace(name="images", type="tensor(float)", shape=[1, 3, 320, 320])]

        def get_modelmeta(self):
            return SimpleNamespace(custom_metadata_map={"names": "{0: 'piano', 1: 'person'}"})

        def run(self, _outputs, inputs):
            image = inputs["images"]
            assert image.shape == (1, 3, 320, 320) and image.dtype == np.float32
            assert abs(float(image[0, 0, 0, 0]) - 114 / 255) < 1e-6
            rows = [[160, 160, 160, 80, .85, .10],
                    [162, 160, 160, 80, .75, .05],
                    [160, 160, 160, 80, .05, .80],
                    [0, 0, 80, 80, .70, .05]]
            return [np.asarray(rows, dtype=np.float32).T[None]]

    items = YoloDetector("unused.onnx", session=Session()).detect(Image.new("RGB", (160, 80), "red"))
    assert [item[1] for item in items] == ["piano", "person"]
    assert items[0][3] == (.25, .25, .75, .75)
