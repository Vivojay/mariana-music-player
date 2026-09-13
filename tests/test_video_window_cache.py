import json
import os
import subprocess
import sys

import pytest

from mariana import video_window_cache as cache


def abandon(store):
    """Model the OS releasing a crashed process's lease, without normal cleanup."""
    assert store._fd is not None
    cache._unlock(store._fd)
    os.close(store._fd)
    store._fd = None


def test_constructor_is_lazy_and_regular_cleanup_removes_only_owned_files(tmp_path):
    root = tmp_path / "video"
    store = cache.VideoWindowCache(root)
    assert not root.exists()
    window = store.allocate()
    with store.writer(window) as writer:
        writer.write(b"picture")
    legacy = root / ("a" * 32 + ".mp4")
    legacy.write_bytes(b"legacy")
    ordinary = root / "my-video.mp4"
    ordinary.write_bytes(b"user media")
    assert store._record is not None
    assert store._fd is not None
    os.lseek(store._fd, 0, os.SEEK_SET)
    saved_record = os.read(store._fd, cache.MAX_RECORD_BYTES).decode()
    manifest = json.loads(saved_record)
    assert set(manifest) == {"version", "windows"}
    assert set(manifest["windows"]) == {window.name}
    assert str(tmp_path) not in saved_record
    store.close()
    assert not window.exists()
    assert legacy.read_bytes() == b"legacy"
    assert ordinary.read_bytes() == b"user media"
    assert set(root.iterdir()) == {legacy, ordinary}


def test_live_owner_is_preserved_and_crash_left_partial_window_is_recovered(tmp_path):
    first = cache.VideoWindowCache(tmp_path)
    window = first.allocate()
    with first.writer(window) as writer:
        writer.write(b"partial picture")
    second = cache.VideoWindowCache(tmp_path)
    other = second.allocate()
    assert window.read_bytes() == b"partial picture"
    abandon(first)
    third = cache.VideoWindowCache(tmp_path)
    latest = third.allocate()
    assert not window.exists()
    assert other.exists() and latest.exists()
    second.close()
    third.close()
    assert not list(tmp_path.iterdir())


