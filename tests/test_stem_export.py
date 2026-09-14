import hashlib
import os
import stat
from pathlib import Path

import pytest

import mariana.stems as stems
from mariana.output_targets import BoundOutputTarget
from mariana.stems import FOUR_STEMS, StemError, StemManifest, StemService


@pytest.fixture
def prepared(tmp_path):
    service = StemService(tmp_path / "cache")
    result = service.results / "prepared"
    result.mkdir(parents=True)
    paths = {}
    for name in FOUR_STEMS:
        paths[name] = result / f"{name}.wav"
        paths[name].write_bytes(name.encode() * 4096)
    service._manifest = StemManifest("track", "Test Song", "htdemucs", paths, 1.0)
    yield service, paths, tmp_path / "exports", tmp_path / "exports" / "Test Song-stems"
    service.shutdown()


def test_export_preserves_bytes_and_requires_explicit_bound_overwrite(prepared):
    service, sources, parent, target = prepared
    exported = service.export("track", parent)
    assert tuple(path.name for path in exported) == tuple(f"{name}.wav" for name in FOUR_STEMS)
    assert all(path.read_bytes() == sources[path.stem].read_bytes() for path in exported)
    with pytest.raises(StemError, match="already exists"):
        service.export("track", parent)
    (target / "vocals.wav").write_bytes(b"previous exported version")
    assert service.export("track", parent, overwrite=True) == exported
    assert (target / "vocals.wav").read_bytes() == sources["vocals"].read_bytes()
    assert not list(target.glob("*.partial"))


@pytest.mark.parametrize("overwrite", [False, True])
def test_file_appearing_while_copying_is_never_overwritten(prepared, monkeypatch, overwrite):
    service, _sources, parent, target = prepared
    copy = stems._copy_export_stream

    def concurrent_file(source, destination):
        result = copy(source, destination)
        (target / "vocals.wav").write_bytes(b"unrelated concurrent file")
        return result

    monkeypatch.setattr(stems, "_copy_export_stream", concurrent_file)
    with pytest.raises(StemError, match="appeared after approval"):
        service.export("track", parent, overwrite=overwrite)
    assert (target / "vocals.wav").read_bytes() == b"unrelated concurrent file"
    assert {path.name for path in target.iterdir()} == {"vocals.wav"}


def test_existing_target_replacement_invalidates_overwrite_approval(prepared, monkeypatch):
    service, _sources, parent, target = prepared
    target.mkdir(parents=True)
    victim = target / "vocals.wav"
    victim.write_bytes(b"approved old output")
    copy = stems._copy_export_stream

    def replace_after_approval(source, destination):
        result = copy(source, destination)
        victim.write_bytes(b"new unapproved output")
        return result

    monkeypatch.setattr(stems, "_copy_export_stream", replace_after_approval)
    with pytest.raises(StemError, match="changed after approval"):
        service.export("track", parent, overwrite=True)
    assert victim.read_bytes() == b"new unapproved output"
    assert {path.name for path in target.iterdir()} == {"vocals.wav"}


def test_no_clobber_is_atomic_if_destination_appears_at_activation(prepared, monkeypatch):
    service, _sources, parent, target = prepared
    link = os.link

    def create_at_link(source, destination, *args, **kwargs):
        if Path(destination).name == "vocals.wav":
            Path(destination).write_bytes(b"arrived after final validation")
        return link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", create_at_link)
    with pytest.raises(StemError, match="appeared after approval"):
        service.export("track", parent)
    assert {path.name for path in target.iterdir()} == {"vocals.wav"}
    assert (target / "vocals.wav").read_bytes() == b"arrived after final validation"


def test_source_replaced_before_open_is_rejected(prepared, monkeypatch):
    service, sources, parent, target = prepared
    bind = stems.bind_output_target

    def replace_last_source(path):
        result = bind(path)
        if path.name == "other.wav":
            replacement = sources["vocals"].with_suffix(".replacement")
            replacement.write_bytes(b"unrelated content")
            replacement.replace(sources["vocals"])
        return result

    monkeypatch.setattr(stems, "bind_output_target", replace_last_source)
    with pytest.raises(StemError, match="Prepared stem changed"):
        service.export("track", parent)
    assert not list(target.iterdir())


def test_source_modified_while_copying_is_rejected(prepared, monkeypatch):
    service, sources, parent, target = prepared
    copy = stems._copy_export_stream

    def modify_source(source, destination):
        result = copy(source, destination)
        path = sources["vocals"]
        before = path.stat()
        path.write_bytes(b"x" * before.st_size)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return result

    monkeypatch.setattr(stems, "_copy_export_stream", modify_source)
    with pytest.raises(StemError, match="bytes changed"):
        service.export("track", parent)
    assert not list(target.iterdir())


def test_equal_sized_corrupt_copy_is_rejected(prepared, monkeypatch):
    service, _sources, parent, target = prepared

    def corrupt(source, destination):
        original = source.read()
        destination.write(b"x" * len(original))
        return hashlib.sha256(original).hexdigest()

    monkeypatch.setattr(stems, "_copy_export_stream", corrupt)
    with pytest.raises(StemError, match="bytes changed"):
        service.export("track", parent)
    assert not list(target.iterdir())


