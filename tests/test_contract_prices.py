"""Energy prices taken from the customer's contracts instead of the URE tariff.

An offer's price list is fixed for its term from the day the contract is
signed, then renewed with a new list or replaced by the tariff, so the
integration cannot bundle it: the customer copies the unit prices off an
invoice, and keeps a history of changes, each in force until the next.
Distribution is billed by the operator either way and stays as the table has it.
"""
from __future__ import annotations

import datetime

import pytest
from homeassistant.exceptions import ConfigEntryError

from custom_components.enea_prices import build_tariff
from custom_components.enea_prices.tariffs import (
    TARIFFS,
    PriceChange,
    Zone,
    invoice_price_to_energy,
    with_price_changes,
)

MARCH_15 = datetime.date(2026, 3, 15)
AUGUST_1 = datetime.date(2026, 8, 1)
DAY = datetime.timedelta(days=1)

OFFER = PriceChange(MARCH_15, {Zone.DAY: 0.6, Zone.NIGHT: 0.3}, 9.82)
RENEWAL = PriceChange(AUGUST_1, {Zone.DAY: 0.65, Zone.NIGHT: 0.32}, 15.94)
BACK_TO_TARIFF = PriceChange(AUGUST_1)

SEZON_CHANGE = {
    "valid_from": "2026-01-01",
    "energy": {"recommended_use": 0.35, "remaining": 0.59},
    "trade_fee": 9.82,
}


def _day_energy(group, day: datetime.date) -> tuple[float, float]:
    period = group.get_period_for_date(day)
    return period.zones[Zone.DAY].energy, period.monthly.trade


def test_invoice_price_loses_the_excise() -> None:
    """An invoice's "Cena jedn. netto" includes the 5 zł/MWh excise.

    Verified on a real 2026 G12 invoice: 0,5829 and 0,3419 against the tariff's
    0,5779 and 0,3369.
    """
    assert invoice_price_to_energy(0.5829) == 0.5779
    assert invoice_price_to_energy(0.3419) == 0.3369
    assert invoice_price_to_energy(0.35) == 0.345


def test_a_period_straddling_a_change_is_split() -> None:
    group = with_price_changes(TARIFFS["G12"], [OFFER])

    before = group.get_period_for_date(MARCH_15 - DAY)
    after = group.get_period_for_date(MARCH_15)

    assert before.valid_until == MARCH_15 - DAY
    assert after.valid_from == MARCH_15
    assert _day_energy(group, MARCH_15 - DAY) == (0.5779, 0.0)
    assert _day_energy(group, MARCH_15) == (0.6, 9.82)


def test_each_change_holds_until_the_next() -> None:
    """A renewed offer must not reach back over the stretch the first one priced.

    This is what a single contract could not express: entering the renewal
    would have dropped the first offer's prices, and the statistics would have
    been rewritten with the tariff for those months.
    """
    group = with_price_changes(TARIFFS["G12"], [OFFER, RENEWAL])

    assert _day_energy(group, MARCH_15 - DAY) == (0.5779, 0.0)
    assert _day_energy(group, AUGUST_1 - DAY) == (0.6, 9.82)
    assert _day_energy(group, AUGUST_1) == (0.65, 15.94)
    assert _day_energy(group, datetime.date(2026, 12, 31)) == (0.65, 15.94)


def test_a_return_to_the_tariff_ends_the_offer() -> None:
    group = with_price_changes(TARIFFS["G12"], [OFFER, BACK_TO_TARIFF])

    assert _day_energy(group, AUGUST_1 - DAY) == (0.6, 9.82)
    assert _day_energy(group, AUGUST_1) == (0.5779, 0.0)


def test_the_table_stays_gapless() -> None:
    """Splitting must neither lose nor duplicate a day."""
    group = with_price_changes(TARIFFS["G12"], [OFFER, RENEWAL])

    day = group.periods[0].valid_from
    while day <= group.periods[-1].valid_until:
        assert len([p for p in group.periods if p.valid_from <= day <= p.valid_until]) == 1, day
        day += DAY


def test_distribution_is_left_as_the_table_has_it() -> None:
    tariff = TARIFFS["G12"].get_period_for_date(MARCH_15)
    offer = with_price_changes(TARIFFS["G12"], [OFFER]).get_period_for_date(MARCH_15)

    for zone in tariff.zones:
        assert offer.zones[zone].total_distribution == tariff.zones[zone].total_distribution
    assert offer.monthly.get_network_fixed(3) == tariff.monthly.get_network_fixed(3)


def test_earlier_periods_keep_their_tariff_prices() -> None:
    """History before the first contract was billed at the tariff and must stay so."""
    group = with_price_changes(TARIFFS["G12"], [OFFER])

    assert group.periods[0].valid_from == TARIFFS["G12"].periods[0].valid_from
    assert group.get_period_for_date(datetime.date(2025, 10, 1)).zones[Zone.NIGHT].energy == 0.3840


def test_a_contract_group_starts_where_its_contract_does() -> None:
    """Before the contract a contract group has no energy price to report."""
    group = with_price_changes(
        TARIFFS["G12sezON"],
        [PriceChange(MARCH_15, {Zone.RECOMMENDED_USE: 0.345, Zone.REMAINING: 0.585}, 9.82)],
    )

    assert group.periods[0].valid_from == MARCH_15
    assert group.get_period_for_date(MARCH_15 - DAY) is None
    assert not group.contract_energy


def test_the_gross_price_matches_the_invoice() -> None:
    """przemirs, G12sezON, July 2026: 0,35 zł/kWh for energy in the cheap zone.

    Energy with excise, plus the distribution rates his invoice agreed with, plus
    VAT, has to give what Enea charges for one kWh in that zone.
    """
    group = build_tariff("G12sezON", [SEZON_CHANGE])
    zone = group.get_period_for_date(datetime.date(2026, 7, 15)).zones[Zone.RECOMMENDED_USE]

    assert round(zone.total_brutto, 4) == round((0.35 + 0.0913 + 0.0332 + 0.0073 + 0.0030) * 1.23, 4)


@pytest.mark.parametrize("changes", [None, [], [{"valid_from": "2026-03-01"}]])
def test_a_contract_group_cannot_be_set_up_without_prices(changes) -> None:
    with pytest.raises(ConfigEntryError):
        build_tariff("G13active", changes)


def test_a_tariff_group_without_changes_is_the_bundled_table() -> None:
    assert build_tariff("G12", None) is TARIFFS["G12"]


async def test_the_trade_fee_sensor_exists_only_with_a_contract(platform) -> None:
    without = await platform("G12")
    assert not [e for e in without.entities if str(e.unique_id).endswith("-monthly_trade_fee")]

    contract = await platform("G12sezON", [SEZON_CHANGE])
    assert contract.sensor("monthly_trade_fee").unique_id == "enea_prices-G12sezON-monthly_trade_fee"
    contract.sensor("recommended_use_price_energy")
    contract.sensor("remaining_price_total_brutto")
