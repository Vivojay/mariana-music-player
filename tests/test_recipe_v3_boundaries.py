"""Strict frozen-gain recipe validation and existing-controller dispatch."""

import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mariana.models import MediaRef, MediaSource
from mariana.playback import PlaybackController
from mariana.recipe_playback import ExistingPlaybackRecipeHost
from mariana.recipe_sources import PreparedRecipeSource
from mariana.session_recipes import (
    RecipeError,
    ReplayBlocked,
    canonical_media_reference,
    effective_state,
    initial_state,
    new_recipe,
    validate_media_reference,
    validate_recipe,
)
from mariana.session_service import SessionRecipeService
from mariana.sources import ResolvedMedia


def reference(identity='a'):
    return {'source': 'local', 'stable_id': identity * 24, 'fingerprint': identity * 64,
            'duration_ms': 60_000, 'live': False, 'provider_id': None}


def overlap():
    return {'incoming': 'b', 'incoming_position_ms': 500, 'duration_ms': 1000, 'progress_ms': 250,
            'outgoing_gain_db': -6, 'incoming_gain_db': -3}


def recipe(*, playing=True, mixed=False):
    value = new_recipe(version=3, media={'a': reference(), 'b': reference('b')})
    value['initial_state'].update(media='a', position_ms=1000, playing=playing, program_gain_db=-6,
                                  overlap=overlap() if mixed else None)
    value['duration_ms'] = 2000
    return value


def add_event(value, kind, data, *, at_ms=0):
    value['events'].append({'seq': len(value['events']), 'at_ms': at_ms, 'session_id': value['session_id'],
                            'kind': kind, 'reason': 'manual', 'data': data})


@pytest.mark.parametrize('change,match', [
    (lambda state: state.update(playing='yes'), 'playing'),
    (lambda state: state.update(media=None), 'inconsistent'),
    (lambda state: state.update(media=None, playing=False, position_ms=0), 'gain'),
    (lambda state: state.update(overlap={**overlap(), 'outgoing_gain_db': -5}), 'outgoing gain'),
])
def test_initial_state_cannot_invent_playback_or_disagree_with_frozen_gain(change, match):
    value = recipe()
    change(value['initial_state'])
    with pytest.raises(RecipeError, match=match):
        validate_recipe(value)


@pytest.mark.parametrize('playing,mixed,kind,data,match', [
    (False, False, 'pause', {'media': 'a', 'position_ms': 1000, 'overlap': None}, 'Pause requires'),
    (True, False, 'resume', {'media': 'a', 'position_ms': 1000, 'overlap': None}, 'Resume requires'),
    (True, False, 'pause', {'media': 'b', 'position_ms': 1000, 'overlap': None}, 'effective source'),
    (True, True, 'pause', {'media': 'a', 'position_ms': 1000, 'overlap': None}, 'lost.*overlap'),
    (True, False, 'pause', {'media': 'a', 'position_ms': 1000, 'overlap': overlap()}, 'lost.*overlap'),
    (True, True, 'pause', {'media': 'a', 'position_ms': 1000,
                         'overlap': {**overlap(), 'incoming_gain_db': -4}}, 'identity or gains'),
    (True, True, 'seek', {'media': 'a', 'position_ms': 2000, 'overlap': overlap()}, 'Seek during overlap'),
    (False, False, 'transition', {**overlap(), 'media': 'a', 'position_ms': 1000}, 'one playing'),
    (True, True, 'transition', {**overlap(), 'media': 'a', 'position_ms': 1000}, 'one playing'),
    (True, False, 'transition', {**overlap(), 'media': 'b', 'position_ms': 1000}, 'outgoing source'),
])
def test_recorded_actions_must_match_effective_single_or_dual_source_state(playing, mixed, kind, data, match):
    value = recipe(playing=playing, mixed=mixed)
    add_event(value, kind, data)
    with pytest.raises(RecipeError, match=match):
        validate_recipe(value)


def test_pause_without_any_active_source_is_not_a_valid_recorded_action():
    value = new_recipe(version=3, media={'a': reference()})
    add_event(value, 'pause', {'media': 'a', 'position_ms': 0, 'overlap': None})
    with pytest.raises(RecipeError, match='current media'):
        validate_recipe(value)


