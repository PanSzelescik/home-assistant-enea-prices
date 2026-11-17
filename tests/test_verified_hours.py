"""A later statistics run only looks at the hours since the last one.

The first run after a start reads and walks every hour of the sensor's
history.  The run after the recorder's first compiled hour, and every reload
of the entry, used to do all of it again; with the hours already checked
remembered in memory they read a day or two.
"""
from __future__ import annotations

import datetime
from typing import Any

import pytest

from custom_components.enea_prices import statistics as price_stats

ENTITY = "sensor.enea_ceny_g12w_peak_zone_energy_price_netto"
PRICE = 0.6518
FIRST = datetime.date(2026, 1, 1)


def _hours(first: datetime.date, days: int = 1) -> list[datetime.datetime]:
    """Every hour of the given days, in the zone the integration treats as local."""
    tz = price_stats.dt_util.DEFAULT_TIME_ZONE
    midnight = datetime.datetime.combine(first, datetime.time(0, 0), tzinfo=tz)
    return [midnight + datetime.timedelta(hours=h) for h in range(24 * days)]


def _midnight(day: datetime.date) -> datetime.datetime:
    """Local midnight of a day, as a UTC time."""
    return price_stats.dt_util.start_of_local_day(day).astimezone(datetime.UTC)


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch):
    """Record the windows read from the recorder and what ran in its executor."""
    seen: dict[str, list[Any]] = {"windows": [], "jobs": []}

    def watch() -> dict[str, list[Any]]:
        """Wrap whatever the wired fixture installed; call after wired()."""
        during = price_stats.statistics_during_period
        recorder = price_stats.get_instance(None)
        run = recorder.async_add_executor_job

        def counted(hass: Any, start: Any, end: Any, *rest: Any) -> Any:
            seen["windows"].append((start, end))
            return during(hass, start, end, *rest)

        async def tracked(target: Any, *args: Any) -> Any:
            seen["jobs"].append(getattr(target, "__name__", getattr(target, "func", target)))
            return await run(target, *args)

        monkeypatch.setattr(price_stats, "statistics_during_period", counted)
        monkeypatch.setattr(recorder, "async_add_executor_job", tracked)
        return seen

    return watch


async def _run(verified: Any, last: datetime.date, price: float = PRICE) -> None:
    """Run the injection for one span from FIRST to last."""
    await price_stats._inject_sensor_statistics(object(), ENTITY, [(price, FIRST, last)], verified)


async def test_first_run_reads_the_whole_window_and_remembers_how_far_it_got(wired, reads):
    """With nothing remembered every hour is read, and the end of the window is kept."""
    store = wired([])
    seen = reads()
    verified: dict[str, Any] = {}

    await _run(verified, datetime.date(2026, 1, 3))

    assert len(store.starts) == 72
    assert seen["windows"] == [(_midnight(FIRST), _midnight(datetime.date(2026, 1, 4)))]
    signature, reached = verified[ENTITY]
    assert signature == ((PRICE, FIRST),)
    assert reached == _midnight(datetime.date(2026, 1, 4))


async def test_same_window_again_asks_the_recorder_nothing(wired, reads):
    """A second run over a window settled to its end returns before any query."""
    store = wired([])
    seen = reads()
    verified: dict[str, Any] = {}
    await _run(verified, datetime.date(2026, 1, 3))
    seen["windows"].clear()
    seen["jobs"].clear()
    store.injected.clear()

    await _run(verified, datetime.date(2026, 1, 3))

    assert seen["windows"] == []
    assert seen["jobs"] == []
    assert store.injected == []


async def test_next_day_reads_and_writes_that_day_alone(wired, reads):
    """A day later the window is a day longer: only the new day is looked at."""
    store = wired([])
    seen = reads()
    verified: dict[str, Any] = {}
    await _run(verified, datetime.date(2026, 1, 3))
    seen["windows"].clear()
    store.injected.clear()

    await _run(verified, datetime.date(2026, 1, 4))

    assert seen["windows"] == [
        (_midnight(datetime.date(2026, 1, 4)), _midnight(datetime.date(2026, 1, 5)))
    ]
    assert store.starts == [h.astimezone(datetime.UTC) for h in _hours(datetime.date(2026, 1, 4))]
    assert verified[ENTITY][1] == _midnight(datetime.date(2026, 1, 5))


async def test_gap_behind_the_recorder_is_filled_by_the_run_that_follows(wired, reads):
    """The marker stops at the recorder's newest hour, so the downtime after it is checked.

    First run: the recorder's newest hour is the last one before a shutdown.
    Second run: the recorder has compiled an hour after the downtime, and the
    hours in between are now interior gaps.
    """
    before = _hours(FIRST)  # 1 January, the last hours before the shutdown
    store = wired(before)
    seen = reads()
    verified: dict[str, Any] = {}
    await _run(verified, datetime.date(2026, 1, 3))
    assert store.injected == []
    assert verified[ENTITY][1] == before[-1].astimezone(datetime.UTC)

    after = _hours(datetime.date(2026, 1, 3))  # the recorder is back on 3 January
    wired([*before, *after])
    seen = reads()
    seen["windows"].clear()
    await _run(verified, datetime.date(2026, 1, 3))

    assert seen["windows"] == [(before[-1].astimezone(datetime.UTC), _midnight(datetime.date(2026, 1, 4)))]
    assert store.starts == [h.astimezone(datetime.UTC) for h in _hours(datetime.date(2026, 1, 2))]


