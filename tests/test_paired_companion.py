import json
import queue
import threading
import time
from types import SimpleNamespace

import pytest

from mariana import paired_companion as module
from mariana.models import PlaybackSnapshot, PlaybackState
from mariana.paired_trust import PairingError

DEVICE = "a" * 32
PROOF = "b" * 16
FINGERPRINT = "c" * 64


def snapshot():
    return PlaybackSnapshot(PlaybackState.IDLE)


def completed(companion):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        status = companion.status()
        if status["state"] not in {"pending", "working"}:
            return status
        threading.Event().wait(.005)
    pytest.fail("Companion operation did not finish")


class MemoryTrust:
    def __init__(self, _path):
        self.revoked = []

    def devices(self):
        return [{"device_id": DEVICE, "permissions": ["status.read"]}]

    def revoke(self, identifier):
        self.revoked.append(identifier)


class MemoryService:
    def __init__(self, trust):
        self.trust = trust
        self.approved = []
        self.rejected = []
        self.snapshots = []
        self.updated = threading.Event()

    def update_status(self, value):
        self.snapshots.append(value)
        self.updated.set()

    def pending(self):
        return [{"request_id": DEVICE, "proof": PROOF}]

    def approve(self, identifier, *, verified_proof):
        self.approved.append((identifier, verified_proof))

    def reject(self, identifier):
        self.rejected.append(identifier)


class MemoryServer:
    def __init__(self, service, _path, *, credentials=None):
        self.service = service
        self.running = False
        self.starts = 0
        self.closes = 0

    def start(self, address, *, port):
        self.running = True
        self.starts += 1
        return SimpleNamespace(address=address, port=port or 43210, fingerprint=FINGERPRINT)

    def close(self):
        self.running = False
        self.closes += 1
        return True

    def invitation(self):
        return {"schema_version": 1, "endpoint": {"fingerprint": FINGERPRINT},
                "secret": "d" * 43, "expires_at": 1000}


class MemoryClient:
    def __init__(self, _path, *, credentials=None):
        self.cancelled = 0
        self.disconnected = 0
        self.begun = None

    def begin(self, invitation, *, verified_fingerprint, label):
        self.begun = invitation, verified_fingerprint, label
        return {"request_id": DEVICE, "proof": PROOF, "expires_at": 1000}

    def poll(self):
        return {"state": "approved", "device_id": DEVICE, "permissions": ["status.read"]}

    def status(self):
        return {"title": "Known song", "state": "paused"}

    def cancel_pending(self):
        self.cancelled += 1

    def disconnect(self):
        self.disconnected += 1


@pytest.fixture
def companion(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "TrustStore", MemoryTrust)
    monkeypatch.setattr(module, "PairedReadOnlyService", MemoryService)
    monkeypatch.setattr(module, "PairedServer", MemoryServer)
    monkeypatch.setattr(module, "PairedClient", MemoryClient)
    value = module.PairedCompanion(tmp_path / "paired", snapshot=snapshot)
    yield value
    value.close()


