"""The one price a customer actually pays per kWh: net total plus excise, then VAT.

Every rate this integration publishes is net.  Anything that turns kWh into
money — the cost statistics of the enea integration, a charge logger fed from
a Home Assistant price sensor — has to add excise and VAT itself, and two
copies of that arithmetic drift apart silently.  The gross total therefore
lives on the pricing model next to the net one, the sensor only rounds it,
and the tax rates keep the import path the code that already uses them knows.
"""
from __future__ import annotations

import datetime

import pytest
from homeassistant.util import dt as dt_util

from custom_components.enea_prices import const, tariffs
from custom_components.enea_prices import sensor as prices_sensor
from custom_components.enea_prices.tariffs import TARIFFS, Zone

IN_2026 = datetime.date(2026, 6, 1)

# Gross totals of the 2026 G12w period.  The off-peak figure is the per-kWh
# rate an Enea invoice for that period shows, to the fourth decimal place.
G12W_2026_GROSS = {Zone.PEAK: 1.1937, Zone.OFF_PEAK: 0.5858}

WEDNESDAY = datetime.date(2026, 6, 3)
SATURDAY = datetime.date(2026, 6, 6)
BEYOND_THE_TABLE = datetime.date(2027, 1, 1)


@pytest.mark.parametrize("zone", sorted(G12W_2026_GROSS), ids=str)
def test_gross_total_is_the_net_total_plus_excise_then_vat(zone: Zone) -> None:
    """Excise is a per-kWh amount added before VAT, not a rate applied after it.

    The other order is off by 0.005 × 0.23 = 0.00115 zł/kWh: invisible on a
    display rounded to two decimals, wrong on every invoice line.
    """
    pricing = TARIFFS["G12w"].get_period_for_date(IN_2026).zones[zone]

    assert pricing.total_brutto == pytest.approx(
        (pricing.total + tariffs.AKCYZA) * (1 + tariffs.VAT_RATE)
    )
    assert round(pricing.total_brutto, 4) == G12W_2026_GROSS[zone]


@pytest.mark.parametrize("name", sorted(TARIFFS))
def test_gross_total_reproduces_the_cost_formula_of_the_enea_integration(name: str) -> None:
    """costs.py computes (energy + AKCYZA + total_distribution) * (1 + VAT_RATE) inline.

    The property has to give the same bits — additions in the same order — or
    the price sensor and the cost statistic for one hour can round to
    different fourth decimals.  Every period of every group, not just today's.
    """
    for period in TARIFFS[name].periods:
        for pricing in period.zones.values():
            inline = (pricing.energy + tariffs.AKCYZA + pricing.total_distribution) * (
                1 + tariffs.VAT_RATE
            )

            assert pricing.total_brutto == inline


def test_the_tax_rates_are_still_importable_from_const() -> None:
    """The enea integration reads AKCYZA as getattr(const, "AKCYZA", 0.0).

    Keeping the constants next to the tariff data must not move them out of
    that module's reach: a missing name would not fail, it would price every
    cost statistic without excise.
    """
    assert const.AKCYZA == tariffs.AKCYZA == 0.005
    assert const.VAT_RATE == tariffs.VAT_RATE == 0.23


def _pin_the_clock(monkeypatch: pytest.MonkeyPatch, day: datetime.date) -> None:
    """Make the dynamic sensors read their zone at local noon on the given day."""
    noon = datetime.datetime.combine(day, datetime.time(12), tzinfo=dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(prices_sensor.dt_util, "now", lambda: noon)


@pytest.mark.parametrize(
    ("day", "expected"),
    [(WEDNESDAY, G12W_2026_GROSS[Zone.PEAK]), (SATURDAY, G12W_2026_GROSS[Zone.OFF_PEAK])],
    ids=["workday-peak", "saturday-off-peak"],
)
async def test_the_sensor_follows_the_zone_in_force(
    day: datetime.date, expected: float, platform, monkeypatch
) -> None:
    """One dynamic sensor: the gross total of whichever zone the clock is in.

    It shares the unit of its net sibling, which is what a charge logger
    filters price entities by, and it changes with the zone, which is what a
    typed-in time band cannot do for a public holiday.
    """
    _pin_the_clock(monkeypatch, day)
    setup = await platform()
    gross = setup.sensor("current_price_total_brutto")

    assert gross.native_unit_of_measurement == const.UNIT_PRICE
    assert gross.native_value == expected
    assert gross.native_value > setup.sensor("current_price_total").native_value


async def test_the_sensor_reports_nothing_outside_the_table(platform, monkeypatch) -> None:
    """Past the last period the gross price is unknown, like every other rate.

    A consumer with a fallback price of its own must see no value here, not a
    stale one, or the fallback never kicks in.
    """
    _pin_the_clock(monkeypatch, BEYOND_THE_TABLE)
    setup = await platform()

    assert setup.sensor("current_price_total_brutto").native_value is None


class _Clock:
    """Stands in for datetime.date inside tariffs, pinned to a day in the table."""

    def today(self) -> datetime.date:
        """Return a day every bundled table prices."""
        return IN_2026


@pytest.mark.parametrize("name", sorted(TARIFFS))
async def test_every_zone_has_a_static_gross_total_too(name: str, platform, monkeypatch) -> None:
    """The per-zone reference rates mirror the net ones, gross included.

    A dashboard showing what peak and off-peak cost, or a fallback price
    typed into a charge logger, wants the rate of a named zone, not of
    whichever zone the clock is in.
    """
    monkeypatch.setattr(tariffs, "date", _Clock())
    setup = await platform(name)
    period = TARIFFS[name].get_period_for_date(IN_2026)

    for zone, pricing in period.zones.items():
        gross = setup.sensor(f"{zone}_price_total_brutto")

        assert gross.native_unit_of_measurement == const.UNIT_PRICE
        assert gross.native_value == round(pricing.total_brutto, 4)
        assert gross.native_value > setup.sensor(f"{zone}_price_total").native_value

