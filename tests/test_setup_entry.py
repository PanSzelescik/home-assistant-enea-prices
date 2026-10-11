"""A G12 entry set up in a running Home Assistant: its sensors, statistics and clock.

The clock is Home Assistant's (dt_util); the platform's time-of-day callbacks
are fired by the test at the hour they are scheduled for.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState

from ha_instance import (  # noqa: F401 - clock, database, triggers and hass are fixtures
    TODAY,
    at_local,
    clock,
    database,
    entity_id,
    hass,
    make_entry,
    state,
    triggers,
)


async def _set_up(hass, **data):
    """Add an entry and wait for its setup and statistics import."""
    entry = make_entry(**data)
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    return entry


async def test_sensors_report_the_prices_in_force(hass):
    """At 10:00 on a weekday in February 2026 G12 is in its day zone."""
    entry = await _set_up(hass)

    assert entry.state is ConfigEntryState.LOADED
    assert state(hass, "G12", "current_zone") == "day"
    assert state(hass, "G12", "current_price_total") == "0.8993"
    assert state(hass, "G12", "day_price_total") == "0.8993"
    assert state(hass, "G12", "night_price_total") == "0.4717"
    assert state(hass, "G12", "quality_fee") == "0.0332"
    assert state(hass, "G12", "valid_from") == "2026-02-01"
    assert state(hass, "G12", "valid_until") == "2026-12-31"


async def test_zone_changes_at_the_scheduled_hour(hass, clock, triggers):
    """At 13:00 G12 moves to its night zone, and the current-price sensors follow."""
    await _set_up(hass)

    clock.now = at_local(TODAY, 13)
    triggers.fire(13, clock.now)

    assert state(hass, "G12", "current_zone") == "night"
    assert state(hass, "G12", "current_price_total") == "0.4717"


async def test_midnight_switches_to_the_new_period_in_home_assistants_time_zone(hass, clock, triggers):
    """The quality fee changed on 1 February 2026; midnight in Poland is 23:00 UTC.

    Every sensor reads the period in force when its state is written, and the
    midnight callback writes them all.  Reading "today" off the process's
    clock picked 31 January for the whole of 1 February on an installation
    running in UTC, until the next midnight.
    """
    clock.now = at_local(date(2026, 1, 31), 22)
    await _set_up(hass)
    assert state(hass, "G12", "quality_fee") == "0.0331"

    clock.now = at_local(date(2026, 2, 1), 0, 0)
    triggers.fire(0, clock.now)

    assert state(hass, "G12", "quality_fee") == "0.0332"
    assert state(hass, "G12", "valid_from") == "2026-02-01"


async def test_history_of_every_period_is_imported_up_to_yesterday(hass, database):
    """Each zone's price statistics start with the table and end yesterday at 23:00."""
    await _set_up(hass)
    day_total = entity_id(hass, "G12", "day_price_total")

    rows = database.series(day_total)

    assert rows[0]["start"] == at_local(date(2024, 7, 1)).timestamp()
    assert rows[-1]["start"] == at_local(TODAY - timedelta(days=1), 23).timestamp()
    # Timestamps, not datetimes: subtracting two in one zone ignores the clock changes.
    hours = (at_local(TODAY).timestamp() - at_local(date(2024, 7, 1)).timestamp()) / 3600
    assert len(rows) == hours
    assert database.mean_at(day_total, at_local(date(2024, 12, 31), 12)) == pytest.approx(0.8193, abs=1e-4)
    assert database.mean_at(day_total, at_local(date(2026, 3, 1), 12)) == pytest.approx(0.8993, abs=1e-4)