def test_default_construction_and_status_are_lazy_and_detached(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unexpected operation")

    for name in ("TrustStore", "PairedReadOnlyService", "PairedServer", "PairedClient"):
        monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(threading.Thread, "start", forbidden)
    root = tmp_path / "not-created"
    value = module.PairedCompanion(root, snapshot=forbidden)
    status = value.status()
    assert status == {"listener_running": False, "read_only": True,
                      "operation": None, "state": "idle", "result": None, "error": None}
    status["state"] = "modified"
    assert value.status()["state"] == "idle"
    assert not root.exists()
    assert value.close()


@pytest.mark.parametrize(("operation", "arguments"), [
    ([], ()), ("unknown", ()), ("host", ()), ("host", ("127.0.0.1",)),
    ("host", ("127.0.0.1", True)), ("host", ("8.8.8.8", 0)), ("host", ("127.0.0.1", 65536)),
    ("stop", ("extra",)), ("invite", (None,)), ("invite", ("",)), ("invite", ("bad\0file",)),
    ("requests", (1,)), ("approve", (DEVICE,)), ("approve", (DEVICE, "wrong")),
    ("reject", ("bad",)), ("revoke", (None,)), ("devices", (1,)),
    ("connect", ("invite.json", "bad", "Desktop")),
    ("connect", ("invite.json", FINGERPRINT, "line\nbreak")),
    ("connect", ("invite.json", FINGERPRINT, [])), ("poll", (1,)), ("now", (1,)),
    ("cancel", (1,)), ("disconnect", (1,)),
])
def test_invalid_controls_start_no_worker_or_io(tmp_path, operation, arguments):
    root = tmp_path / "absent"
    value = module.PairedCompanion(root, snapshot=snapshot)
    with pytest.raises(PairingError):
        value.submit(operation, *arguments)
    assert value._worker is None
    assert value.status()["state"] == "idle"
    assert not root.exists()
    assert value.close()


def test_worker_reuses_host_trust_for_stop_and_rehost(companion):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["listener_running"]
    server, service = companion._server, companion._service
    companion.submit("stop")
    assert not completed(companion)["listener_running"]
    companion.submit("host", "127.0.0.1", 23456)
    assert completed(companion)["result"]["port"] == 23456
    assert companion._service is service
    assert companion._server is server
    assert server.starts == 2


def test_status_never_acquires_server_lifecycle_lock(companion):
    class BusyServer:
        @property
        def running(self):
            raise AssertionError("Status touched blocking transport state")

        def close(self):
            return True

    companion._server = BusyServer()
    assert not companion.status()["listener_running"]


def test_host_management_operations_route_to_the_existing_authority(companion):
    for operation, arguments in (("requests", ()), ("approve", (DEVICE, PROOF)),
                                 ("reject", (DEVICE,)), ("devices", ()), ("revoke", (DEVICE,))):
        companion.submit(operation, *arguments)
        assert completed(companion)["state"] == "ready"
    assert companion._service.approved == [(DEVICE, PROOF)]
    assert companion._service.rejected == [DEVICE]
    assert companion._service.trust.revoked == [DEVICE]
    assert not companion.status()["listener_running"]


def test_client_controls_preserve_the_trusted_boundary_and_cancel_without_provisioning(companion, monkeypatch):
    companion.submit("cancel")
    assert completed(companion)["result"] == {"pending_cancelled": True}
    assert companion._client is None
    invitation = {"schema_version": 1, "secret": "private"}
    monkeypatch.setattr(module, "_read_document", lambda *_args, **_kwargs: invitation)
    companion.submit("connect", "invitation.json", FINGERPRINT, "  Desktop  ")
    assert completed(companion)["state"] == "ready"
    assert companion._client.begun == (invitation, FINGERPRINT, "Desktop")
    assert "private" not in json.dumps(companion.status())
    for operation in ("poll", "now", "cancel", "disconnect"):
        companion.submit(operation)
        assert completed(companion)["state"] == "ready"
    assert companion._client.cancelled == 1
    assert companion._client.disconnected == 1


def test_invitation_export_is_no_clobber_and_status_contains_no_secret_or_path(companion, tmp_path):
    destination = tmp_path / "invitation.json"
    companion.submit("invite", str(destination))
    status = completed(companion)
    assert status["state"] == "ready"
    assert status["result"]["invitation_saved"]
    assert json.loads(destination.read_text())["secret"] == "d" * 43
    assert str(tmp_path) not in json.dumps(status)
    assert "d" * 43 not in json.dumps(status)
    before = destination.read_bytes()
    companion.submit("invite", str(destination))
    assert completed(companion)["state"] == "error"
    assert destination.read_bytes() == before
    assert not list(tmp_path.glob(".mariana-invitation-*"))


def test_invitation_destination_appearing_during_export_is_preserved(companion, tmp_path, monkeypatch):
    destination = tmp_path / "race.json"
    original = MemoryServer.invitation

    def appeared(server):
        destination.write_bytes(b"independent existing file")
        return original(server)

    monkeypatch.setattr(MemoryServer, "invitation", appeared)
    companion.submit("invite", str(destination))
    status = completed(companion)
    assert status["state"] == "error"
    assert "overwrite" in status["error"]
    assert destination.read_bytes() == b"independent existing file"
    assert not list(tmp_path.glob(".mariana-invitation-*"))


@pytest.mark.parametrize("error", [RuntimeError("https://private.test/?token=credential"),
                                   PairingError("password=credential"),
                                   PairingError(r"C:\private\invitation.json"),
                                   PairingError("The invitation has expired")])
def test_errors_are_safe_and_do_not_end_worker(companion, monkeypatch, error):
    original = companion._perform

    def rejected(*_args):
        raise error

    monkeypatch.setattr(companion, "_perform", rejected)
    companion.submit("now")
    status = completed(companion)
    assert status["state"] == "error"
    assert "credential" not in json.dumps(status)
    assert "C:" not in json.dumps(status)
    assert "https:" not in json.dumps(status)
    if "expired" in str(error):
        assert status["error"] == "The invitation has expired"
    monkeypatch.setattr(companion, "_perform", original)
    companion.submit("cancel")
    assert completed(companion)["state"] == "ready"


def test_queue_and_worker_start_failure_are_recoverable(companion, monkeypatch):
    companion._pending.put_nowait(("cancel", ()))
    with pytest.raises(PairingError, match="queue is full"):
        companion.submit("cancel")
    assert companion._worker is None
    companion._pending.get_nowait()
    companion._pending.task_done()
    with monkeypatch.context() as context:
        def cannot_start(_thread):
            raise RuntimeError("no thread")

        context.setattr(threading.Thread, "start", cannot_start)
        with pytest.raises(PairingError, match="worker could not start"):
            companion.submit("cancel")
    assert companion._pending.empty()
    assert companion._worker is None
    companion.submit("cancel")
    assert completed(companion)["state"] == "ready"


@pytest.mark.parametrize("failure", [False, True])
def test_busy_operation_is_nonblocking_and_cannot_publish_after_close(companion, monkeypatch, failure):
    entered, release = threading.Event(), threading.Event()

    def blocked(*_args):
        entered.set()
        assert release.wait(3)
        if failure:
            raise PairingError("A late error")
        return {"late": "must not publish"}

    monkeypatch.setattr(companion, "_perform", blocked)
    companion.submit("now")
    try:
        assert entered.wait(3)
        assert companion.status()["state"] == "working"
        with pytest.raises(PairingError, match="current companion operation"):
            companion.submit("cancel")
        assert not companion.close(timeout=0)
        assert companion.status()["state"] == "closed"
        with pytest.raises(PairingError, match="closed"):
            companion.submit("cancel")
    finally:
        release.set()
        assert companion.close()
    assert companion.status()["state"] == "closed"
    assert companion.status()["result"] is None
    assert companion.status()["error"] is None


def test_blocked_host_start_is_eventually_closed_without_success(companion, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = MemoryServer.start

    def delayed(server, *args, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(server, *args, **kwargs)

    monkeypatch.setattr(MemoryServer, "start", delayed)
    companion.submit("host", "127.0.0.1", 0)
    try:
        assert entered.wait(3)
        assert not companion.close(timeout=0)
    finally:
        release.set()
        assert companion.close()
    assert companion._server.closes == 1
    assert not companion._server.running
    assert not companion.status()["listener_running"]
    assert companion.status()["result"] is None


def test_close_during_invitation_write_discards_staged_secret(companion, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    destination = tmp_path / "not-created.json"
    original = module.os.fsync

    def delayed(descriptor):
        entered.set()
        assert release.wait(3)
        original(descriptor)

    monkeypatch.setattr(module.os, "fsync", delayed)
    companion.submit("invite", str(destination))
    try:
        assert entered.wait(3)
        assert not companion.close(timeout=0)
    finally:
        release.set()
        assert companion.close()
    assert not destination.exists()
    assert not list(tmp_path.glob(".mariana-invitation-*"))
    assert companion.status()["result"] is None


def test_idle_host_updates_are_background_only_and_snapshot_failures_nonfatal(companion):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["state"] == "ready"
    companion._service.updated.clear()
    assert companion._service.updated.wait(2)

    def unavailable():
        raise RuntimeError("temporary snapshot issue")

    companion._snapshot = unavailable
    companion.submit("devices")
    assert completed(companion)["state"] == "ready"
    assert companion.status()["listener_running"]


def test_closed_queue_drops_unstarted_arguments_and_invalid_timeout_is_bounded(companion):
    companion._pending.put_nowait(("connect", ("private path", FINGERPRINT, "Desktop")))
    assert companion.close(timeout=float("nan"))
    assert companion._pending.empty()
    assert companion._pending.unfinished_tasks == 0
    with pytest.raises(queue.Empty):
        companion._pending.get_nowait()


def test_status_result_is_a_copy(companion):
    companion.submit("devices")
    result = completed(companion)
    result["result"][0]["permissions"].append("unrelated")
    assert companion.status()["result"][0]["permissions"] == ["status.read"]


def test_cleanup_failure_is_reported_without_private_exception_or_false_completion(companion, monkeypatch):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["state"] == "ready"

    def unavailable():
        raise RuntimeError("https://private.test/?token=credential")

    monkeypatch.setattr(companion._server, "close", unavailable)
    assert not companion.close()
    assert companion.status()["state"] == "closed"
    assert companion.status()["error"] == "Companion resource cleanup did not complete"
    assert "credential" not in json.dumps(companion.status())


def test_snapshot_read_failure_does_not_corrupt_ready_result(companion):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["state"] == "ready"
    attempted = threading.Event()

    def unavailable():
        attempted.set()
        raise RuntimeError("secret=not-public")

    companion._snapshot = unavailable
    assert attempted.wait(2)
    assert companion.status()["state"] == "ready"
    assert companion.status()["error"] is None
    companion.submit("devices")
    assert completed(companion)["state"] == "ready"


def test_transport_incomplete_cleanup_is_not_reported_as_success(companion, monkeypatch):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["state"] == "ready"
    monkeypatch.setattr(companion._server, "close", lambda: False)
    assert not companion.close()
    assert companion.status()["error"] == "Companion resource cleanup did not complete"


def test_cleanup_failure_is_preserved_and_explicit_close_retries(companion, monkeypatch):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["state"] == "ready"
    attempts = []
    release, entered = threading.Event(), threading.Event()

    def retryable():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("temporary private failure")
        entered.set()
        assert release.wait(3)
        return True

    monkeypatch.setattr(companion._server, "close", retryable)
    assert not companion.close()
    assert companion.status()["error"] == "Companion resource cleanup did not complete"
    try:
        started = time.monotonic()
        assert not companion.close(timeout=0)
        assert time.monotonic() - started < .2
        assert companion.status()["error"] == "Companion resource cleanup did not complete"
        assert entered.wait(1)
    finally:
        release.set()
    assert companion.close()
    assert len(attempts) == 2
    assert companion.status()["error"] is None


def test_stop_reports_incomplete_transport_and_allows_explicit_retry(companion, monkeypatch):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["state"] == "ready"
    original = companion._server.close
    attempts = []

    def incomplete_once():
        original()
        attempts.append(1)
        return len(attempts) > 1

    monkeypatch.setattr(companion._server, "close", incomplete_once)
    companion.submit("stop")
    result = completed(companion)
    assert result["state"] == "error" and "retry stop" in result["error"]
    assert not result["listener_running"]
    companion.submit("stop")
    assert completed(companion)["state"] == "ready"


def test_cleanup_retry_worker_start_failure_preserves_error_and_is_retryable(companion, monkeypatch):
    companion.submit("host", "127.0.0.1", 0)
    assert completed(companion)["state"] == "ready"
    original = companion._server.close
    monkeypatch.setattr(companion._server, "close", lambda: False)
    assert not companion.close()
    monkeypatch.setattr(companion._server, "close", original)

    def failed_start(_thread):
        raise RuntimeError("No worker")

    with monkeypatch.context() as context:
        context.setattr(threading.Thread, "start", failed_start)
        assert not companion.close()
    assert companion.status()["error"] == "Companion resource cleanup did not complete"
    assert companion.close()
    assert companion.status()["error"] is None
