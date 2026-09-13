"""Bounded input, source replacement and process cleanup for captions."""

import io
import subprocess
import threading
from pathlib import Path

import pytest

from mariana import captions

VALID = '1\n00:00:01,000 --> 00:00:02,000\nHello\n'


@pytest.mark.parametrize('timestamp', ['00:60:00,000', '00:00:60,000'])
def test_invalid_clock_fields_are_rejected(timestamp):
    with pytest.raises(captions.CaptionError, match='timing'):
        captions.parse_captions(f'{timestamp} --> 01:01:01,000\ntext')


def test_cue_count_limit_is_enforced_before_exposing_track(monkeypatch):
    monkeypatch.setattr(captions, 'MAX_CAPTION_CUES', 1)
    with pytest.raises(captions.CaptionError, match='too many'):
        captions.parse_captions(VALID + '\n' + VALID)


@pytest.mark.parametrize('kind', ['directory', 'empty', 'oversize', 'invalid-utf8', 'wrong-suffix'])
def test_local_caption_inputs_have_clear_bounded_refusal(tmp_path, monkeypatch, kind):
    path = tmp_path / ('captions.txt' if kind == 'wrong-suffix' else 'captions.srt')
    if kind == 'directory':
        path.mkdir()
    else:
        path.write_bytes(b'' if kind == 'empty' else b'\xff' if kind == 'invalid-utf8' else VALID.encode())
    if kind == 'oversize':
        monkeypatch.setattr(captions, 'MAX_CAPTION_BYTES', 4)
    with pytest.raises(captions.CaptionError) as error:
        captions.load_captions(path)
    assert str(tmp_path) not in str(error.value)


def test_caption_growth_after_size_check_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / 'captions.srt'
    path.write_bytes(VALID.encode())
    monkeypatch.setattr(captions, 'MAX_CAPTION_BYTES', len(VALID.encode()))
    real_open = Path.open

    def grown(path_value, *args, **kwargs):
        if path_value == path and args == ('rb',):
            return io.BytesIO((VALID + 'extra').encode())
        return real_open(path_value, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', grown)
    with pytest.raises(captions.CaptionError, match='exceeds'):
        captions.load_captions(path)


def test_sidecar_scan_ignores_empty_oversize_and_foreign_names(tmp_path, monkeypatch):
    movie = tmp_path / 'movie.mp4'
    movie.touch()
    (tmp_path / 'movie.srt').write_bytes(b'')
    (tmp_path / 'movie.en.srt').write_bytes(b'x' * 65)
    (tmp_path / 'unrelated.srt').write_text(VALID, encoding='utf-8')
    monkeypatch.setattr(captions, 'MAX_CAPTION_BYTES', 64)
    assert captions.matching_sidecars(movie) == ()
    assert captions.matching_sidecars(tmp_path) == ()


def test_unreadable_directory_scan_is_nonfatal(tmp_path, monkeypatch):
    movie = tmp_path / 'movie.mp4'
    movie.touch()
    monkeypatch.setattr(Path, 'iterdir', lambda _path: (_ for _ in ()).throw(PermissionError()))
    assert captions.matching_sidecars(movie) == ()


def test_cancelled_conversion_terminates_and_kills_stalled_tool(tmp_path, monkeypatch):
    calls = []

    class Process:
        returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            calls.append('terminate')

        def wait(self, *, timeout):
            calls.append(('wait', timeout))
            if self.returncode is None:
                raise subprocess.TimeoutExpired('ffmpeg', timeout)

        def kill(self):
            calls.append('kill')
            self.returncode = -9

    monkeypatch.setattr(captions.subprocess, 'Popen', lambda *_args, **_kwargs: Process())
    cancel = threading.Event()
    cancel.set()
    assert not captions._run_caption_tool(['ffmpeg'], tmp_path / 'out.srt', cancel)
    assert calls == ['terminate', ('wait', 1), 'kill', ('wait', 1)]


@pytest.mark.parametrize('payload', [b'null', b'{"streams":{}}', b'not-json'])
def test_bad_embedded_probe_payload_is_not_an_available_track(tmp_path, monkeypatch, payload):
    monkeypatch.setattr(captions, '_caption_probe', lambda *_args: payload)
    assert captions._embedded_tracks(tmp_path / 'media.mp4', 'ffprobe', threading.Event()) == []


def test_conversion_refusal_and_corrupt_output_are_cleaned(tmp_path, monkeypatch):
    def convert(_command, output, _cancel):
        output.write_text('not a subtitle', encoding='utf-8')
        return True

    monkeypatch.setattr(captions, '_run_caption_tool', convert)
    assert captions._converted_track(
        'source.ass', tmp_path, 'ffmpeg', threading.Event(), label='Private source', origin='sidecar',
    ) is None
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(captions, '_run_caption_tool', lambda *_args: False)
    assert captions._converted_track(
        'source.ass', tmp_path, 'ffmpeg', threading.Event(), label='Captions', origin='sidecar',
    ) is None
    assert list(tmp_path.iterdir()) == []


def test_cancelled_discovery_never_probes_or_publishes_sidecars(tmp_path, monkeypatch):
    media = tmp_path / 'movie.mp4'
    media.touch()
    (tmp_path / 'movie.srt').write_text(VALID, encoding='utf-8')
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(captions, '_embedded_tracks', lambda *_args: pytest.fail('cancelled probe'))
    assert captions.discover_caption_tracks(media, 'ffprobe', cancel) == ()
    assert captions.autodetect_local_captions(
        media, tmp_path / 'out', ffprobe_bin='ffprobe', ffmpeg_bin='ffmpeg', cancel=cancel,
    ) is None


def test_changed_source_after_caption_read_does_not_publish_track(tmp_path, monkeypatch):
    sidecar = tmp_path / 'movie.srt'
    sidecar.write_text(VALID, encoding='utf-8')
    candidate = captions.CaptionCandidate(
        'a' * 32, 'Captions', 'eng', 'sidecar', True, False, 'srt',
        sidecar, captions.caption_source_signature(sidecar),
    )
    original_load = captions.load_captions

    def load_then_replace(path, **kwargs):
        loaded = original_load(path, **kwargs)
        path.write_text(VALID + '\nchanged', encoding='utf-8')
        return loaded

    monkeypatch.setattr(captions, 'load_captions', load_then_replace)
    assert captions.load_caption_candidate(candidate, tmp_path / 'out', 'ffmpeg', threading.Event()) is None


def test_unavailable_source_and_invalid_preferences_fail_without_private_projection(tmp_path):
    missing = tmp_path / 'private-name.srt'
    candidate = captions.CaptionCandidate('a' * 32, 'Captions', None, 'sidecar', False, False, 'srt', missing, 'b' * 64)
    assert captions.load_caption_candidate(candidate, tmp_path, 'ffmpeg', threading.Event()) is None
    preferences = captions.CaptionPreferences({'preferred languages': ['not-a-language']})
    assert preferences.languages == ()
    assert str(tmp_path) not in str(candidate.projection())
