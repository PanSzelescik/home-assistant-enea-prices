"""A running Home Assistant with the integration set up, for end-to-end tests.

conftest.py keeps most tests free of Home Assistant: they call the tariff
tables and the platform against fakes.  Setting an entry up through its config
flow, with real entities, translations and registries, needs the real thing.
This builds it the way Home Assistant's bootstrap does, minus the recorder:
the long-term statistics the integration imports live in StatisticsDatabase,
and the clock is Clock, which tests move.  Time-based callbacks are kept by
TimeTriggers and fired by the test, at the hour it says.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Any

import pytest
from homeassistant import bootstrap, config_entries, loader
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from conftest import TEST_TIME_ZONE

TODAY = date(2026, 3, 18)
"""The day the tests run on, unless they move the clock: a Wednesday in a 2026 period."""


def at_local(day: date, hour: int = 0, minute: int = 0) -> datetime:
    """Return a local time as an aware datetime."""
    return datetime.combine(day, time(hour, minute), dt_util.get_default_time_zone())


class Clock:
    """The time Home Assistant's dt_util reports; tests move it."""

    def __init__(self) -> None:
        self.now = at_local(TODAY, 10)

    def __call__(self, time_zone: Any = None) -> datetime:
        """Stand in for dt_util.now."""
        return self.now.astimezone(time_zone or dt_util.get_default_time_zone())

    def utcnow(self) -> datetime:
        """Stand in for dt_util.utcnow."""
        return self.now.astimezone(dt_util.UTC)