def test_recorded_gain_change_is_explicit_and_stop_clears_only_source_gain():
    value = recipe()
    gain = {**value['settings']['replaygain'], 'enabled': True, 'preamp_db': -2, 'program_gain_db': -8}
    add_event(value, 'gain_settings', gain)
    add_event(value, 'seek', {'media': 'a', 'position_ms': 12_000, 'overlap': None}, at_ms=100)
    add_event(value, 'stop', {}, at_ms=1000)
    checked = validate_recipe(value)
    before_stop = effective_state(checked, 500)
    assert before_stop['program_gain_db'] == -8 and before_stop['position_ms'] == 12_400
    stopped = effective_state(checked, 1200)
    assert stopped['media'] is None and stopped['overlap'] is None and stopped['program_gain_db'] is None
    assert stopped['settings']['replaygain'] == {key: val for key, val in gain.items() if key != 'program_gain_db'}


def test_gain_change_during_overlap_is_refused_instead_of_reinterpreting_two_gains():
    value = recipe(mixed=True)
    add_event(value, 'gain_settings', {**value['settings']['replaygain'], 'program_gain_db': -8})
    with pytest.raises(RecipeError, match='Gain changes during overlap'):
        validate_recipe(value)


def test_idle_gain_settings_must_not_create_a_source_gain():
    value = new_recipe(version=3)
    add_event(value, 'gain_settings', {**value['settings']['replaygain'], 'program_gain_db': None})
    assert effective_state(validate_recipe(value), 0)['program_gain_db'] is None


@pytest.mark.parametrize('change', [
    {'fingerprint': 'not-a-fingerprint'}, {'fingerprint': True}, {'live': 1},
    {'source': 'youtube', 'provider_id': 'https://private.invalid/token'}, {'provider_id': 'abcdefghijk'},
])
def test_reference_validation_rejects_untrusted_identity_fields(change):
    with pytest.raises(RecipeError):
        validate_media_reference({**reference(), **change})


@pytest.mark.parametrize('uri', [
    'https://youtu.be/abcdefghijk', 'https://www.youtube.com/shorts/abcdefghijk',
    'https://www.youtube.com/live/abcdefghijk', 'https://www.youtube.com/embed/abcdefghijk',
])
def test_supported_public_youtube_forms_keep_only_the_provider_identity(uri):
    media = SimpleNamespace(source=MediaSource.YOUTUBE, original_uri=uri, stable_id='a' * 24,
                            duration=60, capabilities=SimpleNamespace(live=False))
    result = canonical_media_reference(media)
    assert result == {**reference(), 'source': 'youtube', 'fingerprint': None, 'provider_id': 'abcdefghijk'}


@pytest.mark.parametrize('uri', [
    'https://private:secret@youtube.com/watch?v=abcdefghijk',
    'https://youtube.com:8443/watch?v=abcdefghijk', 'https://other.invalid/watch?v=abcdefghijk',
])
def test_private_or_unrecognized_youtube_references_never_become_portable_links(uri):
    media = SimpleNamespace(source=MediaSource.YOUTUBE, original_uri=uri, stable_id='a' * 24,
                            duration=60, capabilities=SimpleNamespace(live=False))
    with pytest.raises(RecipeError, match='provider identity'):
        canonical_media_reference(media)


def host_fixture():
    playback = Mock(spec=PlaybackController)
    queues, settings, guards = [], [], []
    host = ExistingPlaybackRecipeHost(
        lambda: playback, resolve=lambda _ref: None,
        restore_queue=lambda state, resolved: queues.append((copy.deepcopy(state), resolved)),
        configure_queue=lambda state: settings.append(copy.deepcopy(state)), set_replay_active=guards.append,
    )
    media = MediaRef(MediaSource.LOCAL, 'C:/local.flac', duration=60)
    resolved = ResolvedMedia(media, media.original_uri, media.original_uri, media.capabilities)
    return host, playback, queues, settings, guards, PreparedRecipeSource(media, resolved)


