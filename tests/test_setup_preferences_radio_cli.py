from pathlib import Path
from types import SimpleNamespace

import pytest

import first_boot_setup
import main
from mariana.media_removal import MediaRemovalError, RemovalTarget
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.preferences import PreferenceEntry, PreferenceState
from mariana.radio import RadioError, RadioStation
from mariana.setup import SetupState, SetupStateError
from mariana.tool_setup import MediaToolStatus


class SetupStore:
    def __init__(self):
        self.state = SetupState(status="complete", completed_steps=["library", "samples", "launch"])
        self.reset_count = 0

    def load(self):
        return self.state

    def repair(self):
        self.state = SetupState()
        return Path("corrupt.bak")

    def reset(self):
        self.reset_count += 1
        self.state = SetupState()
        return self.state


def test_setup_command_status_repair_resume_restart_and_errors(monkeypatch):
    printed, reloads = [], []
    store = SetupStore()
    monkeypatch.setattr(main, "SETUP_STORE", store)
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "reload_sounds", lambda **kwargs: reloads.append(kwargs))

    assert main.setup_command([]).status == "complete"
    assert "Setup: complete" in printed[-1]
    assert main.setup_command(["repair"]).status == "pending"
    def finish_setup(*_args):
        store.state = SetupState(status="complete")
        return True

    monkeypatch.setattr(first_boot_setup, "fbs", finish_setup)
    store.state = SetupState(status="complete")
    assert main.setup_command(["resume"]).status == "complete"
    store.state = SetupState(status="complete")
    assert main.setup_command(["restart", "--yes"]).status == "complete"
    assert store.reset_count == 1
    assert reloads == [{"quick_load": False}, {"quick_load": False}]
    with pytest.raises(ValueError, match="Usage"):
        main.setup_command(["invalid"])

    monkeypatch.setattr(store, "load", lambda: (_ for _ in ()).throw(SetupStateError("corrupt")))
    assert main.setup_command(["status"]) is None
    assert "corrupt" in printed[-1]


@pytest.mark.parametrize("token", ["y", "yes", "--yes"])
def test_setup_restart_confirmation_bypass_tokens(monkeypatch, token):
    store = SetupStore()
    monkeypatch.setattr(main, "SETUP_STORE", store)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "reload_sounds", lambda **_kwargs: None)
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args: pytest.fail("setup restart confirmation bypass prompted"),
    )

    def finish_setup(*_args):
        store.state = SetupState(status="complete")
        return True

    monkeypatch.setattr(first_boot_setup, "fbs", finish_setup)
    assert main.setup_command(["restart", token]).status == "complete"
    assert store.reset_count == 1


def test_setup_restart_rejection_preserves_state(monkeypatch):
    store = SetupStore()
    monkeypatch.setattr(main, "SETUP_STORE", store)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    assert main.setup_command(["restart"]).status == "complete"
    assert store.reset_count == 0
    with pytest.raises(ValueError, match="Usage"):
        main.setup_command(["restart", "unexpected"])


def test_tools_command_reports_resolved_versions_and_runs_setup_or_install(monkeypatch, tmp_path):
    printed = []
    status = MediaToolStatus(
        {
            "ffmpeg": "C:/tools/ffmpeg.exe",
            "ffprobe": "C:/tools/ffprobe.exe",
            "ffplay": "C:/tools/ffplay.exe",
            "fpcalc": "C:/tools/fpcalc.exe",
            "rsgain": "C:/tools/rsgain.exe",
        },
        {name: f"{name} version" for name in ("ffmpeg", "ffprobe", "ffplay", "fpcalc", "rsgain")},
    )
    manager = SimpleNamespace(
        install_recommended=lambda **kwargs: kwargs["progress"]("progress") or tmp_path / "tools"
    )
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "discover_media_tools", lambda _settings: status)
    monkeypatch.setattr(main, "find_javascript_runtime", lambda: ("node", "C:/node.exe"))
    monkeypatch.setattr(main, "setup_media_tools", lambda *_args, **_kwargs: status)
    monkeypatch.setattr(main, "load_user_settings", lambda: {"media tools": {"ffmpeg bin": "C:/tools"}})
    monkeypatch.setattr(main, "TOOLCHAIN", manager)
    monkeypatch.setattr(main, "MEDIA_TOOLS", {})

    rows = main.tools_command(["status"])
    assert rows[-1] == ("node", "C:/node.exe", "available")
    monkeypatch.setattr(main, "find_javascript_runtime", lambda: None)
    assert main.tools_command(["status"])[-1] == ("JavaScript", "not found", "unavailable")
    assert main.tools_command(["setup"]) == status
    assert main.MEDIA_TOOLS["ffmpeg bin"] == "C:/tools"
    assert main.tools_command(["install"]) == tmp_path / "tools"
    assert main.tools_command(["repair"]) == tmp_path / "tools"
    assert "progress" in printed
    with pytest.raises(ValueError, match="Usage"):
        main.tools_command(["unknown"])


