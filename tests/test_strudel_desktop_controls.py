from __future__ import annotations

import hashlib
import io
import wave

import main
from mariana.paths import RuntimePaths
from mariana.strudel_projects import StrudelProjectStore


class DesktopEvents:
    enabled = True

    def __init__(self):
        self.events = []

    def emit(self, event, payload=None):
        self.events.append((event, payload))
        return True


def wav_bytes(seconds=1):
    content = io.BytesIO()
    with wave.open(content, "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(48_000)
        stream.writeframes(b"\0\0\0\0" * (48_000 * seconds))
    return content.getvalue()


def setup_store(monkeypatch, tmp_path):
    paths = RuntimePaths(tmp_path / "resources", tmp_path / "runtime")
    store = StrudelProjectStore(paths.state("strudel", "projects.json"))
    events = DesktopEvents()
    monkeypatch.setattr(main, "RUNTIME_PATHS", paths)
    monkeypatch.setattr(main, "STRUDEL_PROJECTS", store)
    monkeypatch.setattr(main, "DESKTOP_CONTROL", events)
    return paths, store, events


def test_desktop_strudel_save_and_delete_are_revision_bound(monkeypatch, tmp_path):
    _paths, store, events = setup_store(monkeypatch, tmp_path)
    save = main._desktop_control_request(
        "strudel.save",
        {
            "project_id": None,
            "name": "Night pattern",
            "code": 'note("c3")',
            "preview_seconds": 12,
            "revision": None,
        },
    )
    assert save == {"ok": True}
    project = store.get("Night pattern")
    assert events.events[-1][0] == "strudel"

    assert main._desktop_control_request(
        "strudel.delete", {"project_id": project.project_id, "revision": project.revision + 1}
    )["ok"] is False
    assert main._desktop_control_request(
        "strudel.delete", {"project_id": project.project_id, "revision": project.revision}
    ) == {"ok": True}


def test_rendered_strudel_preview_is_verified_then_uses_ephemeral_local_playback(monkeypatch, tmp_path):
    paths, store, _events = setup_store(monkeypatch, tmp_path)
    project = store.save(
        project_id=None,
        name="Preview",
        code='note("c3")',
        preview_seconds=1,
        expected_revision=None,
    )
    content = wav_bytes()
    digest = hashlib.sha256(content).hexdigest()
    artifact_name = f"{project.project_id}-{digest}.wav"
    artifact = paths.temporary / "strudel" / artifact_name
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    played = []
    monkeypatch.setattr(
        main,
        "play_local_default_player",
        lambda path, _songindex, **kwargs: played.append((path, kwargs)),
    )

    result = main._desktop_control_request(
        "strudel.preview",
        {"project_id": project.project_id, "revision": project.revision, "artifact_name": artifact_name},
    )

    assert result == {"ok": True}
    assert played[0][0] == str(artifact)
    assert played[0][1]["ephemeral"] is True
    assert played[0][1]["media"].title == "Preview"
    assert played[0][1]["media"].provenance == "strudel-render"


def test_rendered_strudel_preview_rejects_stale_or_unverified_artifacts(monkeypatch, tmp_path):
    paths, store, _events = setup_store(monkeypatch, tmp_path)
    project = store.save(
        project_id=None,
        name="Preview",
        code='note("c3")',
        preview_seconds=1,
        expected_revision=None,
    )
    bad_name = f"{project.project_id}-{'0' * 64}.wav"
    artifact = paths.temporary / "strudel" / bad_name
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(wav_bytes())

    assert main._desktop_control_request(
        "strudel.preview",
        {"project_id": project.project_id, "revision": project.revision + 1, "artifact_name": bad_name},
    )["ok"] is False
    rejected = main._desktop_control_request(
        "strudel.preview",
        {"project_id": project.project_id, "revision": project.revision, "artifact_name": bad_name},
    )
    assert rejected == {"ok": False, "error": "Rendered preview failed its integrity check"}


def test_corrupt_optional_project_state_does_not_block_startup(monkeypatch, tmp_path):
    _paths, store, events = setup_store(monkeypatch, tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text("not json", encoding="utf-8")
    messages = []
    monkeypatch.setattr(main, "IPrint", lambda message, **_kwargs: messages.append(message))

    projection = main._emit_startup_strudel_projects()

    assert projection["projects"] == []
    assert events.events[-1] == ("strudel", projection)
    assert messages == ["[WARNING: Pattern projects were not loaded: Saved Strudel projects are unavailable or corrupt]"]
