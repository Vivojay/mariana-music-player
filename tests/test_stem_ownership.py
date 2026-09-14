"""Owned source bytes and kernel-held result pins across consumers/processes."""

import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import mariana.stems as stems
from mariana.models import MediaCapabilities, MediaRef, MediaSource
from mariana.stems import CACHE_VERSION, StemError, StemInput, StemService


def media_for(path, identity="first"):
    return MediaRef(MediaSource.LOCAL, str(path), stable_id=identity, title="Same title", duration=1,
                    capabilities=MediaCapabilities(finite=True, seekable=True))


def separator(source, output, _model, expected, _cancel):
    output.mkdir(parents=True)
    content = source.read_bytes()
    result = {name: output / f"{name}.wav" for name in expected}
    for path in result.values():
        path.write_bytes(content)
    return result


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / "recording.flac"
    source.write_bytes(b"original recording")
    service = StemService(tmp_path / "cache", runner=separator)
    media = media_for(source)
    service.prepare(media, StemInput(str(source), {}))
    manifest = service.wait(5)
    yield service, source, media, manifest
    service.shutdown()


def test_separator_reads_only_verified_owned_source_and_copy_is_discarded(tmp_path):
    source = tmp_path / "recording.flac"
    source.write_bytes(b"original recording")
    seen = []

    def runner(snapshot, output, model, expected, cancel):
        assert snapshot != source
        assert snapshot.is_relative_to(service.work)
        assert snapshot.read_bytes() == b"original recording"
        source.write_bytes(b"replacement during processing")
        seen.append(snapshot)
        return separator(snapshot, output, model, expected, cancel)

    service = StemService(tmp_path / "cache", runner=runner)
    try:
        media = media_for(source)
        service.prepare(media, StemInput(str(source), {}))
        manifest = service.wait(5)
        assert all(path.read_bytes() == b"original recording" for path in manifest.stems.values())
        assert seen and all(not path.exists() for path in seen)
        payload = json.loads((service._directory_for(manifest) / "manifest.json").read_text())
        assert payload["version"] == CACHE_VERSION
        assert len(payload["source_signature"]) == 64
        assert all(value == hashlib.sha256(b"original recording").hexdigest()
                   for value in payload["stem_digests"].values())
        assert str(source) not in json.dumps(payload)
    finally:
        service.shutdown()


def test_same_size_same_timestamp_different_source_bytes_are_not_cache_hits(prepared):
    service, source, media, original = prepared
    previous = source.stat()
    source.write_bytes(b"different content!")
    assert source.stat().st_size == previous.st_size
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    service.prepare(media, StemInput(str(source), {}))
    replacement = service.wait(5)
    assert original.source_signature != replacement.source_signature
    assert set(original.stems.values()).isdisjoint(replacement.stems.values())
    assert all(path.read_bytes() == b"different content!" for path in replacement.stems.values())


def test_unchanged_source_is_verified_and_reused_after_service_restart(prepared):
    service, source, media, original = prepared
    service.shutdown()
    restarted = StemService(service.cache_dir, runner=lambda *_args: pytest.fail("Unexpected separation"))
    try:
        restarted.prepare(media, StemInput(str(source), {}))
        assert restarted.wait(5) == original
        assert not tuple(restarted.work.iterdir())
    finally:
        restarted.shutdown()


@pytest.mark.parametrize("change", ["replace", "rewrite-preserve-stat", "cancel"])
def test_snapshot_rejects_changed_or_cancelled_source_before_separator(tmp_path, monkeypatch, change):
    source = tmp_path / "recording.wav"
    source.write_bytes(b"original recording")
    service = StemService(tmp_path / "cache", runner=lambda *_args: pytest.fail("Unexpected separator"))
    digest_file = service._digest_file
    triggered = False

    def mutate(path, cancel, limit):
        nonlocal triggered
        if path == source and not triggered:
            triggered = True
            details = source.stat()
            if change == "cancel":
                cancel.set()
            elif change == "replace":
                source.unlink()
                source.write_bytes(b"different content!")
            else:
                source.write_bytes(b"different content!")
                os.utime(source, ns=(details.st_atime_ns, details.st_mtime_ns))
        return digest_file(path, cancel, limit)

    monkeypatch.setattr(service, "_digest_file", mutate)
    try:
        service.prepare(media_for(source), StemInput(str(source), {}))
        with pytest.raises(StemError, match=r"changed|cancelled"):
            service.wait(5)
        assert not tuple(service.results.iterdir())
        assert not tuple(service.work.iterdir())
    finally:
        service.shutdown()


