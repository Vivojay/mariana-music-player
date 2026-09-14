"""Real FFmpeg recipe acceptance with deterministic PCM, not audible-device QA."""

import os
import subprocess

import numpy as np
import pytest

from mariana.database import MarianaDatabase
from mariana.models import MediaRef, MediaSource, PlaybackState
from mariana.playback import SAMPLE_RATE, DecoderSession, PlaybackController, probe_media
from mariana.queueing import PersistentQueue
from mariana.recipe_playback import ExistingPlaybackRecipeHost
from mariana.recipe_queue import GroupIdentityMap, restore_snapshot
from mariana.session_recipes import (
    RecipeReplayEngine,
    ResolvedRecipeMedia,
    SessionRecipeRecorder,
    canonical_media_reference,
    fingerprint_file,
    initial_state,
    load_recipe,
)
from mariana.toolchain import find_tool_executable


class RecipeClock:
    def __init__(self):
        self.seconds = 0.0

    def __call__(self):
        return self.seconds


class DeterministicOutput:
    """Only the hardware output is replaced; the controller/decoder stay real."""

    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.active = False
        self.closed = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.closed = True

    def render(self, frames):
        output = np.full((frames, 2), np.nan, dtype=np.float32)
        self.callback(output, frames, None, None)
        return output


