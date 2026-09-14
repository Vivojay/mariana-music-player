"""Atomic recipe PCM restoration, including real installed FFmpeg decoding."""

import math
import threading
import time
import wave
from dataclasses import replace

import numpy as np
import pytest

from mariana import playback as playback_module
from mariana.models import MediaRef, MediaSource, PlaybackState, PlayRegion
from mariana.playback import SAMPLE_RATE, PlaybackController, PlaybackError
from mariana.recipe_mix import CommittedProgramEvent, RecipeMixSource, RecipeMixSpec
from mariana.recipe_playback import ExistingPlaybackRecipeHost
from mariana.session_recipes import (
    RecipeError,
    RecipeReplayEngine,
    ResolvedRecipeMedia,
    SessionRecipeRecorder,
    canonical_media_reference,
    effective_state,
    fingerprint_file,
    initial_state,
    load_recipe,
    new_recipe,
    validate_recipe,
)
from mariana.session_service import SessionRecipeService
from mariana.sources import ResolvedMedia
from mariana.toolchain import find_tool_executable


class Output:
    def __init__(self, **kwargs):
        self.callback = kwargs['callback']
        self.active = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.active = False


@pytest.fixture
def mixes(tmp_path):
    ffmpeg = find_tool_executable('ffmpeg')
    if ffmpeg is None:
        pytest.skip('Installed FFmpeg is required for recipe PCM acceptance')
    controller = PlaybackController(ffmpeg_bin=ffmpeg, output_factory=Output)
    sources = []
    for index, frequency in enumerate((1000, 2000)):
        path = tmp_path / f'source-{index}.wav'
        samples = .2 * np.sin(2 * math.pi * frequency * np.arange(SAMPLE_RATE * 4) / SAMPLE_RATE)
        stereo = np.column_stack((samples, -samples))
        with wave.open(str(path), 'wb') as writer:
            writer.setnchannels(2)
            writer.setsampwidth(2)
            writer.setframerate(SAMPLE_RATE)
            writer.writeframes((stereo * 32767).astype('<i2').tobytes())
        media = MediaRef(MediaSource.LOCAL, str(path), duration=4)
        resolved = ResolvedMedia(media, str(path), str(path), media.capabilities)
        sources.append(RecipeMixSource(media, resolved, 0, -6 if index == 0 else -3))
    yield controller, sources
    controller.close()


def render(controller, frames):
    output = np.full((frames, 2), np.nan, np.float32)
    with controller._lock:
        controller._audio_callback(output, frames, None, None)
    return output


def commit_at_block(controller, prepared, frames=128):
    errors = []
    for source in (prepared.outgoing, prepared.incoming):
        if source is not None:
            assert source.wait_for_buffer(minimum_seconds=4 - source.start_at, timeout=3)

    def commit():
        try:
            controller.commit_recipe_mix(prepared)
        except Exception as error:
            errors.append(error)

    worker = threading.Thread(target=commit)
    worker.start()
    deadline = time.monotonic() + 3
    while controller._pending_recipe_mix is None and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(.005)
    assert controller._pending_recipe_mix is prepared
    output = render(controller, frames)
    worker.join(3)
    assert not worker.is_alive() and not errors
    return output


def test_real_pair_restores_equal_power_pcm_then_promotes_at_exact_frame(mixes):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], 1000, 990))
    program = []
    controller.add_program_sink(lambda samples, _frames: program.append(np.array(samples, copy=True)))
    controller.set_volume(.5)
    output = commit_at_block(controller, prepared, 1024)
    frame = np.arange(1024)
    incoming = .2 * np.sin(2 * math.pi * 2000 * frame / SAMPLE_RATE) * 10 ** (-3 / 20)
    expected = incoming.copy()
    angle = (990 + frame[:10]) / 1000 * math.pi / 2
    expected[:10] = (
        .2 * np.sin(2 * math.pi * 1000 * frame[:10] / SAMPLE_RATE) * 10 ** (-6 / 20) * np.cos(angle)
        + incoming[:10] * np.sin(angle)
    )
    np.testing.assert_allclose(output[:, 0], expected * .5, atol=4e-5)
    np.testing.assert_allclose(output[:, 1], -expected * .5, atol=4e-5)
    np.testing.assert_allclose(program[-1][:, 0], expected, atol=8e-5)
    assert prepared.outgoing.frames_emitted == 10
    assert prepared.incoming.frames_emitted == 1024
    assert controller._active is prepared.incoming and controller._next is None
    assert controller._active.program_gain_db == -3
    assert controller.snapshot().state == PlaybackState.PLAYING
    with pytest.raises(PlaybackError):
        controller.commit_recipe_mix(prepared)


