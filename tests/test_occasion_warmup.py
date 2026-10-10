import threading

import pytest

from mariana import occasions


@pytest.fixture(autouse=True)
def isolated_warmup(monkeypatch):
    # Other CLI tests import main during collection, starting real preparation.
    # Finish that existing worker before replacing its dependencies in this unit.
    existing = occasions._warmup_thread
    if existing is not None:
        existing.join(10)
        assert not existing.is_alive()
    monkeypatch.setattr(occasions, "_warmup_thread", None)
    yield
    worker = occasions._warmup_thread
    if worker is not None:
        worker.join(10)
        assert not worker.is_alive()


def test_calendar_warmup_is_nonblocking_bounded_and_uses_a_settings_snapshot(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    observed = []

    def prepare(**settings):
        entered.set()
        assert release.wait(5)
        observed.append(settings)

    monkeypatch.setattr(occasions, "occasion_greeting", prepare)
    settings = {"banner": {"country": "IN", "subdivision": "MH"}}
    worker = occasions.prewarm_occasion_calendars(settings)
    assert worker is not None and worker.daemon
    try:
        assert entered.wait(5)
        assert occasions.prewarm_occasion_calendars(settings) is worker
        settings["banner"]["country"] = "US"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert observed == [{"country_setting": "IN", "subdivision": "MH"}]


def test_disabled_or_invisible_banner_does_not_prepare_calendars(monkeypatch):
    monkeypatch.setattr(occasions, "occasion_greeting", lambda **_: (_ for _ in ()).throw(AssertionError()))
    assert occasions.prewarm_occasion_calendars({"visible": False}) is None
    assert occasions.prewarm_occasion_calendars({"banner": {"occasion greetings": False}}) is None


def test_optional_calendar_error_is_nonfatal_and_does_not_print(monkeypatch, capsys):
    monkeypatch.setattr(occasions, "occasion_greeting", lambda **_: (_ for _ in ()).throw(ValueError("unavailable")))
    worker = occasions.prewarm_occasion_calendars({})
    assert worker is not None
    worker.join(5)
    assert not worker.is_alive()
    assert capsys.readouterr().out == ""
    assert capsys.readouterr().err == ""


def test_unavailable_worker_leaves_normal_banner_fallback_usable(monkeypatch):
    start = threading.Thread.start

    def unavailable(worker):
        if worker.name == "occasion-calendar":
            raise RuntimeError("thread unavailable")
        return start(worker)

    monkeypatch.setattr(threading.Thread, "start", unavailable)
    assert occasions.prewarm_occasion_calendars({}) is None
    assert occasions._warmup_thread is None


def test_banner_reuses_the_exact_existing_calendar_cache(monkeypatch):
    from datetime import date

    today = date(2026, 6, 21)
    normal_greeting = occasions.occasion_greeting
    observed = []

    def prepare(**settings):
        observed.append(normal_greeting(today, **settings))

    monkeypatch.setattr(occasions, "occasion_greeting", prepare)
    worker = occasions.prewarm_occasion_calendars({"banner": {"country": "US"}})
    assert worker is not None
    worker.join(5)
    assert not worker.is_alive()
    assert observed == [normal_greeting(today, country_setting="US")]


def test_simultaneous_banner_and_warmup_only_build_the_calendar_once(monkeypatch):
    import holidays

    entered = threading.Event()
    release = threading.Event()
    calls = []
    results = []

    def calendar(country, **settings):
        calls.append((country, settings))
        entered.set()
        assert release.wait(5)
        return {}

    occasions._cached_calendar.cache_clear()
    monkeypatch.setattr(holidays, "country_holidays", calendar)
    first = threading.Thread(target=lambda: results.append(occasions._calendar("US", None, 2099)))
    second = threading.Thread(target=lambda: results.append(occasions._calendar("US", None, 2099)))
    first.start()
    try:
        assert entered.wait(5)
        second.start()
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert len(calls) == 1
    assert results == [(), ()]
    occasions._cached_calendar.cache_clear()
