from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from mariana.integrations import discord_presence
from mariana.integrations.discord_presence import (
    DiscordConnectionState,
    DiscordPresenceFailureCode,
    DiscordPresencePublisher,
)
from mariana.models import MediaRef, MediaSource, PlaybackSnapshot, PlaybackState
from mariana.presence import (
    PresenceCoordinator,
    PresenceProjection,
    project_presence,
    sanitize_presence_text,
)


def snapshot(media=None, state=PlaybackState.PLAYING, **values):
    return PlaybackSnapshot(state, media=media, **values)


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Song\n\tTitle  ", "SongTitle"),
        ("https://example.test/song", None),
        ("www.example.test", None),
        (r"C:\Users\name\song.mp3", None),
        (r"\\server\private\song.mp3", None),
        ("/home/name/song.mp3", None),
        ("file:///private/song.mp3", None),
        (None, None),
    ],
)
def test_presence_text_sanitization(value, expected):
    assert sanitize_presence_text(value) == expected


@pytest.mark.parametrize(
    "values",
    [
        {"details": "https://private.example"},
        {"details": r"C:\private\song.mp3"},
        {"details": "X"},
        {"details": "Valid", "state": "bad\nstate"},
        {"details": "Valid", "activity_type": "playing"},
        {"details": "Valid", "start_timestamp": -1},
        {"details": "Valid", "end_timestamp": -1},
        {"details": "Valid", "start_timestamp": 20, "end_timestamp": 10},
    ],
)
def test_projection_contract_rejects_unsanitized_or_invalid_values(values):
    with pytest.raises(ValueError):
        PresenceProjection(**values)


def test_presence_text_is_bounded():
    value = sanitize_presence_text("x" * 200, maximum=10)
    assert value == "x" * 9 + "…"


def test_projection_modes_and_inactive_state():
    media = MediaRef(MediaSource.YOUTUBE, "https://example.test/private?id=secret", title="Track", artist="Artist")
    playing = snapshot(media, position=20, duration=100)
    assert project_presence(playing, "off") is None
    assert project_presence(playing, "app") == PresenceProjection("Using Mariana")
    track = project_presence(playing, "track")
    assert track == PresenceProjection("Track", "by Artist")
    session = project_presence(playing, "session", now=1_000)
    assert session == PresenceProjection("Track", "by Artist · YouTube music", 980, 1080)
    assert project_presence(snapshot(media, PlaybackState.IDLE), "track") is None
    assert project_presence(snapshot(None), "session") is None


def test_projection_never_uses_a_direct_local_path_or_filename():
    direct = MediaRef(
        MediaSource.LOCAL,
        r"C:\Users\name\Private Song.mp3",
        title="Private Song",
        artist="Private Artist",
        album="Private Album",
        provenance="user",
    )
    projection = project_presence(snapshot(direct), "session")
    assert projection == PresenceProjection("Local audio", "Local audio")
    rendered = repr(projection)
    assert "Private" not in rendered and "Users" not in rendered and ".mp3" not in rendered


def test_projection_allows_authoritative_indexed_local_metadata():
    indexed = MediaRef(
        MediaSource.LOCAL,
        r"C:\Users\name\song.mp3",
        title="Song",
        artist="Artist",
        album="Album",
        provenance="library",
    )
    assert project_presence(snapshot(indexed, PlaybackState.PAUSED), "track") == PresenceProjection(
        "Song", "Paused · by Artist"
    )
    assert project_presence(snapshot(indexed, PlaybackState.PAUSED), "session") == PresenceProjection(
        "Song", "Paused · by Artist · on Album · Local audio"
    )
    indexed.provenance = "library-album"
    assert project_presence(snapshot(indexed), "track") == PresenceProjection("Song", "by Artist")


def test_projection_uses_safe_source_fallbacks_without_urls_or_endpoints():
    cases = [
        (MediaSource.URL, "Online media"),
        (MediaSource.PODCAST, "Podcast"),
        (MediaSource.RADIO, "Internet radio"),
        (MediaSource.RECOMMENDATION, "Recommended music"),
    ]
    for source, expected in cases:
        media = MediaRef(source, "https://secret.example/path?token=private", title="https://secret.example/path")
        projection = project_presence(snapshot(media), "track")
        assert projection == PresenceProjection(expected)
        assert "secret" not in repr(projection)


def test_radio_title_is_sanitized_and_youtube_id_is_never_projected():
    radio = MediaRef(MediaSource.RADIO, "https://radio.example/private", title="Station")
    assert project_presence(snapshot(radio, stream_title="Artist - Song"), "track") == PresenceProjection(
        "Artist - Song"
    )
    assert project_presence(
        snapshot(radio, stream_title="https://radio.example/private"), "track"
    ) == PresenceProjection("Station")
    youtube = MediaRef(
        MediaSource.YOUTUBE,
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        title="Song [dQw4w9WgXcQ]",
        resolver_data={"id": "dQw4w9WgXcQ"},
    )
    assert project_presence(snapshot(youtube), "track") == PresenceProjection("YouTube music")