class StatisticsDatabase:
    """Long-term statistics kept in memory, one series per statistic id.

    Answers the recorder calls the integration makes — get_last_statistics
    and statistics_during_period (hourly) — and stores what
    async_import_statistics writes, replacing rows by start time as the
    recorder does.  It also stands in for the recorder instance, running
    executor jobs straight away.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[float, dict[str, Any]]] = defaultdict(dict)
        self.imports: list[tuple[str, int]] = []
        """(statistic id, rows written) for every import call."""

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Point the integration's statistics module at this database."""
        from custom_components.enea_prices import statistics  # noqa: PLC0415

        monkeypatch.setattr(statistics, "get_instance", lambda hass: self)
        monkeypatch.setattr(statistics, "get_last_statistics", self.last)
        monkeypatch.setattr(statistics, "statistics_during_period", self.during)
        monkeypatch.setattr(statistics, "async_import_statistics", self.import_statistics)

    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        """Run a recorder query at once instead of in the recorder's thread."""
        return target(*args)

    def import_statistics(self, hass: Any, metadata: dict[str, Any], rows: list[Any]) -> None:
        """Store rows the way async_import_statistics does."""
        statistic_id = metadata["statistic_id"]
        self.imports.append((statistic_id, len(rows)))
        for row in rows:
            self.rows[statistic_id][row["start"].timestamp()] = {
                key: value for key, value in row.items() if key != "start"
            }

    def series(self, statistic_id: str) -> list[dict[str, Any]]:
        """Return a statistic's rows oldest first, each with its start timestamp."""
        return [
            {"start": start, **row}
            for start, row in sorted(self.rows.get(statistic_id, {}).items())
        ]

    def mean_at(self, statistic_id: str, moment: datetime) -> float | None:
        """Return the mean stored for the hour starting at moment."""
        return self.rows.get(statistic_id, {}).get(moment.timestamp(), {}).get("mean")

    def last(
        self, hass: Any, number: int, statistic_id: str, convert: bool, types: set[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Stand in for get_last_statistics: the newest rows, newest first."""
        rows = self.series(statistic_id)[-number:][::-1]
        return {statistic_id: rows} if rows else {}

    def during(
        self,
        hass: Any,
        start: datetime,
        end: datetime | None = None,
        statistic_ids: set[str] | None = None,
        period: str = "hour",
        units: Any = None,
        types: set[str] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Stand in for statistics_during_period, hourly."""
        assert period == "hour", period
        found = {}
        for statistic_id in statistic_ids or []:
            rows = [
                row for row in self.series(statistic_id)
                if row["start"] >= start.timestamp() and (end is None or row["start"] < end.timestamp())
            ]
            if rows:
                found[statistic_id] = rows
        return found


class TimeTriggers:
    """Keeps the callbacks the platform schedules by time of day, for tests to fire."""

    def __init__(self) -> None:
        self.callbacks: list[tuple[int, Callable[[Any], None]]] = []

    def track(self, hass: Any, action: Callable[[Any], None], **when: int) -> Callable[[], None]:
        """Stand in for async_track_time_change: record the action and its hour."""
        entry = (when["hour"], action)
        self.callbacks.append(entry)
        return lambda: self.callbacks.remove(entry)

    def fire(self, hour: int, now: datetime) -> None:
        """Run every action scheduled for the hour, as Home Assistant would at now."""
        for scheduled, action in list(self.callbacks):
            if scheduled == hour:
                action(now)


async def async_start_hass(config_dir: str) -> HomeAssistant:
    """Return a running Home Assistant with its registries and config entries loaded.

    The recorder is marked as set up rather than started — the integration's
    statistics go to StatisticsDatabase.
    """
    hass = HomeAssistant(config_dir)
    await hass.config.async_set_time_zone(TEST_TIME_ZONE)
    hass.config.skip_pip = True
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    assert await bootstrap.async_load_base_functionality(hass)
    hass.config.components.add("recorder")
    await hass.async_start()
    assert hass.state is CoreState.running
    return hass


def make_entry(
    tariff: str = "G12",
    phases: int = 3,
    annual_kwh: int = 2000,
    billing_months: int = 2,
    price_changes: list[dict[str, Any]] | None = None,
) -> config_entries.ConfigEntry:
    """Return a config entry pricing one tariff group."""
    data: dict[str, Any] = {
        "tariff": tariff,
        "phases": phases,
        "annual_kwh": annual_kwh,
        "billing_months": billing_months,
    }
    if price_changes is not None:
        data["price_changes"] = price_changes
    return config_entries.ConfigEntry(
        data=data,
        discovery_keys=MappingProxyType({}),
        domain="enea_prices",
        minor_version=1,
        options={},
        source="user",
        subentries_data=None,
        title=f"Enea Ceny {tariff}",
        unique_id=tariff,
        version=1,
    )


def entity_id(hass: HomeAssistant, tariff: str, key: str) -> str:
    """Return the entity id of a tariff group's sensor with the given key."""
    found = er.async_get(hass).async_get_entity_id("sensor", "enea_prices", f"enea_prices-{tariff}-{key}")
    assert found is not None, key
    return found


def state(hass: HomeAssistant, tariff: str, key: str) -> str:
    """Return the state of a tariff group's sensor with the given key."""
    current = hass.states.get(entity_id(hass, tariff, key))
    assert current is not None, key
    return current.state


# --- fixtures, imported by the test modules that use them ---------------------


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """Fix the clock on TODAY at 10:00, as a container running in UTC sees it.

    Home Assistant keeps its own time zone (Europe/Warsaw) in dt_util and never
    sets the process's; a Container or Core installation without TZ runs the
    process in UTC.  So the standard library's date.today() is the UTC date of
    the same moment — a day behind in the first hours after Polish midnight.
    """
    current = Clock()
    monkeypatch.setattr(dt_util, "now", current)

    from custom_components.enea_prices import tariffs  # noqa: PLC0415

    class _SystemDate(date):
        """date with today() read off the clock in UTC, as the process sees it."""

        @classmethod
        def today(cls) -> date:
            return current.utcnow().date()

    monkeypatch.setattr(tariffs, "date", _SystemDate)
    return current


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch) -> StatisticsDatabase:
    """Keep the long-term statistics in memory."""
    store = StatisticsDatabase()
    store.install(monkeypatch)
    return store


@pytest.fixture
def triggers(monkeypatch: pytest.MonkeyPatch) -> TimeTriggers:
    """Keep the platform's time-of-day callbacks for the test to fire."""
    from custom_components.enea_prices import sensor  # noqa: PLC0415

    kept = TimeTriggers()
    monkeypatch.setattr(sensor, "async_track_time_change", kept.track)
    return kept


@pytest.fixture
async def hass(tmp_path, clock, database, triggers):
    """A running Home Assistant; stopped, with its tasks, after the test."""
    instance = await async_start_hass(str(tmp_path))
    yield instance
    await instance.async_stop(force=True)
