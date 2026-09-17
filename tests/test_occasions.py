from datetime import date

import pytest

from config_manager import deep_merge_defaults
from mariana.occasions import (
    configured_country,
    country_from_locale,
    current_occasions,
    normalize_country,
    occasion_greeting,
    occasion_palette,
    validate_region,
)


@pytest.mark.parametrize(
    ("locale_name", "country"),
    [("en_IN", "IN"), ("en-US", "US"), ("pt-BR.UTF-8", "BR"), ("C", None)],
)
def test_country_uses_local_region_without_network(locale_name, country):
    assert country_from_locale(locale_name) == country
    assert configured_country("auto", locale_name=locale_name) == country


def test_explicit_country_override_is_validated_and_normalized():
    assert normalize_country("in") == "IN"
    with pytest.raises(ValueError, match="two-letter ISO"):
        normalize_country("India")


def test_country_and_international_occasions_can_coexist():
    matches = current_occasions(date(2026, 6, 21), country="US")
    assert [item.name for item in matches] == ["World Music Day", "Pride Month"]
    assert all(item.international for item in matches)


def test_domestic_occasion_is_scoped_to_selected_country():
    assert [item.name for item in current_occasions(date(2026, 8, 15), country="IN")] == [
        "Independence Day"
    ]
    assert current_occasions(date(2026, 8, 15), country="US") == ()


def test_greeting_reports_name_message_and_resolved_country():
    greeting, matches, country = occasion_greeting(
        date(2026, 1, 26), country_setting="auto", locale_name="en-IN"
    )
    assert country == "IN"
    assert matches[0].name == "Republic Day"
    assert greeting == "Republic Day: Wishing India a happy Republic Day"


def test_ordinary_day_has_no_synthetic_greeting():
    greeting, matches, country = occasion_greeting(
        date(2026, 2, 2), country_setting="JP", locale_name="en-US"
    )
    assert (greeting, matches, country) == (None, (), "JP")


def test_additive_migration_preserves_explicit_banner_preferences():
    merged, changed = deep_merge_defaults(
        {"show banner": True, "banner": {"country": "JP", "occasion greetings": False}},
        {"show banner": True, "banner": {"country": "auto", "occasion greetings": True}},
    )
    assert changed is False
    assert merged["banner"] == {"country": "JP", "occasion greetings": False}


@pytest.mark.parametrize(("day", "country", "name"), [
    (date(2026, 3, 4), "IN", "Holi"),
    (date(2026, 11, 8), "IN", "Diwali"),
    (date(2026, 2, 17), "CN", "Chinese New Year"),
    (date(2026, 4, 5), "US", "Easter"),
])
def test_movable_calendars(day, country, name):
    matches = current_occasions(day, country=country)
    assert any(item.name.startswith(name) for item in matches)
    assert occasion_palette(matches)


def test_subdivision_uses_its_own_calendar_and_validates_selection():
    assert validate_region("IN", "mh") == "MH"
    assert any(item.name == "Holi" for item in current_occasions(date(2026, 3, 3), country="IN", subdivision="MH"))
    assert not any(item.name == "Holi" for item in current_occasions(date(2026, 3, 3), country="IN"))
    with pytest.raises(ValueError, match="Unsupported subdivision"):
        validate_region("IN", "XX")
    with pytest.raises(ValueError, match="No holiday calendar"):
        validate_region("ZZ")


def test_calendar_failure_retains_fixed_greeting(monkeypatch):
    monkeypatch.setattr("mariana.occasions._calendar", lambda *_: (_ for _ in ()).throw(ImportError()))
    assert current_occasions(date(2026, 1, 26), country="IN")[0].name == "Republic Day"
    assert occasion_palette(()) is None


def test_explicit_country_lookup_is_bounded_and_keeps_only_country(monkeypatch):
    from mariana.occasions import detect_country

    class Response:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def iter_content(self, chunk_size):
            assert chunk_size == 16
            yield b"IN\n"

    def request(url, **kwargs):
        assert url == "https://ipapi.co/country/"
        assert kwargs == {"timeout": (3.05, 5), "allow_redirects": False, "stream": True}
        return Response()

    monkeypatch.setattr("requests.get", request)
    assert detect_country() == "IN"


def test_offline_calendar_never_requests_location(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: pytest.fail("unexpected network request"))
    greeting, _, _ = occasion_greeting(date(2026, 11, 8), country_setting="IN")
    assert "Diwali" in greeting


@pytest.mark.parametrize("payload", [[b"IN", b"x" * 16], [b"not a country"], [b"\xff"], []])
def test_country_lookup_rejects_oversized_malformed_or_empty_responses(monkeypatch, payload):
    from mariana.occasions import detect_country

    class Response:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def iter_content(self, chunk_size):
            return iter(payload)

    monkeypatch.setattr("requests.get", lambda *_args, **_kwargs: Response())
    with pytest.raises(ValueError):
        detect_country()


def test_international_movable_greeting_identifies_reference_calendar():
    greeting, _, _ = occasion_greeting(date(2026, 11, 8), country_setting="JP")
    assert "Diwali" in greeting
    assert "IN calendar; local dates may differ" in greeting