@pytest.mark.parametrize('kind', ['media_start', 'seek', 'transition'])
def test_native_host_passes_verified_offsets_and_frozen_gains_to_one_atomic_controller(kind):
    host, playback, queues, _settings, _guards, source = host_fixture()
    state = initial_state(version=3)
    state.update(media='a', position_ms=1200, program_gain_db=-7, playing=False)
    host.apply({'kind': kind, 'data': {'media': 'a', 'position_ms': 1200}}, state, {'a': source})
    spec = playback.prepare_recipe_mix.call_args.args[0]
    assert spec.outgoing.media is source.media and spec.outgoing.resolved is source.resolved
    assert spec.outgoing.position_seconds == 1.2 and spec.outgoing.program_gain_db == -7 and spec.paused
    playback.commit_recipe_mix.assert_called_once()
    playback.discard_recipe_mix.assert_called_once_with(playback.prepare_recipe_mix.return_value)
    playback.play.assert_not_called()
    playback.seek.assert_not_called()
    assert queues == []


def test_atomic_host_always_discards_preparation_when_commit_is_refused():
    host, playback, _queues, _settings, _guards, source = host_fixture()
    playback.commit_recipe_mix.side_effect = RuntimeError('cancelled before acknowledgement')
    state = initial_state(version=3)
    state.update(media='a', position_ms=0, program_gain_db=0, playing=True)
    with pytest.raises(RuntimeError, match='cancelled'):
        host.apply({'kind': 'media_start', 'data': {'media': 'a', 'position_ms': 0}}, state, {'a': source})
    playback.discard_recipe_mix.assert_called_once_with(playback.prepare_recipe_mix.return_value)


@pytest.mark.parametrize('operation', ['pause', 'resume', 'stop'])
def test_simple_host_actions_use_existing_authority(operation):
    host, playback, _queues, _settings, _guards, _source = host_fixture()
    host.apply({'kind': operation, 'data': {}}, initial_state(), {})
    expected = {} if operation == 'stop' else {'origin': 'recovery'}
    getattr(playback, operation).assert_called_once_with(**expected)


@pytest.mark.parametrize('prepared', [False, True])
def test_legacy_seek_uses_verified_input_when_available_without_changing_source(prepared):
    host, playback, _queues, _settings, _guards, source = host_fixture()
    state = initial_state()
    state.update(media='a', playing=True)
    host.apply({'kind': 'seek', 'data': {'position_ms': 2000}}, state, {'a': source if prepared else source.media})
    extra = {'resolved': source.resolved} if prepared else {}
    playback.seek.assert_called_once_with(2, origin='recovery', **extra)
    playback.play.assert_not_called()


def test_legacy_start_still_uses_existing_playback_without_claiming_atomic_capability():
    host, playback, _queues, _settings, _guards, source = host_fixture()
    host.apply({'kind': 'media_start', 'data': {'media': 'a', 'position_ms': 1500}}, initial_state(), {'a': source})
    playback.play.assert_called_once_with(source.media, start_at=1.5, probe=False, origin='recovery',
                                         start_paused=False, resolved=source.resolved)


@pytest.mark.parametrize('operation', ['queue_set', 'shuffle'])
def test_queue_dispatch_restores_occurrences_without_reshuffling(operation):
    host, playback, queues, _settings, _guards, source = host_fixture()
    state = initial_state()
    state.update(queue=['a', 'a'], current_index=1)
    host.apply({'kind': operation, 'data': {}}, state, {'a': source})
    assert len(queues) == 1 and queues[0][0]['queue'] == ['a', 'a'] and queues[0][0]['current_index'] == 1
    assert queues[0][1] == {'a': source.media}
    assert playback.mock_calls == []


@pytest.mark.parametrize('gain', [None, -8])
def test_gain_dispatch_keeps_frozen_gain_out_of_replaygain_settings(gain):
    host, playback, _queues, _settings, _guards, _source = host_fixture()
    state = initial_state(version=3)
    state['program_gain_db'] = gain
    data = {**state['settings']['replaygain'], 'program_gain_db': gain}
    host.apply({'kind': 'gain_settings', 'data': data}, state, {})
    playback.configure_replaygain.assert_called_once_with(**state['settings']['replaygain'])
    if gain is None:
        playback.set_recipe_program_gain.assert_not_called()
    else:
        playback.set_recipe_program_gain.assert_called_once_with(gain)


def test_other_allowed_settings_and_unknown_operation_do_not_become_commands():
    host, playback, _queues, settings, _guards, _source = host_fixture()
    state = initial_state(version=3)
    policy = {'repeat': 'all', 'consume': False, 'autofill': False}
    host.apply({'kind': 'queue_settings', 'data': policy}, state, {})
    assert settings == [policy]
    host.apply({'kind': 'crossfade_settings', 'data': {'crossfade_ms': 1500}}, state, {})
    playback.set_crossfade_seconds.assert_called_once_with(1.5)
    before = playback.mock_calls[:]
    with pytest.raises(ReplayBlocked, match='unsupported host capability'):
        host.apply({'kind': 'delete', 'data': {}}, state, {})
    assert playback.mock_calls == before


