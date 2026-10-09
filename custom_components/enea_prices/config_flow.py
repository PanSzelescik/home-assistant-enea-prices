"""Config flow for Enea Ceny integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ANNUAL_KWH_OPTIONS,
    BILLING_OPTIONS,
    CONF_ANNUAL_KWH,
    CONF_BILLING_MONTHS,
    CONF_PHASES,
    CONF_TARIFF,
    DEFAULT_ANNUAL_KWH,
    DEFAULT_BILLING_MONTHS,
    DEFAULT_PHASES,
    DOMAIN,
    PHASES_OPTIONS,
)
from .meter import MeterHint, annual_kwh_option, form_defaults, meter_hint, meter_hints
from .tariffs import TARIFFS

# Shown for a fact the meter does not settle.
_UNKNOWN = "—"


class EneaPricesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Enea Ceny."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._tariff_name: str = ""

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

        With an Enea meter in the chosen group, the facts it settles pre-fill
        the form, under a description that lists them.
        """
        if user_input is not None:
            await self.async_set_unique_id(self._tariff_name)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Enea Ceny {self._tariff_name}",
                data={
                    CONF_TARIFF: self._tariff_name,
                    CONF_PHASES: int(user_input[CONF_PHASES]),
                    CONF_ANNUAL_KWH: int(user_input[CONF_ANNUAL_KWH]),
                    CONF_BILLING_MONTHS: int(user_input[CONF_BILLING_MONTHS]),
                },
            )

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
        """Allow user to change installation details without removing the integration.

        The form keeps the entry's settings; what an Enea meter settles is only
        listed in the description, so that saving another change cannot
        quietly replace a setting the user chose.
        """
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    CONF_PHASES: int(user_input[CONF_PHASES]),
                    CONF_ANNUAL_KWH: int(user_input[CONF_ANNUAL_KWH]),
                    CONF_BILLING_MONTHS: int(user_input[CONF_BILLING_MONTHS]),
                },
            )

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
