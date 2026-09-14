"""Integration coverage for homepage and current-artwork application boundaries."""

from __future__ import annotations

import threading
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from config_manager import load_user_settings
from mariana.artwork import (
    ArtworkOrigin,
    ArtworkProjection,
    ArtworkState,
    CurrentArtwork,
)
from mariana.homepage import HomepageArticle, HomepageConfiguration
from mariana.models import MediaCapabilities, MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.presence import PresencePrivacyMode
from mariana.sources import ResolvedMedia


def _homepage_projection(*, startup: bool = True, online: bool = False) -> dict[str, object]:
    return {
        "schema_version": 2,
        "show_on_startup": startup,
        "online_enabled": online,
        "state": "offline" if not online else "ready",
        "refreshed_at": None,
        "safe_message": "Online discovery is off" if not online else None,
        "sections": [
            {
                "key": "local",
                "title": "Your Mariana",
                "items": [
                    {
                        "id": "local-summary:library",
                        "title": "Library",
                        "summary": "2 media items",
                        "source": "Mariana",
                        "published_at": None,
                        "link": None,
                        "image_key": None,
                        "image_mime": None,
                    }
                ],
            },
            {"key": "culture", "title": "Music, art, and culture", "items": []},
        ],
    }


class HomepageStub:
    def __init__(self, projection: dict[str, object], *, refresh_result: bool = True) -> None:
        self.value = deepcopy(projection)
        self.refresh_result = refresh_result
        self.refresh_calls = 0
        self.configure_calls: list[tuple[bool | None, bool | None]] = []

    def snapshot(self) -> dict[str, object]:
        return deepcopy(self.value)

    def configure(
        self,
        *,
        show_on_startup: bool | None = None,
        online_enabled: bool | None = None,
    ) -> dict[str, object]:
        self.configure_calls.append((show_on_startup, online_enabled))
        if show_on_startup is not None:
            self.value["show_on_startup"] = show_on_startup
        if online_enabled is not None:
            self.value["online_enabled"] = online_enabled
            self.value["state"] = "ready" if online_enabled else "offline"
        return self.snapshot()

    def refresh_async(self) -> bool:
        self.refresh_calls += 1
        return self.refresh_result


class ArtworkStub:
    def __init__(
        self,
        projection: ArtworkProjection,
        *,
        image: CurrentArtwork | None = None,
        fetch_result: int | None = 1,
    ) -> None:
        self.value = projection
        self.image = image
        self.fetch_result = fetch_result
        self.enabled_calls: list[bool] = []
        self.activations: list[dict[str, object]] = []
        self.clear_calls = 0

    def projection(self) -> ArtworkProjection:
        return self.value

    def set_automatic_online(self, enabled: bool) -> None:
        self.enabled_calls.append(enabled)
        self.value = replace(self.value, automatic_online=enabled)

    def fetch_current(self, expected_media_id: str | None = None) -> int | None:
        if expected_media_id is not None and expected_media_id != self.value.media_id:
            return None
        return self.fetch_result

    def wait_for_idle(self, timeout: float = 5.0) -> ArtworkProjection:
        del timeout
        return self.value

    def current_image(self, expected_cache_key: str | None = None) -> CurrentArtwork | None:
        if self.image is None or expected_cache_key != self.image.cache_key:
            return None
        return self.image

    def activate(self, media_identity: str, **kwargs: object) -> int:
        self.activations.append({"media_identity": media_identity, **kwargs})
        return len(self.activations)

    def clear(self) -> int:
        self.clear_calls += 1
        return self.clear_calls


def _ready_artwork(path: Path, *, automatic_online: bool = False) -> tuple[ArtworkProjection, CurrentArtwork]:
    cache_key = f"{'a' * 64}.png"
    projection = ArtworkProjection(
        1,
        "media-1",
        ArtworkState.READY,
        automatic_online,
        available=True,
        cache_key=cache_key,
        mime_type="image/png",
        source=ArtworkOrigin.EMBEDDED,
    )
    return projection, CurrentArtwork(path, cache_key, "image/png", ArtworkOrigin.EMBEDDED)


