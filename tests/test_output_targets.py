import os
from pathlib import Path

import pytest

from mariana.output_targets import BoundOutputTarget, OutputTargetError, bind_output_target


def test_new_output_activates_without_clobbering(tmp_path: Path):
    destination = tmp_path / "output.mp3"
    target = bind_output_target(destination)
    staged = tmp_path / ".staged.mp3"
    staged.write_bytes(b"new")

    assert target.activate(staged) == destination.resolve()
    assert destination.read_bytes() == b"new"
    assert not staged.exists()


def test_existing_output_requires_same_bound_file(tmp_path: Path):
    destination = tmp_path / "output.mp3"
    destination.write_bytes(b"old")
    target = bind_output_target(destination)
    replacement = tmp_path / "replacement.mp3"
    replacement.write_bytes(b"changed")
    os.replace(replacement, destination)
    staged = tmp_path / ".staged.mp3"
    staged.write_bytes(b"new")

    with pytest.raises(OutputTargetError, match="changed after approval"):
        target.activate(staged)

    assert destination.read_bytes() == b"changed"
    assert staged.read_bytes() == b"new"


def test_absent_output_refuses_file_appearing_after_binding(tmp_path: Path):
    destination = tmp_path / "output.mp3"
    target = bind_output_target(destination)
    destination.write_bytes(b"other")
    staged = tmp_path / ".staged.mp3"
    staged.write_bytes(b"new")

    with pytest.raises(OutputTargetError, match="appeared after approval"):
        target.activate(staged)

    assert destination.read_bytes() == b"other"


def test_output_binding_rejects_symlink_and_directory(tmp_path: Path):
    directory = tmp_path / "directory.m3u8"
    directory.mkdir()
    with pytest.raises(OutputTargetError, match="regular file"):
        bind_output_target(directory)

    link = tmp_path / "linked.m3u8"
    try:
        link.symlink_to(tmp_path / "target.m3u8")
    except OSError:
        pytest.skip("symbolic links are unavailable in this environment")
    with pytest.raises(OutputTargetError, match="Symbolic-link"):
        bind_output_target(link)


def test_output_binding_rejects_parent_traversal(tmp_path: Path):
    with pytest.raises(OutputTargetError, match="parent traversal"):
        bind_output_target(tmp_path / "folder" / ".." / "output.mp3")


@pytest.mark.parametrize("exists", [False, True])
def test_stored_approval_roundtrip_preserves_exact_target(tmp_path: Path, exists: bool):
    destination = tmp_path / "output.wav"
    if exists:
        destination.write_bytes(b"original")
    target = bind_output_target(destination)
    restored = BoundOutputTarget.from_dict(target.to_dict())
    assert restored == target
    assert restored.existed is exists
    staged = tmp_path / "staged.wav"
    staged.write_bytes(b"complete output")

    assert restored.activate(staged) == destination
    assert destination.read_bytes() == b"complete output"
    assert not staged.exists()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"path": "output", "parent_signature": None},
        {"path": "output", "parent_signature": ["invalid", 2, 3]},
        {"path": "output", "parent_signature": [1, 2]},
        {"path": "output", "parent_signature": [1, 2, 3], "file_signature": [1, 2, 3]},
    ],
)
def test_malformed_stored_approval_is_typed(payload):
    with pytest.raises(OutputTargetError, match="Stored output approval is invalid"):
        BoundOutputTarget.from_dict(payload)


def test_replaced_parent_refuses_activation_and_preserves_both_directories(tmp_path: Path):
    parent = tmp_path / "exports"
    parent.mkdir()
    destination = parent / "output.wav"
    destination.write_bytes(b"approved output")
    target = bind_output_target(destination)
    retired = tmp_path / "retired"
    parent.rename(retired)
    parent.mkdir()
    destination.write_bytes(b"unrelated replacement")
    staged = tmp_path / "staged.wav"
    staged.write_bytes(b"new output")

    with pytest.raises(OutputTargetError, match="changed after approval"):
        target.activate(staged)

    assert (retired / "output.wav").read_bytes() == b"approved output"
    assert destination.read_bytes() == b"unrelated replacement"
    assert staged.read_bytes() == b"new output"


@pytest.mark.parametrize("replacement", ["missing", "directory"])
def test_approved_file_cannot_disappear_or_become_directory(tmp_path: Path, replacement: str):
    destination = tmp_path / "output.wav"
    destination.write_bytes(b"original")
    target = bind_output_target(destination)
    destination.unlink()
    if replacement == "directory":
        destination.mkdir()
    staged = tmp_path / "staged.wav"
    staged.write_bytes(b"new")

    with pytest.raises(OutputTargetError, match="changed after approval"):
        target.activate(staged)

    assert staged.read_bytes() == b"new"
    assert destination.is_dir() if replacement == "directory" else not destination.exists()


def test_missing_parent_and_missing_staged_output_are_refused(tmp_path: Path):
    parent = tmp_path / "exports"
    target = bind_output_target(parent / "output.wav")
    staged = tmp_path / "staged.wav"
    with pytest.raises(OutputTargetError, match="Generated output is unavailable"):
        target.activate(staged)
    parent.rmdir()
    staged.write_bytes(b"new")

    with pytest.raises(OutputTargetError, match="changed after approval"):
        target.activate(staged)

    assert staged.read_bytes() == b"new"
    assert not parent.exists()


def test_atomic_activation_refuses_target_appearing_after_revalidation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    destination = tmp_path / "output.wav"
    target = bind_output_target(destination)
    staged = tmp_path / "staged.wav"
    staged.write_bytes(b"new")
    real_link = os.link

    def competing_link(source, output):
        Path(output).write_bytes(b"competing writer")
        return real_link(source, output)

    monkeypatch.setattr(os, "link", competing_link)
    with pytest.raises(OutputTargetError, match="appeared after approval"):
        target.activate(staged)

    assert destination.read_bytes() == b"competing writer"
    assert staged.read_bytes() == b"new"


@pytest.mark.parametrize("existing", [False, True])
def test_activation_filesystem_failure_keeps_staged_and_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool,
):
    destination = tmp_path / "output.wav"
    if existing:
        destination.write_bytes(b"original")
    target = bind_output_target(destination)
    staged = tmp_path / "staged.wav"
    staged.write_bytes(b"complete new output")

    def refused(*_args, **_kwargs):
        raise PermissionError("activation denied")

    monkeypatch.setattr(os, "replace" if existing else "link", refused)
    with pytest.raises(OutputTargetError, match=r"Could not replace|Could not activate"):
        target.activate(staged)

    assert staged.read_bytes() == b"complete new output"
    if existing:
        assert destination.read_bytes() == b"original"
    else:
        assert not destination.exists()


def test_parent_creation_failure_is_typed_without_modifying_existing_file(tmp_path: Path):
    parent = tmp_path / "not-a-directory"
    parent.write_bytes(b"keep")

    with pytest.raises(OutputTargetError, match="could not be bound safely"):
        bind_output_target(parent / "output.wav")

    assert parent.read_bytes() == b"keep"


def test_revalidation_permission_error_is_typed_and_preserves_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    destination = tmp_path / "output.wav"
    destination.write_bytes(b"original")
    target = bind_output_target(destination)
    original = Path.stat

    def denied(path: Path, *args, **kwargs):
        if path == destination:
            raise PermissionError("read access denied")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", denied)
        with pytest.raises(OutputTargetError, match="could not be revalidated safely"):
            target.revalidate()

    assert destination.read_bytes() == b"original"