def test_separator_cannot_rewrite_owned_input_and_publish_incorrect_binding(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"recording")

    def corrupt(snapshot, output, model, expected, cancel):
        snapshot.write_bytes(b"changed by separator")
        return separator(snapshot, output, model, expected, cancel)

    service = StemService(tmp_path / "cache", runner=corrupt)
    try:
        service.prepare(media_for(source), StemInput(str(source), {}))
        with pytest.raises(StemError, match="Owned stem input changed"):
            service.wait(5)
        assert not tuple(service.results.iterdir())
        assert not tuple(service.work.iterdir())
    finally:
        service.shutdown()


def test_retained_lease_blocks_clear_until_every_consumer_releases(prepared):
    service, _source, media, manifest = prepared
    monitor = service.acquire(media.stable_id, ["vocals"])
    retiring = monitor.retain()
    assert monitor.paths == (manifest.stems["vocals"],)
    monitor.release()
    monitor.release()
    with pytest.raises(StemError, match="already released"):
        monitor.retain()
    with pytest.raises(StemError, match="in use"):
        service.clear(media.stable_id)
    assert retiring.paths[0].exists()
    retiring.release()
    assert service.clear(media.stable_id)


def test_releasing_service_pin_does_not_release_monitor_pin(prepared):
    service, _source, media, manifest = prepared
    monitor = service.acquire(media.stable_id, ["vocals"])
    service.shutdown()
    other = StemService(service.cache_dir)
    other._manifest = manifest
    try:
        with pytest.raises(StemError, match="in use"):
            other.clear(media.stable_id)
        monitor.release()
        assert other.clear(media.stable_id)
    finally:
        monitor.release()
        other.shutdown()


def test_decoder_stop_keeps_kernel_pin_until_resource_cleanup_completes(prepared, monkeypatch):
    import mariana.playback as playback

    service, _source, media, _manifest = prepared
    pin = service.acquire(media.stable_id, ["vocals"])
    monkeypatch.setattr(playback, "find_executable", lambda *_args: "unused")
    decoder = playback.DecoderSession(media, input_sources=pin.paths, resource_lease=pin)
    entered, finish = threading.Event(), threading.Event()

    class ClosingJob:
        def close(self):
            entered.set()
            assert finish.wait(5)

    monkeypatch.setattr(decoder, "job", ClosingJob())
    cleanup = threading.Thread(target=decoder.stop)
    cleanup.start()
    try:
        assert entered.wait(3)
        with pytest.raises(StemError, match="in use"):
            service.clear(media.stable_id)
        finish.set()
        cleanup.join(timeout=5)
        assert not cleanup.is_alive()
        assert decoder.resource_lease is None
        assert service.clear(media.stable_id)
    finally:
        finish.set()
        cleanup.join(timeout=5)


def test_new_preparation_cannot_prune_active_or_retiring_old_result(prepared):
    service, source, media, original = prepared
    monitor = service.acquire(media.stable_id, ["vocals"])
    retiring = monitor.retain()
    service.retention_seconds = 0
    service.prepare(media_for(source, "second"), StemInput(str(source), {}))
    service.wait(5)
    monitor.release()
    service.prepare(media_for(source, "third"), StemInput(str(source), {}))
    service.wait(5)
    assert all(path.exists() for path in original.stems.values())
    retiring.release()
    service.prepare(media_for(source, "fourth"), StemInput(str(source), {}))
    service.wait(5)
    assert all(not path.exists() for path in original.stems.values())


def test_export_holds_pin_until_copy_and_activation_finish(prepared, tmp_path, monkeypatch):
    service, _source, media, manifest = prepared
    other = StemService(service.cache_dir)
    other._manifest = manifest
    copied = []
    original_copy = stems._copy_export_stream

    def copy(source, destination):
        # Drop the ready-selection pin; export must independently protect files.
        service.shutdown()
        with pytest.raises(StemError, match="in use"):
            other.clear(media.stable_id)
        copied.append(True)
        return original_copy(source, destination)

    monkeypatch.setattr(stems, "_copy_export_stream", copy)
    try:
        assert len(service.export(media.stable_id, tmp_path / "exports")) == 4
        assert len(copied) == 4
        assert other.clear(media.stable_id)
    finally:
        other.shutdown()