def test_release_guidance_reuses_album_search_without_executing_during_display(monkeypatch):
    release_id = "1f1db316-8361-4a40-9633-550b259642f5"
    article = HomepageArticle(
        "release", "An album", "A release", "ListenBrainz fresh releases",
        f"https://musicbrainz.org/release/{release_id}", section="releases",
    )
    searches = []
    printed = []
    events = []
    monkeypatch.setattr(main, "ALBUMS", SimpleNamespace(
        search=lambda query, **kwargs: searches.append((query, kwargs)) or [],
    ))
    monkeypatch.setattr(main, "IPrint", lambda value, **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(
        emit=lambda event, payload: events.append((event, payload)),
    ))
    projection = _homepage_projection()
    projection["sections"] = [{"key": "releases", "title": "New releases", "items": [article.to_projection_item()]}]
    main._print_homepage(projection)
    expected = f"album search reid:{release_id} --scope online"
    assert expected in "\n".join(printed)
    assert searches == [] and events == []
    # Only an explicit invocation of the existing command performs a search.
    main.album_command(expected.split()[1:])
    assert searches == [(f"reid:{release_id}", {"scope": "online", "limit": 10})]
    assert events == [("album", {"view": "search", "results": []})]


def test_shipped_discovery_defaults_and_additive_migration_preserve_explicit_choices(tmp_path: Path):
    defaults_path = Path(main.__file__).resolve().parent / "settings" / "settings.yml.default"

    first_boot = load_user_settings(
        tmp_path / "new" / "settings.yml",
        defaults_path,
        persist_migration=False,
    )
    assert first_boot["homepage"] == {
        "show on startup": True,
        "online content": False,
    }
    assert first_boot["artwork"] == {"automatic online retrieval": False}

    explicit_path = tmp_path / "settings.yml"
    explicit_path.write_text(
        "homepage:\n  show on startup: false\n  online content: true\n"
        "artwork:\n  automatic online retrieval: true\n",
        encoding="utf-8",
    )
    migrated = load_user_settings(explicit_path, defaults_path, persist_migration=False)
    assert main._configured_homepage(migrated) == HomepageConfiguration(False, True)
    assert main._configured_automatic_artwork(migrated) is True
    assert main._configured_homepage({}) == HomepageConfiguration(True, False)
    assert main._configured_automatic_artwork({}) is False


def test_home_commands_keep_startup_visibility_and_network_consent_independent(monkeypatch, tmp_path):
    service = HomepageStub(_homepage_projection())
    settings = {"homepage": {"show on startup": True, "online content": False}}
    saved: list[dict[str, object]] = []
    events: list[tuple[str, dict[str, object]]] = []
    printed: list[str] = []
    monkeypatch.setattr(main, "HOMEPAGE", service)
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    monkeypatch.setattr(
        main,
        "save_user_settings",
        lambda value, _path: saved.append(deepcopy(value)),
    )
    monkeypatch.setattr(
        main,
        "DESKTOP_CONTROL",
        SimpleNamespace(emit=lambda event, payload: events.append((event, payload))),
    )
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))

    assert main.home_command([])["state"] == "offline"
    assert events[-1][0] == "homepage" and events[-1][1]["open_requested"] is True
    assert main.home_command(["status"])["online_enabled"] is False
    main.home_command(["disable"])
    assert settings["homepage"] == {"show on startup": False, "online content": False}
    main.home_command(["online", "enable"])
    assert settings["homepage"] == {"show on startup": False, "online content": True}
    assert service.refresh_calls == 1
    main.home_command(["refresh"])
    assert service.refresh_calls == 2
    main.home_command(["online", "off"])
    assert settings["homepage"] == {"show on startup": False, "online content": False}
    with pytest.raises(ValueError, match="Online discovery is disabled"):
        main.home_command(["refresh"])
    with pytest.raises(ValueError, match="Usage: home"):
        main.home_command(["unexpected"])

    assert saved[0]["homepage"] == {"show on startup": False, "online content": False}
    assert saved[1]["homepage"] == {"show on startup": False, "online content": True}
    assert "Mariana Home" in "\n".join(printed)


