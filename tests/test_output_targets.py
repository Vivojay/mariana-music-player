import os
from pathlib import Path

import pytest

from mariana.output_targets import OutputTargetError, bind_output_target


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
