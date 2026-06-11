"""Enea Ceny – integracja cen energii elektrycznej."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ANNUAL_KWH, CONF_BILLING_MONTHS, CONF_PHASES, CONF_TARIFF, PLATFORMS
from .tariffs import TariffGroup, TARIFFS


@dataclass
class EneaPricesRuntimeData:
    """Runtime data for the Enea Ceny integration."""

    tariff: TariffGroup
    phases: int
    annual_kwh: int
    billing_months: int
    unsub_listeners: list[Callable[[], None]] = field(default_factory=list)


type EneaPricesConfigEntry = ConfigEntry[EneaPricesRuntimeData]


def _async_reload_matching_enea_entries(hass: HomeAssistant, tariff_name: str) -> None:
    """Schedule a reload for enea meter entries whose tariff matches tariff_name.

    Called after enea_prices finishes setup so that enea can discover the
    newly available tariff and create cost sensor entities.  Uses
    async_create_task to avoid blocking the current setup coroutine.
    """
    for enea_entry in hass.config_entries.async_entries("enea"):
        coordinator = getattr(getattr(enea_entry, "runtime_data", None), "coordinator", None)
        if coordinator is None:
            continue
        if getattr(coordinator, "_tariff_name", None) == tariff_name:
            hass.async_create_task(
                hass.config_entries.async_reload(enea_entry.entry_id)
            )


async def async_setup_entry(hass: HomeAssistant, entry: EneaPricesConfigEntry) -> bool:
    """Set up Enea Ceny from a config entry."""
    tariff_name: str = entry.data[CONF_TARIFF]
    group = TARIFFS[tariff_name]

    entry.runtime_data = EneaPricesRuntimeData(
        tariff=group,
        phases=entry.data[CONF_PHASES],
        annual_kwh=entry.data[CONF_ANNUAL_KWH],
        billing_months=entry.data[CONF_BILLING_MONTHS],
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload any enea (meter) entries that share this tariff so they can
    # create cost sensors now that enea_prices runtime data is available.
    _async_reload_matching_enea_entries(hass, tariff_name)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EneaPricesConfigEntry) -> bool:
    """Unload a config entry."""
    for unsub in entry.runtime_data.unsub_listeners:
        unsub()
    entry.runtime_data.unsub_listeners.clear()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