def test_session_timestamps_require_finite_active_media():
    media = MediaRef(MediaSource.YOUTUBE, "https://example.test", title="Song")
    assert project_presence(snapshot(media, duration=float("inf")), "session", now=100).end_timestamp is None
    assert project_presence(snapshot(media, PlaybackState.BUFFERING, duration=10), "session", now=100).end_timestamp is None
    assert project_presence(snapshot(media, PlaybackState.PAUSED, duration=10), "session", now=100).end_timestamp is None


class Publisher:
    def __init__(self):
        self.events = []

    def publish(self, projection):
        self.events.append(("publish", projection))

    def clear(self, *, disconnect=False):
        self.events.append(("clear", disconnect))

    def refresh(self):
        self.events.append(("refresh",))

    def close(self, timeout=1.0):
        self.events.append(("close", timeout))


def test_coordinator_polls_deduplicates_changes_and_disconnects_when_disabled():
    media = MediaRef(MediaSource.YOUTUBE, "https://example.test", title="Song")
    current = {"snapshot": snapshot(media)}
    publisher = Publisher()
    coordinator = PresenceCoordinator(lambda: current["snapshot"], publisher, mode="track", poll_seconds=0.01)
    coordinator.start()
    wait_until(lambda: len(publisher.events) == 1)
    time.sleep(0.03)
    assert len(publisher.events) == 1
    current["snapshot"] = snapshot(media, PlaybackState.PAUSED)
    wait_until(lambda: len(publisher.events) == 2)
    coordinator.set_mode("off")
    wait_until(lambda: ("clear", True) in publisher.events)
    coordinator.close()
    assert publisher.events[-1][0] == "close"


def test_coordinator_clears_app_presence_when_track_mode_is_idle():
    publisher = Publisher()
    current = {"snapshot": snapshot(None, PlaybackState.IDLE)}
    coordinator = PresenceCoordinator(lambda: current["snapshot"], publisher, mode="app", poll_seconds=0.01)
    coordinator.start()
    wait_until(lambda: publisher.events == [("publish", PresenceProjection("Using Mariana"))])
    coordinator.set_mode("track")
    wait_until(lambda: publisher.events[-1] == ("clear", False))
    coordinator.close()


def test_coordinator_refresh_idempotent_start_and_snapshot_failure_isolation():
    publisher = Publisher()
    calls = {"count": 0}

    def provider():
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("snapshot unavailable")
        return snapshot(None, PlaybackState.IDLE)

    coordinator = PresenceCoordinator(provider, publisher, mode="app", poll_seconds=0.01)
    coordinator.start()
    thread = coordinator._thread
    coordinator.start()
    assert coordinator._thread is thread
    wait_until(lambda: publisher.events == [("publish", PresenceProjection("Using Mariana"))])
    coordinator.refresh()
    wait_until(lambda: ("refresh",) in publisher.events and len(publisher.events) >= 3)
    coordinator.close(timeout=10)
    assert publisher.events[-1] == ("close", 1.0)


def test_coordinator_deduplicates_identical_projection_deterministically():
    publisher = Publisher()
    coordinator = PresenceCoordinator(
        lambda: snapshot(None, PlaybackState.IDLE),
        publisher,
        mode="app",
    )

    coordinator._publish_current()
    coordinator._publish_current()

    assert publisher.events == [("publish", PresenceProjection("Using Mariana"))]
    coordinator.close()


class Transport:
    def __init__(self):
        self.updates = []
        self.cleared = 0
        self.closed = 0

    def update(self, **values):
        self.updates.append(values)

    def clear(self):
        self.cleared += 1

    def close(self):
        self.closed += 1


def test_default_transport_connects_local_rpc(monkeypatch):
    transport = Transport()
    transport.connect = lambda: setattr(transport, "connected", True)
    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: SimpleNamespace(Presence=lambda application_id: transport if application_id == "public-id" else None),
    )
    assert discord_presence._default_transport("public-id") is transport
    assert transport.connected is True


def test_default_transport_reports_missing_library(monkeypatch):
    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    )
    with pytest.raises(RuntimeError, match="library is unavailable"):
        discord_presence._default_transport("public-id")


def test_discord_publisher_updates_clears_and_closes_best_effort(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: SimpleNamespace(ActivityType=SimpleNamespace(LISTENING="listening")),
    )
    publisher = DiscordPresencePublisher(
        "public-application-id",
        transport_factory=lambda _application_id: transport,
        minimum_interval=0,
        retry_delays=(0.01,),
    )
    publisher.publish(PresenceProjection("Song", "by Artist"))
    wait_until(lambda: len(transport.updates) == 1)
    assert transport.updates[0] == {"details": "Song", "state": "by Artist", "activity_type": "listening"}
    publisher.clear(disconnect=True)
    wait_until(lambda: transport.closed == 1)
    assert transport.cleared == 1
    publisher.publish(PresenceProjection("Again"))
    wait_until(lambda: len(transport.updates) == 2)
    publisher.close()
    assert transport.cleared == 2 and transport.closed == 2
    assert publisher.status().state == DiscordConnectionState.CLOSED


