"""Config flow for Enea Ceny integration."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ANNUAL_KWH_OPTIONS,
    BILLING_OPTIONS,
    CONF_ANNUAL_KWH,
    CHANGE_ENERGY,
    CHANGE_TRADE_FEE,
    CHANGE_VALID_FROM,
    CONF_BILLING_MONTHS,
    CONF_PHASES,
    CONF_PRICE_CHANGES,
    CONF_TARIFF,
    DEFAULT_ANNUAL_KWH,
    DEFAULT_BILLING_MONTHS,
    DEFAULT_PHASES,
    DOMAIN,
    PHASES_OPTIONS,
)
from .meter import MeterHint, annual_kwh_option, form_defaults, meter_hint, meter_hints
from .tariffs import AKCYZA, TARIFFS, TariffGroup, Zone

# Pole formularza z ceną energii danej strefy, np. "energy_day".
_ENERGY_FIELD = "energy_{}"
# Shown for a fact the meter does not settle.
_UNKNOWN = "—"


class EneaPricesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Enea Ceny."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._tariff_name: str = ""
        self._details: dict[str, int] = {}
        self._reconfigure_entry: ConfigEntry | None = None
        self._changes: list[dict[str, Any]] = []
        """The entry's price history, oldest first; edited, then saved whole."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: select tariff group.

        Pre-selected when the Enea meters leave exactly one group without an
        entry.
        """
        if user_input is not None:
            self._tariff_name = user_input[CONF_TARIFF]
            return await self.async_step_details()

        configured = {entry.data[CONF_TARIFF] for entry in self._async_current_entries()}
        unpriced = {hint.tariff for hint in meter_hints(self.hass)} - configured
        tariff = (
            vol.Required(CONF_TARIFF, default=next(iter(unpriced)))
            if len(unpriced) == 1
            else vol.Required(CONF_TARIFF)
        )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    tariff: SelectSelector(
                        SelectSelectorConfig(
                            options=list(TARIFFS.keys()),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: installation details for monthly fee calculation.

        The prices step still follows, and a flow left there (dialog closed,
        page reloaded) stays in progress until Home Assistant restarts.  So an
        earlier flow for the same group must not block this one; whichever
        finishes first wins, the other is turned away in _async_finish.

        With an Enea meter in the chosen group, the facts it settles pre-fill
        the form, under a description that lists them.
        """
        if user_input is not None:
            await self.async_set_unique_id(self._tariff_name, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            self._details = _details_from_input(user_input)
            return await self.async_step_prices()

        hint = meter_hint(self.hass, self._tariff_name)
        if hint is None:
            return self.async_show_form(
                step_id="details",
                data_schema=_details_schema(),
            )

        defaults = form_defaults(hint)
        return self.async_show_form(
            step_id="details_from_meter",
            data_schema=_details_schema(
                default_phases=defaults.get(CONF_PHASES, DEFAULT_PHASES),
                default_annual_kwh=defaults.get(CONF_ANNUAL_KWH, DEFAULT_ANNUAL_KWH),
                default_billing_months=defaults.get(CONF_BILLING_MONTHS, DEFAULT_BILLING_MONTHS),
            ),
            description_placeholders=_hint_placeholders(hint),
        )

    # The pre-filled form only differs in its description, which needs a step id
    # of its own; what it sends back is handled the same.
    async_step_details_from_meter = async_step_details

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow user to change installation details and prices without removing the integration.

        The form keeps the entry's settings; what an Enea meter settles is only
        listed in the description, so that saving another change cannot
        quietly replace a setting the user chose.
        """
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self._reconfigure_entry = entry
            self._tariff_name = entry.data[CONF_TARIFF]
            self._details = _details_from_input(user_input)
            self._changes = [dict(c) for c in entry.data.get(CONF_PRICE_CHANGES, [])]
            return await self.async_step_change_prices()

        schema = _details_schema(
            default_phases=str(entry.data[CONF_PHASES]),
            # A measured consumption (set from a repair of the enea integration)
            # is shown as the option of its bracket.
            default_annual_kwh=annual_kwh_option(entry.data[CONF_ANNUAL_KWH]),
            default_billing_months=str(entry.data[CONF_BILLING_MONTHS]),
        )
        hint = meter_hint(self.hass, entry.data[CONF_TARIFF])
        if hint is None:
            return self.async_show_form(step_id="reconfigure", data_schema=schema)
        return self.async_show_form(
            step_id="reconfigure_from_meter",
            data_schema=schema,
            description_placeholders=_hint_placeholders(hint),
        )

    async_step_reconfigure_from_meter = async_step_reconfigure

    # A menu is a step like any other: Home Assistant drops a flow whose result
    # names a step id without an async_step_ method, so both menus need one.

    async def async_step_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3 of a new entry: where the energy price comes from.

        A group the URE tariff prices offers a choice; a group only an offer
        prices (G12sezON, G13active) goes straight to the contract form.
        """
        if TARIFFS[self._tariff_name].contract_energy:
            return await self.async_step_contract()
        return self.async_show_menu(
            step_id="prices",
            menu_options=["tariff_prices", "contract"],
        )

    async def async_step_change_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: keep the price history, or add a change to it.

        Prices change over time – an offer ends, is renewed with a new price
        list or gives way to the tariff – so a change is added from a date
        rather than replacing what was there: the hours before it keep the
        prices they were billed at.
        """
        options = ["keep_prices", "contract"]
        if not TARIFFS[self._tariff_name].contract_energy and self._changes:
            options += ["tariff_prices", "clear_prices"]
        return self.async_show_menu(
            step_id="change_prices",
            menu_options=options,
            description_placeholders={"history": _format_history(self._changes)},
        )

    async def async_step_keep_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: leave the price history as it is."""
        return self._async_finish()

    async def async_step_clear_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: forget every price change; the tariff prices all hours again."""
        self._changes = []
        return self._async_finish()

    async def async_step_tariff_prices(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Use the energy prices of the URE-approved tariff.

        A new entry simply has no price changes.  An entry with a history
        returns to the tariff from a date, which is asked for next.
        """
        if not self._changes:
            return self._async_finish()
        return await self.async_step_tariff_from()

    async def async_step_tariff_from(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Reconfigure: from which day the tariff prices apply again."""
        errors: dict[str, str] = {}
        if user_input is not None:
            valid_from = date.fromisoformat(user_input[CHANGE_VALID_FROM])
            errors = self._validate_start(valid_from)
            if not errors:
                self._add_change({CHANGE_VALID_FROM: valid_from.isoformat()})
                return self._async_finish()

        current = user_input or {CHANGE_VALID_FROM: date.today().isoformat()}
        return self.async_show_form(
            step_id="tariff_from",
            data_schema=vol.Schema(
                {vol.Required(CHANGE_VALID_FROM, default=current[CHANGE_VALID_FROM]): DateSelector()}
            ),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_contract(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Energy prices and trade fee copied off the customer's invoice."""
        group = TARIFFS[self._tariff_name]
        zones = _contract_zones(group)
        errors: dict[str, str] = {}

        if user_input is not None:
            valid_from = date.fromisoformat(user_input[CHANGE_VALID_FROM])
            errors = self._validate_start(valid_from)
            if not errors:
                self._add_change(
                    {
                        CHANGE_VALID_FROM: valid_from.isoformat(),
                        CHANGE_ENERGY: {
                            str(zone): float(user_input[_ENERGY_FIELD.format(zone)])
                            for zone in zones
                        },
                        CHANGE_TRADE_FEE: float(user_input[CHANGE_TRADE_FEE]),
                    }
                )
                return self._async_finish()

        current = user_input or self._contract_defaults(group, zones)
        return self.async_show_form(
            step_id="contract",
            data_schema=_contract_schema(zones, current),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    def _contract_defaults(self, group: TariffGroup, zones: list[Zone]) -> dict[str, Any]:
        """Pre-fill the contract form.

        Prices: those of the latest contract, since a renewed offer often
        changes only some of them; else the tariff's own, shown the way an
        invoice prints them (excise included).  A contract group has no tariff
        price to offer.  Start: today when prices change, the first day of the
        table for a contract group's first contract.
        """
        defaults: dict[str, Any] = {
            CHANGE_TRADE_FEE: 0.0,
            CHANGE_VALID_FROM: date.today().isoformat(),
        }
        latest = next((c for c in reversed(self._changes) if c.get(CHANGE_ENERGY)), None)
        if latest is not None:
            defaults[CHANGE_TRADE_FEE] = latest.get(CHANGE_TRADE_FEE, 0.0)
            for zone in zones:
                defaults[_ENERGY_FIELD.format(zone)] = latest[CHANGE_ENERGY].get(str(zone))
        elif group.contract_energy:
            defaults[CHANGE_VALID_FROM] = group.earliest_date.isoformat()
        else:
            period = group.get_current_period() or group.periods[-1]
            for zone in zones:
                defaults[_ENERGY_FIELD.format(zone)] = round(period.zones[zone].energy + AKCYZA, 4)
        return defaults

    def _validate_start(self, valid_from: date) -> dict[str, str]:
        """A change may start neither before the table nor before the latest change.

        Starting on the latest change's own day replaces it, which is how a
        mistyped price is corrected.  An earlier day would rewrite a stretch
        already billed at other prices – clearing the history and entering it
        again covers that rare case.
        """
        if valid_from < TARIFFS[self._tariff_name].earliest_date:
            return {CHANGE_VALID_FROM: "before_tariff"}
        if self._changes and valid_from.isoformat() < self._changes[-1][CHANGE_VALID_FROM]:
            return {CHANGE_VALID_FROM: "before_last_change"}
        return {}

    def _add_change(self, change: dict[str, Any]) -> None:
        """Append a change, replacing the latest one when it starts the same day."""
        if self._changes and self._changes[-1][CHANGE_VALID_FROM] == change[CHANGE_VALID_FROM]:
            self._changes[-1] = change
        else:
            self._changes.append(change)

    def _placeholders(self) -> dict[str, str]:
        """Values the price forms' texts refer to."""
        return {
            "tariff": self._tariff_name,
            "earliest": TARIFFS[self._tariff_name].earliest_date.isoformat(),
            "last": self._changes[-1][CHANGE_VALID_FROM] if self._changes else "",
        }

    def _async_finish(self) -> ConfigFlowResult:
        """Create the entry, or update the one being reconfigured."""
        if self._reconfigure_entry is not None:
            data = {**self._reconfigure_entry.data, **self._details}
        else:
            data = {CONF_TARIFF: self._tariff_name, **self._details}
        data.pop(CONF_PRICE_CHANGES, None)
        if self._changes:
            data[CONF_PRICE_CHANGES] = self._changes

        if self._reconfigure_entry is not None:
            return self.async_update_reload_and_abort(self._reconfigure_entry, data=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=f"Enea Ceny {self._tariff_name}", data=data)


def _hint_placeholders(hint: MeterHint) -> dict[str, str]:
    """Return what a meter settles, for the description of a form."""
    return {
        "phases": _UNKNOWN if hint.phases is None else str(hint.phases),
        "billing_months": _UNKNOWN if hint.billing_months is None else str(hint.billing_months),
        "annual_kwh": _UNKNOWN if hint.annual_kwh is None else str(round(hint.annual_kwh)),
        "annual_until": (
            _UNKNOWN if hint.annual_kwh_until is None else hint.annual_kwh_until.isoformat()
        ),
    }


def _format_history(changes: list[dict[str, Any]]) -> str:
    """One line per price change, oldest first, for the reconfigure menu."""
    if not changes:
        return "URE"
    lines = []
    for change in changes:
        energy = change.get(CHANGE_ENERGY)
        if energy is None:
            lines.append(f"- {change[CHANGE_VALID_FROM]}: URE")
            continue
        prices = " / ".join(f"{price:.4f}" for price in energy.values())
        fee = change.get(CHANGE_TRADE_FEE, 0.0)
        lines.append(f"- {change[CHANGE_VALID_FROM]}: {prices} zł/kWh, {fee:.2f} zł/mies.")
    return "\n".join(lines)


def _details_from_input(user_input: dict[str, Any]) -> dict[str, int]:
    """Convert the selector strings of the details form into entry data."""
    return {
        CONF_PHASES: int(user_input[CONF_PHASES]),
        CONF_ANNUAL_KWH: int(user_input[CONF_ANNUAL_KWH]),
        CONF_BILLING_MONTHS: int(user_input[CONF_BILLING_MONTHS]),
    }


def _details_schema(
    default_phases: str = DEFAULT_PHASES,
    default_annual_kwh: str = DEFAULT_ANNUAL_KWH,
    default_billing_months: str = DEFAULT_BILLING_MONTHS,
) -> vol.Schema:
    """Build the installation details schema, optionally pre-filled with existing values."""
    return vol.Schema(
        {
            vol.Required(CONF_PHASES, default=default_phases): SelectSelector(
                SelectSelectorConfig(
                    options=PHASES_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_ANNUAL_KWH, default=default_annual_kwh): SelectSelector(
                SelectSelectorConfig(
                    options=ANNUAL_KWH_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_BILLING_MONTHS, default=default_billing_months): SelectSelector(
                SelectSelectorConfig(
                    options=BILLING_OPTIONS,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _contract_zones(group: TariffGroup) -> list[Zone]:
    """Zones the contract has to price: those of the period in force, else the last one."""
    period = group.get_current_period() or group.periods[-1]
    return list(period.zones)


def _required(key: str, current: dict[str, Any]) -> vol.Required:
    """A required field, pre-filled when there is something to pre-fill it with."""
    value = current.get(key)
    return vol.Required(key) if value is None else vol.Required(key, default=value)


def _contract_schema(zones: list[Zone], current: dict[str, Any]) -> vol.Schema:
    """Build the contract form: one energy price per zone, the trade fee and the start date."""
    energy = NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=5,
            step="any",
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="zł/kWh",
        )
    )
    fields: dict[Any, Any] = {
        _required(_ENERGY_FIELD.format(zone), current): energy for zone in zones
    }
    fields[_required(CHANGE_TRADE_FEE, current)] = NumberSelector(
        NumberSelectorConfig(
            min=0,
            max=500,
            step=0.01,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement="zł/mies.",
        )
    )
    fields[_required(CHANGE_VALID_FROM, current)] = DateSelector()
    return vol.Schema(fields)
