"""Enea Ceny – integracja cen energii elektrycznej."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .const import (
    CONF_ANNUAL_KWH,
    CHANGE_ENERGY,
    CHANGE_TRADE_FEE,
    CHANGE_VALID_FROM,
    CONF_BILLING_MONTHS,
    CONF_PHASES,
    CONF_PRICE_CHANGES,
    CONF_TARIFF,
    DOMAIN,
    PLATFORMS,
)
from .tariffs import (
    TARIFFS,
    PriceChange,
    TariffGroup,
    Zone,
    invoice_price_to_energy,
    with_price_changes,
)


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
        reported = getattr(coordinator, "_tariff_name", None) or ""
        if reported.casefold() == tariff_name.casefold():
            hass.async_create_task(
                hass.config_entries.async_reload(enea_entry.entry_id)
            )


def price_change_from_data(data: Mapping[str, Any]) -> PriceChange:
    """Convert one stored price change into the model.

    Contract prices are stored exactly as typed off the invoice, excise
    included, so the form shows them unchanged when opened again; the excise
    comes off here.
    """
    energy = data.get(CHANGE_ENERGY)
    return PriceChange(
        valid_from=date.fromisoformat(data[CHANGE_VALID_FROM]),
        energy=(
            {Zone(zone): invoice_price_to_energy(price) for zone, price in energy.items()}
            if energy is not None
            else None
        ),
        trade_fee=data.get(CHANGE_TRADE_FEE, 0.0),
    )


def build_tariff(
    tariff_name: str, price_changes: list[Mapping[str, Any]] | None
) -> TariffGroup:
    """Return the tariff group of an entry, priced by its history of price changes."""
    group = TARIFFS[tariff_name]
    changes = [price_change_from_data(change) for change in price_changes or []]
    if group.contract_energy and not any(c.energy is not None for c in changes):
        raise ConfigEntryError(
            translation_domain=DOMAIN,
            translation_key="contract_required",
            translation_placeholders={"tariff": tariff_name},
        )
    return with_price_changes(group, changes) if changes else group


async def async_setup_entry(hass: HomeAssistant, entry: EneaPricesConfigEntry) -> bool:
    """Set up Enea Ceny from a config entry."""
    tariff_name: str = entry.data[CONF_TARIFF]
    group = build_tariff(tariff_name, entry.data.get(CONF_PRICE_CHANGES))

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