def test_separate_process_lease_excludes_recovery_until_process_exits(tmp_path):
    program = (
        "import sys; from pathlib import Path; from mariana.video_window_cache import VideoWindowCache; "
        "store=VideoWindowCache(Path(sys.argv[1])); p=store.allocate(); "
        "print(p.name, flush=True); sys.stdin.readline()"
    )
    process = subprocess.Popen([sys.executable, "-c", program, str(tmp_path)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout is not None
        name = process.stdout.readline().strip()
        assert cache._WINDOW.fullmatch(name)
        live = tmp_path / name
        store = cache.VideoWindowCache(tmp_path)
        store.allocate()
        assert live.exists()
        store.close()
        assert process.stdin is not None
        process.stdin.write("exit\n")
        process.stdin.flush()
        process.wait(timeout=5)
        reopened = cache.VideoWindowCache(tmp_path)
        reopened.allocate()
        assert not live.exists()
        reopened.close()
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
    assert not list(tmp_path.iterdir())


def test_replaced_window_is_not_deleted_or_opened_for_writing(tmp_path):
    store = cache.VideoWindowCache(tmp_path)
    window = store.allocate()
    saved = tmp_path / "original-kept.mp4"
    window.rename(saved)
    window.write_bytes(b"replacement source")
    with pytest.raises(OSError, match="not owned"):
        store.writer(window)
    with pytest.raises(OSError, match="changed"):
        store.validate(window)
    assert not store.remove(window)
    abandon(store)
    reopened = cache.VideoWindowCache(tmp_path)
    reopened.allocate()
    reopened.close()
    assert window.read_bytes() == b"replacement source"
    assert saved.exists()


def test_symlink_hardlink_and_record_path_traversal_are_never_followed(tmp_path):
    root = tmp_path / "cache"
    store = cache.VideoWindowCache(root)
    window = store.allocate()
    saved = tmp_path / "outside.mp4"
    window.rename(saved)
    try:
        window.symlink_to(saved)
    except OSError:
        # Windows installations may disallow symlink creation; hardlinks remain
        # an actual filesystem test of the same no-aliased-source requirement.
        os.link(saved, window)
    with pytest.raises(OSError, match="ordinary owned file"):
        store.remove(window)
    abandon(store)
    assert store._record is not None
    hostile = root / (".mariana-video-" + "b" * 32 + ".json")
    hostile.write_text(json.dumps({"version": 1, "windows": {"../outside.mp4": [0, 0, 0]}}))
    reopened = cache.VideoWindowCache(root)
    reopened.allocate()
    reopened.close()
    assert saved.exists() and window.exists() and hostile.exists()


@pytest.mark.parametrize("payload", [b"not json", b"[]", b'{"version": 2, "windows": {}}', b"x" * 8193],
                         ids=["malformed", "wrong-shape", "unknown-version", "oversized"])
def test_malformed_or_oversized_records_are_preserved(tmp_path, payload):
    record = tmp_path / (".mariana-video-" + "c" * 32 + ".json")
    record.write_bytes(payload)
    store = cache.VideoWindowCache(tmp_path)
    store.allocate()
    store.close()
    assert record.read_bytes() == payload


def test_root_replacement_stops_cleanup_and_never_touches_new_directory(tmp_path):
    root = tmp_path / "cache"
    store = cache.VideoWindowCache(root)
    window = store.allocate()
    moved = tmp_path / "moved"
    if os.name == "nt":
        # The live lease also prevents renaming its containing directory.
        with pytest.raises(PermissionError):
            root.rename(moved)
    abandon(store)
    root.rename(moved)
    root.mkdir()
    substitute = root / window.name
    substitute.write_bytes(b"unrelated")
    with pytest.raises(OSError, match="directory changed"):
        store.remove(window)
    store.close()
    assert substitute.read_bytes() == b"unrelated"
    assert (moved / window.name).exists()


def test_cache_reparse_root_is_refused_without_touching_target(tmp_path):
    target = tmp_path / "external"
    target.mkdir()
    source = target / "keep.mp4"
    source.write_bytes(b"source")
    linked = tmp_path / "cache"
    if os.name == "nt":
        # Junction creation is available without the symlink privilege.
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(target)],
                                capture_output=True, check=False)
        assert result.returncode == 0
    else:
        linked.symlink_to(target, target_is_directory=True)
    try:
        with pytest.raises(OSError, match="ordinary owned file"):
            cache.VideoWindowCache(linked).allocate()
        assert set(target.iterdir()) == {source}
        assert source.read_bytes() == b"source"
    finally:
        if os.name == "nt":
            linked.rmdir()
        else:
            linked.unlink()


def test_output_creation_and_writer_never_replace_existing_data(tmp_path, monkeypatch):
    store = cache.VideoWindowCache(tmp_path)
    first = store.allocate()
    with store.writer(first) as writer:
        writer.write(b"first picture")
    monkeypatch.setattr(cache.secrets, "token_hex", lambda _count: first.stem)
    with pytest.raises(FileExistsError):
        store.allocate()
    assert first.read_bytes() == b"first picture"
    foreign = tmp_path / "foreign.mp4"
    foreign.write_bytes(b"source")
    with pytest.raises(OSError, match="not owned"):
        store.writer(foreign)
    assert foreign.read_bytes() == b"source"
    store.close()


def test_writer_rejects_replacement_between_path_check_and_descriptor_open(tmp_path, monkeypatch):
    store = cache.VideoWindowCache(tmp_path)
    window = store.allocate()
    original_open = cache.os.open
    saved = tmp_path / "saved-original.mp4"

    def replace_then_open(path, flags, *args, **kwargs):
        if path == window:
            window.rename(saved)
            window.write_bytes(b"replacement")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(cache.os, "open", replace_then_open)
    with pytest.raises(OSError, match="changed before writing"):
        store.writer(window)
    assert window.read_bytes() == b"replacement"
    store.close()
    assert window.read_bytes() == b"replacement" and saved.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows verified-handle removal boundary")
