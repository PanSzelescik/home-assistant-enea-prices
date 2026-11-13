"""C11: one energy price all day, a capacity fee per kWh in selected hours, a fee per kW.

The two zones of C11 do not price energy differently – they only tell the hours
the capacity fee is charged in (7:00–22:00 on working days) from the rest, so
that every hour gets the price actually paid in it, as in the G groups.
"""
from __future__ import annotations

import datetime
from typing import Any

import pytest
from homeassistant.util import dt as dt_util

from custom_components.enea_prices import build_tariff
from custom_components.enea_prices.config_flow import EneaPricesConfigFlow
from custom_components.enea_prices.const import (
    CONF_BILLING_MONTHS,
    CONF_CONTRACT_POWER,
    CONF_PRICE_CHANGES,
    CONF_TARIFF,
    DOMAIN,
)
from custom_components.enea_prices.tariffs import TARIFFS, Zone

from conftest import FakeConfigEntry

C11 = TARIFFS["C11"]
PERIOD = C11.periods[0]

WEDNESDAY = datetime.date(2026, 11, 4)
SATURDAY = datetime.date(2026, 11, 7)
INDEPENDENCE_DAY = datetime.date(2026, 11, 11)
"""A Wednesday, and a public holiday: no capacity fee hours on it."""

OFFER = {
    "valid_from": "2026-03-01",
    "energy": {"capacity_hours": 0.65, "remaining": 0.65},
    "trade_fee": 20.0,
}


# --- The table -------------------------------------------------------------


def test_the_2026_rates() -> None:
    """Enea S.A.'s A/B/C/R tariff, Enea Operator's 2026 tariff, URE's capacity fee."""
    peak, rest = PERIOD.zones[Zone.CAPACITY_HOURS], PERIOD.zones[Zone.REMAINING]

    assert PERIOD.valid_from == datetime.date(2026, 2, 1)
    for pricing in (peak, rest):
        assert (pricing.energy, pricing.variable_network, pricing.quality) == (0.8880, 0.2304, 0.0332)
        assert (pricing.oze, pricing.cogeneration) == (0.0073, 0.0030)
    assert (peak.capacity, rest.capacity) == (0.2194, 0.0)
    assert PERIOD.monthly.network_fixed_per_kw == 7.41
    assert PERIOD.monthly.trade == 35.00
    assert PERIOD.monthly.get_subscription(2) == 1.92


def test_the_capacity_fee_is_part_of_the_distribution_price() -> None:
    """Whatever reads total or total_distribution – sensors, statistics, the
    enea integration's costs – gets the capacity fee without knowing about it."""
    peak, rest = PERIOD.zones[Zone.CAPACITY_HOURS], PERIOD.zones[Zone.REMAINING]

    assert round(rest.total, 4) == 1.1619
    assert round(peak.total, 4) == 1.3813
    assert round(peak.total_brutto, 4) == round((0.8880 + 0.005 + 0.2739 + 0.2194) * 1.23, 4)


def test_household_prices_do_not_change_by_a_bit() -> None:
    """The new term is + 0.0 for every G group; total_brutto must stay identical
    to what the enea integration computes inline."""
    for name, group in TARIFFS.items():
        if group.contract_power:
            continue
        for period in group.periods:
            for p in period.zones.values():
                assert p.total_distribution == p.variable_network + p.quality + p.oze + p.cogeneration


@pytest.mark.parametrize(
    ("day", "hour", "zone"),
    [
        (WEDNESDAY, 6, Zone.REMAINING),
        (WEDNESDAY, 7, Zone.CAPACITY_HOURS),
        (WEDNESDAY, 21, Zone.CAPACITY_HOURS),
        (WEDNESDAY, 22, Zone.REMAINING),
        (SATURDAY, 12, Zone.REMAINING),
        (INDEPENDENCE_DAY, 12, Zone.REMAINING),
    ],
)
def test_the_capacity_fee_hours(day: datetime.date, hour: int, zone: Zone) -> None:
    """Informacja Prezesa URE nr 57/2025: 7:00–22:00, Monday to Friday, no holidays."""
    assert PERIOD.get_zone_at_hour(hour, day=day) is zone


def test_the_sensors_refresh_where_the_fee_starts_and_stops() -> None:
    assert PERIOD.get_zone_change_hours() == [7, 22]


# --- The entry's settings --------------------------------------------------


def test_the_fixed_network_fee_is_charged_per_kw() -> None:
    """Both network_fixed fields, so get_network_fixed answers alike for any phases."""
    group = build_tariff("C11", None, 12.5)

    for period in group.periods:
        assert period.monthly.get_network_fixed(1) == period.monthly.get_network_fixed(3)
        assert period.monthly.get_network_fixed(3) == pytest.approx(7.41 * 12.5)


def test_contract_prices_replace_energy_in_both_zones_and_keep_the_power() -> None:
    group = build_tariff("C11", [OFFER], 10.0)
    february = group.get_period_for_date(datetime.date(2026, 2, 15))
    march = group.get_period_for_date(datetime.date(2026, 3, 15))

    assert {p.energy for p in february.zones.values()} == {0.8880}
    assert february.monthly.trade == 35.00
    assert {p.energy for p in march.zones.values()} == {0.645}
    assert march.monthly.trade == 20.0
    assert march.zones[Zone.CAPACITY_HOURS].capacity == 0.2194
    for period in (february, march):
        assert round(period.monthly.get_network_fixed(1), 2) == 74.10


# --- Sensors ---------------------------------------------------------------


