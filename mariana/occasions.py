"""Privacy-preserving occasion greetings for the startup banner."""

from __future__ import annotations

import locale
import os
import re
import sys
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

COUNTRY_CODE = re.compile(r"^[A-Za-z]{2}$")
_WARMUP_LOCK = threading.Lock()
_CALENDAR_LOCK = threading.RLock()
_warmup_thread: threading.Thread | None = None


def prewarm_occasion_calendars(settings: Mapping[str, object]) -> threading.Thread | None:
    """Overlap offline calendar preparation with remaining application startup.

    This never prints or looks up a location. The normal banner remains the
    authority for today's settings and presentation; completed calendars reuse
    the existing bounded in-memory caches. Only one warmup runs at a time.
    """
    global _warmup_thread
    section = settings.get("banner")
    section = section if isinstance(section, Mapping) else {}
    if not settings.get("visible", True) or not section.get("occasion greetings", True):
        return None
    country_setting = section.get("country", "auto")
    raw_subdivision = section.get("subdivision")
    subdivision = raw_subdivision if isinstance(raw_subdivision, str) else None

    def prepare() -> None:
        # Optional calendar preparation must not change startup availability.
        with suppress(Exception):
            occasion_greeting(country_setting=country_setting, subdivision=subdivision)

    with _WARMUP_LOCK:
        if _warmup_thread is not None and _warmup_thread.is_alive():
            return _warmup_thread
        worker = threading.Thread(target=prepare, name="occasion-calendar", daemon=True)
        _warmup_thread = worker
        try:
            worker.start()
        except (RuntimeError, OSError):
            _warmup_thread = None
            return None
        return worker


@dataclass(frozen=True, slots=True)
class Occasion:
    name: str
    greeting: str
    month: int
    day: int
    countries: frozenset[str] = frozenset()
    duration_days: int = 1
    priority: int = 50
    year: int | None = None
    calendar: str | None = None

    @property
    def international(self) -> bool:
        return not self.countries

    def applies(self, current: date, country: str | None) -> bool:
        active = any(
            date(year, self.month, self.day) <= current
            < date(year, self.month, self.day) + timedelta(days=self.duration_days)
            for year in ([self.year] if self.year is not None else [current.year - 1, current.year])
            if year >= 1
        )
        return active and (self.international or country in self.countries)


INTERNATIONAL_OCCASIONS = (
    Occasion("New Year", "Wishing you a joyful year of listening and discovery", 1, 1, priority=100),
    Occasion("World Radio Day", "Celebrating radio's power to connect cultures", 2, 13),
    Occasion("International Women's Day", "Celebrating women shaping music, art, and culture", 3, 8),
    Occasion("International Jazz Day", "Celebrating jazz and its worldwide dialogue", 4, 30),
    Occasion("Pride Month", "Celebrating LGBTQ+ artists, listeners, and communities", 6, 1, duration_days=30),
    Occasion("World Music Day", "Wishing everyone a day filled with music", 6, 21, priority=80),
    Occasion(
        "International Day of the World's Indigenous Peoples",
        "Honouring Indigenous cultures, voices, and music",
        8,
        9,
    ),
    Occasion("International Peace Day", "Wishing for peace through culture and connection", 9, 21),
    Occasion("World Audiovisual Heritage Day", "Celebrating preserved sound and moving-image heritage", 10, 27),
    Occasion("Christmas", "Wishing you a peaceful Christmas", 12, 25, priority=90),
)

