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
from .tariffs import TARIFFS


class EneaPricesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Enea Ceny."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._tariff_name: str = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: select tariff group."""
        if user_input is not None:
            self._tariff_name = user_input[CONF_TARIFF]
            return await self.async_step_details()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TARIFF): SelectSelector(
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
        """Step 2: installation details for monthly fee calculation."""
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

        return self.async_show_form(
            step_id="details",
            data_schema=_details_schema(),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow user to change installation details without removing the integration."""
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

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_details_schema(
                default_phases=str(entry.data[CONF_PHASES]),
                default_annual_kwh=str(entry.data[CONF_ANNUAL_KWH]),
                default_billing_months=str(entry.data[CONF_BILLING_MONTHS]),
            ),
        )


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
