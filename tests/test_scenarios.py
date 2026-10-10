"""What users do with the integration, in a running Home Assistant.

Adding a group through the config flow, entering contract prices or changing
them from a date, a contract-only group, holidays, restarts and downtime.  The
statistics are checked where the Energy Dashboard reads them: the mean of each
hour of a price sensor.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_RECORDER_HOURLY_STATISTICS_GENERATED
from homeassistant.data_entry_flow import FlowResultType

from custom_components.enea_prices.tariffs import AKCYZA, TARIFFS
from ha_instance import (  # noqa: F401 - clock, database, triggers and hass are fixtures
    TODAY,
    async_start_hass,
    at_local,
    clock,
    database,
    entity_id,
    hass,
    make_entry,
    state,
    triggers,
)

DETAILS = {"phases": "3", "annual_kwh": "2000", "billing_months": "2"}
CONTRACT_FROM = date(2026, 3, 1)
OFFER = {"energy_day": 0.65, "energy_night": 0.35, "trade_fee": 9.82}
"""Prices as an invoice prints them, excise included."""


def _g12(day: date):
    """Return the G12 table's period of a day."""
    return TARIFFS["G12"].get_period_for_date(day)


async def _add_through_the_flow(hass, prices_step: str, prices: dict | None = None):
    """Add G12 through the config flow, choosing a prices step; return the entry."""
    flow = await hass.config_entries.flow.async_init("enea_prices", context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"tariff": "G12"})
    assert flow["step_id"] == "details"
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], DETAILS)
    assert (flow["type"], flow["step_id"]) == (FlowResultType.MENU, "prices")
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"next_step_id": prices_step})
    if prices is not None:
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], prices)
    assert flow["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    [entry] = hass.config_entries.async_entries("enea_prices")
    return entry


async def _reconfigure(hass, entry, step: str, prices: dict | None = None):
    """Reconfigure with the same details, adding a price change through a menu step."""
    flow = await hass.config_entries.flow.async_init(
        "enea_prices", context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], DETAILS)
    assert (flow["type"], flow["step_id"]) == (FlowResultType.MENU, "change_prices")
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"next_step_id": step})
    if prices is not None:
        flow = await hass.config_entries.flow.async_configure(flow["flow_id"], prices)
    assert (flow["type"], flow["reason"]) == (FlowResultType.ABORT, "reconfigure_successful")
    await hass.async_block_till_done()


async def test_tariff_prices_through_the_config_flow(hass):
    """The flow's entry is set up with the installation and the tariff's prices."""
    entry = await _add_through_the_flow(hass, "tariff_prices")

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data == {"tariff": "G12", "phases": 3, "annual_kwh": 2000, "billing_months": 2}
    assert state(hass, "G12", "day_price_energy") == str(round(_g12(TODAY).zones["day"].energy, 4))
    assert state(hass, "G12", "monthly_network_fixed") == str(_g12(TODAY).monthly.get_network_fixed(3))


async def test_contract_prices_through_the_config_flow(hass, database):
    """An offer from 1 March prices energy from that day on; the trade fee appears.

    The invoice price includes the excise, which comes off the stored energy
    price.  The hours before the offer keep the tariff's price.
    """
    await _add_through_the_flow(hass, "contract", {**OFFER, "valid_from": CONTRACT_FROM.isoformat()})
    day_energy = entity_id(hass, "G12", "day_price_energy")

    assert state(hass, "G12", "day_price_energy") == str(round(OFFER["energy_day"] - AKCYZA, 4))
    assert state(hass, "G12", "monthly_trade_fee") == "9.82"
    assert database.mean_at(day_energy, at_local(date(2026, 3, 2), 12)) == pytest.approx(0.645)
    assert database.mean_at(day_energy, at_local(date(2026, 2, 27), 12)) == pytest.approx(
        _g12(date(2026, 2, 27)).zones["day"].energy
    )


async def test_back_dated_offer_rewrites_the_price_history(hass, database):
    """An offer entered later with a start in the past corrects the hours already stored.

    The newest hour stays with the recorder, which compiles it itself.
    """
    entry = await _add_through_the_flow(hass, "tariff_prices")
    day_energy = entity_id(hass, "G12", "day_price_energy")
    tariff_price = _g12(CONTRACT_FROM).zones["day"].energy
    assert database.mean_at(day_energy, at_local(date(2026, 3, 2), 12)) == pytest.approx(tariff_price)

    await _reconfigure(hass, entry, "contract", {**OFFER, "valid_from": CONTRACT_FROM.isoformat()})

    assert entry.data["price_changes"][0]["valid_from"] == "2026-03-01"
    assert database.mean_at(day_energy, at_local(date(2026, 3, 2), 12)) == pytest.approx(0.645)
    assert database.mean_at(day_energy, at_local(date(2026, 2, 28), 12)) == pytest.approx(tariff_price)
    newest = at_local(TODAY - timedelta(days=1), 23)
    assert database.mean_at(day_energy, newest) == pytest.approx(tariff_price)


