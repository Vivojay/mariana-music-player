"""Project commands use revision-bound storage, not a terminal code evaluator."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import main
from mariana.strudel_projects import StrudelProjectError, StrudelProjectStore


@pytest.fixture
def projects(tmp_path, monkeypatch):
    store = StrudelProjectStore(tmp_path / 'projects.json')
    monkeypatch.setattr(main, 'STRUDEL_PROJECTS', store)
    monkeypatch.setattr(main, 'IPrint', Mock())
    monkeypatch.setattr(main, 'DESKTOP_CONTROL', SimpleNamespace(enabled=True, emit=Mock()))
    monkeypatch.setattr(main, '_emit_strudel_projects', Mock())
    monkeypatch.setattr(main, 'play_vas_media', Mock(side_effect=AssertionError('Commands must request a bounded render')))
    return store


@pytest.mark.parametrize('arguments', [[], ['open'], ['editor']])
def test_open_uses_existing_desktop_surface_only(projects, arguments):
    main.strudel_command(arguments)
    main._emit_strudel_projects.assert_called_once_with(open_requested=True)
    assert projects.list() == []
    main.DESKTOP_CONTROL.enabled = False
    main._emit_strudel_projects.reset_mock()
    with pytest.raises(StrudelProjectError, match='desktop'):
        main.strudel_command(arguments)
    main._emit_strudel_projects.assert_not_called()


def test_create_list_show_and_reload_preserve_code_without_executing_it(projects):
    assert main.strudel_command(['list']) == []
    assert 'no Strudel projects' in main.IPrint.call_args.args[0]
    created = main.strudel_command(['new', 'Evening', 'Pattern'])
    assert created.name == 'Evening Pattern'
    main._emit_strudel_projects.assert_called_with(open_requested=True, selected_id=created.project_id)
    assert main.strudel_command(['ls']) == [created]
    listed = main.IPrint.call_args.args[0]
    assert all(value in listed for value in ('Evening Pattern', 'Preview seconds', 'Revision'))
    assert main.strudel_command(['show', 'Evening', 'Pattern']) == created
    assert created.code in main.IPrint.call_args.args[0]
    assert StrudelProjectStore(projects.path).get(created.project_id) == created
    main.DESKTOP_CONTROL.emit.assert_not_called()
    main.play_vas_media.assert_not_called()


def test_cli_only_can_manage_projects_but_cannot_start_an_unavailable_renderer(projects):
    main.DESKTOP_CONTROL.enabled = False
    created = main.strudel_command(['new', 'Offline'])
    main._emit_strudel_projects.assert_called_with(open_requested=False, selected_id=created.project_id)
    assert main.strudel_command(['show', created.project_id]) == created
    with pytest.raises(StrudelProjectError, match='rendered by'):
        main.strudel_command(['play', created.project_id])
    main.DESKTOP_CONTROL.emit.assert_not_called()
    main.play_vas_media.assert_not_called()


def test_play_requests_exact_saved_project_via_structured_event(projects):
    created = projects.create('Selected')
    assert main.strudel_command(['play', 'Selected']) == created
    main._emit_strudel_projects.assert_called_once_with(open_requested=True, selected_id=created.project_id)
    main.DESKTOP_CONTROL.emit.assert_called_once_with('strudel-render-requested', {'project_id': created.project_id})
    main.play_vas_media.assert_not_called()


def test_delete_decline_and_revision_change_preserve_project(projects, monkeypatch):
    created = projects.create('Preserve me')
    monkeypatch.setattr(main, '_confirm_action', lambda *_a, **_k: False)
    assert main.strudel_command(['delete', created.project_id]) is None
    assert projects.get(created.project_id) == created
    main._emit_strudel_projects.assert_not_called()

    def concurrent_edit(*_args, **_kwargs):
        projects.save(project_id=created.project_id, name=created.name, code='note("d3")',
                      preview_seconds=12, expected_revision=created.revision)
        return True

    monkeypatch.setattr(main, '_confirm_action', concurrent_edit)
    with pytest.raises(StrudelProjectError, match='changed'):
        main.strudel_command(['delete', created.project_id])
    assert projects.get(created.project_id).code == 'note("d3")'
    main._emit_strudel_projects.assert_not_called()


def test_explicit_delete_updates_storage_and_projection(projects, monkeypatch):
    created = projects.create('Delete me')
    confirm = Mock(return_value=True)
    monkeypatch.setattr(main, '_confirm_action', confirm)
    assert main.strudel_command(['delete', 'Delete', 'me', '--yes']) == created
    assert confirm.call_args.kwargs == {'assume_yes': True}
    assert StrudelProjectStore(projects.path).list() == []
    main._emit_strudel_projects.assert_called_once_with()


@pytest.mark.parametrize('arguments', [
    ['unknown'], ['open', 'extra'], ['list', 'extra'], ['new'], ['show'], ['play'], ['delete', '--yes'],
])
def test_invalid_project_commands_never_write_or_render(projects, arguments):
    with pytest.raises(StrudelProjectError, match='Usage'):
        main.strudel_command(arguments)
    assert not projects.path.exists()
    main.DESKTOP_CONTROL.emit.assert_not_called()
    main._emit_strudel_projects.assert_not_called()