def test_real_paused_overlap_is_silent_and_frozen_until_resume(mixes):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, SAMPLE_RATE // 2, True))
    np.testing.assert_array_equal(commit_at_block(controller, prepared), 0)
    np.testing.assert_array_equal(render(controller, 512), 0)
    assert prepared.outgoing.frames_emitted == prepared.incoming.frames_emitted == 0
    assert controller._recipe_mix.elapsed_frames == SAMPLE_RATE // 2
    controller.resume(origin='recovery')
    assert np.max(np.abs(render(controller, 512))) > .05
    assert prepared.outgoing.frames_emitted == prepared.incoming.frames_emitted == 512
    controller.pause(origin='recovery')
    assert controller.snapshot().state == PlaybackState.PAUSED
    np.testing.assert_array_equal(render(controller, 512), 0)


def test_unequal_availability_consumes_neither_source_and_freezes_envelope(mixes):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0, True))
    commit_at_block(controller, prepared)
    incoming = prepared.incoming
    assert incoming is not None
    # Exclude the producer while testing true starvation, not wall-clock timing.
    with incoming._condition:
        saved, incoming._buffer = incoming._buffer, bytearray()
        incoming.eof = False
        controller.resume(origin='recovery')
        np.testing.assert_array_equal(render(controller, 512), 0)
        assert prepared.outgoing.frames_emitted == incoming.frames_emitted == 0
        assert controller._recipe_mix.elapsed_frames == 0
        assert controller.snapshot().state == PlaybackState.BUFFERING
        incoming._buffer = saved
    with prepared.outgoing._condition, incoming._condition:
        assert np.max(np.abs(render(controller, 512))) > 0
    assert controller.snapshot().state == PlaybackState.CROSSFADING


def test_premature_eof_never_advances_or_promotes_the_other_input(mixes):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0, True))
    commit_at_block(controller, prepared)
    incoming = prepared.incoming
    assert incoming is not None
    with incoming._condition:
        incoming._buffer.clear()
        incoming.eof = True
        controller.resume(origin='recovery')
        np.testing.assert_array_equal(render(controller, 512), 0)
        assert prepared.outgoing.frames_emitted == incoming.frames_emitted == 0
        assert controller.snapshot().state == PlaybackState.FAILED
        assert controller._active is prepared.outgoing


def test_stalled_output_and_stale_preparation_never_claim_commit(mixes):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0))
    with pytest.raises(PlaybackError, match='timed out'):
        controller.commit_recipe_mix(prepared, timeout=.05)
    assert prepared.status == 'discarded' and controller._active is None
    assert prepared.outgoing.process is None and prepared.incoming.process is None
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0))
    controller.stop()
    with pytest.raises(PlaybackError):
        controller.commit_recipe_mix(prepared)
    assert prepared.outgoing.process is None and prepared.incoming.process is None


def test_cancellation_during_second_source_preparation_retires_both(mixes):
    controller, sources = mixes
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(PlaybackError, match='cancelled'):
        controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0), cancelled=cancelled)
    assert controller._prepared_recipe_mix is None and controller._active is None


@pytest.mark.parametrize('field,value', [('duration_frames', 0), ('elapsed_frames', -1),
                                       ('elapsed_frames', SAMPLE_RATE), ('paused', 1)])
def test_invalid_envelopes_do_not_prepare_decoders(mixes, field, value):
    controller, sources = mixes
    options = {'duration_frames': SAMPLE_RATE, 'elapsed_frames': 0, 'paused': False, field: value}
    with pytest.raises(ValueError):
        controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], **options))
    assert controller._active is None and controller._prepared_recipe_mix is None