def test_partial_write_failure_cleans_only_exclusive_owned_temporary(prepared, monkeypatch):
    service, _sources, parent, target = prepared
    target.mkdir(parents=True)
    sentinel = target / f".vocals.{os.getpid()}.partial"
    sentinel.write_bytes(b"another operation")

    def disk_full(_source, destination):
        destination.write(b"incomplete")
        destination.flush()
        raise OSError("simulated disk exhaustion")

    monkeypatch.setattr(stems, "_copy_export_stream", disk_full)
    with pytest.raises(StemError, match="filesystem operation failed"):
        service.export("track", parent)
    assert {path.name for path in target.iterdir()} == {sentinel.name}
    assert sentinel.read_bytes() == b"another operation"


def test_copy_failure_on_last_stem_does_not_activate_earlier_stems(prepared, monkeypatch):
    service, _sources, parent, target = prepared
    copy = stems._copy_export_stream
    calls = 0

    def last_fails(source, destination):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("simulated read failure")
        return copy(source, destination)

    monkeypatch.setattr(stems, "_copy_export_stream", last_fails)
    with pytest.raises(StemError, match="filesystem operation failed"):
        service.export("track", parent)
    assert not list(target.iterdir())


def test_source_changed_after_its_copy_rejects_whole_export(prepared, monkeypatch):
    service, sources, parent, target = prepared
    copy = stems._copy_export_stream
    calls = 0

    def change_previous_source(source, destination):
        nonlocal calls
        calls += 1
        result = copy(source, destination)
        if calls == 4:
            sources["vocals"].write_bytes(b"updated prepared stem")
        return result

    monkeypatch.setattr(stems, "_copy_export_stream", change_previous_source)
    with pytest.raises(StemError, match="Prepared stem changed"):
        service.export("track", parent)
    assert not list(target.iterdir())


def test_staged_file_replacement_is_not_activated_or_deleted(prepared, monkeypatch):
    service, _sources, parent, target = prepared
    revalidate = stems._revalidate_export_directories
    count = 0
    replacement_path = None

    def replace_staged(bindings):
        nonlocal count, replacement_path
        count += 1
        if count == 5:
            replacement_path = next(target.glob(".vocals.*.partial"))
            different = target / "different-file"
            different.write_bytes(b"unrelated replacement")
            different.replace(replacement_path)
        return revalidate(bindings)

    monkeypatch.setattr(stems, "_revalidate_export_directories", replace_staged)
    with pytest.raises(StemError, match="Staged stem changed"):
        service.export("track", parent)
    assert replacement_path is not None
    assert {path.name for path in target.iterdir()} == {replacement_path.name}
    assert replacement_path.read_bytes() == b"unrelated replacement"


def test_activation_failure_retains_completed_outputs_and_reports_partial_result(prepared, monkeypatch):
    service, sources, parent, target = prepared
    activate = BoundOutputTarget.activate

    def fail_second(bound, temporary):
        if bound.path.name == "drums.wav":
            raise OSError("simulated activation failure")
        return activate(bound, temporary)

    monkeypatch.setattr(BoundOutputTarget, "activate", fail_second)
    with pytest.raises(StemError, match=r"1 completed output\(s\) retained"):
        service.export("track", parent)
    assert {path.name for path in target.iterdir()} == {"vocals.wav"}
    assert (target / "vocals.wav").read_bytes() == sources["vocals"].read_bytes()


def test_changed_export_directory_is_not_followed_during_activation_or_cleanup(prepared, monkeypatch):
    service, _sources, parent, target = prepared
    alternate = parent / "original-export"
    revalidate = stems._revalidate_export_directories
    count = 0

    def replace_after_staging(bindings):
        nonlocal count
        count += 1
        if count == 5:
            target.rename(alternate)
            target.mkdir()
            for owned in alternate.iterdir():
                (target / owned.name).write_bytes(b"unrelated replacement")
        return revalidate(bindings)

    monkeypatch.setattr(stems, "_revalidate_export_directories", replace_after_staging)
    with pytest.raises(StemError, match="directory changed"):
        service.export("track", parent)
    assert all(path.read_bytes() == b"unrelated replacement" for path in target.iterdir())
    assert len(list(alternate.glob("*.partial"))) == 4
    assert not list(alternate.glob("*.wav"))


def test_linked_source_and_destination_are_rejected(prepared):
    service, sources, parent, target = prepared
    alias = sources["vocals"].with_suffix(".alias")
    os.link(sources["vocals"], alias)
    with pytest.raises(StemError, match="unlinked regular"):
        service.export("track", parent)
    alias.unlink()
    target.mkdir(parents=True, exist_ok=True)
    unrelated = parent / "unrelated.wav"
    unrelated.write_bytes(b"other content")
    os.link(unrelated, target / "vocals.wav")
    with pytest.raises(StemError, match="unlinked regular"):
        service.export("track", parent, overwrite=True)


def test_reparse_directory_is_rejected_before_outputs(prepared, monkeypatch):
    service, _sources, parent, target = prepared
    parent.mkdir()
    lstat = Path.lstat

    def reparse(path):
        result = lstat(path)
        if path == parent:
            from types import SimpleNamespace

            return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
        return result

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(StemError, match="reparse"):
        service.export("track", parent)
    assert not target.exists()


def test_parent_traversal_and_invalid_stem_names_are_rejected(prepared):
    service, sources, parent, _target = prepared
    with pytest.raises(StemError, match="parent traversal"):
        service.export("track", parent / ".." / "another")
    service._manifest = StemManifest("track", "Test", "htdemucs", {"../outside": sources["vocals"]}, 1)
    with pytest.raises(StemError, match="identities"):
        service.export("track", parent)


def test_link_detection_covers_symbolic_links_and_windows_junction_attributes():
    assert stems._export_link(os.stat_result((stat.S_IFLNK, 0, 0, 1, 0, 0, 1, 0, 0, 0)))
