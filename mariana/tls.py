"""Application-level TLS configuration backed by the operating-system trust store."""

from __future__ import annotations

import threading

import truststore

_LOCK = threading.Lock()
_ENABLED = False


def enable_system_trust_store() -> bool:
    """Make Python HTTPS clients honor certificates trusted by the host OS.

    Mariana is an application, so enabling truststore's process-wide SSL
    integration at startup is appropriate. The operation is idempotent and a
    failure leaves Python's default certificate verification enabled.
    """
    global _ENABLED
    with _LOCK:
        if _ENABLED:
            return True
        try:
            truststore.inject_into_ssl()
        except Exception:
            return False
        _ENABLED = True
        return True