def test_version_three_preserves_incoming_gain_after_promotion_and_rejects_implicit_gains(mixes, tmp_path):
    _controller, sources = mixes
    media = {key: canonical_media_reference(source.media, fingerprint=fingerprint_file(source.media.original_uri))
             for key, source in zip(('a', 'b'), sources, strict=True)}
    state = initial_state(version=3)
    state.update(media='a', position_ms=0, playing=True, program_gain_db=-6)
    path = tmp_path / 'overlap.jsonl'
    recorder = SessionRecipeRecorder(path, media=media, initial_state=state, clock=lambda: 0, version=3)
    assert recorder.commit('transition', {
        'media': 'a', 'position_ms': 100,
        'incoming': 'b', 'incoming_position_ms': 100, 'duration_ms': 1000, 'progress_ms': 0,
        'outgoing_gain_db': -6, 'incoming_gain_db': -3,
    }, at_ms=100)
    assert recorder.checkpoint(at_ms=1500)
    assert recorder.close()
    recipe = load_recipe(path)
    assert recipe['version'] == 3 and recipe['complete']
    after = effective_state(recipe, 1500)
    assert after['media'] == 'b' and after['position_ms'] == 1500
    assert after['overlap'] is None and after['program_gain_db'] == -3
    recipe['checkpoints'][0]['state']['program_gain_db'] = 0
    with pytest.raises(RecipeError, match='Checkpoint'):
        validate_recipe(recipe)
    recipe = new_recipe(media=media, version=3)
    recipe['initial_state'].update(media='a', playing=True)
    with pytest.raises(RecipeError, match='gain'):
        validate_recipe(recipe)


def test_actual_host_seeks_into_paused_overlap_and_post_promotion_without_recomputing_gains(mixes):
    controller, sources = mixes
    media = {key: canonical_media_reference(source.media, fingerprint=fingerprint_file(source.media.original_uri))
             for key, source in zip(('a', 'b'), sources, strict=True)}
    recipe = new_recipe(media=media, version=3)
    recipe['initial_state'].update(media='a', position_ms=0, playing=True, program_gain_db=-6)
    recipe['events'] = [
        {'seq': 0, 'at_ms': 0, 'session_id': recipe['session_id'], 'kind': 'transition', 'reason': 'automatic',
         'data': {'incoming': 'b', 'incoming_position_ms': 0, 'duration_ms': 1000, 'progress_ms': 0,
                  'outgoing_gain_db': -6, 'incoming_gain_db': -3, 'media': 'a', 'position_ms': 0}},
        {'seq': 1, 'at_ms': 250, 'session_id': recipe['session_id'], 'kind': 'pause', 'reason': 'manual',
         'data': {'position_ms': 250, 'media': 'a', 'overlap': {
             'incoming': 'b', 'incoming_position_ms': 250, 'duration_ms': 1000, 'progress_ms': 250,
             'outgoing_gain_db': -6, 'incoming_gain_db': -3,
         }}},
        {'seq': 2, 'at_ms': 500, 'session_id': recipe['session_id'], 'kind': 'resume', 'reason': 'manual',
         'data': {'position_ms': 250, 'media': 'a', 'overlap': {
             'incoming': 'b', 'incoming_position_ms': 250, 'duration_ms': 1000, 'progress_ms': 250,
             'outgoing_gain_db': -6, 'incoming_gain_db': -3,
         }}},
    ]
    recipe['duration_ms'] = 2000
    by_id = {source.media.stable_id: source.media for source in sources}
    queues = []
    host = ExistingPlaybackRecipeHost(
        controller,
        resolve=lambda expected: ResolvedRecipeMedia(by_id[expected['stable_id']], expected),
        restore_queue=lambda state, _resolved: queues.append(state['current_index']),
        configure_queue=lambda _settings: None, set_replay_active=lambda _active: None,
    )
    engine = RecipeReplayEngine(recipe, host)

    def seek_at_block(at_ms):
        errors = []

        def seek():
            try:
                engine.seek(at_ms)
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=seek)
        worker.start()
        deadline = time.monotonic() + 5
        while controller._pending_recipe_mix is None and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(.005)
        assert controller._pending_recipe_mix is not None
        output = render(controller, 128)
        worker.join(3)
        assert not worker.is_alive() and not errors
        return output

    np.testing.assert_array_equal(seek_at_block(300), 0)
    assert controller._recipe_mix.elapsed_frames == SAMPLE_RATE // 4
    assert controller._active.position == pytest.approx(.25)
    assert controller._next.position == pytest.approx(.25)
    assert controller._active.program_gain_db == -6 and controller._next.program_gain_db == -3
    # Changed repository loudness must not replace the recorded effective gain.
    controller._program_gain_db = lambda _media: 12
    assert np.max(np.abs(seek_at_block(1750))) > 0
    assert controller._active.media.stable_id == sources[1].media.stable_id
    assert controller._active.program_gain_db == -3 and controller._next is None
    assert queues == [None, None]
    engine.stop()