COUNTRY_OCCASIONS = (
    Occasion("Republic Day", "Wishing India a happy Republic Day", 1, 26, frozenset({"IN"}), priority=90),
    Occasion("Independence Day", "Wishing India a happy Independence Day", 8, 15, frozenset({"IN"}), priority=90),
    Occasion("Gandhi Jayanti", "Remembering Mahatma Gandhi's legacy of non-violence", 10, 2, frozenset({"IN"})),
    Occasion("Australia Day", "Wishing Australia a thoughtful national day", 1, 26, frozenset({"AU"})),
    Occasion("Canada Day", "Wishing Canada a happy Canada Day", 7, 1, frozenset({"CA"})),
    Occasion("Bastille Day", "Wishing France a happy national day", 7, 14, frozenset({"FR"})),
    Occasion("German Unity Day", "Wishing Germany a happy Unity Day", 10, 3, frozenset({"DE"})),
    Occasion("Independence Day", "Wishing the United States a happy Independence Day", 7, 4, frozenset({"US"})),
    Occasion("Juneteenth", "Honouring freedom, history, and Black culture", 6, 19, frozenset({"US"})),
    Occasion("Mexico Independence Day", "Wishing Mexico a happy Independence Day", 9, 16, frozenset({"MX"})),
    Occasion("Brazil Independence Day", "Wishing Brazil a happy Independence Day", 9, 7, frozenset({"BR"})),
    Occasion("Freedom Day", "Wishing South Africa a meaningful Freedom Day", 4, 27, frozenset({"ZA"})),
    Occasion("Nigeria Independence Day", "Wishing Nigeria a happy Independence Day", 10, 1, frozenset({"NG"})),
    Occasion("Culture Day", "Celebrating culture, arts, and learning in Japan", 11, 3, frozenset({"JP"})),
)