def test_preference_listing_download_root_and_recycle_helpers(monkeypatch, tmp_path: Path):
    printed, states, scans, reloads = [], [], [], []
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "song.mp3"), title="Song")
    controller = SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media))
    preferences = SimpleNamespace(
        get=lambda _media: PreferenceState.NEUTRAL,
        toggle=lambda _media, state: state,
        set=lambda *_args: True,
        list=lambda *_args: [
            PreferenceEntry(
                media.stable_id,
                PreferenceState.FAVORITE,
                "Song",
                media.original_uri,
                1,
                MediaSource.LOCAL,
                "available",
            )
        ],
    )
    monkeypatch.setattr(main.vas, "controller", controller)
    monkeypatch.setattr(main, "PREFERENCES", preferences)
    monkeypatch.setattr(main, "_sound_files", [media.original_uri])
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: printed.append(str(value)))

    assert main.preference_command([], PreferenceState.FAVORITE) == PreferenceState.NEUTRAL
    assert main.preference_command(["!"], PreferenceState.FAVORITE) == PreferenceState.FAVORITE
    assert main.preference_command(["+"], PreferenceState.BLOCKED) == PreferenceState.BLOCKED
    assert main.preference_command(["-"], PreferenceState.BLOCKED) == PreferenceState.NEUTRAL
    with pytest.raises(ValueError, match="Usage"):
        main.preference_command(["bad"], PreferenceState.FAVORITE)
    controller.snapshot = lambda: PlaybackSnapshot(PlaybackState.IDLE)
    with pytest.raises(ValueError, match="No active"):
        main.preference_command([], PreferenceState.FAVORITE)
    assert main.list_preferences(PreferenceState.FAVORITE, ["1"])[0].label == "Song"
    assert any("Library #" in value and "Source" in value for value in printed)
    with pytest.raises(ValueError, match="optional numeric"):
        main.list_preferences(PreferenceState.FAVORITE, ["all"])
    with pytest.raises(ValueError, match="optional numeric"):
        main.list_preferences(PreferenceState.FAVORITE, ["1", "2"])

    monkeypatch.setattr(main.DATABASE, "set_state", lambda key, value: states.append((key, value)))
    monkeypatch.setattr(main.LIBRARY, "sync_roots", lambda: None)
    monkeypatch.setattr(
        main.LIBRARY,
        "scan",
        lambda mode: scans.append(mode) or SimpleNamespace(changed=2),
    )
    monkeypatch.setattr(main, "reload_sounds", lambda **kwargs: reloads.append(kwargs))
    assert main.set_download_library_inclusion(True).changed == 2
    assert states == [("library_include_downloads", True)]
    assert scans == ["changed"]

    target = RemovalTarget("track", tmp_path / "song.mp3", 1, "Song", (1, 2, 3, 4))
    resolved = []
    monkeypatch.setattr(main.MEDIA_REMOVAL, "resolve", lambda value: resolved.append(value) or target)
    monkeypatch.setattr(main.MEDIA_REMOVAL, "remove", lambda value: value)
    with pytest.raises(MediaRemovalError, match="Usage"):
        main.recycle_library_media([])
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or "n")
    assert main.recycle_library_media(["1"]) is None
    assert resolved[-1] == media.original_uri
    assert all(value in prompts[-1] for value in ('Library #1', '"Song"', 'track', str(target.path)))
    monkeypatch.setattr("builtins.input", lambda *_args: "yes")
    assert main.recycle_library_media(["1"]) == target

    monkeypatch.setattr(
        "builtins.input",
        lambda *_args: pytest.fail("media-removal confirmation bypass prompted"),
    )
    for token in ("y", "yes", "--yes"):
        assert main.recycle_library_media(["1", token]) == target

    monkeypatch.setattr(main.MEDIA_REMOVAL, "resolve", lambda value: resolved.append(value) or target)
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    assert main.recycle_library_media(["yes"]) is None
    assert resolved[-1] == "yes"