def test_windows_handle_removal_rejects_replacement_after_path_check(tmp_path, monkeypatch):
    store = cache.VideoWindowCache(tmp_path)
    window = store.allocate()
    remove = cache._windows_remove
    saved = tmp_path / "saved-original.mp4"

    def replace_then_remove(path, expected):
        if path == window:
            window.rename(saved)
            window.write_bytes(b"replacement")
        return remove(path, expected)

    monkeypatch.setattr(cache, "_windows_remove", replace_then_remove)
    assert not store.remove(window)
    assert window.read_bytes() == b"replacement" and saved.exists()
    store.close()


def test_short_manifest_writes_are_completed_before_exposing_window(tmp_path, monkeypatch):
    original = cache.os.write
    calls = []

    def short_write(fd, data):
        calls.append(len(data))
        return original(fd, data[:7])

    monkeypatch.setattr(cache.os, "write", short_write)
    store = cache.VideoWindowCache(tmp_path)
    window = store.allocate()
    abandon(store)
    assert store._record is not None
    assert window.name in json.loads(store._record.read_text())["windows"]
    assert len(calls) > 3
    reopened = cache.VideoWindowCache(tmp_path)
    reopened.allocate()
    assert not window.exists()
    reopened.close()


def test_recovery_count_and_owned_backlog_are_bounded(tmp_path, monkeypatch):
    for index in range(5):
        record = tmp_path / f".mariana-video-{index:032x}.json"
        record.write_text('{"version":1,"windows":{}}')
    monkeypatch.setattr(cache, "MAX_RECOVERY_RECORDS", 2)
    store = cache.VideoWindowCache(tmp_path)
    windows = [store.allocate()]
    assert len(list(tmp_path.glob(".mariana-video-*.json"))) == 4
    windows.extend(store.allocate() for _ in range(cache.MAX_OWNED_WINDOWS - 1))
    assert len(list(tmp_path.glob(".mariana-video-*.json"))) == 1
    with pytest.raises(OSError, match="backlog"):
        store.allocate()
    assert all(window.exists() for window in windows)
    store.close()


def test_incremental_scan_reaches_records_beyond_legacy_entries(tmp_path, monkeypatch):
    for index in range(6):
        (tmp_path / f"legacy-{index}.mp4").write_bytes(b"legacy")
    old = cache.VideoWindowCache(tmp_path)
    window = old.allocate()
    abandon(old)
    monkeypatch.setattr(cache, "MAX_RECOVERY_RECORDS", 2)
    current = cache.VideoWindowCache(tmp_path)
    for _ in range(8):
        allocated = current.allocate()
        current.remove(allocated)
    assert not window.exists()
    assert len(list(tmp_path.glob("legacy-*.mp4"))) == 6
    current.close()


def test_recovery_deadline_preserves_unvisited_records(tmp_path, monkeypatch):
    record = tmp_path / (".mariana-video-" + "d" * 32 + ".json")
    record.write_text('{"version":1,"windows":{}}')
    monkeypatch.setattr(cache, "MAX_RECOVERY_SECONDS", 0)
    store = cache.VideoWindowCache(tmp_path)
    store.allocate()
    store.close()
    assert record.exists()


def test_locked_viewer_file_cleanup_can_be_retried(tmp_path, monkeypatch):
    store = cache.VideoWindowCache(tmp_path)
    window = store.allocate()
    original = store._remove_verified
    monkeypatch.setattr(store, "_remove_verified", lambda *_args: (_ for _ in ()).throw(PermissionError()))
    with pytest.raises(PermissionError):
        store.remove(window)
    assert window.exists() and window.name in store._files
    monkeypatch.setattr(store, "_remove_verified", original)
    assert store.remove(window)
    store.close()
    assert not list(tmp_path.iterdir())