def test_discovery_setting_writes_roll_back_live_and_persisted_state(monkeypatch, tmp_path):
    homepage = HomepageStub(_homepage_projection(startup=False, online=True))
    artwork_projection, _ = _ready_artwork(tmp_path / "cover.png", automatic_online=True)
    artwork = ArtworkStub(artwork_projection)
    original = {
        "homepage": {"show on startup": False, "online content": True},
        "artwork": {"automatic online retrieval": True},
    }
    settings = deepcopy(original)
    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "HOMEPAGE", homepage)
    monkeypatch.setattr(main, "ARTWORK", artwork)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    monkeypatch.setattr(
        main,
        "save_user_settings",
        lambda *_args: (_ for _ in ()).throw(OSError("read only")),
    )

    with pytest.raises(OSError, match="read only"):
        main._persist_homepage_configuration(show_on_startup=True, online_enabled=False)
    assert settings == original
    assert homepage.configure_calls[-1] == (False, True)

    with pytest.raises(OSError, match="read only"):
        main._persist_artwork_configuration(False)
    assert settings == original
    assert artwork.enabled_calls == [True]


def test_desktop_and_terminal_setting_writes_share_one_transaction_lock(
    monkeypatch, tmp_path
):
    homepage = HomepageStub(_homepage_projection())
    settings = {
        "homepage": {"show on startup": True, "online content": False},
        "appearance": {"terminal theme": "aurora"},
    }
    first_save_entered = threading.Event()
    release_first_save = threading.Event()
    second_writer_started = threading.Event()
    saved: list[dict[str, object]] = []
    failures: list[Exception] = []

    def save_settings(value, _path):
        saved.append(deepcopy(value))
        if len(saved) == 1:
            first_save_entered.set()
            assert release_first_save.wait(2)

    def run_safely(action):
        try:
            action()
        except Exception as error:
            failures.append(error)

    monkeypatch.setattr(main, "SETTINGS", settings)
    monkeypatch.setattr(main, "HOMEPAGE", homepage)
    monkeypatch.setattr(main, "RUNTIME_PATHS", SimpleNamespace(settings=tmp_path / "settings.yml"))
    monkeypatch.setattr(main, "save_user_settings", save_settings)
    monkeypatch.setattr(main, "DESKTOP_CONTROL", SimpleNamespace(emit=lambda *_args: None))
    monkeypatch.setattr(main, "IPrint", lambda *_args, **_kwargs: None)

    homepage_writer = threading.Thread(
        target=lambda: run_safely(
            lambda: main._persist_homepage_configuration(show_on_startup=False)
        )
    )

    def write_theme():
        second_writer_started.set()
        main.theme_command(["gruvbox"])

    theme_writer = threading.Thread(target=lambda: run_safely(write_theme))
    homepage_writer.start()
    assert first_save_entered.wait(2)
    theme_writer.start()
    assert second_writer_started.wait(2)

    # The second writer cannot mutate or persist the shared mapping while the
    # first read-mutate-write transaction is still in progress.
    assert len(saved) == 1
    assert settings["appearance"]["terminal theme"] == "aurora"

    release_first_save.set()
    homepage_writer.join(2)
    theme_writer.join(2)

    assert not homepage_writer.is_alive()
    assert not theme_writer.is_alive()
    assert failures == []
    assert len(saved) == 2
    assert saved[-1]["homepage"] == {
        "show on startup": False,
        "online content": False,
    }
    assert saved[-1]["appearance"] == {"terminal theme": "gruvbox"}


