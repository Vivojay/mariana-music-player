"""HTTP diagnostics and the Apple storefront used for artist-name fallback."""
from __future__ import annotations

import os
import re
import threading
import time

import requests

from .version import __version__


_APPLE_LOCK = threading.Lock()
_last_apple_request = float("-inf")


def catalogue_error(provider, error):
    if isinstance(error, requests.HTTPError) and error.response is not None:
        status = error.response.status_code
        if status in {429, 503}:
            reason = "rate limit" if status == 429 else "service unavailable"
            after = error.response.headers.get("Retry-After", "")
            wait = f" in {after} seconds" if re.fullmatch(r"[0-9]{1,6}", after) else " later"
            return f"{provider} returned HTTP {status} ({reason}). Try again{wait}."
        return f"{provider} returned HTTP {status}."
    if isinstance(error, requests.exceptions.SSLError):
        return f"{provider} TLS connection failed. Check the system clock and trusted certificates."
    if isinstance(error, requests.Timeout):
        return f"{provider} timed out."
    if isinstance(error, requests.ConnectionError):
        return f"Could not connect to {provider}. Check the network or proxy."
    if isinstance(error, requests.RequestException) and not isinstance(error, ValueError):
        return f"{provider} request failed."
    return f"{provider} returned an unexpected response."


def apple_country():
    country = os.environ.get("MARIANA_APPLE_COUNTRY", "US").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country):
        raise ValueError("Set MARIANA_APPLE_COUNTRY to a two-letter country code such as US or IN.")
    return country


def apple_id(value):
    return value if isinstance(value, str) and re.fullmatch(r"apple:[1-9][0-9]{0,18}", value) else ""


def apple_rows(endpoint, **params):
    global _last_apple_request
    country = apple_country()
    # Apple documents approximately 20 calls per minute across Search and Lookup.
    with _APPLE_LOCK:
        delay = 3 - (time.monotonic() - _last_apple_request)
        if delay > 0:
            time.sleep(delay)
        _last_apple_request = time.monotonic()
    try:
        response = requests.get(
            "https://itunes.apple.com/" + endpoint,
            params={**params, "country": country},
            headers={"User-Agent": f"Mariana/{__version__} (https://github.com/Vivojay/mariana-music-player)",
                     "Accept": "application/json"},
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise ValueError(catalogue_error("Apple Music", error)) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Apple Music returned an unexpected response.")
    return [row for row in payload["results"] if isinstance(row, dict)]
