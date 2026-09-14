"""Listener reuse must permit restart without sharing an active endpoint."""

from __future__ import annotations

import errno
import socket
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_paired_desktops import MemorySecrets

from mariana import paired_transport as transport
from mariana import paired_trust as trust


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_listener_configures_platform_safe_reuse_before_binding(tmp_path, monkeypatch, platform):
    events = []
    identity = trust.server_identity(tmp_path / "identity.json", MemorySecrets())
    connection = Mock()
    connection.getsockname.return_value = ("127.0.0.1", 32123)
    connection.setsockopt.side_effect = lambda *args: events.append(("option", args))

    def bind(address):
        events.append(("bind", address))
        if platform != "win32" and events[0] != ("option", (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)):
            raise OSError(errno.EADDRINUSE, "A prior connection is in TIME_WAIT")

    connection.bind.side_effect = bind
    monkeypatch.setattr(transport, "sys", SimpleNamespace(platform=platform), raising=False)
    monkeypatch.setattr(transport, "server_identity", lambda *_args: identity)
    monkeypatch.setattr(transport.socket, "socket", lambda *_args: connection)
    worker = Mock()
    worker.is_alive.return_value = False
    monkeypatch.setattr(transport.threading, "Thread", lambda **_kwargs: worker)
    service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "trust.json"))
    server = transport.PairedServer(service, tmp_path / "identity.json")
    try:
        endpoint = server.start("127.0.0.1", port=32123)
        assert endpoint.port == 32123
        expected = [] if platform == "win32" else [("option", (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1))]
        assert events == [*expected, ("bind", ("127.0.0.1", 32123))]
        connection.listen.assert_called_once_with(transport.MAX_CONNECTIONS)
    finally:
        assert server.close()
    connection.close.assert_called_once()


def test_second_listener_cannot_take_an_active_endpoint(tmp_path):
    credentials = MemorySecrets()
    first_service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "first-trust.json"))
    second_service = trust.PairedReadOnlyService(trust.TrustStore(tmp_path / "second-trust.json"))
    first = transport.PairedServer(first_service, tmp_path / "first-identity.json", credentials=credentials)
    second = transport.PairedServer(second_service, tmp_path / "second-identity.json", credentials=credentials)
    endpoint = first.start("127.0.0.1")
    try:
        with pytest.raises(trust.PairingError, match="local interface"):
            second.start(endpoint.address, port=endpoint.port)
        assert first.running
        assert not second.running
    finally:
        assert second.close()
        assert first.close()
