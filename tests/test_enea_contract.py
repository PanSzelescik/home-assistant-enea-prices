"""The contract with the real Enea Licznik integration, checked against its code.

The two integrations never import each other: each reads the other by
attribute names, entry data keys and module names.  This loads the enea
integration's own code from a checkout of home-assistant-enea (ENEA_PATH, or
next to this repository) and checks both directions; the enea repository has
the mirror of this test against this integration.

What enea reads from here: entries keyed by data["tariff"], their runtime_data,
TARIFFS, AKCYZA from const, and of the tariff groups their periods, zones and
fees.  What this integration reads from enea: each meter coordinator's tariff
name and detected_installation, and it reloads the meters of its group.
"""
from __future__ import annotations

import importlib
from datetime import date, timedelta
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntry

from custom_components.enea_prices import const
from custom_components.enea_prices.meter import meter_hints
from custom_components.enea_prices.tariffs import AKCYZA, TARIFFS, Zone
from ha_instance import (  # noqa: F401 - clock, database, triggers, hass and real_enea are fixtures
    clock,
    database,
    hass,
    make_entry,
    real_enea,
    triggers,
)

pytestmark = pytest.mark.usefixtures("real_enea")


def _enea(name: str):
    """Return a module of the real enea integration."""
    return importlib.import_module(f"custom_components.enea.{name}")


def test_the_real_integration_is_loaded(real_enea):
    """The package comes from the enea checkout."""
    from ha_instance import find_enea_repository  # noqa: PLC0415

    repository = find_enea_repository()
    assert repository is not None
    assert Path(real_enea.__file__).resolve().is_relative_to(repository.resolve())


def test_entry_keys_and_domains_agree():
    """The keys enea writes a repair fix into are the ones this integration reads."""
    enea = _enea("const")

    assert enea.ENEA_PRICES_DOMAIN == const.DOMAIN
    assert enea.DOMAIN == const.ENEA_DOMAIN
    assert (
        enea.ENEA_PRICES_CONF_TARIFF,
        enea.ENEA_PRICES_CONF_PHASES,
        enea.ENEA_PRICES_CONF_ANNUAL_KWH,
        enea.ENEA_PRICES_CONF_BILLING_MONTHS,
    ) == (const.CONF_TARIFF, const.CONF_PHASES, const.CONF_ANNUAL_KWH, const.CONF_BILLING_MONTHS)


def test_every_zone_has_a_display_name_in_enea():
    """enea names cost statistics and bill attributes after the zones."""
    assert {str(zone) for zone in Zone} <= set(_enea("const").COST_ZONE_DISPLAY)


def test_portal_aliases_name_groups_priced_here():
    """Every group name the portal shortens maps to a group of TARIFFS."""
    assert set(_enea("const").TARIFF_GROUP_ALIASES.values()) <= set(TARIFFS)


def test_excise_duty_is_where_enea_looks_for_it():
    """enea reads AKCYZA from the const module once this package is loaded."""
    assert _enea("costs")._akcyza() == const.AKCYZA == AKCYZA


@pytest.mark.parametrize("group_name", sorted(TARIFFS))
def test_enea_costs_a_kwh_at_the_gross_price(group_name):
    """The brutto kWh price here and the one enea's costs charge round alike."""
    kwh_price = _enea("costs")._kwh_price
    for period in TARIFFS[group_name].periods:
        for zone, pricing in period.zones.items():
            assert kwh_price(pricing, AKCYZA) == round(pricing.total_brutto, 4), (period.valid_from, zone)


@pytest.mark.parametrize("group_name", sorted(TARIFFS))
def test_enea_bills_with_the_monthly_fees(group_name):
    """enea's bill estimate reads the fees through these calls."""
    for period in TARIFFS[group_name].periods:
        monthly = period.monthly
        assert monthly.get_network_fixed(3) >= 0
        assert monthly.get_capacity(2000) >= 0
        assert monthly.get_subscription(2) >= 0
        assert getattr(monthly, "trade", 0.0) >= 0


async def test_enea_finds_this_entry_and_its_settings(hass):
    """enea's lookups return the tariff and settings of a set-up entry."""
    entry = make_entry(phases=1, annual_kwh=3170, billing_months=6)
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()

    cfg = _enea("billing").find_prices_config(hass, "g12")

    assert cfg is not None
    assert cfg.tariff is entry.runtime_data.tariff is _enea("costs").find_tariff_group(hass, "G12")
    assert (cfg.phases, cfg.annual_kwh, cfg.billing_months, cfg.akcyza) == (1, 3170, 6, AKCYZA)


async def test_enea_costs_across_two_agreements_with_real_groups(hass):
    """enea's tariff history combines groups of several agreements; these fit it."""
    g11, g12 = TARIFFS["G11"], TARIFFS["G12"]
    change = date(2026, 2, 1)
    history = _enea("costs").TariffHistory(g12, [(date(2000, 1, 1), change, g11, "G11"), (change, None, g12, "G12")])

    assert history.get_period_for_date(change - timedelta(days=1)) is g11.get_period_for_date(change - timedelta(days=1))
    assert history.get_period_for_date(change) is g12.get_period_for_date(change)


def _meter(hass, tariff: str, detected) -> ConfigEntry:
    """Register an enea meter entry whose coordinator is a real, unstarted one."""
    entry = ConfigEntry(
        data={"meter_name": "590310600000001234", "meter_id": 12345, "username": "u", "password": "p"},
        discovery_keys=MappingProxyType({}),
        domain="enea",
        minor_version=1,
        options={},
        source="user",
        subentries_data=None,
        title="Enea 590310600000001234",
        unique_id="590310600000001234",
        version=1,
    )
    coordinator = _enea("coordinator").EneaUpdateCoordinator(
        hass, entry, client=None, meter_id=12345, meter_code="590310600000001234",
        update_interval=timedelta(hours=3),
    )
    coordinator._tariff_name = tariff
    coordinator.detected_installation = detected
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    hass.config_entries._entries[entry.entry_id] = entry  # noqa: SLF001
    return entry


async def test_form_hints_read_the_real_coordinator(hass):
    """The meter's tariff name and detected installation reach the form hints."""
    detected = _enea("installation").DetectedInstallation(
        phases=3, billing_months=2, annual_kwh=3170.0, annual_kwh_until=date(2026, 8, 5)
    )
    _meter(hass, "G12", detected)

    [hint] = meter_hints(hass)

    assert (hint.tariff, hint.phases, hint.billing_months, hint.annual_kwh, hint.annual_kwh_until) == (
        "G12", 3, 2, 3170.0, date(2026, 8, 5),
    )


async def test_setting_up_prices_reloads_the_meters_of_the_group(hass, monkeypatch):
    """A G12 entry reloads the G12 meter and leaves a G11 one alone."""
    detected = _enea("installation").DetectedInstallation()
    g12_meter = _meter(hass, "G12", detected)
    _meter(hass, "G11", detected)
    reloads = AsyncMock()
    monkeypatch.setattr(hass.config_entries, "async_reload", reloads)

    await hass.config_entries.async_add(make_entry())
    await hass.async_block_till_done()

    assert [call.args[0] for call in reloads.await_args_list] == [g12_meter.entry_id]
