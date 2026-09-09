"""Crossing into another tariff period, with the installation never restarted.

The bundled tables hold more than one period — the quality fee changed on
1 February 2026 — and they stop at a fixed date.  Every sensor therefore has to
read the period the day belongs to at the moment its state is written, and the
platform has to write those states once a day for that reading to reach Home
Assistant at all.
"""
from __future__ import annotations

import datetime
from typing import Any

import pytest

from custom_components.enea_prices import sensor as prices_sensor
from custom_components.enea_prices import tariffs

JANUARY = datetime.date(2026, 1, 15)
FEBRUARY = datetime.date(2026, 2, 15)
BEYOND_THE_TABLE = datetime.date(2027, 1, 1)

QUALITY_IN_JANUARY = 0.0331
QUALITY_FROM_FEBRUARY = 0.0332
"""The one rate the two 2026 periods disagree on."""


class _Clock:
    """Stands in for datetime.date inside tariffs, with a settable today().

    Only get_current_period() reads the clock; the tables themselves were
    built at import time, so replacing the name afterwards is enough.
    """

    def __init__(self) -> None:
        self.today_is = JANUARY

    def today(self) -> datetime.date:
        """Return the date the test has moved to."""
        return self.today_is


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    """Put the tariff lookup on a clock the test controls."""
    fake = _Clock()
    monkeypatch.setattr(tariffs, "date", fake)
    return fake


async def test_a_rate_follows_the_period_the_day_belongs_to(clock, platform) -> None:
    """A rate set up in January must report February's value in February.

    The value used to be captured in the constructor, so it stayed at the
    January rate for as long as the config entry lived.
    """
    quality = (await platform()).sensor("quality_fee")
    assert quality.native_value == QUALITY_IN_JANUARY

    clock.today_is = FEBRUARY

    assert quality.native_value == QUALITY_FROM_FEBRUARY


async def test_rates_report_nothing_once_the_table_runs_out(clock, platform) -> None:
    """Past the last period a rate has to be unknown, not last year's number.

    Nobody can update an installation on the owner's behalf, so this is the
    state a table that ends on 31 December leaves behind.
    """
    setup = await platform()
    quality = setup.sensor("quality_fee")
    total = setup.sensor("peak_price_total")

    clock.today_is = BEYOND_THE_TABLE

    assert quality.native_value is None
    assert total.native_value is None


def _writes(setup: Any, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Capture the state writes of every entity the platform created."""
    written: list[Any] = []
    for entity in setup.entities:
        monkeypatch.setattr(
            entity, "async_write_ha_state", lambda e=entity: written.append(e)
        )
    return written


async def test_midnight_writes_every_sensor(
    clock, platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A period starting today only reaches Home Assistant if states are written.

    Reading the current period per state write is half the fix; the daily write
    is the other half.  Midnight used to refresh the dynamic sensors alone.
    """
    setup = await platform()
    written = _writes(setup, monkeypatch)

    for action in setup.at_hour[0]:
        action(None)

    assert set(written) == set(setup.entities)


async def test_a_zone_boundary_writes_only_the_dynamic_sensors(
    clock, platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rates do not change at 06:00, so only the zone-dependent sensors do."""
    setup = await platform()
    written = _writes(setup, monkeypatch)

    for action in setup.at_hour[6]:  # G12w peak hours start at 06:00
        action(None)

    assert written, "the zone boundary must refresh something"
    assert {type(entity) for entity in written} == {
        prices_sensor.EneaPricesDynamicSensor
    }
