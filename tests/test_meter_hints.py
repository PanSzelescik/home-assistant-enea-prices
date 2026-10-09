"""Pre-filling the forms with what the Enea Licznik integration knows about the meter.

The flow object is driven directly, against a hass that only holds config
entries: the enea entries carry a coordinator the way enea's runtime_data
does, read by duck typing.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from custom_components.enea_prices.config_flow import EneaPricesConfigFlow
from custom_components.enea_prices.const import DOMAIN
from custom_components.enea_prices.meter import annual_kwh_option, meter_hint

from conftest import FakeConfigEntry


class _Entries:
    """hass.config_entries: entries by domain, and the one a reconfigure is for."""

    def __init__(self, entries: list[FakeConfigEntry]) -> None:
        self._entries = entries

    def async_entries(self, domain: str, *args: Any, **kwargs: Any) -> list[FakeConfigEntry]:
        return [entry for entry in self._entries if entry.domain == domain]

    def async_get_known_entry(self, entry_id: str) -> FakeConfigEntry:
        return next(entry for entry in self._entries if entry.entry_id == entry_id)


def _meter(tariff: str, **detected: Any) -> FakeConfigEntry:
    """An enea entry whose coordinator reports a tariff and the detected facts."""
    coordinator = SimpleNamespace(
        tariff_name=tariff, detected_installation=SimpleNamespace(**detected)
    )
    return FakeConfigEntry(
        domain="enea", runtime_data=SimpleNamespace(coordinator=coordinator), entry_id=tariff
    )


def _old_meter(tariff: str) -> FakeConfigEntry:
    """An enea entry from before the facts were worked out."""
    coordinator = SimpleNamespace(_tariff_name=tariff)
    return FakeConfigEntry(domain="enea", runtime_data=SimpleNamespace(coordinator=coordinator))


ONE_PHASE = {
    "phases": 1,
    "billing_months": 2,
    "annual_kwh": 1530.4,
    "annual_kwh_until": date(2026, 8, 5),
}


def _flow(*entries: FakeConfigEntry, source: str = "user") -> EneaPricesConfigFlow:
    flow = EneaPricesConfigFlow()
    flow.hass = SimpleNamespace(config_entries=_Entries(list(entries)))  # type: ignore[assignment]
    flow.context = {"source": source}
    flow.flow_id = "flow"
    flow.handler = DOMAIN
    return flow


def _defaults(result: dict[str, Any]) -> dict[str, Any]:
    """The values a form opens with, by field name."""
    return {
        str(key): key.default()
        for key in result["data_schema"].schema
        if callable(getattr(key, "default", None))
    }


@pytest.mark.parametrize(
    ("kwh", "option"),
    [(0, "250"), (499.9, "250"), (500, "850"), (1200, "850"), (1201, "2000"), (2800, "2000"), (2801, "5000")],
)
def test_a_consumption_maps_to_the_option_of_its_capacity_bracket(kwh: float, option: str) -> None:
    assert annual_kwh_option(kwh) == option


async def test_the_meters_group_is_preselected() -> None:
    result = await _flow(_meter("G12w")).async_step_user()

    assert _defaults(result) == {"tariff": "G12w"}


async def test_a_portal_name_in_other_case_still_matches() -> None:
    result = await _flow(_old_meter("G12W")).async_step_user()

    assert _defaults(result) == {"tariff": "G12w"}


async def test_a_group_already_priced_is_not_preselected() -> None:
    priced = FakeConfigEntry(domain=DOMAIN, data={"tariff": "G12"})

    result = await _flow(_meter("G12"), priced).async_step_user()

    assert _defaults(result) == {}


async def test_the_details_are_prefilled_from_the_meter() -> None:
    flow = _flow(_meter("G12", **ONE_PHASE))
    flow._tariff_name = "G12"

    result = await flow.async_step_details()

    assert result["step_id"] == "details_from_meter"
    assert _defaults(result) == {"phases": "1", "annual_kwh": "2000", "billing_months": "2"}
    assert result["description_placeholders"] == {
        "phases": "1",
        "billing_months": "2",
        "annual_kwh": "1530",
        "annual_until": "2026-08-05",
    }


async def test_what_the_meter_leaves_open_keeps_its_default() -> None:
    flow = _flow(_meter("G12", phases=None, billing_months=None, annual_kwh=None, annual_kwh_until=None))
    flow._tariff_name = "G12"

    result = await flow.async_step_details()

    assert _defaults(result) == {"phases": "3", "annual_kwh": "2000", "billing_months": "1"}
    assert result["description_placeholders"]["phases"] == "—"


async def test_without_a_meter_the_form_is_the_plain_one() -> None:
    flow = _flow()
    flow._tariff_name = "G12"

    result = await flow.async_step_details()

    assert result["step_id"] == "details"


async def test_two_meters_in_one_group_offer_nothing() -> None:
    """They share the entry here and their facts may differ."""
    hass = SimpleNamespace(
        config_entries=_Entries([_meter("G11", **ONE_PHASE), _meter("G11", **ONE_PHASE)])
    )

    assert meter_hint(hass, "G11") is None  # type: ignore[arg-type]


async def test_reconfigure_keeps_the_settings_and_lists_the_meter() -> None:
    """Saving another change must not quietly take the meter's values."""
    entry = FakeConfigEntry(
        domain=DOMAIN,
        data={"tariff": "G12", "phases": 3, "annual_kwh": 3170, "billing_months": 1},
        entry_id="prices",
    )
    flow = _flow(_meter("G12", **ONE_PHASE), entry, source="reconfigure")
    flow.context["entry_id"] = "prices"

    result = await flow.async_step_reconfigure()

    assert result["step_id"] == "reconfigure_from_meter"
    # A measured consumption shows as the option of its bracket.
    assert _defaults(result) == {"phases": "3", "annual_kwh": "5000", "billing_months": "1"}
    assert result["description_placeholders"]["phases"] == "1"
