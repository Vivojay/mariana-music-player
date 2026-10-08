from __future__ import annotations

import json

import pytest

from mariana.strudel_projects import (
    MAX_CODE_BYTES,
    STARTER_CODE,
    StrudelProjectError,
    StrudelProjectStore,
)


def test_strudel_project_round_trip_and_revision_guard(tmp_path):
    path = tmp_path / "state" / "projects.json"
    store = StrudelProjectStore(path)

    created = store.create("Night pattern")
    assert created.code == STARTER_CODE
    assert created.revision == 1
    assert store.get("night PATTERN") == created

    updated = store.save(
        project_id=created.project_id,
        name="Night pattern",
        code='note("c3 e3 g3")',
        preview_seconds=24,
        expected_revision=created.revision,
    )
    assert updated.revision == 2
    assert StrudelProjectStore(path).get(created.project_id) == updated
    with pytest.raises(StrudelProjectError, match="changed"):
        store.save(
            project_id=created.project_id,
            name=created.name,
            code=created.code,
            preview_seconds=16,
            expected_revision=created.revision,
        )


def test_strudel_projects_validate_names_code_duration_and_duplicates(tmp_path):
    store = StrudelProjectStore(tmp_path / "projects.json")
    store.create("One")
    with pytest.raises(StrudelProjectError, match="already exists"):
        store.create(" one ")
    with pytest.raises(StrudelProjectError, match="64 KiB"):
        store.save(
            project_id=None,
            name="Large",
            code="x" * (MAX_CODE_BYTES + 1),
            preview_seconds=10,
            expected_revision=None,
        )
    with pytest.raises(StrudelProjectError, match="whole number"):
        store.save(
            project_id=None,
            name="Duration",
            code='note("c3")',
            preview_seconds=True,
            expected_revision=None,
        )


def test_strudel_delete_is_revision_bound_and_projection_is_sanitized(tmp_path):
    store = StrudelProjectStore(tmp_path / "projects.json")
    project = store.create("Delete me")
    projection = store.projection(open_requested=True, selected_id=project.project_id)
    assert projection["open_requested"] is True
    assert projection["selected_id"] == project.project_id
    assert projection["limits"] == {
        "max_projects": 100,
        "max_code_bytes": 64 * 1024,
        "max_preview_seconds": 60,
    }
    with pytest.raises(StrudelProjectError, match="changed"):
        store.delete(project.project_id, project.revision + 1)
    assert store.delete(project.project_id, project.revision) == project
    assert store.list() == []


def test_strudel_store_rejects_corrupt_or_future_data(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"schema_version": 99, "projects": []}), encoding="utf-8")
    with pytest.raises(StrudelProjectError, match="unsupported format"):
        StrudelProjectStore(path).list()
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(StrudelProjectError, match="corrupt"):
        StrudelProjectStore(path).list()