async def test_marker_never_passes_the_recorders_newest_hour(wired):
    """Hours left to the recorder are not counted as settled."""
    stored = _hours(FIRST, days=2)[:30]
    wired(stored)
    verified: dict[str, Any] = {}

    await _run(verified, datetime.date(2026, 1, 5))

    assert verified[ENTITY][1] == stored[-1].astimezone(datetime.UTC)


async def test_changed_price_checks_everything_again(wired, reads):
    """Prices entered with a past start date: the remembered hours no longer count."""
    store = wired([])
    seen = reads()
    verified: dict[str, Any] = {}
    await _run(verified, datetime.date(2026, 1, 3))
    stored = _hours(FIRST, days=3)
    late = stored[-1] + datetime.timedelta(days=2)
    wired(stored, late=late)
    seen = reads()
    seen["windows"].clear()
    store.injected.clear()

    await _run(verified, datetime.date(2026, 1, 3), price=0.7)

    assert seen["windows"] == [(_midnight(FIRST), _midnight(datetime.date(2026, 1, 4)))]
    assert len(store.starts) == 72
    assert verified[ENTITY][0] == ((0.7, FIRST),)


async def test_price_differing_past_four_decimals_is_the_same_price(wired, reads):
    """The sensors report four decimals; a difference beyond them changes nothing."""
    wired([])
    seen = reads()
    verified: dict[str, Any] = {}
    await _run(verified, datetime.date(2026, 1, 3), price=0.65181)
    seen["windows"].clear()

    await _run(verified, datetime.date(2026, 1, 3), price=0.65184)

    assert seen["windows"] == []


async def test_earlier_period_added_checks_everything_again(wired, reads):
    """A table that now starts earlier has hours before everything remembered."""
    store = wired([])
    seen = reads()
    verified: dict[str, Any] = {}
    await _run(verified, datetime.date(2026, 1, 3))
    seen["windows"].clear()
    store.injected.clear()
    earlier = datetime.date(2025, 12, 30)

    await price_stats._inject_sensor_statistics(
        object(), ENTITY,
        [(0.6, earlier, datetime.date(2025, 12, 31)), (PRICE, FIRST, datetime.date(2026, 1, 3))],
        verified,
    )

    assert seen["windows"] == [(_midnight(earlier), _midnight(datetime.date(2026, 1, 4)))]
    assert len(store.starts) == 5 * 24
    assert verified[ENTITY][0] == ((0.6, earlier), (PRICE, FIRST))


async def test_sensors_are_remembered_apart(wired, reads):
    """What one sensor has settled says nothing about another."""
    wired([])
    seen = reads()
    verified: dict[str, Any] = {}
    await _run(verified, datetime.date(2026, 1, 3))
    seen["windows"].clear()

    await price_stats._inject_sensor_statistics(
        object(), "sensor.other", [(PRICE, FIRST, datetime.date(2026, 1, 3))], verified
    )

    assert seen["windows"] == [(_midnight(FIRST), _midnight(datetime.date(2026, 1, 4)))]
    assert set(verified) == {ENTITY, "sensor.other"}


async def test_without_a_memory_every_run_reads_everything(wired, reads):
    """Called without verified — as before — nothing is skipped and nothing kept."""
    wired([])
    seen = reads()

    await _run(None, datetime.date(2026, 1, 3))
    await _run(None, datetime.date(2026, 1, 3))

    assert seen["windows"] == [(_midnight(FIRST), _midnight(datetime.date(2026, 1, 4)))] * 2


async def test_hours_are_walked_in_the_recorders_executor(wired, reads):
    """Years of hours are compared off the event loop."""
    wired([])
    seen = reads()

    await _run({}, datetime.date(2026, 1, 3))

    assert "_hours_to_write" in seen["jobs"]


def test_walk_skips_what_was_settled_and_stops_at_the_recorder():
    """_hours_to_write starts at check_from and ends before the recorder's newest hour."""
    start, end = _midnight(FIRST), _midnight(datetime.date(2026, 1, 3))
    check_from = start + datetime.timedelta(hours=10)
    owns_after = (start + datetime.timedelta(hours=30)).timestamp()

    rows = price_stats._hours_to_write([(PRICE, start, end)], {}, owns_after, check_from)

    assert [row["start"] for row in rows] == [
        start + datetime.timedelta(hours=h) for h in range(10, 30)
    ]
    assert {row["mean"] for row in rows} == {PRICE}


def test_walk_writes_missing_and_mispriced_hours_only():
    """An hour stored at the expected price, to four decimals, is left alone."""
    start, end = _midnight(FIRST), _midnight(FIRST) + datetime.timedelta(hours=4)
    stored = {
        int(start.timestamp()): PRICE,
        int((start + datetime.timedelta(hours=1)).timestamp()): PRICE + 0.00004,
        int((start + datetime.timedelta(hours=2)).timestamp()): 0.5,
    }

    rows = price_stats._hours_to_write([(PRICE, start, end)], stored, None, None)

    assert [row["start"] for row in rows] == [
        start + datetime.timedelta(hours=2), start + datetime.timedelta(hours=3),
    ]


def test_walk_applies_check_from_to_later_spans_only_where_it_falls():
    """A span that starts after check_from is walked from its own start."""
    first = (0.5, _midnight(FIRST), _midnight(datetime.date(2026, 1, 2)))
    second = (0.6, _midnight(datetime.date(2026, 1, 2)), _midnight(datetime.date(2026, 1, 3)))
    check_from = _midnight(FIRST) + datetime.timedelta(hours=20)

    rows = price_stats._hours_to_write([first, second], {}, None, check_from)

    assert [row["mean"] for row in rows] == [0.5] * 4 + [0.6] * 24