def normalize_country(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.casefold() == "auto":
        return None
    if not COUNTRY_CODE.fullmatch(text):
        raise ValueError("Banner country must be 'auto' or a two-letter ISO country code")
    return text.upper()


def _system_locale_name() -> str | None:
    """Read the local OS region without sending an address or identifier online."""
    if sys.platform == "win32":
        try:
            import ctypes

            buffer = ctypes.create_unicode_buffer(86)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
                return buffer.value
        except (AttributeError, OSError, ValueError):
            pass
    language, _encoding = locale.getlocale()
    return language or os.environ.get("LC_ALL") or os.environ.get("LANG")


def country_from_locale(locale_name: str | None) -> str | None:
    value = str(locale_name or "").split(".", 1)[0].replace("_", "-")
    parts = value.split("-")
    for part in reversed(parts[1:]):
        if COUNTRY_CODE.fullmatch(part):
            return part.upper()
    return None


def configured_country(value: object = "auto", *, locale_name: str | None = None) -> str | None:
    explicit = normalize_country(value)
    if explicit:
        return explicit
    return country_from_locale(_system_locale_name() if locale_name is None else locale_name)


def validate_region(country: str | None, subdivision: object = None) -> str | None:
    """Validate an explicit region using the installed offline calendar registry."""
    import holidays

    value = str(subdivision or "").strip().upper()
    value = None if value in {"", "NONE", "AUTO"} else value
    if country is None:
        if value:
            raise ValueError("Set a banner country before its subdivision")
        return None
    supported = holidays.list_supported_countries()
    if country not in supported:
        raise ValueError(f"No holiday calendar is available for country {country}")
    if value and value not in supported[country]:
        raise ValueError(f"Unsupported subdivision for {country}; use one of: {', '.join(supported[country]) or 'none'}")
    return value


def _calendar(country: str, subdivision: str | None, year: int) -> tuple[Occasion, ...]:
    # functools' cache alone permits duplicate computation on concurrent misses.
    # Recheck it after taking the lock when the banner races startup warmup.
    with _CALENDAR_LOCK:
        return _cached_calendar(country, subdivision, year)


@lru_cache(maxsize=16)
def _cached_calendar(country: str, subdivision: str | None, year: int) -> tuple[Occasion, ...]:
    import holidays

    calendar = holidays.country_holidays(
        country, subdiv=subdivision, years=year, expand=False, observed=False, language="en_US",
    )
    region = f"{country}-{subdivision}" if subdivision else country
    return tuple(
        Occasion(name, f"Observing {name}", day.month, day.day, frozenset({country}),
                 year=year, calendar=region)
        for day in sorted(calendar)
        for name in calendar.get_list(day)
        if not name.startswith("Day off")
    )


@lru_cache(maxsize=4)
def _international_movable(year: int) -> tuple[Occasion, ...]:
    """A small curated global selection with an explicit reference calendar."""
    from dateutil.easter import easter

    day = easter(year)
    result = [Occasion("Easter", "Wishing those celebrating a peaceful Easter", day.month,
                       day.day, year=year, calendar="Western Christian")]
    for country, prefixes in (("IN", ("Holi", "Diwali")), ("CN", ("Chinese New Year (",)),
                              ("SA", ("Eid al-Fitr", "Eid al-Adha"))):
        seen = set()
        for item in _calendar(country, None, year):
            for prefix in prefixes:
                if item.name.startswith(prefix) and prefix not in seen:
                    seen.add(prefix)
                    result.append(Occasion(
                        item.name, f"Warm wishes to those celebrating {item.name}",
                        item.month, item.day, year=year, calendar=country,
                    ))
    return tuple(result)


def detect_country() -> str:
    """Explicit country-only lookup; never called during startup or redraw."""
    import requests

    try:
        with requests.get("https://ipapi.co/country/", timeout=(3.05, 5),
                          allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ValueError("Country lookup is unavailable; set the country manually")
            payload = bytearray()
            for chunk in response.iter_content(chunk_size=16):
                payload.extend(chunk)
                if len(payload) > 16:
                    raise ValueError("Country lookup returned an invalid response")
            value = payload.decode("ascii").strip()
            country = normalize_country(value)
            if country is None:
                raise ValueError("Country lookup returned no country")
            validate_region(country)
            return country
    except (requests.RequestException, UnicodeError) as error:
        raise ValueError("Country lookup failed; set the country manually") from error


def occasion_palette(matches: tuple[Occasion, ...]) -> list[tuple[str, str]] | None:
    """Use the existing terminal banner renderer with readable occasion colours."""
    if not matches:
        return None
    names = " ".join(item.name.casefold() for item in matches)
    if any(word in names for word in ("holi", "pride")):
        colors = ("red", "yellow", "green", "cyan", "blue", "magenta")
    elif any(word in names for word in ("diwali", "new year", "christmas")):
        colors = ("red", "yellow", "white", "yellow", "red")
    elif any(word in names for word in ("eid", "easter")):
        colors = ("green", "cyan", "white", "cyan", "green")
    else:
        colors = ("magenta", "blue", "cyan", "blue", "magenta")
    return [(color, "black" if color in {"yellow", "white", "cyan", "green"} else "white") for color in colors]


def current_occasions(
    current: date | None = None,
    *,
    country: str | None = None,
    subdivision: str | None = None,
) -> tuple[Occasion, ...]:
    today = current or date.today()
    normalized = normalize_country(country) if country else None
    matches = [
        occasion
        for occasion in (*INTERNATIONAL_OCCASIONS, *COUNTRY_OCCASIONS)
        if occasion.applies(today, normalized)
    ]
    try:
        domestic = _calendar(normalized, subdivision, today.year) if normalized else ()
        known_names = {item.name.casefold() for item in matches}
        for item in domestic:
            if item.applies(today, normalized) and item.name.casefold() not in known_names:
                matches.append(item)
                known_names.add(item.name.casefold())
        for item in _international_movable(today.year):
            # Prefer the locally observed date when this country has its own rule.
            family = item.name.split(" (")[0]
            locally_defined = any(value.name.startswith(family) for value in domestic)
            if not locally_defined and item.applies(today, normalized) and item.name.casefold() not in known_names:
                matches.append(item)
    except (ImportError, KeyError, ValueError, NotImplementedError):
        # The fixed calendar still works when an optional platform calendar is unavailable.
        pass
    return tuple(sorted(matches, key=lambda item: (-item.priority, item.name)))


def occasion_greeting(
    current: date | None = None,
    *,
    country_setting: object = "auto",
    locale_name: str | None = None,
    subdivision: str | None = None,
) -> tuple[str | None, tuple[Occasion, ...], str | None]:
    country = configured_country(country_setting, locale_name=locale_name)
    matches = current_occasions(current, country=country, subdivision=subdivision)
    if not matches:
        return None, matches, country
    greeting = " | ".join(
        f"{item.name}: {item.greeting}"
        + (f" [{item.calendar} calendar; local dates may differ]" if item.calendar and item.international else "")
        for item in matches
    )
    return greeting, matches, country