async def test_back_to_the_tariff_from_a_date(hass, database, clock):
    """After an offer ends, the tariff prices the days from the date given."""
    clock.now = at_local(date(2026, 3, 20), 10)
    await _add_through_the_flow(hass, "contract", {**OFFER, "valid_from": CONTRACT_FROM.isoformat()})
    entry = hass.config_entries.async_entries("enea_prices")[0]

    await _reconfigure(hass, entry, "tariff_prices", {"valid_from": "2026-03-10"})

    day_energy = entity_id(hass, "G12", "day_price_energy")
    assert [c["valid_from"] for c in entry.data["price_changes"]] == ["2026-03-01", "2026-03-10"]
    assert state(hass, "G12", "day_price_energy") == str(round(_g12(TODAY).zones["day"].energy, 4))
    assert database.mean_at(day_energy, at_local(date(2026, 3, 5), 12)) == pytest.approx(0.645)
    assert database.mean_at(day_energy, at_local(date(2026, 3, 12), 12)) == pytest.approx(
        _g12(date(2026, 3, 12)).zones["day"].energy
    )


async def test_a_change_cannot_start_before_the_last_one(hass):
    """Rewriting a stretch already billed at other prices is refused."""
    entry = await _add_through_the_flow(hass, "contract", {**OFFER, "valid_from": CONTRACT_FROM.isoformat()})
    flow = await hass.config_entries.flow.async_init(
        "enea_prices", context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], DETAILS)
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"next_step_id": "contract"})

    flow = await hass.config_entries.flow.async_configure(
        flow["flow_id"], {**OFFER, "valid_from": "2026-02-15"}
    )

    assert (flow["type"], flow["errors"]) == (FlowResultType.FORM, {"valid_from": "before_last_change"})


async def test_contract_only_group_needs_an_offer(hass):
    """G13active has no tariff energy price: without an offer the entry does not load."""
    entry = make_entry(tariff="G13active")
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_contract_only_group_goes_straight_to_the_offer(hass):
    """The flow for G13active skips the prices menu and asks for the offer."""
    flow = await hass.config_entries.flow.async_init("enea_prices", context={"source": "user"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {"tariff": "G13active"})
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], DETAILS)

    assert (flow["type"], flow["step_id"]) == (FlowResultType.FORM, "contract")
    fields = {str(key) for key in flow["data_schema"].schema}
    assert {f"energy_{zone}" for zone in TARIFFS["G13active"].periods[0].zones} <= fields


async def test_g12w_holiday_is_off_peak_all_day(hass, clock, triggers):
    """11 November 2026 is a Wednesday and a public holiday: no peak hours that day."""
    clock.now = at_local(date(2026, 11, 11), 10)
    await hass.config_entries.async_add(make_entry(tariff="G12w"))
    await hass.async_block_till_done()
    assert state(hass, "G12w", "current_zone") == "off_peak"

    clock.now = at_local(date(2026, 11, 12), 0)
    triggers.fire(0, clock.now)
    clock.now = at_local(date(2026, 11, 12), 6)
    triggers.fire(6, clock.now)

    assert state(hass, "G12w", "current_zone") == "peak"


async def test_restart_imports_nothing_again(tmp_path, clock, database, triggers):
    """A second start finds every hour stored with its price and writes nothing."""
    hass = await async_start_hass(str(tmp_path))
    await hass.config_entries.async_add(make_entry())
    await hass.async_block_till_done()
    await hass.async_stop()
    database.imports.clear()

    hass = await async_start_hass(str(tmp_path))
    try:
        [entry] = hass.config_entries.async_entries("enea_prices")
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert database.imports == []
    finally:
        await hass.async_stop()


async def test_downtime_is_filled_once_the_recorder_compiles_an_hour(tmp_path, clock, database, triggers):
    """Days the installation was down are filled after the recorder's first hourly run.

    Right after the start the newest stored hour is from before the downtime,
    so nothing after it is written — it might race the recorder.  Once the
    recorder compiles an hour of its own, the downtime is a gap behind it.
    """
    hass = await async_start_hass(str(tmp_path))
    await hass.config_entries.async_add(make_entry())
    await hass.async_block_till_done()
    await hass.async_stop()

    clock.now = at_local(TODAY + timedelta(days=5), 10)
    hass = await async_start_hass(str(tmp_path))
    try:
        [entry] = hass.config_entries.async_entries("enea_prices")
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        day_total = entity_id(hass, "G12", "day_price_total")
        down = at_local(TODAY + timedelta(days=2), 12)
        assert database.mean_at(day_total, down) is None

        # What the recorder compiles itself: the hour just closed.
        database.rows[day_total][at_local(TODAY + timedelta(days=5), 9).timestamp()] = {"mean": 0.8993}
        hass.bus.async_fire(EVENT_RECORDER_HOURLY_STATISTICS_GENERATED)
        await hass.async_block_till_done()

        assert database.mean_at(day_total, down) == pytest.approx(_g12(down.date()).zones["day"].total)
    finally:
        await hass.async_stop()


async def test_unload_stops_the_time_callbacks(hass, triggers):
    """Unloading the entry leaves no zone or midnight callback behind."""
    entry = make_entry()
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    assert triggers.callbacks

    assert await hass.config_entries.async_unload(entry.entry_id)

    assert triggers.callbacks == []