def test_real_controller_captures_one_transition_with_actual_offsets_and_gains(mixes, tmp_path):
    controller, sources = mixes
    now = [0.0]
    by_id = {source.media.stable_id: source.media for source in sources}
    gain = {source.media.stable_id: source.program_gain_db for source in sources}
    controller._program_gain_db = lambda media: gain[media.stable_id]
    controller.set_crossfade_seconds(1)
    controller.play(sources[0].media, start_at=2.5, probe=False)
    controller.prefetch(sources[1].media, probe=False)
    service = SessionRecipeService(
        tmp_path / 'sessions', playback=controller, lookup_media=by_id.get,
        restore_queue=lambda _state, _resolved: None, configure_queue=lambda _settings: None,
        set_replay_active=lambda _active: None, clock=lambda: now[0],
    )
    # Existing analytics multicast still executes; the typed capture must win exactly once.
    controller._playback_event_sink = service.capture_playback_event
    snapshot = controller.snapshot()
    settings = initial_state()['settings']
    settings['crossfade_ms'] = 1000
    try:
        service.start('captured', initial_media_id=snapshot.media.stable_id,
                      initial_playback_session_id=snapshot.session_id, position_ms=2500, playing=True,
                      queue_ids=[sources[0].media.stable_id, sources[1].media.stable_id], current_index=0,
                      settings=settings)
        deadline = time.monotonic() + 3
        while service.status()['state'] == 'preparing' and time.monotonic() < deadline:
            time.sleep(.005)
        assert service.status()['state'] == 'recording'
        render(controller, SAMPLE_RATE // 2)
        now[0] = .5
        render(controller, 960)
        now[0] = .52
        controller.pause(origin='cli')
        now[0] = .72
        controller.resume(origin='desktop')
        # Simulate real 20 ms output blocks until ordinary automatic promotion.
        for _ in range(49):
            render(controller, 960)
            now[0] += .02
        now[0] += .1
        assert service.stop()
        recipe = load_recipe(tmp_path / 'sessions' / 'captured.jsonl')
        assert recipe['complete'] and recipe['version'] == 3
        assert [event['kind'] for event in recipe['events']] == ['transition', 'pause', 'resume', 'media_start']
        transition = recipe['events'][0]['data']
        assert transition['position_ms'] == 3000 and transition['incoming_position_ms'] == 0
        assert transition['outgoing_gain_db'] == -6 and transition['incoming_gain_db'] == -3
        assert transition['duration_ms'] == 1000 and transition['progress_ms'] == 0
        paused = recipe['events'][1]['data']
        assert paused['position_ms'] == 3020 and paused['overlap']['incoming_position_ms'] == 20
        assert paused['overlap']['progress_ms'] == 20
        assert recipe['events'][-1]['data']['media'] == sources[1].media.stable_id
        assert recipe['events'][-1]['data']['program_gain_db'] == -3
        final = effective_state(recipe, recipe['duration_ms'])
        assert final['program_gain_db'] == -3 and final['media'] == sources[1].media.stable_id
    finally:
        service.close()


@pytest.mark.parametrize('progress', [0, 24_000, 43_200])
def test_measured_equal_power_contributions_at_start_middle_and_late_overlap(mixes, progress):
    controller, sources = mixes
    outgoing = replace(sources[0], position_seconds=.5)
    incoming = replace(sources[1], position_seconds=.75)
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(outgoing, incoming, SAMPLE_RATE, progress))
    output = commit_at_block(controller, prepared, 512)
    frame = np.arange(512)
    angle = (progress + frame) / SAMPLE_RATE * math.pi / 2
    expected = (.2 * np.sin(2 * math.pi * 1000 * frame / SAMPLE_RATE) * 10 ** (-6 / 20) * np.cos(angle)
                + .2 * np.sin(2 * math.pi * 2000 * frame / SAMPLE_RATE) * 10 ** (-3 / 20) * np.sin(angle))
    np.testing.assert_allclose(output[:, 0], expected, atol=7e-5)
    np.testing.assert_allclose(output[:, 1], -expected, atol=7e-5)
    assert prepared.outgoing.position == pytest.approx(.5 + 512 / SAMPLE_RATE)
    assert prepared.incoming.position == pytest.approx(.75 + 512 / SAMPLE_RATE)