def test_desktop_homepage_controls_validate_payloads_and_return_safe_failures(monkeypatch):
    homepage = HomepageStub(_homepage_projection())
    emitted: list[tuple[str, dict[str, object]]] = []
    configured: list[tuple[str, bool]] = []
    monkeypatch.setattr(main, "HOMEPAGE", homepage)
    monkeypatch.setattr(
        main,
        "DESKTOP_CONTROL",
        SimpleNamespace(emit=lambda event, payload: emitted.append((event, payload))),
    )
    monkeypatch.setattr(
        main,
        "_persist_homepage_configuration",
        lambda **values: configured.extend(values.items()),
    )

    assert main._desktop_control_request("homepage.open", {}) == {"ok": True}
    assert emitted[-1][1]["open_requested"] is True
    assert main._desktop_control_request("homepage.open", {"unexpected": True}) == {
        "ok": False,
        "error": "Homepage request is invalid",
    }
    assert main._desktop_control_request(
        "homepage.configure", {"setting": "startup", "enabled": False}
    ) == {"ok": True}
    assert configured == [("show_on_startup", False)]
    assert main._desktop_control_request(
        "homepage.configure", {"setting": "online", "enabled": "yes"}
    ) == {"ok": False, "error": "Homepage setting is invalid"}
    assert main._desktop_control_request("homepage.refresh", {}) == {
        "ok": False,
        "error": "Enable online discovery before refreshing",
    }

    homepage.value["online_enabled"] = True
    assert main._desktop_control_request("homepage.refresh", {}) == {"ok": True}
    homepage.refresh_result = False
    assert main._desktop_control_request("homepage.refresh", {}) == {
        "ok": False,
        "error": "Homepage refresh is unavailable",
    }

    monkeypatch.setattr(
        main,
        "_persist_homepage_configuration",
        lambda **_values: (_ for _ in ()).throw(RuntimeError("C:/private?token=secret")),
    )
    assert main._desktop_control_request(
        "homepage.configure", {"setting": "online", "enabled": True}
    ) == {"ok": False, "error": "Could not update homepage settings"}


def test_thumb_commands_use_typed_desktop_request_or_direct_platform_open(monkeypatch, tmp_path):
    projection, image = _ready_artwork(tmp_path / "cover.png")
    artwork = ArtworkStub(projection, image=image)
    opened: list[Path] = []
    emitted: list[tuple[str, dict[str, object]]] = []
    configured: list[bool] = []
    printed: list[str] = []
    media = MediaRef(MediaSource.LOCAL, str(tmp_path / "song.mp3"), stable_id="media-1")
    desktop = SimpleNamespace(
        enabled=False,
        emit=lambda event, payload: emitted.append((event, payload)),
    )
    monkeypatch.setattr(main, "ARTWORK", artwork)
    monkeypatch.setattr(
        main.vas,
        "controller",
        SimpleNamespace(snapshot=lambda: PlaybackSnapshot(PlaybackState.PLAYING, media=media)),
    )
    monkeypatch.setattr(main, "DESKTOP_CONTROL", desktop)
    monkeypatch.setattr(main, "open_path", lambda path: opened.append(path))
    monkeypatch.setattr(main, "IPrint", lambda value="", **_kwargs: printed.append(str(value)))
    monkeypatch.setattr(
        main,
        "_persist_artwork_configuration",
        lambda enabled: configured.append(enabled) or replace(projection, automatic_online=enabled),
    )

    assert main.thumb_command([]) is projection
    assert "Automatic online artwork: disabled" in printed[-1]
    main.thumb_command(["enable"])
    main.thumb_command(["disable"])
    assert configured == [True, False]

    assert main.thumb_command(["show"]) is projection
    assert opened == [image.path]
    assert not emitted

    monkeypatch.setattr(
        main,
        "open_path",
        lambda _path: (_ for _ in ()).throw(main.PlatformCapabilityError("private detail")),
    )
    with pytest.raises(ValueError, match="Artwork viewer is unavailable on this system"):
        main.thumb_command(["show"])
    with pytest.raises(ValueError, match="Current media changed"):
        main._show_current_artwork(
            fetch=True,
            desktop=True,
            expected_media_id="stale-media",
        )

    desktop.enabled = True
    assert main.thumb_command(["show", "--fetch"]) is projection
    assert opened == [image.path]
    assert emitted[-1] == ("artwork", {**projection.to_dict(), "show_requested": True})
    with pytest.raises(ValueError, match="Usage: thumb"):
        main.thumb_command(["show", "unexpected"])

    artwork.fetch_result = None
    with pytest.raises(ValueError, match="no supported provider artwork"):
        main.thumb_command(["show", "--fetch"])