def test_legacy_overlap_is_refused_before_controller_or_queue_changes():
    host, playback, queues, settings, guards, _source = host_fixture()
    state = initial_state()
    state['settings']['crossfade_ms'] = 1000
    with pytest.raises(ReplayBlocked, match='unsupported overlap'):
        host.restore(state, {})
    assert playback.mock_calls == [] and queues == settings == guards == []


def service_fixture(tmp_path, monkeypatch, *, capacity=2):
    playback = Mock(spec=PlaybackController)
    guards = []
    service = SessionRecipeService(
        tmp_path, playback=lambda: playback, lookup_media=lambda _identity: None,
        restore_queue=lambda _state, _resolved: None, configure_queue=lambda _settings: None,
        set_replay_active=guards.append, capacity=capacity,
    )
    monkeypatch.setattr(service, '_ensure_worker', lambda: None)
    return service, guards


def test_service_rejects_conflicting_queue_inputs_and_concurrent_operations(tmp_path, monkeypatch):
    service, _guards = service_fixture(tmp_path, monkeypatch)
    with pytest.raises(RecipeError, match='one committed queue'):
        service.start('evening', queue_ids=['track'], queue_snapshot={})
    service.start('evening')
    with pytest.raises(RecipeError, match='already active'):
        service.start('another')
    assert service.status()['name'] == 'evening' and service._pending.qsize() == 1


@pytest.mark.parametrize('operation', ['record', 'replay'])
def test_service_saturation_does_not_claim_recording_or_replay_ownership(tmp_path, monkeypatch, operation):
    service, guards = service_fixture(tmp_path, monkeypatch, capacity=1)
    service._pending.put_nowait(('occupied', None, 0, None))
    with pytest.raises(RecipeError, match='queue is full'):
        service.start('evening') if operation == 'record' else service.replay('evening')
    assert service.status()['error_code'] == 'overflow'
    assert service.status()['replay_active'] is False
    if operation == 'replay':
        assert guards == [True, False]
    assert not tmp_path.joinpath('evening.jsonl').exists()


def test_inactive_service_rejects_capture_and_invalid_buffering_flags(tmp_path, monkeypatch):
    service, _guards = service_fixture(tmp_path, monkeypatch)
    assert not service.capture_queue_snapshot({})
    assert not service.capture_playback_event(action='delete')
    assert not service.capture_playback_event(stable_id='a' * 24, session_id='s', action='delete', position_seconds=0)
    assert not service.capture_settings('output_device', {})
    assert not service.capture_queue([], None)
    with pytest.raises(RecipeError, match='true or false'):
        service.set_buffering('yes')
    with pytest.raises(RecipeError, match='No prepared recipe'):
        service.seek_replay(0)
    assert service._pending.empty()


@pytest.mark.parametrize('kind', ['wrong_identity', 'live', 'preferred_region'])
def test_service_source_boundary_refuses_unverifiable_or_unrepresented_media(tmp_path, monkeypatch, kind):
    service, _guards = service_fixture(tmp_path, monkeypatch)
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / 'not-opened.wav'), duration=60)
    if kind == 'live':
        media.capabilities.live = True
    elif kind == 'preferred_region':
        media.resolver_data['play_region'] = {'start_seconds': 1}
    service._lookup_media = lambda _identity: media
    expected = 'a' * 24 if kind == 'wrong_identity' else media.stable_id
    with pytest.raises(ReplayBlocked):
        service._media(expected)
    assert not tmp_path.joinpath('not-opened.wav').exists()


def test_cancelled_service_does_not_resolve_or_reacquire_playback(tmp_path, monkeypatch):
    service, guards = service_fixture(tmp_path, monkeypatch)
    service._cancel_replay.set()
    with pytest.raises(ReplayBlocked, match='replay cancelled'):
        service._resolve(reference())
    with pytest.raises(ReplayBlocked, match='replay cancelled'):
        service._set_replay_active(True)
    assert guards == [] and service.status()['replay_active'] is False