@pytest.fixture
def at_noon(monkeypatch: pytest.MonkeyPatch):
    """Set Home Assistant's clock to noon of a given day."""

    def _set(day: datetime.date) -> None:
        monkeypatch.setattr(
            dt_util,
            "now",
            lambda time_zone=None: datetime.datetime.combine(
                day, datetime.time(12), dt_util.get_default_time_zone()
            ),
        )

    return _set


async def test_c11_sensors(at_noon, platform) -> None:
    at_noon(WEDNESDAY)
    setup = await platform("C11", contract_power=10.0)

    assert setup.sensor("current_zone").native_value == "capacity_hours"
    assert setup.sensor("current_price_total").native_value == 1.3813
    assert setup.sensor("remaining_price_total").native_value == 1.1619
    assert setup.sensor("capacity_fee").native_value == 0.2194
    assert setup.sensor("monthly_network_fixed").native_value == 74.10
    assert setup.sensor("monthly_trade_fee").native_value == 35.00
    keys = {str(e.unique_id).removeprefix("enea_prices-C11-") for e in setup.entities}
    # The household flat rates mean nothing for a business connection.
    assert not keys & {"monthly_capacity", "monthly_transition"}


async def test_no_capacity_fee_on_a_holiday(at_noon, platform) -> None:
    at_noon(INDEPENDENCE_DAY)
    setup = await platform("C11", contract_power=10.0)

    assert setup.sensor("current_zone").native_value == "remaining"
    assert setup.sensor("current_price_total").native_value == 1.1619


async def test_household_groups_get_no_capacity_fee_sensor(at_noon, platform) -> None:
    at_noon(WEDNESDAY)
    setup = await platform("G12")

    keys = {str(e.unique_id).removeprefix("enea_prices-G12-") for e in setup.entities}
    assert "capacity_fee" not in keys
    assert {"monthly_capacity", "monthly_transition"} <= keys


# --- Config flow -----------------------------------------------------------


def _flow(details: dict[str, Any]) -> EneaPricesConfigFlow:
    """A new C11 flow that has just been through the details step."""
    flow = EneaPricesConfigFlow()
    flow.context = {"source": "user"}
    flow.flow_id = "flow"
    flow.handler = DOMAIN
    flow._tariff_name = "C11"
    flow._details = dict(details)
    return flow


def _fields(result: dict[str, Any]) -> list[str]:
    return [str(key) for key in result["data_schema"].schema]


def _defaults(result: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): key.default()
        for key in result["data_schema"].schema
        if callable(getattr(key, "default", None))
    }


DETAILS = {CONF_CONTRACT_POWER: 10.0, CONF_BILLING_MONTHS: 2}


class _NoMeters:
    """The hass surface the details step reads: no Enea meters configured."""

    def __init__(self) -> None:
        self.config_entries = self

    def async_entries(self, domain: str) -> list[Any]:
        return []


async def test_the_details_ask_for_contracted_power_instead_of_phases() -> None:
    flow = _flow({})
    flow.hass = _NoMeters()

    result = await flow.async_step_details()

    assert result["step_id"] == "details_power"
    assert _fields(result) == [CONF_CONTRACT_POWER, CONF_BILLING_MONTHS]
    assert hasattr(flow, "async_step_details_power")


async def test_c11_offers_its_tariff_or_a_contract() -> None:
    result = await _flow(DETAILS).async_step_prices()

    assert list(result["menu_options"]) == ["tariff_prices", "contract"]


async def test_the_tariff_entry_stores_power_not_phases() -> None:
    result = await _flow(DETAILS).async_step_tariff_prices()

    assert result["data"] == {CONF_TARIFF: "C11", **DETAILS}


async def test_a_contract_asks_for_one_price() -> None:
    """Pre-filled with the tariff as the invoice prints it, trade fee included."""
    result = await _flow(DETAILS).async_step_contract()

    assert _fields(result) == ["energy_all_day", "trade_fee", "valid_from"]
    defaults = _defaults(result)
    assert (defaults["energy_all_day"], defaults["trade_fee"]) == (0.893, 35.0)


async def test_the_one_price_is_stored_for_every_zone() -> None:
    result = await _flow(DETAILS).async_step_contract(
        {"energy_all_day": 0.65, "trade_fee": 20.0, "valid_from": "2026-03-01"}
    )

    assert result["data"][CONF_PRICE_CHANGES] == [OFFER]


async def test_reconfigure_keeps_the_power_and_shows_one_price(monkeypatch) -> None:
    flow = EneaPricesConfigFlow()
    flow.context = {"source": "reconfigure"}
    flow.flow_id = "flow"
    flow.handler = DOMAIN
    flow.hass = _NoMeters()
    entry = FakeConfigEntry(
        domain=DOMAIN, data={CONF_TARIFF: "C11", **DETAILS, CONF_PRICE_CHANGES: [OFFER]}
    )
    monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: entry)

    form = await flow.async_step_reconfigure()
    assert form["step_id"] == "reconfigure_power"
    assert _defaults(form) == {CONF_CONTRACT_POWER: 10.0, CONF_BILLING_MONTHS: "2"}
    assert hasattr(flow, "async_step_reconfigure_power")

    menu = await flow.async_step_reconfigure({CONF_CONTRACT_POWER: 12.5, CONF_BILLING_MONTHS: "1"})
    assert menu["description_placeholders"]["history"] == (
        "- 2026-03-01: 0.6500 zł/kWh, 20.00 zł/mies."
    )
    assert flow._details == {CONF_CONTRACT_POWER: 12.5, CONF_BILLING_MONTHS: 1}