def test_another_process_pin_blocks_deletion_and_crash_releases_it(prepared):
    service, _source, media, manifest = prepared
    script = """
import os, sys
from pathlib import Path
from mariana.stems import StemService
service = StemService(Path(sys.argv[1]))
service._manifest = service._read_manifest(Path(sys.argv[2]))
pin = service.acquire(sys.argv[3], ['vocals'])
print('PINNED', flush=True)
sys.stdin.readline()
os._exit(0)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(service.cache_dir),
         str(service._directory_for(manifest) / "manifest.json"), media.stable_id],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=stems.CREATE_NO_WINDOW,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "PINNED"
        with pytest.raises(StemError, match="in use"):
            service.clear(media.stable_id)
        _output, error = process.communicate("exit\n", timeout=10)
        assert process.returncode == 0, error
        assert service.clear(media.stable_id)
    finally:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=10)


def test_recovery_removes_only_unlocked_owned_abandoned_work(prepared):
    service, source, media, _manifest = prepared
    abandoned = service.work / "abandoned"
    abandoned.mkdir()
    service._mark_owned(abandoned)
    (abandoned / "source.partial").write_bytes(b"partial input")
    active = service.work / "active"
    active.mkdir()
    service._mark_owned(active)
    (active / "reservation.json").write_text('{"bytes": 1}')
    (active / "source.partial").write_bytes(b"live input")
    pin = service._result_lock("work-active", exclusive=True)
    try:
        service.prepare(media, StemInput(str(source), {}))
        service.wait(5)
        assert not abandoned.exists()
        assert (active / "source.partial").read_bytes() == b"live input"
    finally:
        pin.release()


def test_recovery_cleans_crashed_incomplete_result_but_preserves_unknown_directory(prepared):
    service, source, media, _manifest = prepared
    partial = service.results / "partial"
    partial.mkdir()
    service._mark_owned(partial)
    (partial / "vocals.wav").write_bytes(b"partial")
    unknown = service.results / "foreign"
    unknown.mkdir()
    valuable = unknown / "keep.txt"
    valuable.write_text("not owned")
    service.retention_seconds = 0
    service.prepare(media, StemInput(str(source), {}))
    service.wait(5)
    assert not partial.exists()
    assert valuable.read_text() == "not owned"


@pytest.mark.parametrize("case", ["manifest", "stem", "traversal", "version"])
def test_cached_manifest_rejects_corruption_without_claiming_cache_hit(prepared, case):
    service, _source, _media, manifest = prepared
    path = service._directory_for(manifest) / "manifest.json"
    value = json.loads(path.read_text())
    if case == "manifest":
        path.write_text("{")
    elif case == "stem":
        manifest.stems["vocals"].write_bytes(b"incorrect source")
    elif case == "traversal":
        value["stems"]["vocals"] = "../outside.wav"
        path.write_text(json.dumps(value))
    else:
        value["version"] = 2
        path.write_text(json.dumps(value))
    assert service._read_manifest(path, verify_bytes=True) is None


@pytest.mark.parametrize("kind", ["source-file", "source-parent", "cache-root", "result-child"])
def test_reparse_paths_are_rejected_without_following_them(prepared, monkeypatch, kind):
    service, source, media, manifest = prepared
    victim = {"source-file": source, "source-parent": source.parent,
              "cache-root": service.cache_dir, "result-child": manifest.stems["vocals"]}[kind]
    lstat = Path.lstat

    def linked(path, *args, **kwargs):
        actual = lstat(path, *args, **kwargs)
        if path == victim:
            values = {field: getattr(actual, field) for field in dir(actual) if field.startswith("st_")}
            values["st_file_attributes"] = getattr(actual, "st_file_attributes", 0) | getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            from types import SimpleNamespace

            return SimpleNamespace(**values)
        return actual

    monkeypatch.setattr(Path, "lstat", linked)
    if kind == "result-child":
        with pytest.raises(StemError, match="unlinked regular"):
            service.acquire(media.stable_id, ["vocals"])
    else:
        service.prepare(media, StemInput(str(source), {}))
        with pytest.raises(StemError, match=r"reparse|regular"):
            service.wait(5)
    assert source.read_bytes() == b"original recording"


def test_active_reservations_refuse_overcommit_and_release_after_completion(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    entered, release = threading.Event(), threading.Event()

    def hold(snapshot, output, model, expected, cancel):
        entered.set()
        assert release.wait(5)
        return separator(snapshot, output, model, expected, cancel)

    first = StemService(tmp_path / "cache", runner=hold, max_cache_bytes=20_000)
    second = StemService(first.cache_dir, runner=separator, max_cache_bytes=20_000)
    monkeypatch.setattr(first, "_check_storage", lambda *_args: 15_000)
    monkeypatch.setattr(second, "_check_storage", lambda *_args: 15_000)
    try:
        first.prepare(media_for(source), StemInput(str(source), {}))
        assert entered.wait(3)
        second.prepare(media_for(source, "second"), StemInput(str(source), {}))
        with pytest.raises(StemError, match="capacity is reserved"):
            second.wait(5)
        release.set()
        first.wait(5)
        second.prepare(media_for(source, "second"), StemInput(str(source), {}))
        assert second.wait(5).media_id == "second"
    finally:
        release.set()
        first.shutdown()
        second.shutdown()


def test_disk_exhaustion_during_snapshot_never_invokes_separator(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    service = StemService(tmp_path / "cache", runner=lambda *_args: pytest.fail("Unexpected separator"))
    fsync = os.fsync

    def no_space(descriptor):
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", no_space)
    try:
        service.prepare(media_for(source), StemInput(str(source), {}))
        with pytest.raises(OSError, match="disk full"):
            service.wait(5)
        assert service.status().error == "Stem preparation failed"
        assert not tuple(service.work.iterdir())
        monkeypatch.setattr(os, "fsync", fsync)
    finally:
        service.shutdown()


def test_remote_reference_and_headers_are_not_in_owned_result_manifest(tmp_path, monkeypatch):
    service = StemService(tmp_path / "cache", runner=separator)
    media = MediaRef(MediaSource.YOUTUBE, "https://www.youtube.com/watch?v=abcdefghijk", stable_id="online",
                     title="Online recording", duration=1, capabilities=MediaCapabilities(finite=True))
    commands = []

    def materialize(command, _cancel, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"finite audio")

    monkeypatch.setattr(service, "_run_process", materialize)
    try:
        service.prepare(media, StemInput("https://cdn.example/media?secret=signed", {"Authorization": "secret-token"}))
        manifest = service.wait(5)
        value = (service._directory_for(manifest) / "manifest.json").read_text()
        assert "signed" not in value and "secret-token" not in value and "cdn.example" not in value
        assert commands and "-fs" in commands[0]
    finally:
        service.shutdown()


def test_file_uri_and_spaces_use_the_same_verified_source_bytes(prepared):
    service, source, media, original = prepared
    renamed = source.with_name("another source name.flac")
    source.rename(renamed)
    service.prepare(media, StemInput(renamed.as_uri(), {}))
    assert service.wait(5) == original


def test_local_hardlink_is_refused_before_separator(tmp_path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"recording")
    os.link(source, tmp_path / "alias.wav")
    service = StemService(tmp_path / "cache", runner=lambda *_args: pytest.fail("Unexpected separator"))
    try:
        service.prepare(media_for(source), StemInput(str(source), {}))
        with pytest.raises(StemError, match="unlinked regular"):
            service.wait(5)
        assert source.read_bytes() == b"recording"
    finally:
        service.shutdown()


def test_foreign_files_cannot_be_deleted_through_forged_manifest(prepared):
    service, _source, _media, original = prepared
    directory = service._directory_for(original)
    (directory / "ownership.json").write_text('{"owner": "different application"}')
    with pytest.raises(StemError, match="verified owned"):
        service.clear(original.media_id)
    assert all(path.exists() for path in original.stems.values())


def test_result_tree_limits_fail_closed_without_deleting_unknown_files(prepared, monkeypatch):
    service, _source, media, manifest = prepared
    monkeypatch.setattr(stems, "MAX_RESULT_FILES", 2)
    with pytest.raises(StemError, match="too many entries"):
        service.clear(media.stable_id)
    assert all(path.exists() for path in manifest.stems.values())


def test_remote_materialization_at_byte_limit_is_not_a_complete_recording(tmp_path, monkeypatch):
    service = StemService(tmp_path / "cache", runner=lambda *_args: pytest.fail("Unexpected separator"),
                          max_cache_bytes=512)
    media = MediaRef(MediaSource.URL, "https://example.test/finite.mp3", duration=1,
                     capabilities=MediaCapabilities(finite=True))
    monkeypatch.setattr(service, "_check_storage", lambda *_args: 0)

    def oversized(command, _cancel, **_kwargs):
        Path(command[-1]).write_bytes(b"x" * 512)

    monkeypatch.setattr(service, "_run_process", oversized)
    try:
        service.prepare(media, StemInput(media.original_uri, {}))
        with pytest.raises(StemError, match="byte limit"):
            service.wait(5)
        assert not tuple(service.work.iterdir())
        assert not tuple(service.results.iterdir())
    finally:
        service.shutdown()


@pytest.mark.parametrize("change", [
    "missing-hashes", "invalid-hash", "invalid-source-binding", "invalid-created-time", "overflow-created-time",
    "wrong-model", "unexpected-stem", "absolute-path", "oversized-manifest", "empty-stem",
])
def test_manifest_validation_rejects_untrusted_result_structure(prepared, change):
    service, _source, _media, manifest = prepared
    path = service._directory_for(manifest) / "manifest.json"
    payload = json.loads(path.read_text())
    if change == "missing-hashes":
        payload["stem_digests"] = {}
    elif change == "invalid-hash":
        payload["stem_digests"]["vocals"] = "not a byte digest"
    elif change == "invalid-source-binding":
        payload["source_signature"] = "not a byte binding"
    elif change == "invalid-created-time":
        payload["created_at"] = "NaN"
    elif change == "overflow-created-time":
        payload["created_at"] = 10**400
    elif change == "wrong-model":
        payload["model"] = "unknown model"
    elif change == "unexpected-stem":
        payload["stems"]["unexpected"] = "other.wav"
    elif change == "absolute-path":
        payload["stems"]["vocals"] = str(manifest.stems["vocals"])
    elif change == "oversized-manifest":
        payload["title"] = "x" * stems.MAX_MANIFEST_BYTES
    else:
        manifest.stems["vocals"].write_bytes(b"")
    path.write_text(json.dumps(payload))
    assert service._read_manifest(path, verify_bytes=True) is None


@pytest.mark.parametrize("payload", [[], {"bytes": True}, {"bytes": -1}, {"bytes": "100"}, {"bytes": 2**64}])
def test_workspace_reservation_rejects_invalid_capacity_claims(prepared, payload):
    service, _source, _media, _manifest = prepared
    directory = service.work / "reservation"
    directory.mkdir()
    service._mark_owned(directory)
    (directory / "reservation.json").write_text(json.dumps(payload))
    with pytest.raises(StemError, match="reservation is invalid"):
        service._storage_usage()
    assert directory.exists()


@pytest.mark.parametrize("state", ["closed", "wrong-media", "replaced-result"])
def test_acquire_rejects_stale_selection_and_releases_temporary_pin(prepared, monkeypatch, state):
    service, _source, media, manifest = prepared
    if state == "closed":
        service.shutdown()
        reason = "service is closed"
    elif state == "wrong-media":
        reason = "current media first"
    else:
        monkeypatch.setattr(service, "manifest", lambda _media_id: None)
        reason = "changed before use"
    with pytest.raises(StemError, match=reason):
        service.acquire("different" if state == "wrong-media" else media.stable_id, ["vocals"])
    service.shutdown()
    # Failed acquisition must not leak a shared lock after the ready-selection pin is dropped.
    with service._result_lock(service._directory_for(manifest).name, exclusive=True):
        assert all(path.exists() for path in manifest.stems.values())


@pytest.mark.parametrize("source", ["file://remote-host/share/source.wav", "../outside.wav"])
def test_local_input_cannot_escape_through_authority_or_parent_traversal(source):
    with pytest.raises(StemError, match=r"authority|traversal"):
        StemService._local_path(StemInput(source, {}))


@pytest.mark.parametrize("output", [None, b""])
def test_remote_materialization_missing_or_empty_output_never_reaches_separator(tmp_path, monkeypatch, output):
    service = StemService(tmp_path / "cache", runner=lambda *_args: pytest.fail("Unexpected separator"))
    media = MediaRef(MediaSource.URL, "https://example.test/episode.mp3", duration=1,
                     capabilities=MediaCapabilities(finite=True))

    def materialize(command, _cancel, **_kwargs):
        if output is not None:
            Path(command[-1]).write_bytes(output)

    monkeypatch.setattr(service, "_run_process", materialize)
    try:
        service.prepare(media, StemInput(media.original_uri, {}))
        with pytest.raises(StemError, match="Could not materialize"):
            service.wait(5)
        assert not tuple(service.results.iterdir())
        assert not tuple(service.work.iterdir())
    finally:
        service.shutdown()


@pytest.mark.parametrize("kind", ["empty", "oversized", "changed-before-open", "growing", "truncated"])
def test_byte_verification_refuses_changed_or_unbounded_inputs(tmp_path, monkeypatch, kind):
    path = tmp_path / "source.wav"
    path.write_bytes(b"original")
    original_open = Path.open
    reads = 0

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, count):
            nonlocal reads
            data = self.stream.read(count)
            reads += 1
            if reads == 1 and kind in {"growing", "truncated"}:
                with original_open(path, "ab" if kind == "growing" else "wb") as writer:
                    writer.write(b"more" if kind == "growing" else b"short")
            return data

    def open_source(selected, mode="r", *args, **kwargs):
        if selected == path and mode == "rb":
            if kind == "changed-before-open":
                with original_open(path, "wb") as writer:
                    writer.write(b"replacement recording")
            return Reader(original_open(selected, mode, *args, **kwargs))
        return original_open(selected, mode, *args, **kwargs)

    if kind == "empty":
        path.write_bytes(b"")
    monkeypatch.setattr(Path, "open", open_source)
    with pytest.raises(StemError, match=r"byte limit|changed|grew"):
        StemService._digest_file(path, threading.Event(), 4 if kind == "oversized" else 64)


@pytest.mark.parametrize("kind", ["empty", "changed-before-open", "cancelled", "growing", "truncated"])
def test_owned_snapshot_never_accepts_a_partial_or_changed_source(tmp_path, monkeypatch, kind):
    source = tmp_path / "source.wav"
    source.write_bytes(b"original")
    workspace = tmp_path / "owned-input"
    workspace.mkdir()
    service = StemService(tmp_path / "cache")
    original_open = Path.open
    cancel = threading.Event()
    reads = 0

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.stream.close()

        def fileno(self):
            return self.stream.fileno()

        def read(self, count):
            nonlocal reads
            data = self.stream.read(count)
            reads += 1
            if reads == 1 and kind in {"growing", "truncated"}:
                with original_open(source, "ab" if kind == "growing" else "wb") as writer:
                    writer.write(b"more" if kind == "growing" else b"short")
            if kind == "cancelled":
                cancel.set()
            return data

    def open_source(selected, mode="r", *args, **kwargs):
        if selected == source and mode == "rb":
            if kind == "changed-before-open":
                with original_open(source, "wb") as writer:
                    writer.write(b"replacement recording")
            return Reader(original_open(selected, mode, *args, **kwargs))
        return original_open(selected, mode, *args, **kwargs)

    if kind == "empty":
        source.write_bytes(b"")
    monkeypatch.setattr(Path, "open", open_source)
    try:
        with pytest.raises(StemError, match=r"cache limit|changed|cancelled|grew"):
            service._materialize(StemInput(str(source), {}), media_for(source), workspace, cancel)
        assert service.status().state == "idle"
    finally:
        service.shutdown()


@pytest.mark.parametrize("reason", ["no-stems", "result-root", "outside", "split-result"])
def test_result_identity_cannot_point_at_an_unrelated_cache_directory(prepared, reason):
    service, _source, media, manifest = prepared
    if reason == "no-stems":
        manifest.stems.clear()
    elif reason == "result-root":
        manifest.stems["vocals"] = service.results
    elif reason == "outside":
        manifest.stems["vocals"] = service.cache_dir / "outside.wav"
    else:
        manifest.stems["other"] = service.results / "another-result" / "other.wav"
    with pytest.raises(StemError, match=r"identit|one cache result|Unsupported stem"):
        service.acquire(media.stable_id, ["vocals"])


@pytest.mark.parametrize("key", ["../result", "result/child", "a" * 81, ""])
def test_result_lock_keys_cannot_escape_the_owned_namespace(prepared, key):
    service, _source, _media, _manifest = prepared
    before = set(service.locks.iterdir())
    with pytest.raises(StemError, match="identity is invalid"):
        service._result_lock(key, exclusive=True)
    assert set(service.locks.iterdir()) == before


@pytest.mark.parametrize("reason", ["unknown-owner", "oversized-reservation", "oversized-marker", "too-many-workspaces"])
def test_cache_inspection_bounds_untrusted_workspace_metadata(prepared, reason):
    service, _source, _media, _manifest = prepared
    directory = service.work / "unexpected"
    directory.mkdir()
    if reason != "unknown-owner":
        service._mark_owned(directory)
    if reason == "oversized-marker":
        (directory / "ownership.json").write_text("x" * 1025)
        assert service._owned(directory) is False
    elif reason == "too-many-workspaces":
        with pytest.raises(StemError, match="too many result entries"):
            service._entries(service.work, maximum=0)
    else:
        if reason == "oversized-reservation":
            (directory / "reservation.json").write_text("x" * 513)
        with pytest.raises(StemError, match=r"Unrecognized|reservation is invalid"):
            service._storage_usage()
    assert directory.exists()


@pytest.mark.parametrize("duration", [None, float("nan"), float("inf"), -1, stems.MAX_MEDIA_SECONDS + 1])
def test_unknown_or_invalid_media_duration_never_creates_preparation_work(tmp_path, duration):
    service = StemService(tmp_path / "cache")
    media = media_for(tmp_path / "source.wav")
    media.duration = duration
    try:
        with pytest.raises(StemError, match=r"finite duration|four hours"):
            service.prepare(media, StemInput(media.original_uri, {}))
        assert service.status().state == "idle"
        assert not service.work.exists()
    finally:
        service.shutdown()


@pytest.mark.parametrize("source", ["ftp://example.test/recording.wav", "rtsp://example.test/stream"])
def test_unsupported_transport_is_rejected_before_materialization(tmp_path, source):
    service = StemService(tmp_path / "cache")
    try:
        with pytest.raises(StemError, match="transport"):
            service.prepare(media_for(tmp_path / "source.wav"), StemInput(source, {}))
        assert not service.work.exists()
    finally:
        service.shutdown()


@pytest.mark.parametrize("selection", [["original", "vocals"], ["karaoke", "drums"]])
def test_original_and_composite_mixes_cannot_be_accidentally_double_summed(selection):
    with pytest.raises(StemError, match=r"combined|complete non-vocal"):
        stems.parse_stem_selection(selection, stems.FOUR_STEMS)


def test_low_disk_space_is_refused_before_creating_an_owned_snapshot(prepared, monkeypatch):
    service, source, media, _manifest = prepared
    monkeypatch.setattr(stems.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))
    with pytest.raises(StemError, match="Not enough free space"):
        service._check_storage(media, StemInput(str(source), {}), 4)
    assert not tuple(service.work.iterdir())


@pytest.mark.parametrize("invalid", ["empty", "outside", "oversized"])
def test_separator_result_cannot_publish_empty_unowned_or_over_budget_audio(tmp_path, monkeypatch, invalid):
    source = tmp_path / "source.wav"
    source.write_bytes(b"source")
    outside = tmp_path / "unrelated.wav"
    outside.write_bytes(b"must stay intact")

    def produce(snapshot, directory, model, expected, cancel):
        result = separator(snapshot, directory, model, expected, cancel)
        if invalid == "empty":
            result["vocals"].write_bytes(b"")
        elif invalid == "outside":
            result["vocals"] = outside
        else:
            for path in result.values():
                path.write_bytes(b"x" * 128)
        return result

    service = StemService(tmp_path / "cache", runner=produce, max_cache_bytes=256 if invalid == "oversized" else stems.DEFAULT_CACHE_BYTES)
    monkeypatch.setattr(service, "_check_storage", lambda *_args: 0)
    try:
        service.prepare(media_for(source), StemInput(str(source), {}))
        with pytest.raises(StemError, match=r"valid vocals|cache limit"):
            service.wait(5)
        assert service.manifest() is None
        assert not tuple(service.results.iterdir())
        assert not tuple(service.work.iterdir())
        assert outside.read_bytes() == b"must stay intact"
    finally:
        service.shutdown()


def test_changed_lock_file_is_rejected_and_its_open_handle_is_closed(tmp_path, monkeypatch):
    path = tmp_path / "result.lock"
    actual_signature = stems._export_file_signature
    original_fdopen = os.fdopen
    streams = []

    def changed(selected):
        if selected == path:
            path.write_bytes(b"changed lock file")
        return actual_signature(selected)

    def opened(*args, **kwargs):
        stream = original_fdopen(*args, **kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setattr(stems, "_export_file_signature", changed)
    monkeypatch.setattr(stems.os, "fdopen", opened)
    with pytest.raises(StemError, match="lock identity changed"):
        stems._FileLease(path, exclusive=True)
    assert len(streams) == 1 and streams[0].closed


def test_empty_prepared_stem_is_no_longer_exposed_for_monitoring(prepared):
    service, _source, media, manifest = prepared
    manifest.stems["vocals"].write_bytes(b"")
    assert service.manifest(media.stable_id) is None
    with pytest.raises(StemError, match="current media first"):
        service.selection(media.stable_id, ["vocals"])
    with pytest.raises(StemError, match="current media first"):
        service.export(media.stable_id, service.cache_dir / "exports")
    assert not (service.cache_dir / "exports").exists()


def test_unknown_model_is_refused_by_service_before_work_is_created(tmp_path):
    service = StemService(tmp_path / "cache")
    media = media_for(tmp_path / "source.wav")
    try:
        with pytest.raises(StemError, match="must be 4 or 6"):
            service.prepare(media, StemInput(media.original_uri, {}), stem_count="5")
        assert not service.work.exists()
    finally:
        service.shutdown()


def test_closed_service_cannot_clear_files_owned_by_another_consumer(prepared):
    service, _source, media, manifest = prepared
    pin = service.acquire(media.stable_id, ["vocals"])
    service.shutdown()
    try:
        with pytest.raises(StemError, match="service is closed"):
            service.clear(media.stable_id)
        assert all(path.exists() for path in manifest.stems.values())
    finally:
        pin.release()


def test_unknown_workspace_is_preserved_and_blocks_new_capacity_reservation(prepared):
    service, source, media, _manifest = prepared
    foreign = service.work / "foreign"
    foreign.mkdir()
    valuable = foreign / "keep.txt"
    valuable.write_text("not owned")
    service.prepare(media, StemInput(str(source), {}))
    with pytest.raises(StemError, match="Unrecognized"):
        service.wait(5)
    assert valuable.read_text() == "not owned"


def test_new_result_pruning_does_not_claim_foreign_output(prepared):
    service, source, _media, _manifest = prepared
    foreign = service.results / "foreign"
    foreign.mkdir()
    valuable = foreign / "keep.txt"
    valuable.write_text("not owned")
    service.retention_seconds = 0
    service.prepare(media_for(source, "next-recording"), StemInput(str(source), {}))
    assert service.wait(5).media_id == "next-recording"
    assert valuable.read_text() == "not owned"


def test_recovery_rechecks_completion_after_acquiring_exclusive_result_lock(prepared, monkeypatch):
    service, source, media, _manifest = prepared
    completing = service.results / "completing"
    completing.mkdir()
    service._mark_owned(completing)
    (completing / "vocals.wav").write_bytes(b"completed audio")
    native_lock = service._result_lock

    def finish_before_lock(key, *, exclusive):
        if key == completing.name and exclusive:
            # Another instance finished immediately before yielding the kernel lock.
            (completing / "manifest.json").write_text('{"completed": true}')
        return native_lock(key, exclusive=exclusive)

    monkeypatch.setattr(service, "_result_lock", finish_before_lock)
    service.prepare(media, StemInput(str(source), {}))
    service.wait(5)
    assert (completing / "vocals.wav").read_bytes() == b"completed audio"
    assert (completing / "manifest.json").exists()
