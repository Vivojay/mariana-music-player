import shutil
import wave

import pytest

from mariana.strudel_projects import StrudelProjectError, StrudelProjectStore, render_portable

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node required for terminal WAV export")


def test_offline_render_and_collision(tmp_path):
    store = StrudelProjectStore(tmp_path / "projects.json")
    project = store.create("Study")
    project = store.save(project_id=project.project_id, name=project.name, code=project.code,
                         preview_seconds=1, expected_revision=project.revision)
    target = tmp_path / "my preview.wav"
    render_portable(project, target)
    with wave.open(str(target)) as reader:
        assert (reader.getframerate(), reader.getnframes(), reader.getsampwidth()) == (22050, 22050, 2)
        assert any(reader.readframes(100))
    first = target.read_bytes()
    with pytest.raises(StrudelProjectError, match="already exists"):
        render_portable(project, target)
    assert target.read_bytes() == first


def test_unsupported_source_creates_no_file(tmp_path):
    store = StrudelProjectStore(tmp_path / "projects.json")
    project = store.create("Sample")
    project = store.save(project_id=project.project_id, name=project.name, code='s("bd")',
                         preview_seconds=1, expected_revision=project.revision)
    target = tmp_path / "kit.wav"
    with pytest.raises(StrudelProjectError, match="Electron"):
        render_portable(project, target)
    assert not target.exists()