@pytest.mark.parametrize('after_transition', [False, True])
def test_ordinary_crossfade_starvation_marks_capture_unsupported_without_changing_playback(mixes, after_transition):
    controller, sources = mixes
    controller.set_crossfade_seconds(1)
    controller.play(sources[0].media, start_at=3, probe=False)
    controller.prefetch(sources[1].media, probe=False)
    outgoing, incoming = controller._active, controller._next
    assert outgoing.wait_for_buffer(minimum_seconds=1, timeout=3)
    assert incoming.wait_for_buffer(minimum_seconds=4, timeout=3)
    events = []
    controller._recipe_capture_sink = lambda event: events.append(event) or True
    if after_transition:
        render(controller, 960)
        assert [event.action for event in events] == ['transition']
        events.clear()
    before = outgoing.position
    with incoming._condition:
        incoming._buffer = incoming._buffer[:8 * 10]
        incoming.eof = False
        output = render(controller, 960)
    assert [event.action for event in events] == ['unsupported']
    assert np.max(np.abs(output)) > 0
    assert outgoing.position == pytest.approx(before + .02)
    assert controller.snapshot().state == PlaybackState.CROSSFADING


def test_typed_capture_does_not_wait_on_service_lock_and_seals_loss(mixes, tmp_path):
    controller, sources = mixes
    controller.play(sources[0].media, probe=False, start_paused=True)
    service = SessionRecipeService(
        tmp_path / 'contention', playback=controller,
        lookup_media=lambda identity: sources[0].media if identity == sources[0].media.stable_id else None,
        restore_queue=lambda _state, _resolved: None, configure_queue=lambda _settings: None,
        set_replay_active=lambda _active: None,
    )
    snapshot = controller.snapshot()
    try:
        service.start('captured', initial_media_id=snapshot.media.stable_id,
                      initial_playback_session_id=snapshot.session_id, playing=False)
        deadline = time.monotonic() + 3
        while service.status()['state'] == 'preparing' and time.monotonic() < deadline:
            time.sleep(.005)
        assert service.status()['state'] == 'recording'
        event = CommittedProgramEvent('pause', snapshot.media.stable_id, snapshot.session_id, 0, 0, False)
        with service._lock:
            started = time.monotonic()
            assert not service.capture_program_event(event)
            assert time.monotonic() - started < .1
        assert not service.stop()
        recipe = load_recipe(tmp_path / 'contention' / 'captured.jsonl')
        assert not recipe['complete'] and recipe['incomplete_reason'] == 'overflow'
        assert controller.snapshot().state == PlaybackState.PAUSED
    finally:
        service.close()


def test_typed_capture_full_queue_reports_loss_without_recorder_calls(tmp_path):
    service = SessionRecipeService(
        tmp_path, playback=object(), lookup_media=lambda _identity: None,
        restore_queue=lambda _state, _resolved: None, configure_queue=lambda _settings: None,
        set_replay_active=lambda _active: None, capacity=1,
    )
    service._state = 'recording'
    event = CommittedProgramEvent('pause', 'media', 'session', 0, 0, False)
    assert service.capture_program_event(event)
    assert not service.capture_program_event(event)
    assert service._capture_loss and service._pending.qsize() == 1
    assert service.status()['error_code'] == 'overflow'


@pytest.mark.parametrize('lock_name', ['_audio_block_lock', '_lock'])
@pytest.mark.parametrize('buffer_kind', ['array', 'bytes'])
def test_busy_callback_locks_emit_silence_without_consuming_or_waiting(mixes, lock_name, buffer_kind):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], paused=True))
    commit_at_block(controller, prepared)
    acquired, release = threading.Event(), threading.Event()

    def owner():
        with getattr(controller, lock_name):
            acquired.set()
            assert release.wait(3)

    owner_thread = threading.Thread(target=owner)
    owner_thread.start()
    assert acquired.wait(3)
    output = np.ones((128, 2), np.float32) if buffer_kind == 'array' else bytearray(b'\xff' * 128 * 8)
    started = time.monotonic()
    try:
        controller._audio_callback(output, 128, None, None)
        assert time.monotonic() - started < .1
        if buffer_kind == 'array':
            np.testing.assert_array_equal(output, 0)
        else:
            assert output == bytes(128 * 8)
        assert prepared.outgoing.frames_emitted == 0
    finally:
        release.set()
        owner_thread.join(3)
    assert not owner_thread.is_alive()


@pytest.mark.parametrize('gain', [True, float('nan'), float('inf'), -121, 61])
def test_invalid_effective_recipe_gain_preserves_existing_source(mixes, gain):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], paused=True))
    commit_at_block(controller, prepared)
    with pytest.raises(ValueError, match='program gain'):
        controller.set_recipe_program_gain(gain)
    assert controller._active is prepared.outgoing and controller._active.program_gain_db == -6
    assert controller.snapshot().position == 0 and controller.snapshot().state == PlaybackState.PAUSED