def test_discord_clear_before_connection_is_a_noop_and_refresh_is_safe():
    publisher = DiscordPresencePublisher("public-id", transport_factory=lambda _value: Transport())
    publisher.clear(disconnect=True)
    publisher.refresh()
    assert publisher.status().state == DiscordConnectionState.DISCONNECTED
    publisher.close()


def test_discord_clear_without_disconnect_keeps_transport_connected(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: SimpleNamespace(ActivityType=SimpleNamespace(LISTENING="listening")),
    )
    publisher = DiscordPresencePublisher(
        "public-id", transport_factory=lambda _value: transport, minimum_interval=0, retry_delays=(0.01,)
    )
    publisher.publish(PresenceProjection("Playing"))
    wait_until(lambda: transport.updates)
    publisher.clear()
    wait_until(lambda: transport.cleared == 1)
    assert transport.closed == 0 and publisher.status().state == DiscordConnectionState.CONNECTED
    publisher.close()


def test_discord_absent_and_missing_application_id_are_typed(monkeypatch):
    missing_id = DiscordPresencePublisher(None, minimum_interval=0, retry_delays=(0.01,))
    missing_id.publish(PresenceProjection("Using Mariana"))
    wait_until(lambda: missing_id.status().failure_code == DiscordPresenceFailureCode.NOT_CONFIGURED)
    missing_id.close()

    def unavailable(_name):
        raise ImportError("missing")

    monkeypatch.setattr(discord_presence.importlib, "import_module", unavailable)
    absent = DiscordPresencePublisher("public-id", minimum_interval=0, retry_delays=(0.01,))
    absent.publish(PresenceProjection("Using Mariana"))
    wait_until(lambda: absent.status().failure_code == DiscordPresenceFailureCode.SDK_UNAVAILABLE)
    absent.close()


def test_discord_generic_connection_failure_is_typed():
    publisher = DiscordPresencePublisher(
        "public-id",
        transport_factory=lambda _value: (_ for _ in ()).throw(OSError("private path")),
        minimum_interval=0,
        retry_delays=(1,),
    )
    publisher.publish(PresenceProjection("Using Mariana"))
    wait_until(lambda: publisher.status().failure_code == DiscordPresenceFailureCode.CLIENT_UNAVAILABLE)
    assert "private path" not in (publisher.status().message or "")
    publisher.close()


def test_discord_payload_remains_valid_without_activity_enum(monkeypatch):
    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ImportError("missing")),
    )
    assert DiscordPresencePublisher._payload(PresenceProjection("Using Mariana")) == {"details": "Using Mariana"}


def test_discord_publisher_coalesces_latest_pending_update(monkeypatch):
    transport = Transport()
    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: SimpleNamespace(ActivityType=SimpleNamespace(LISTENING="listening")),
    )
    publisher = DiscordPresencePublisher(
        "public-id",
        transport_factory=lambda _application_id: transport,
        minimum_interval=0.05,
        retry_delays=(0.01,),
    )
    publisher.publish(PresenceProjection("First"))
    wait_until(lambda: len(transport.updates) == 1)
    publisher.publish(PresenceProjection("Second"))
    publisher.publish(PresenceProjection("Latest"))
    wait_until(lambda: len(transport.updates) == 2)
    assert transport.updates[-1]["details"] == "Latest"
    publisher.close()


def test_transport_failure_is_typed_and_never_escapes_callers(monkeypatch):
    class BrokenTransport(Transport):
        def update(self, **values):
            raise OSError("private diagnostic")

    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: SimpleNamespace(ActivityType=SimpleNamespace(LISTENING="listening")),
    )
    publisher = DiscordPresencePublisher(
        "public-id",
        transport_factory=lambda _application_id: BrokenTransport(),
        minimum_interval=0,
        retry_delays=(1,),
    )
    publisher.publish(PresenceProjection("Song"))
    wait_until(lambda: publisher.status().failure_code == DiscordPresenceFailureCode.TRANSPORT_ERROR)
    assert "private diagnostic" not in (publisher.status().message or "")
    publisher.close()


def test_clear_transport_failure_is_typed_without_reconnecting(monkeypatch):
    class BrokenClearTransport(Transport):
        def clear(self):
            raise OSError("private clear diagnostic")

    monkeypatch.setattr(
        discord_presence.importlib,
        "import_module",
        lambda _name: SimpleNamespace(ActivityType=SimpleNamespace(LISTENING="listening")),
    )
    transports = []

    def create_transport(_application_id):
        transport = BrokenClearTransport()
        transports.append(transport)
        return transport

    publisher = DiscordPresencePublisher(
        "public-id",
        transport_factory=create_transport,
        minimum_interval=0,
        retry_delays=(0.01,),
    )
    publisher.publish(PresenceProjection("Song"))
    wait_until(lambda: transports and transports[0].updates)
    publisher.clear()
    wait_until(lambda: publisher.status().failure_code == DiscordPresenceFailureCode.TRANSPORT_ERROR)

    time.sleep(0.03)
    assert len(transports) == 1
    assert "private clear diagnostic" not in (publisher.status().message or "")
    publisher.close()
