"""Transactional, resumable first-run setup state."""

from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

from .paths import RuntimePaths, runtime_paths

VALID_STATUSES = {"pending", "in_progress", "complete", "failed"}


class SetupStateError(RuntimeError):
    """Raised when setup state or locking cannot be trusted."""


class SetupAlreadyRunning(SetupStateError):
    pass


@dataclass(slots=True)
class SetupState:
    schema_version: int = 1
    status: str = "pending"
    attempt_id: str | None = None
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    started_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    error: dict[str, str] | None = None
    migrated_existing_install: bool = False

    @classmethod
    def from_dict(cls, payload: dict) -> SetupState:
        state = cls(**payload)
        if state.schema_version != 1 or state.status not in VALID_STATUSES:
            raise SetupStateError("Unsupported or invalid setup state")
        if not isinstance(state.completed_steps, list) or not all(
            isinstance(step, str) for step in state.completed_steps
        ):
            raise SetupStateError("Invalid completed setup steps")
        return state


class SetupStateStore:
    def __init__(self, paths: RuntimePaths | None = None):
        self.paths = paths or runtime_paths()
        self.path = self.paths.setup_state
        self.lock_path = self.paths.setup_lock

    def load(self) -> SetupState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise SetupStateError("Setup state must contain an object")
            return SetupState.from_dict(payload)
        except SetupStateError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise SetupStateError(f"Setup state is unreadable: {error}") from error

    def save(self, state: SetupState) -> SetupState:
        state.updated_at = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(asdict(state), stream, indent=2, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        return state

    def begin(self, step: str | None = None) -> SetupState:
        state = self.load()
        if state.status == "complete":
            return state
        state.status = "in_progress"
        state.attempt_id = state.attempt_id or uuid.uuid4().hex
        state.started_at = state.started_at or time.time()
        state.current_step = step
        state.error = None
        return self.save(state)

    def complete_step(self, step: str) -> SetupState:
        state = self.load()
        if step not in state.completed_steps:
            state.completed_steps.append(step)
        state.status = "in_progress"
        state.current_step = None
        state.error = None
        return self.save(state)

    def fail(self, step: str | None, error: BaseException) -> SetupState:
        try:
            state = self.load()
        except SetupStateError:
            state = SetupState()
        state.status = "failed"
        state.current_step = step
        state.error = {"type": type(error).__name__, "message": str(error)[:500]}
        return self.save(state)

    def complete(self) -> SetupState:
        state = self.load()
        state.status = "complete"
        state.current_step = None
        state.error = None
        return self.save(state)

    def reset(self) -> SetupState:
        return self.save(SetupState())

    def repair(self) -> Path | None:
        backup = None
        if self.path.exists():
            backup = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}.bak")
            os.replace(self.path, backup)
        self.reset()
        return backup

    @staticmethod
    def _process_matches(payload: dict) -> bool:
        try:
            pid = int(payload["pid"])
            created = float(payload["created_at"])
            process = psutil.Process(pid)
            return process.is_running() and abs(process.create_time() - created) < 1.0
        except (KeyError, TypeError, ValueError, psutil.Error):
            return False

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "created_at": psutil.Process(os.getpid()).create_time(),
            "nonce": uuid.uuid4().hex,
        }
        while True:
            try:
                descriptor = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    existing = json.loads(self.lock_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    existing = {}
                if self._process_matches(existing):
                    raise SetupAlreadyRunning(
                        "First-run setup is already active for this data directory"
                    ) from None
                stale = self.lock_path.with_name(f"{self.lock_path.name}.stale-{int(time.time())}")
                try:
                    os.replace(self.lock_path, stale)
                except FileNotFoundError:
                    continue
                continue
            else:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    json.dump(payload, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
                break
        try:
            yield
        finally:
            try:
                current = json.loads(self.lock_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                current = {}
            if current.get("nonce") == payload["nonce"]:
                self.lock_path.unlink(missing_ok=True)