def test_recipe_gain_applies_only_to_single_restored_program_source(mixes):
    controller, sources = mixes
    with pytest.raises(PlaybackError, match='single restored'):
        controller.set_recipe_program_gain(-9)
    paired = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0, True))
    commit_at_block(controller, paired)
    with pytest.raises(PlaybackError, match='single restored'):
        controller.set_recipe_program_gain(-9)
    single = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], paused=True))
    commit_at_block(controller, single)
    controller.set_volume(.4)
    controller.set_recipe_program_gain(-9)
    assert controller._active is single.outgoing and controller.snapshot().position == 0
    assert controller.snapshot().volume == .4 and controller._active.program_gain_db == -9
    controller.resume(origin='recovery')
    output = bytearray(512 * 8)
    with controller._lock:
        controller._audio_callback(output, 512, None, None)
    samples = np.frombuffer(output, dtype=np.float32).reshape(-1, 2)
    expected = .2 * np.sin(2 * math.pi * 1000 * np.arange(512) / SAMPLE_RATE) * 10 ** (-9 / 20) * .4
    np.testing.assert_allclose(samples[:, 0], expected, atol=4e-5)


def test_replacing_prepared_mix_retires_old_pair_after_acknowledgement(mixes):
    controller, sources = mixes
    original = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0, True))
    commit_at_block(controller, original)
    replacement = controller.prepare_recipe_mix(RecipeMixSpec(replace(sources[1], position_seconds=1), paused=True))
    assert controller._active is original.outgoing and original.outgoing.process is not None
    commit_at_block(controller, replacement)
    assert original.outgoing.process is None and original.incoming.process is None
    assert replacement.retired == () and replacement.outgoing.process is not None
    assert controller.snapshot().position == 1 and controller.snapshot().state == PlaybackState.PAUSED


def test_promoted_source_is_published_only_after_worker_retires_outgoing(mixes):
    controller, sources = mixes
    publications = []
    remove = controller.add_active_media_sink(lambda media, _resolved: publications.append(media))
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], 64, 63))
    commit_at_block(controller, prepared, 128)
    deadline = time.monotonic() + 3
    while (prepared.outgoing.process is not None or sources[1].media not in publications) and time.monotonic() < deadline:
        time.sleep(.005)
    assert prepared.outgoing.process is None and prepared.incoming.process is not None
    assert publications == [sources[1].media]
    assert controller.snapshot().media is sources[1].media
    remove()
    remove()  # Subscription removal is deliberately idempotent.


def test_recipe_preparation_rejects_regions_and_existing_stem_ownership(mixes, monkeypatch):
    controller, sources = mixes
    spec = RecipeMixSpec(sources[0], paused=True)
    monkeypatch.setattr(controller, '_play_region', lambda media: PlayRegion(media.stable_id, start_seconds=1, end_seconds=2))
    with pytest.raises(PlaybackError, match='preferred regions'):
        controller.prepare_recipe_mix(spec)
    monkeypatch.setattr(controller, '_play_region', lambda _media: None)
    for field in ('_stem_session', '_stem_previous'):
        setattr(controller, field, object())
        try:
            with pytest.raises(PlaybackError, match='original mix'):
                controller.prepare_recipe_mix(spec)
        finally:
            setattr(controller, field, None)
    assert controller._active is None and controller._prepared_recipe_mix is None


def test_superseding_admission_during_final_preparation_publication_retires_decoder(mixes, monkeypatch):
    controller, sources = mixes
    constructed = []
    constructor = playback_module.PreparedRecipeMix

    def admit_new_request(*args, **kwargs):
        result = constructor(*args, **kwargs)
        constructed.append(result)
        controller.reserve_media_request()
        return result

    monkeypatch.setattr(playback_module, 'PreparedRecipeMix', admit_new_request)
    with pytest.raises(PlaybackError, match='replaced'):
        controller.prepare_recipe_mix(RecipeMixSpec(sources[0], paused=True))
    assert len(constructed) == 1 and constructed[0].outgoing.process is None
    assert controller._prepared_recipe_mix is None and controller._active is None


