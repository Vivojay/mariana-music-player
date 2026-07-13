from __future__ import annotations

import mariana.tls as tls


def test_system_trust_store_enablement_is_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr(tls, "_ENABLED", False)
    monkeypatch.setattr(tls.truststore, "inject_into_ssl", lambda: calls.append(True))

    assert tls.enable_system_trust_store() is True
    assert tls.enable_system_trust_store() is True
    assert calls == [True]


def test_system_trust_store_failure_keeps_default_verification(monkeypatch):
    monkeypatch.setattr(tls, "_ENABLED", False)
    monkeypatch.setattr(
        tls.truststore,
        "inject_into_ssl",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    assert tls.enable_system_trust_store() is False
    assert tls._ENABLED is False