class RadioCatalog:
    def __init__(self):
        self.station = RadioStation(
            "station-id",
            "station",
            "Station",
            "fixture",
            ["https://radio.test/live"],
            homepage="https://radio.test",
            country="IN",
            language="en",
            tags=["test"],
        )
        self.calls = []

    def list(self, favorites=False):
        self.calls.append(("list", favorites))
        return [self.station]

    def search(self, query):
        self.calls.append(("search", query))
        return [self.station]

    def get(self, _value):
        return self.station

    def endpoints(self, _station):
        return list(self.station.endpoints)

    def credential(self, _station_id):
        return {"reference": "radio:station-id", "username": "source"}

    def add(self, url, name):
        self.calls.append(("add", url, name))
        return self.station

    def set_credential(self, *args):
        self.calls.append(("credential", *args))

    def favorite(self, _station, enabled):
        self.calls.append(("favorite", enabled))
        return self.station

    def health(self, station_id, **kwargs):
        self.calls.append(("health", station_id, kwargs))
        return {"healthy": True}


class CredentialFixture:
    def __init__(self):
        self.calls = []

    def set(self, *args):
        self.calls.append(("set", *args))

    def delete(self, *args):
        self.calls.append(("delete", *args))
        return True

    def status(self, *args):
        self.calls.append(("status", *args))
        return {"available": True}


def test_radio_command_all_operations_and_validation(monkeypatch):
    printed, played, jumps, state_writes = [], [], [], []
    catalog = RadioCatalog()
    credentials = CredentialFixture()
    queued = []

    def add(media, **_kwargs):
        item = SimpleNamespace(media=media)
        queued.append(item)
        return item

    controller = SimpleNamespace(
        stream_metadata={"StreamTitle": "Track"},
        snapshot=lambda: SimpleNamespace(stream_metadata={"StreamTitle": "Track"}),
        restart_live=lambda: played.append("resync"),
        set_live_leveling=lambda enabled: played.append(("leveling", enabled)),
        live_leveling=False,
        live_target_lufs=-18,
        live_true_peak_dbtp=-1,
        live_lra=11,
    )
    monkeypatch.setattr(main, "RADIO", catalog)
    monkeypatch.setattr(main, "QUEUE", SimpleNamespace(add=add, items=lambda: queued, jump=lambda index: jumps.append(index)))
    monkeypatch.setattr(main, "CredentialStore", lambda: credentials)
    monkeypatch.setattr(main, "getpass", lambda _prompt: "secret")
    monkeypatch.setattr(main.vas, "controller", controller)
    monkeypatch.setattr(main, "_play_queue_item", lambda item: played.append(item))
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main.DATABASE, "set_state", lambda *args: state_writes.append(args))
    monkeypatch.setattr(main, "LIVE_LEVELING_SETTINGS", {"enabled": False})

    for arguments in (
        [],
        ["list", "favorites"],
        ["search", "ambient", "radio"],
        ["play", "station"],
        ["add", "https://radio.test/live", "My", "Station"],
        ["info", "station"],
        ["metadata"],
        ["resync"],
        ["leveling", "on"],
        ["leveling", "off"],
        ["leveling", "status"],
        ["credentials", "set", "station", "dj"],
        ["credentials", "delete", "station", "--yes"],
        ["credentials", "status", "station"],
        ["favorite", "station", "off"],
        ["health"],
        ["refresh", "station"],
    ):
        main.radio_command(arguments)

    assert queued[0].media.source == MediaSource.RADIO
    assert queued[0].media.resolver_data["credential_ref"] == "radio:station-id"
    assert jumps == [0]
    assert "resync" in played
    assert ("set", "radio:station-id", "secret") in credentials.calls
    assert ("favorite", False) in catalog.calls
    assert state_writes
    assert printed

    with pytest.raises(RadioError, match="leveling"):
        main.radio_command(["leveling", "invalid"])
    with pytest.raises(RadioError, match="credentials"):
        main.radio_command(["credentials", "invalid", "station"])
    with pytest.raises(RadioError, match="Unknown"):
        main.radio_command(["unknown"])


@pytest.mark.parametrize("token", ["y", "yes", "--yes"])
def test_radio_credential_delete_confirmation_bypass_tokens(monkeypatch, token):
    credentials = CredentialFixture()
    monkeypatch.setattr(main, "RADIO", RadioCatalog())
    monkeypatch.setattr(main, "CredentialStore", lambda: credentials)
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args: pytest.fail("radio credential confirmation bypass prompted"),
    )
    main.radio_command(["credentials", "delete", "station", token])
    assert credentials.calls == [("delete", "radio:station-id")]


def test_radio_credential_delete_rejection_and_usage(monkeypatch):
    credentials = CredentialFixture()
    printed = []
    monkeypatch.setattr(main, "RADIO", RadioCatalog())
    monkeypatch.setattr(main, "CredentialStore", lambda: credentials)
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr("builtins.input", lambda *_args: "n")
    main.radio_command(["credentials", "delete", "station"])
    assert credentials.calls == []
    assert printed[-1] == "Radio credential deletion cancelled"
    with pytest.raises(RadioError, match="Usage"):
        main.radio_command(["credentials", "delete", "station", "extra"])