@pytest.mark.parametrize('cancel_mode', ['discard', 'supersede'])
def test_pending_mix_rejects_other_restore_and_cannot_claim_cancelled_commit(mixes, cancel_mode):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], paused=True))
    errors = []

    def commit():
        try:
            controller.commit_recipe_mix(prepared)
        except PlaybackError as error:
            errors.append(error)

    worker = threading.Thread(target=commit)
    worker.start()
    deadline = time.monotonic() + 3
    while controller._pending_recipe_mix is None and worker.is_alive() and time.monotonic() < deadline:
        time.sleep(.001)
    assert controller._pending_recipe_mix is prepared
    with pytest.raises(PlaybackError, match='awaiting commitment'):
        controller.prepare_recipe_mix(RecipeMixSpec(sources[1], paused=True))
    if cancel_mode == 'discard':
        controller.discard_recipe_mix(prepared)
    else:
        # Invalidate and enter the callback while holding the publication lock,
        # so the waiting control thread cannot discard before block admission.
        with controller._lock:
            controller.reserve_media_request()
            render(controller, 128)
    worker.join(3)
    assert not worker.is_alive() and len(errors) == 1
    assert prepared.outgoing.process is None and prepared.status == 'discarded'
    assert controller._active is None


def test_recipe_owns_seek_and_completion_instead_of_advancing_queue(mixes, monkeypatch):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], paused=True))
    commit_at_block(controller, prepared)
    with pytest.raises(PlaybackError, match='recipe timeline'):
        controller.seek(1, origin='desktop')
    callbacks = []
    monkeypatch.setattr(controller, '_finish_active', lambda active: callbacks.append(active))
    with prepared.outgoing._condition:
        prepared.outgoing._buffer.clear()
        prepared.outgoing.eof = True
    controller._watch_stop.clear()
    worker = threading.Thread(target=controller._watch_completion)
    worker.start()
    time.sleep(.22)
    controller._watch_stop.set()
    worker.join(3)
    assert not worker.is_alive() and callbacks == []
    assert controller._active is prepared.outgoing and controller.snapshot().position == 0


def test_request_generation_admits_only_current_typed_tokens(mixes):
    controller, sources = mixes
    for invalid in (True, '1', None):
        assert controller.reserve_media_request_if_current(invalid) is None
        assert not controller.media_request_is_current(invalid)
        with pytest.raises(ValueError, match='integer'):
            controller.stop_reserved_media_request(invalid)
    original = controller.reserve_media_request()
    current = controller.reserve_media_request_if_current(original)
    assert current == original + 1 and not controller.media_request_is_current(original)
    controller.play(sources[0].media, probe=False, start_paused=True, request_generation=current)
    assert controller.snapshot().media is sources[0].media
    assert not controller.stop_reserved_media_request(original)
    assert controller.snapshot().state == PlaybackState.PAUSED
    assert controller.stop_reserved_media_request(current)
    assert controller.snapshot().state == PlaybackState.IDLE


def test_resolved_input_without_selection_and_invalid_paused_intent_cannot_start_audio(mixes):
    controller, sources = mixes
    with pytest.raises(PlaybackError, match='selected media'):
        controller.play(resolved=sources[0].resolved)
    with pytest.raises(ValueError, match='true or false'):
        controller.play(sources[0].media, start_paused=1)
    assert controller._active is None


def test_capture_rejects_a_retired_identity_and_no_media_without_changing_playback(mixes):
    controller, sources = mixes
    controller._capture_program_event(CommittedProgramEvent('pause', None, None, 0, None, False))
    events = []
    controller._recipe_capture_sink = lambda event: events.append(event) or True
    controller._capture_playback_event('pause', origin='cli', position_seconds=0)
    assert events == []
    controller.play(sources[0].media, probe=False, start_paused=True)
    events.clear()
    controller._capture_playback_event('pause', origin='cli', position_seconds=0,
                                       media=sources[1].media, session_id='retired-session')
    assert [event.action for event in events] == ['unsupported']
    assert controller.snapshot().media is sources[0].media and controller.snapshot().state == PlaybackState.PAUSED


@pytest.mark.parametrize('problem', ['owner', 'expired', 'live', 'unbounded', 'nonseekable', 'position_nan',
                                   'position_negative', 'position_past_end', 'gain_nan', 'gain_bool',
                                   'gain_extreme', 'duration_missing', 'duration_nan', 'overlap_past_end'])