@pytest.mark.timeout(45)
@pytest.mark.parametrize('nested', [False, True], ids=['flat', 'nested-duplicates'])
def test_real_ffmpeg_committed_recipe_restores_silent_paused_checkpoint(tmp_path, nested):
    configured = os.environ.get("MARIANA_TEST_FFMPEG_BIN")
    ffmpeg = find_tool_executable("ffmpeg", configured)
    ffprobe = find_tool_executable("ffprobe", configured)
    if not ffmpeg or not ffprobe:
        pytest.skip("FFmpeg and ffprobe are required for real recipe acceptance")
    tone = tmp_path / "recipe-tone.flac"
    subprocess.run(
        [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-n", "-f", "lavfi", "-i",
         "sine=frequency=997:sample_rate=44100:duration=4", "-c:a", "flac", str(tone)],
        check=True, timeout=20, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    media = probe_media(MediaRef(MediaSource.LOCAL, str(tone)), ffprobe_bin=ffprobe)
    assert media.duration == pytest.approx(4, abs=.01)
    reference = canonical_media_reference(media, fingerprint=fingerprint_file(tone))
    clock = RecipeClock()
    recipe_path = tmp_path / "committed.jsonl"
    initial = initial_state()
    if nested:
        projected = GroupIdentityMap().project({
            'groups': [
                {'group_id': 'private-album', 'sibling_position': 0, 'kind': 'album'},
                {'group_id': 'private-playlist', 'parent_id': 'private-album', 'sibling_position': 1, 'kind': 'playlist'},
            ],
            'items': [
                {'stable_id': 'tone', 'group_id': 'private-album', 'sibling_position': 0},
                {'stable_id': 'tone', 'group_id': 'private-playlist', 'sibling_position': 0},
            ],
            'state': {'current_position': 1},
        })
        initial.update({key: projected[key] for key in ('queue', 'current_index', 'queue_tree')})
    recorder = SessionRecipeRecorder(recipe_path, media={"tone": reference}, initial_state=initial, clock=clock)
    captured, streams, decoders = [], [], []
    recording = True

    def committed_event(**event):
        if not recording:
            return False
        captured.append(event)
        kind = event["action"]
        if kind == "play":
            kind = "media_start" if event["play_kind"] == "start" else "resume"
        data = {"position_ms": round(event["position_seconds"] * 1000)}
        if kind == "media_start":
            data["media"] = "tone"
        return recorder.commit(kind, data)

    def output_factory(**kwargs):
        output = DeterministicOutput(**kwargs)
        streams.append(output)
        return output

    controller = PlaybackController(
        ffmpeg_bin=ffmpeg, ffprobe_bin=ffprobe, output_factory=output_factory,
        playback_event_sink=committed_event, crossfade_seconds=0,
    )
    engine = None
    try:
        controller.play(media, probe=False, origin="cli")
        decoders.append(controller._active)
        assert isinstance(decoders[-1], DecoderSession) and decoders[-1].process is not None
        assert np.max(np.abs(streams[0].render(SAMPLE_RATE // 10))) > .01
        clock.seconds = .1
        controller.pause(origin="cli")
        assert controller.snapshot().position == pytest.approx(.1, abs=1 / SAMPLE_RATE)

        clock.seconds = .2
        controller.seek(1.25, origin="cli")
        decoders.append(controller._active)
        assert decoders[-1] is not decoders[0] and decoders[0].process is None
        assert controller.snapshot().state == PlaybackState.PAUSED
        np.testing.assert_array_equal(streams[0].render(512), 0)
        assert recorder.checkpoint(at_ms=200)

        clock.seconds = .4
        controller.resume(origin="cli")
        assert np.max(np.abs(streams[0].render(SAMPLE_RATE // 10))) > .01
        clock.seconds = .5
        controller.pause(origin="cli")
        clock.seconds = .6
        recording = False
        assert recorder.close()

        recipe = load_recipe(recipe_path)
        assert recipe["complete"] and recipe["duration_ms"] == 600
        assert [event["kind"] for event in recipe["events"]] == [
            "media_start", "pause", "seek", "resume", "pause",
        ]
        assert [event["at_ms"] for event in recipe["events"]] == [0, 100, 200, 400, 500]
        assert [event["data"]["position_ms"] for event in recipe["events"]] == [0, 100, 1250, 1250, 1350]
        assert all(event["stable_id"] == media.stable_id for event in captured)
        assert len({event["session_id"] for event in captured}) == 1
        checkpoint = recipe["checkpoints"][0]
        assert checkpoint["state"]["position_ms"] == 1250 and not checkpoint["state"]["playing"]
        assert str(tone) not in recipe_path.read_text(encoding="utf-8")

        guard = []
        queue_restores = []
        queue_path = tmp_path / 'restored-queue.db'
        queue = PersistentQueue(MarianaDatabase(queue_path))

        def restore_queue(state, resolved):
            queue.restore_snapshot(restore_snapshot(state, resolved))
            queue_restores.append((state['queue'], resolved))

        def resolve(expected):
            assert expected["stable_id"] == media.stable_id
            return ResolvedRecipeMedia(media, canonical_media_reference(media, fingerprint=fingerprint_file(tone)))

        host = ExistingPlaybackRecipeHost(
            lambda: controller, resolve=resolve,
            restore_queue=restore_queue,
            configure_queue=lambda settings: None, set_replay_active=guard.append,
        )
        replay_clock = RecipeClock()
        engine = RecipeReplayEngine(recipe, host, clock=replay_clock)
        engine.seek(200)
        decoders.append(controller._active)
        assert host.playback is controller and len(streams) == 1
        assert decoders[-1] is not decoders[-2] and decoders[-2].process is None
        assert isinstance(decoders[-1], DecoderSession) and decoders[-1].process is not None
        assert controller.snapshot().state == PlaybackState.PAUSED
        assert controller.snapshot().position == pytest.approx(1.25, abs=1 / SAMPLE_RATE)
        paused_position = controller.snapshot().position
        np.testing.assert_array_equal(streams[0].render(SAMPLE_RATE // 10), 0)
        assert controller.snapshot().position == paused_position
        assert queue_restores[0][0] == initial['queue'] and guard == [True]
        restored = PersistentQueue(MarianaDatabase(queue_path))
        assert len(restored.items()) == (2 if nested else 0)
        if nested:
            assert restored.current().queue_id == restored.items()[1].queue_id
            groups = restored.export_snapshot()['groups']
            assert {group['name'] for group in groups} == {'Album group 1', 'Playlist group 2'}
            assert next(group for group in groups if group['kind'] == 'playlist')['parent_id'] is not None
            assert all(item.media.stable_id == media.stable_id for item in restored.items())

        replay_clock.seconds = .2
        assert engine.tick() == 1  # Recorded resume at recipe time 400 ms.
        assert controller.snapshot().state == PlaybackState.PLAYING
        assert np.max(np.abs(streams[0].render(SAMPLE_RATE // 10))) > .01
        replay_clock.seconds = .3
        assert engine.tick() == 1
        assert controller.snapshot().state == PlaybackState.PAUSED
        assert controller.snapshot().position == pytest.approx(1.35, abs=1 / SAMPLE_RATE)
        replay_clock.seconds = .4
        engine.tick()
        assert engine.status == "completed" and guard[-1] is False
        assert controller.snapshot().state == PlaybackState.IDLE
    finally:
        recording = False
        recorder.close()
        if engine is not None:
            engine.stop()
        controller.close()
    assert all(decoder.process is None for decoder in decoders)
    assert all(stream.closed for stream in streams)