def test_desktop_artwork_controls_are_narrow_and_sanitize_backend_errors(monkeypatch):
    configured: list[bool] = []
    shown: list[tuple[bool, bool, str | None]] = []
    monkeypatch.setattr(
        main,
        "_persist_artwork_configuration",
        lambda enabled: configured.append(enabled),
    )
    monkeypatch.setattr(
        main,
        "_show_current_artwork",
        lambda *, fetch, desktop, expected_media_id=None: shown.append(
            (fetch, desktop, expected_media_id)
        ),
    )

    assert main._desktop_control_request("artwork.configure", {"enabled": True}) == {"ok": True}
    assert configured == [True]
    assert main._desktop_control_request("artwork.configure", {"enabled": 1}) == {
        "ok": False,
        "error": "Artwork setting is invalid",
    }
    assert main._desktop_control_request(
        "artwork.show", {"media_id": "media-1", "fetch": False}
    ) == {"ok": True}
    assert shown == [(False, True, "media-1")]
    assert main._desktop_control_request("artwork.show", {"fetch": False}) == {
        "ok": False,
        "error": "Artwork request is invalid",
    }
    assert main._desktop_control_request(
        "artwork.show", {"media_id": "media-1", "fetch": False, "path": "private"}
    ) == {
        "ok": False,
        "error": "Artwork request is invalid",
    }

    monkeypatch.setattr(
        main,
        "_show_current_artwork",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("C:/private?token=secret")),
    )
    assert main._desktop_control_request(
        "artwork.show", {"media_id": "media-1", "fetch": True}
    ) == {
        "ok": False,
        "error": "Current artwork is unavailable",
    }
    monkeypatch.setattr(
        main,
        "_show_current_artwork",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("No media is currently active")),
    )
    assert main._desktop_control_request(
        "artwork.show", {"media_id": "media-1", "fetch": False}
    ) == {
        "ok": False,
        "error": "No media is currently active",
    }


