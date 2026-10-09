"""What the Enea Licznik integration knows about the meter an entry prices.

The enea integration reads the meter off the Portal Odbiorcy Enea and works out
the installation facts this integration asks for: phases, billing period length
and yearly consumption.  They are read here to pre-fill the forms, the same way
enea reads this integration — duck typing on the coordinator in runtime_data,
no import — so either integration works without the other, and with an older
version of it that does not offer the facts yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from homeassistant.core import HomeAssistant

from .const import (
    ANNUAL_KWH_OPTIONS,
    BILLING_OPTIONS,
    CONF_ANNUAL_KWH,
    CONF_BILLING_MONTHS,
    CONF_PHASES,
    ENEA_DOMAIN,
    PHASES_OPTIONS,
)
from .tariffs import TARIFFS


@dataclass(frozen=True)
class MeterHint:
    """One Enea meter: its tariff group and the facts worked out for it.

    A fact the meter does not settle is None.
    """

    tariff: str
    phases: int | None = None
    billing_months: int | None = None
    annual_kwh: float | None = None
    annual_kwh_until: date | None = None


def _tariff_key(name: str | None) -> str | None:
    """Return the TARIFFS key a portal tariff name stands for, matched like enea does."""
    if not name:
        return None
    return next((key for key in TARIFFS if key.casefold() == name.casefold()), None)


def meter_hints(hass: HomeAssistant) -> list[MeterHint]:
    """Return a hint for every loaded Enea meter whose tariff group is priced here."""
    hints = []
    for entry in hass.config_entries.async_entries(ENEA_DOMAIN):
        coordinator = getattr(getattr(entry, "runtime_data", None), "coordinator", None)
        if coordinator is None:
            continue
        tariff = _tariff_key(
            getattr(coordinator, "tariff_name", None)
            or getattr(coordinator, "_tariff_name", None)
        )
        if tariff is None:
            continue
        detected = getattr(coordinator, "detected_installation", None)
        hints.append(
            MeterHint(
                tariff=tariff,
                phases=getattr(detected, "phases", None),
                billing_months=getattr(detected, "billing_months", None),
                annual_kwh=getattr(detected, "annual_kwh", None),
                annual_kwh_until=getattr(detected, "annual_kwh_until", None),
            )
        )
    return hints


def meter_hint(hass: HomeAssistant, tariff: str) -> MeterHint | None:
    """Return the hint of the meter in a tariff group, None unless there is exactly one.

    Two meters in one group share an entry here, and their facts may well
    differ — then neither is offered.
    """
    hints = [hint for hint in meter_hints(hass) if hint.tariff == tariff]
    return hints[0] if len(hints) == 1 else None


def annual_kwh_option(annual_kwh: float) -> str:
    """Return the form option for a yearly consumption.

    The options stand for the capacity fee brackets, by the same boundaries as
    MonthlyFees.get_capacity: below 500, up to 1200, up to 2800, above.
    """
    lowest, middle, upper, highest = (option["value"] for option in ANNUAL_KWH_OPTIONS)
    if annual_kwh < 500:
        return lowest
    if annual_kwh <= 1200:
        return middle
    if annual_kwh <= 2800:
        return upper
    return highest


def form_defaults(hint: MeterHint) -> dict[str, str]:
    """Return the details form values a meter settles, as the selectors take them."""
    defaults: dict[str, str] = {}
    if hint.phases is not None and str(hint.phases) in _values(PHASES_OPTIONS):
        defaults[CONF_PHASES] = str(hint.phases)
    if hint.billing_months is not None and str(hint.billing_months) in _values(BILLING_OPTIONS):
        defaults[CONF_BILLING_MONTHS] = str(hint.billing_months)
    if hint.annual_kwh is not None:
        defaults[CONF_ANNUAL_KWH] = annual_kwh_option(hint.annual_kwh)
    return defaults


def _values(options: list[dict[str, str]]) -> set[str]:
    """Return the values of selector options."""
    return {option["value"] for option in options}
