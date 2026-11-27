"""Private app registration for a listener who operates their own provider client."""
from __future__ import annotations

import json

from .paths import runtime_paths

SUPPORTED = {"spotify", "lastfm", "youtube", "tiktok", "musicbrainz"}


def marker(provider):
    if provider not in SUPPORTED:
        raise ValueError("This connector does not support a local app registration.")
    return runtime_paths().state("connector-clients", provider)


def vault():
    from .paired_trust import KeyringPairingSecrets
    return KeyringPairingSecrets(service="io.github.vivojay.mariana.connector-clients")


def read(provider):
    if provider not in SUPPORTED or not marker(provider).is_file():
        return "", ""
    from .paired_trust import PairingError
    try:
        fields = json.loads(vault().get(provider) or "{}")
        if isinstance(fields, dict) and all(isinstance(fields.get(k), str) for k in ("id","secret")):
            return fields["id"], fields["secret"]
    except (PairingError, ValueError):
        pass
    return "", ""


def save(provider, public_id, secret=""):
    location = marker(provider)
    if not public_id or (provider != "spotify" and not secret):
        raise ValueError("Include the client identifier and the required secret.")
    if any(len(v) > 512 or not all(c.isprintable() for c in v) for v in (public_id, secret)):
        raise ValueError("Invalid provider registration.")
    location.parent.mkdir(parents=True, exist_ok=True)
    from .paired_trust import PairingError
    try:
        vault().set(provider, json.dumps({"id":public_id,"secret":secret}))
    except PairingError:
        raise ValueError("Unlock or enable the operating-system credential store and retry.") from None
    location.touch()  # Records the opt-in. Credential bytes only live in the keyring.


def forget(provider):
    location = marker(provider)
    from .paired_trust import PairingError
    try:
        vault().delete(provider)
    except PairingError:
        raise ValueError("Unlock the operating-system credential store and retry.") from None
    location.unlink(missing_ok=True)
