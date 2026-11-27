import concurrent.futures
from pathlib import Path
from unittest.mock import Mock

import pytest

from mariana import paths
from mariana.connection_setup import setup
from mariana.listener_profiles import ListenerProfiles


def test_new_listener_is_clean_and_keeps_stable_identity_on_rename(tmp_path, monkeypatch):
    resources = tmp_path / "bundle"
    for name, value in {"settings/settings.yml.default": "fresh: yes", "settings/system.toml":"name='Mariana'",
                         "settings/settings.yml":"secret: old", "lib.lib":"/old/library", "data/mariana.db":"legacy"}.items():
        dest = resources / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(value)
    root = tmp_path / "users"
    monkeypatch.setenv("MARIANA_DATA_DIR", str(root))
    monkeypatch.setenv("MARIANA_RESOURCE_DIR", str(resources))
    monkeypatch.delenv("MARIANA_PROFILE", raising=False)
    original = paths.initialize_runtime_paths(paths.discover_runtime_paths())
    assert original.data == root and original.database.read_text() == "legacy"
    reg = ListenerProfiles(root)
    reg.command(["create", "Studio A"], "default")
    reg.command(["use", "studio", "a"], "default")
    chosen = paths.initialize_runtime_paths(paths.discover_runtime_paths())
    assert chosen.data != root and chosen.profile_root == root
    assert not chosen.database.exists() and chosen.settings.read_text() == "fresh: yes"
    assert "/old/library" not in chosen.library_file.read_text()
    reg.command(["rename", "Studio A", "Practice"], chosen.profile_id)
    assert paths.discover_runtime_paths().data == chosen.data
    monkeypatch.setattr(paths, "_runtime_paths", chosen)
    from mariana.credentials import CredentialStore, environment_name
    from mariana.paired_trust import KeyringPairingSecrets
    assert CredentialStore().service.endswith(chosen.profile_id)
    assert KeyringPairingSecrets()._service.endswith(chosen.profile_id)
    assert chosen.profile_id.upper() in environment_name("station")
    monkeypatch.setenv("MARIANA_PROFILE", "Default")
    assert paths.discover_runtime_paths() == original
    monkeypatch.setattr(paths, "_runtime_paths", original)
    assert environment_name("station") == "MARIANA_ICECAST_PASSWORD_STATION"
    assert original.settings.read_text() == "secret: old"


def test_parallel_create_and_invalid_selection(tmp_path):
    reg = ListenerProfiles(tmp_path)
    def create():
        try:
            reg.command(["create", "Practice"], "default")
            return 1
        except ValueError:
            return 0
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        assert sum(pool.map(lambda _: create(), range(8))) == 1
    for name in ["../../tmp", "/outside", "A\nB", "x"*41]:
        with pytest.raises(ValueError):
            reg.command(["create", name], "default")
    with pytest.raises(ValueError):
        reg.command(["use", "Missing"], "default")
    assert reg.resolve() == "default"
    assert "Practice" in reg.command(["list"], "default")


def test_guided_public_tools_and_provider_consent(monkeypatch):
    dispatch = Mock()
    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert "singer" in setup(["karaoke"], None, dispatch)
    dispatch.assert_called_once_with("karaoke demo")
    monkeypatch.setattr("builtins.input", lambda _: "Great Music")
    setup(["podcasts"], None, dispatch)
    dispatch.assert_called_with('podbean search "Great Music"')
    monkeypatch.setattr("builtins.input", lambda _: "")
    assert setup(["audiobooks"], None, dispatch) == "Setup cancelled."
    db = object()
    mock_hub = Mock()
    mock_hub.run.return_value = {"services":[{"id":"spotify","name":"Spotify","identity":None,
                                               "pending":False,"available":True,"hint":"ID"}]}
    monkeypatch.setattr("mariana.connection_setup.hub", lambda _: mock_hub)
    action = Mock(return_value="Consent opened")
    monkeypatch.setattr("mariana.connection_setup.command", action)
    monkeypatch.setattr("builtins.input", lambda _: "1")
    assert setup(["spotify"], db, dispatch) == "Consent opened"
    action.assert_called_once_with(["connect","spotify"], db)


def test_personal_registration_uses_profile_vault_and_never_writes_keys_to_disk(tmp_path, monkeypatch):
    from mariana import account_services as services, connector_registration as registration
    from mariana import connection_setup
    runtime = paths.RuntimePaths(tmp_path, tmp_path / "listener", "ab"*16, tmp_path)
    monkeypatch.setattr(paths, "_runtime_paths", runtime)
    store = {}
    backend = Mock(get=store.get, set=store.__setitem__, delete=store.pop)
    monkeypatch.setattr(registration, "vault", lambda: backend)
    monkeypatch.delenv("MARIANA_LASTFM_API_KEY", raising=False)
    monkeypatch.delenv("MARIANA_LASTFM_API_SECRET", raising=False)
    values = iter(["fixture-id", "fixture-secret"])
    monkeypatch.setattr(connection_setup, "secret_input", lambda _: next(values))
    assert "keychain" in connection_setup._register("lastfm")
    assert services.settings("lastfm") == ("fixture-id", "fixture-secret")
    assert registration.marker("lastfm").read_bytes() == b""
    monkeypatch.setenv("MARIANA_LASTFM_API_KEY","publisher-key")
    monkeypatch.setenv("MARIANA_LASTFM_API_SECRET","publisher-secret")
    assert services.settings("lastfm") == ("publisher-key", "publisher-secret")
    registration.forget("lastfm")
    assert not registration.marker("lastfm").exists() and store == {}