def test_untrusted_mix_source_validation_never_publishes_or_starts_output(mixes, problem):
    controller, sources = mixes
    source = sources[0]
    if problem == 'owner':
        source.resolved.media = sources[1].media
    elif problem == 'expired':
        source.resolved.expires_at = time.time()
    elif problem in {'live', 'unbounded', 'nonseekable'}:
        setattr(source.resolved.capabilities, {'live': 'live', 'unbounded': 'finite', 'nonseekable': 'seekable'}[problem],
                problem == 'live')
    elif problem.startswith('position_'):
        source = replace(source, position_seconds={'position_nan': math.nan, 'position_negative': -1,
                                                  'position_past_end': 4}[problem])
    elif problem.startswith('gain_'):
        source = replace(source, program_gain_db={'gain_nan': math.nan, 'gain_bool': True, 'gain_extreme': 61}[problem])
    elif problem.startswith('duration_'):
        source.media.duration = None if problem == 'duration_missing' else math.nan
    else:
        source = replace(source, position_seconds=3.5)
    with pytest.raises(ValueError):
        controller.prepare_recipe_mix(RecipeMixSpec(source, sources[1], SAMPLE_RATE, 0))
    assert controller._active is None and controller._stream is None


def test_superseding_preparation_discards_only_uncommitted_pair(mixes):
    controller, sources = mixes
    first = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0, True))
    second = controller.prepare_recipe_mix(RecipeMixSpec(sources[1], paused=True))
    assert first.status == 'discarded'
    assert first.outgoing.process is None and first.incoming.process is None
    controller.discard_recipe_mix(first)
    assert second.outgoing.process is not None
    commit_at_block(controller, second)
    controller.discard_recipe_mix(second)
    assert controller._active is second.outgoing and second.outgoing.process is not None


def test_foreign_preparation_cannot_be_committed_or_discarded(mixes):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], paused=True))
    other = PlaybackController(output_factory=Output)
    try:
        with pytest.raises(PlaybackError):
            other.commit_recipe_mix(prepared)
        with pytest.raises(PlaybackError):
            other.discard_recipe_mix(prepared)
        assert prepared.status == 'prepared' and prepared.outgoing.process is not None
    finally:
        other.close()
        controller.discard_recipe_mix(prepared)


@pytest.mark.parametrize('timeout', [0, -1, math.nan, math.inf, 31])
def test_invalid_preparation_deadlines_leave_playback_unchanged(mixes, timeout):
    controller, sources = mixes
    with pytest.raises(ValueError):
        controller.prepare_recipe_mix(RecipeMixSpec(sources[0]), timeout=timeout)
    assert controller._active is None and controller._stream is None


def test_output_interruption_mute_and_sleep_gain_do_not_change_program_or_overlap(mixes):
    controller, sources = mixes
    prepared = controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0, True))
    commit_at_block(controller, prepared)
    captured = []
    controller.add_program_sink(lambda samples, _frames: captured.append(np.array(samples, copy=True)))
    controller.resume(origin='recovery')
    controller._output_interrupted = True
    np.testing.assert_array_equal(render(controller, 512), 0)
    assert prepared.outgoing.frames_emitted == prepared.incoming.frames_emitted == 0
    controller._output_interrupted = False
    controller.set_muted(True)
    np.testing.assert_array_equal(render(controller, 512), 0)
    assert np.max(np.abs(captured[-1])) > .05
    controller.set_muted(False)
    controller.set_volume(.5)
    controller.set_automation_gain(.2)
    output = render(controller, 512)
    np.testing.assert_allclose(output, captured[-1] * .1, atol=1e-7)
    assert prepared.outgoing.frames_emitted == prepared.incoming.frames_emitted == 1024


def test_preparation_failure_of_second_decoder_retains_current_paused_media(mixes):
    controller, sources = mixes
    controller.play(sources[0].media, probe=False, start_paused=True)
    active = controller._active
    sources[1].media.duration = 60  # Declared duration is not proof of decoded availability.
    with open(sources[1].media.original_uri, 'wb') as target:
        target.write(b'not media')
    with pytest.raises(PlaybackError, match='no verified playable audio'):
        controller.prepare_recipe_mix(RecipeMixSpec(sources[0], sources[1], SAMPLE_RATE, 0))
    assert controller._active is active and controller.snapshot().state == PlaybackState.PAUSED
    assert controller._prepared_recipe_mix is None


def test_recipe_capture_failure_does_not_interrupt_successful_playback(mixes):
    controller, sources = mixes
    controller._recipe_capture_sink = lambda _event: (_ for _ in ()).throw(RuntimeError('capture unavailable'))
    controller.play(sources[0].media, probe=False)
    assert controller.snapshot().state == PlaybackState.PLAYING
    controller.pause(origin='cli')
    assert controller.snapshot().state == PlaybackState.PAUSED