def test_active_media_artwork_binding_uses_only_trusted_provider_metadata(monkeypatch):
    projection = ArtworkProjection(1, None, ArtworkState.IDLE, False)
    artwork = ArtworkStub(projection)
    monkeypatch.setattr(main, "ARTWORK", artwork)

    local = MediaRef(MediaSource.LOCAL, "C:/private/music/song.flac", stable_id="local-1")
    main._artwork_active_media_changed(local, None)

    podcast = MediaRef(
        MediaSource.PODCAST,
        "https://media.test/episode.mp3?token=secret",
        stable_id="podcast-1",
        resolver_data={"artwork": "https://images.test/podcast.jpg"},
    )
    main._artwork_active_media_changed(podcast, None)

    generic = MediaRef(
        MediaSource.URL,
        "https://media.test/track.mp3?token=secret",
        stable_id="url-1",
        resolver_data={"artwork": "https://untrusted.test/caller.jpg"},
    )
    main._artwork_active_media_changed(generic, None)

    youtube = MediaRef(MediaSource.YOUTUBE, "https://youtu.be/public", stable_id="youtube-1")
    resolved = ResolvedMedia(
        youtube,
        "https://cdn.test/private-playback?token=secret",
        "https://www.youtube.com/watch?v=public",
        MediaCapabilities(),
        metadata={"artwork": "https://images.test/provider.jpg"},
    )
    main._artwork_active_media_changed(youtube, resolved)

    radio = MediaRef(MediaSource.RADIO, "station-id", stable_id="radio-1")
    radio_resolved = ResolvedMedia(
        radio,
        "https://radio.test/live",
        "station-id",
        MediaCapabilities(live=True, finite=False),
        metadata={"artwork": "https://images.test/radio.jpg"},
    )
    main._artwork_active_media_changed(radio, radio_resolved)
    main._artwork_active_media_changed(None, None)

    assert artwork.activations == [
        {
            "media_identity": "local-1",
            "projection_media_id": "local-1",
            "local_path": "C:/private/music/song.flac",
            "trusted_provider_url": None,
        },
        {
            "media_identity": "podcast-1",
            "projection_media_id": "podcast-1",
            "local_path": None,
            "trusted_provider_url": "https://images.test/podcast.jpg",
        },
        {
            "media_identity": "url-1",
            "projection_media_id": "url-1",
            "local_path": None,
            "trusted_provider_url": None,
        },
        {
            "media_identity": "youtube-1",
            "projection_media_id": "youtube-1",
            "local_path": None,
            "trusted_provider_url": "https://images.test/provider.jpg",
        },
        {
            "media_identity": "radio-1",
            "projection_media_id": "radio-1",
            "local_path": None,
            "trusted_provider_url": None,
        },
    ]
    assert artwork.clear_calls == 1


def test_run_publishes_discovery_state_and_refreshes_only_opted_in_homepage(monkeypatch):
    homepage = HomepageStub(_homepage_projection(startup=True, online=True))
    artwork_projection = ArtworkProjection(1, None, ArtworkState.IDLE, False)
    artwork = ArtworkStub(artwork_projection)
    events: list[tuple[str, object]] = []
    desktop = SimpleNamespace(
        enabled=True,
        start_request_listener=lambda callback: events.append(("request-listener", callback)),
        start_playback_monitor=lambda callback: events.append(("playback-monitor", callback)),
        start_safety_monitor=lambda callback: events.append(("safety-monitor", callback)),
        emit=lambda event, payload=None: events.append((event, payload)),
    )
    monkeypatch.setattr(main, "HOMEPAGE", homepage)
    monkeypatch.setattr(main, "ARTWORK", artwork)
    monkeypatch.setattr(main, "DESKTOP_CONTROL", desktop)
    monkeypatch.setattr(main, "PRESENCE", SimpleNamespace(mode=PresencePrivacyMode.OFF))
    monkeypatch.setattr(main, "FIRST_BOOT", False)
    monkeypatch.setattr(main, "visible", False)
    monkeypatch.setattr(main, "initialize_audio_output", lambda: None)
    monkeypatch.setattr(main, "_emit_queue_desktop_state", lambda: None)
    monkeypatch.setattr(main, "DOWNLOADS", SimpleNamespace(status=list))
    monkeypatch.setattr(main, "LIBRARY_SERVICE", SimpleNamespace(start=lambda **_kwargs: None))
    monkeypatch.setattr(main, "save_user_data", lambda: None)
    monkeypatch.setattr(main, "mainprompt", lambda: None)
    monkeypatch.setattr(main, "USER_DATA", {"default_user_data": {"stats": {"log_ins": 0}}})

    main.run()

    assert ("homepage", homepage.snapshot()) in events
    assert ("artwork", artwork_projection.to_dict()) in events
    assert homepage.refresh_calls == 1
    assert main.USER_DATA["default_user_data"]["stats"]["log_ins"] == 1
