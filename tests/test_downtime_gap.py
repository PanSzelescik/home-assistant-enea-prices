"""The gap a downtime leaves must not be skipped for the rest of the session.

The injection writes nothing past the newest stored statistic, because those
hours are the recorder's to compile and racing it rolls back its whole
catch-up batch.  Right after a start that boundary still sits before the
downtime, so the whole gap lies on the far side of it and is skipped.  The
first two tests pin that mechanism down; the rest cover the second chance the
platform now takes once the recorder has moved the boundary.
"""
from __future__ import annotations

import datetime
from typing import Any

import pytest
from conftest import FakeConfigEntry, FakeHass
from homeassistant.const import EVENT_RECORDER_HOURLY_STATISTICS_GENERATED

from custom_components import enea_prices
from custom_components.enea_prices import sensor as prices_sensor
from custom_components.enea_prices import statistics as price_stats
from custom_components.enea_prices.const import CONF_TARIFF
from custom_components.enea_prices.tariffs import TARIFFS

ENTITY = "sensor.enea_ceny_g12w_peak_zone_energy_price_netto"
UTC = datetime.timezone.utc

# The recorder compiled hours from 1 Jan up to 15 Jan 09:00Z, then HA went down.
BEFORE_DOWNTIME = [
    datetime.datetime(2026, 1, 1, 0, tzinfo=UTC) + datetime.timedelta(hours=i)
    for i in range(24 * 14 + 10)
]
# The first hour the recorder compiles after HA starts again on 5 Mar.
AFTER_RESTART = datetime.datetime(2026, 3, 5, 11, tzinfo=UTC)

# The February period, injected up to yesterday (4 Mar).
PERIOD = (datetime.date(2026, 2, 1), datetime.date(2026, 3, 4))
HOURS_IN_PERIOD = 28 * 24 + 4 * 24
"""All of February plus 1–4 March; no clocks change in between."""


async def test_the_gap_is_skipped_at_setup(wired) -> None:
    """At setup the boundary still sits before the downtime: nothing is written."""
    store = wired(BEFORE_DOWNTIME)

    await price_stats._inject_sensor_statistics(object(), ENTITY, 0.6518, *PERIOD)

    assert store.injected == []


async def test_the_gap_is_filled_once_the_recorder_has_moved(wired) -> None:
    """One hour compiled after startup moves the boundary and unblocks the gap."""
    store = wired([*BEFORE_DOWNTIME, AFTER_RESTART])

    await price_stats._inject_sensor_statistics(object(), ENTITY, 0.6518, *PERIOD)

    assert len(store.starts) == HOURS_IN_PERIOD


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch):
    """Set the sensor platform up against fakes, recording every injection."""
    injections: list[Any] = []

    async def _record(hass: Any, group: Any) -> None:
        """Stand in for the injection, which has its own tests above."""
        injections.append(group)

    monkeypatch.setattr(prices_sensor, "async_inject_price_statistics", _record)
    monkeypatch.setattr(
        prices_sensor, "async_track_time_change", lambda *args, **kwargs: lambda: None
    )

    async def _setup() -> tuple[FakeHass, FakeConfigEntry, list[Any]]:
        entry = FakeConfigEntry(domain="enea_prices", data={CONF_TARIFF: "G12w"})
        entry.runtime_data = enea_prices.EneaPricesRuntimeData(
            tariff=TARIFFS["G12w"], phases=1, annual_kwh=2000, billing_months=6
        )
        hass = FakeHass([entry])
        await prices_sensor.async_setup_entry(hass, entry, lambda entities: None)
        await hass.async_settle()
        return hass, entry, injections

    return _setup


async def test_the_injection_runs_again_once_the_recorder_moves(platform) -> None:
    """The compiled hour that unblocks the gap must trigger a second injection.

    Setup is the only place the injection used to run, so the gap stayed until
    the entry was set up again — a restart or a manual reload.
    """
    hass, _entry, injections = await platform()
    assert len(injections) == 1  # the one at setup

    hass.bus.async_fire(EVENT_RECORDER_HOURLY_STATISTICS_GENERATED)
    await hass.async_settle()

    assert len(injections) == 2


async def test_unloading_before_the_hour_drops_the_listener(platform) -> None:
    """An entry unloaded within the hour must not inject afterwards."""
    hass, entry, injections = await platform()

    assert await enea_prices.async_unload_entry(hass, entry)
    hass.bus.async_fire(EVENT_RECORDER_HOURLY_STATISTICS_GENERATED)
    await hass.async_settle()

    assert len(injections) == 1


async def test_unloading_after_the_hour_leaves_the_fired_listener_alone(
    platform,
) -> None:
    """Unloading later must not remove a listener that has already fired.

    A one-shot listener unsubscribes itself when it fires, and Home Assistant
    logs an exception for a removal it cannot match — which every entry
    unloaded more than an hour after its setup would then produce.
    """
    hass, entry, _injections = await platform()
    hass.bus.async_fire(EVENT_RECORDER_HOURLY_STATISTICS_GENERATED)
    await hass.async_settle()

    assert await enea_prices.async_unload_entry(hass, entry)
