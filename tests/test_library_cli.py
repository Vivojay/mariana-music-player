import pytest

import main
from mariana.library import LibraryError, ScanResult


class Library:
    def __init__(self):
        self.actions = []

    def sync_roots(self):
        return [{"path": "C:/Music", "kind": "local", "available": 1, "error": None}]

    def scan(self, mode):
        self.actions.append(("scan", mode))
        return ScanResult("scan", 2, 1, 0, 0)

    def errors(self):
        return []

    def retry(self, target=None):
        self.actions.append(("retry", target))
        return 1

    def verify(self):
        return {"database": "ok", "unavailable_paths": []}

    def clean_missing(self):
        self.actions.append(("clean",))
        return 2

    def info(self, value):
        return {"library_id": "id", "canonical_path": value} if value != "missing" else None


class Service:
    def __init__(self):
        self.actions = []

    def status(self):
        return {
            "files": {"available": 2, "missing": 1},
            "jobs": [{"stage": "probe", "status": "pending", "count": 1}],
            "service": {"paused": False, "running": True},
        }

    def pause(self):
        self.actions.append("pause")

    def resume(self):
        self.actions.append("resume")


@pytest.mark.parametrize("command", ["roots", "status", "pause", "resume", "errors", "verify", "clean --missing", "info 1"])
def test_library_commands_are_stable(monkeypatch, command):
    library, service, printed = Library(), Service(), []
    monkeypatch.setattr(main, "LIBRARY", library)
    monkeypatch.setattr(main, "LIBRARY_SERVICE", service)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    main.library_command(command.split())
    assert printed


def test_scan_refreshes_compatibility_projection_and_retry_resolves_item(monkeypatch):
    library, service = Library(), Service()
    reloaded = []
    monkeypatch.setattr(main, "LIBRARY", library)
    monkeypatch.setattr(main, "LIBRARY_SERVICE", service)
    monkeypatch.setattr(main, "reload_sounds", lambda **kwargs: reloaded.append(kwargs))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    main.library_command(["scan", "full"])
    main.library_command(["retry", "1"])
    assert ("scan", "full") in library.actions
    assert ("retry", "id") in library.actions
    assert reloaded == [{"quick_load": True}]
    with pytest.raises(LibraryError):
        main.library_command(["info", "missing"])
    with pytest.raises(LibraryError):
        main.library_command(["clean"])
