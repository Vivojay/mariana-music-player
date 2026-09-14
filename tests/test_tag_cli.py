from types import SimpleNamespace

import pytest

import main
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.navigation import NavigationContext, NavigationEntry, NavigationScope
from mariana.tag_commands import TagCommandResult
from mariana.tags import TagError


@pytest.mark.parametrize("topic", ["tag", "tags"])
def test_tag_help_has_a_dedicated_topic_and_examples(monkeypatch, topic):
    printed = []
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))

    rows = main.help_command([topic])

    assert rows == (next(row for row in main.HELP_GROUPS if row[0] == "Tags"),)
    assert "tag help/list/create/attach/detach/show/rename/delete/find/play/queue/group" in rows[0][1]
    output = "\n".join(printed)
    assert 'tag attach current "Late night"' in output
    assert "tag play 1" in output


def test_tag_host_resolves_current_and_library_once_without_url_parsing(monkeypatch):
    media = MediaRef(MediaSource.YOUTUBE, 'abcdefghijk', title='Named video')
    bindings = {}
    monkeypatch.setattr(main.vas.controller, 'snapshot', lambda: PlaybackSnapshot(PlaybackState.PAUSED, media=media))
    monkeypatch.setattr(main, '_preference_media', lambda value: value)
    monkeypatch.setattr(main, '_library_media', lambda value: bindings.setdefault('index', value) or media)
    monkeypatch.setattr(main, 'IPrint', lambda *_args, **_kwargs: None)

    def service(_store, **kwargs):
        bindings.update(kwargs)
        return SimpleNamespace(execute=lambda arguments: TagCommandResult('list', 'No tags'))

    monkeypatch.setattr(main, 'TagCommandService', service)
    main.tag_command(['list'])
    assert bindings['resolve_target']('current') is media
    bindings['resolve_target']('3')
    assert bindings['index'] == 3
    with pytest.raises(ValueError):
        bindings['resolve_target']('https://example.invalid/private')


def test_tag_results_use_shared_size_format_rating_and_current_markers(monkeypatch):
    media = MediaRef(MediaSource.LOCAL, '/example/song.unknown', title='Song')
    entry = NavigationEntry(media, media.stable_id, 1, 'Song', NavigationScope.RESULTS)
    printed = []
    monkeypatch.setattr(main, '_LAST_TAG_CONTEXT', None)
    monkeypatch.setattr(main, '_LAST_SEARCH_CONTEXT', None)
    monkeypatch.setattr(main, 'TagCommandService', lambda *_args, **_kwargs: SimpleNamespace(
        execute=lambda arguments: TagCommandResult('find', '1 result', entries=(entry,)),
    ))
    monkeypatch.setattr(main, 'IPrint', lambda value, **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, '_media_listing_fields', lambda value: ('2.0 MiB', 'WebM / Opus'))
    monkeypatch.setattr(main, '_active_media_marker', lambda value: '▶')
    monkeypatch.setattr(main, '_favorite_marker', lambda value: '♥')
    monkeypatch.setattr(main, '_media_rating', lambda value: 3)
    monkeypatch.setattr(main, '_blocked_label', lambda label, value: label)
    main.tag_command(['find', '--all', 'jazz'])
    output = '\n'.join(printed)
    assert all(value in output for value in ('2.0 MiB', 'WebM / Opus', '▶', '♥', '★★★', 'Fav', 'Rating', 'Song', 'tag play N'))
    assert main._LAST_TAG_CONTEXT.entries == (entry,)
    assert main._LAST_SEARCH_CONTEXT.entries == (entry,)


@pytest.mark.parametrize('operation', ['play', 'queue'])
def test_tag_selection_revalidates_bound_result_and_block_policy(monkeypatch, operation):
    media = MediaRef(MediaSource.YOUTUBE, 'abcdefghijk', title='Selected')
    entry = NavigationEntry(media, media.stable_id, 1, 'Selected', NavigationScope.RESULTS)
    monkeypatch.setattr(main, '_LAST_TAG_CONTEXT', NavigationContext(NavigationScope.RESULTS, (entry,), -1))
    monkeypatch.setattr(main, '_NAVIGATION_CONTEXT', None)
    calls = []
    monkeypatch.setattr(main, 'TagCommandService', lambda *_args, **_kwargs: SimpleNamespace(
        resolve_result=lambda value: calls.append(('resolve', value.stable_id)) or value,
    ))
    monkeypatch.setattr(main, '_ensure_media_playable', lambda value: calls.append(('policy', value.stable_id)))
    monkeypatch.setattr(main, '_play_navigation_entry', lambda value: calls.append(('play', value.stable_id)))
    monkeypatch.setattr(main.QUEUE, 'extend', lambda values: calls.append(('queue', values[0].stable_id)))
    monkeypatch.setattr(main, '_emit_queue_desktop_state', lambda: None)
    monkeypatch.setattr(main, 'IPrint', lambda *_args, **_kwargs: None)
    main.tag_command([operation, '1'])
    assert calls == [('resolve', media.stable_id), ('policy', media.stable_id), (operation, media.stable_id)]
    with pytest.raises(TagError):
        main.tag_command([operation, '2'])
