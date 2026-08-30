"""Writing hourly price statistics for a tariff period."""
from __future__ import annotations

import datetime
from typing import Any

import pytest
from conftest import StatsStore

from custom_components.enea_prices import statistics as price_stats

ENTITY = "sensor.enea_ceny_g12w_peak_zone_energy_price_netto"


class _Recorder:
    """Answers recorder queries from a set of stored hour starts.

    late, when given, is a row committed between the two queries the code
    makes: the window read does not see it, the newest-entry read does.
    """

    def __init__(
        self,
        stored: list[datetime.datetime],
        late: datetime.datetime | None = None,
    ) -> None:
        self.stored = sorted(stored)
        self.late = late

    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        """Run the query inline."""
        return target(*args)

    def last(self, hass: Any, count: int, sid: str, convert: bool, types: set) -> dict:
        """Newest entry first, mirroring get_last_statistics."""
        newest = self.late or (self.stored[-1] if self.stored else None)
        if newest is None:
            return {}
        return {sid: [{"start": newest.timestamp()}]}

    def during(self, hass: Any, start: Any, end: Any, ids: set, *rest: Any) -> dict:
        """Ascending entries inside [start, end)."""
        sid = next(iter(ids))
        rows = [{"start": dt.timestamp()} for dt in self.stored if start <= dt < end]
        return {sid: rows} if rows else {}


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, stats_store: StatsStore):
    """Wire the module to an in-memory recorder and capture writes."""

    def _wire(
        stored: list[datetime.datetime],
        late: datetime.datetime | None = None,
    ) -> StatsStore:
        rec = _Recorder(stored, late)
        monkeypatch.setattr(price_stats, "get_instance", lambda hass: rec)
        monkeypatch.setattr(price_stats, "statistics_during_period", rec.during, raising=False)
        # Kept wired so the pre-fix code path runs too and the regression test
        # fails for the defect itself, not for a missing stub.
        monkeypatch.setattr(price_stats, "get_last_statistics", rec.last, raising=False)
        monkeypatch.setattr(
            price_stats, "async_import_statistics", stats_store.import_statistics
        )
        return stats_store

    return _wire


def _hours(day: datetime.date, count: int = 24) -> list[datetime.datetime]:
    """The first count hours of a day, in the zone the integration treats as local."""
    tz = price_stats.dt_util.DEFAULT_TIME_ZONE
    midnight = datetime.datetime.combine(day, datetime.time(0, 0), tzinfo=tz)
    return [midnight + datetime.timedelta(hours=h) for h in range(count)]


async def test_writes_every_hour_when_nothing_is_stored(wired) -> None:
    """A sensor with nothing stored yet gets every hour of the period."""
    store = wired([])

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.6518, datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)
    )

    assert len(store.starts) == 48


async def test_hours_after_the_newest_statistic_are_left_to_the_recorder(wired) -> None:
    """Everything after the newest stored hour belongs to the recorder.

    The price sensors have a state class, so the recorder compiles their
    hourly statistics itself from the states it saw, and after a restart it
    catches up on the hour the shutdown cut short.  Importing those hours here
    races the recorder's own blind insert into the same unique key, and losing
    that race rolls back the recorder's whole catch-up batch — for every
    entity in the install, not just this sensor.  Hours the sensor was dead
    for become interior gaps once the recorder writes again, and the next run
    fills them then.
    """
    store = wired(_hours(datetime.date(2026, 1, 1)))

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.6518, datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)
    )

    assert store.injected == []


async def test_the_hour_a_shutdown_cut_short_is_not_imported(wired) -> None:
    """The single missing hour right after the newest one stays untouched.

    That is the hour the recorder still compiles from its short-term data
    after a restart — the exact write this import must not race.
    """
    store = wired(_hours(datetime.date(2026, 1, 1), 23))

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.6518, datetime.date(2026, 1, 1), datetime.date(2026, 1, 1)
    )

    assert store.injected == []


async def test_an_hour_committed_between_the_two_reads_is_not_raced(wired) -> None:
    """A row the recorder commits between the two queries must not be written.

    The hours present in the window are read first, the newest statistic only
    second.  A row committed in between shows up solely in the second read —
    counting it as missing because the window read predates it would import
    over the recorder's freshest write, the very collision this boundary
    exists to prevent.
    """
    hours = _hours(datetime.date(2026, 1, 1))
    store = wired(hours[:-1], late=hours[-1])

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.6518, datetime.date(2026, 1, 1), datetime.date(2026, 1, 1)
    )

    assert store.injected == []


async def test_an_interior_gap_is_filled(wired) -> None:
    """A missing hour with stored hours after it can no longer be compiled.

    The recorder only moves forward from its newest statistic, so a hole
    behind it would stay a hole for ever — that is the gap this module is for.
    """
    hours = _hours(datetime.date(2026, 1, 1))
    missing = hours.pop(5)
    store = wired(hours)

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.6518, datetime.date(2026, 1, 1), datetime.date(2026, 1, 1)
    )

    assert store.starts == [missing]


async def test_fills_a_period_older_than_stored_data(wired) -> None:
    """An older tariff period added later must still be filled in.

    The injection used to look only at the newest stored entry and return early
    whenever it was newer than the period being written, so statistics could
    only ever grow forward.  Adding a historical period to TARIFFS then had no
    effect at all.
    """
    store = wired(_hours(datetime.date(2026, 1, 1)))

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.5000, datetime.date(2025, 1, 1), datetime.date(2025, 1, 2)
    )

    assert len(store.starts) == 48
    assert max(store.starts).date() == datetime.date(2025, 1, 2)


async def test_fully_covered_period_writes_nothing(wired) -> None:
    """Running again over a period that is already stored writes nothing."""
    stored = _hours(datetime.date(2026, 1, 1)) + _hours(datetime.date(2026, 1, 2))
    store = wired(stored)

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.6518, datetime.date(2026, 1, 1), datetime.date(2026, 1, 2)
    )

    assert store.injected == []


async def test_inverted_range_writes_nothing(wired) -> None:
    """A period that ends before it starts is ignored rather than looped over."""
    store = wired([])

    await price_stats._inject_sensor_statistics(
        object(), ENTITY, 0.6518, datetime.date(2026, 2, 1), datetime.date(2026, 1, 1)
    )

    assert store.injected == []
