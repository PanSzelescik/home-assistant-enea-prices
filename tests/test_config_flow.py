"""The price steps of the config flow: tariff prices, or a history of contract prices.

The flow object is driven directly; the steps under test only build forms and
results, so they need no running Home Assistant.  The installation details
step before them is left out, as it is unchanged and touches the entry registry.
"""
from __future__ import annotations

import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.data_entry_flow import AbortFlow

from custom_components.enea_prices.config_flow import EneaPricesConfigFlow
from custom_components.enea_prices.const import (
    CONF_ANNUAL_KWH,
    CONF_BILLING_MONTHS,
    CONF_PHASES,
    CONF_PRICE_CHANGES,
    CONF_TARIFF,
    DOMAIN,
)

from conftest import FakeConfigEntry

DETAILS = {CONF_PHASES: 1, CONF_ANNUAL_KWH: 850, CONF_BILLING_MONTHS: 2}

SEZON_INPUT = {
    "energy_recommended_use": 0.35,
    "energy_remaining": 0.59,
    "trade_fee": 9.82,
    "valid_from": "2026-01-01",
}

G12_OFFER = {
    "valid_from": "2026-03-01",
    "energy": {"day": 0.6, "night": 0.3},
    "trade_fee": 9.82,
}


def _flow(tariff: str) -> EneaPricesConfigFlow:
    """A new-entry flow that has just been through the details step."""
    flow = EneaPricesConfigFlow()
    flow.context = {"source": "user"}
    flow.flow_id = "flow"
    flow.handler = DOMAIN
    flow._tariff_name = tariff
    flow._details = dict(DETAILS)
    return flow


def _defaults(result: dict[str, Any]) -> dict[str, Any]:
    """The values a form opens with, by field name."""
    return {
        str(key): key.default()
        for key in result["data_schema"].schema
        if callable(getattr(key, "default", None))
    }


def _fields(result: dict[str, Any]) -> list[str]:
    return [str(key) for key in result["data_schema"].schema]


async def test_a_tariff_group_offers_the_choice() -> None:
    result = await _flow("G12")._async_step_prices()

    assert result["type"] == "menu"
    assert list(result["menu_options"]) == ["tariff_prices", "contract"]


async def test_tariff_prices_store_no_history() -> None:
    result = await _flow("G12").async_step_tariff_prices()

    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_TARIFF: "G12", **DETAILS}


async def test_a_contract_group_goes_straight_to_the_contract_form() -> None:
    """G12sezON has no tariff price to choose, so there is no menu."""
    result = await _flow("G12sezON")._async_step_prices()

    assert result["type"] == "form"
    assert result["step_id"] == "contract"
    assert _fields(result) == [
        "energy_recommended_use",
        "energy_remaining",
        "trade_fee",
        "valid_from",
    ]


async def test_a_contract_group_starts_its_prices_with_its_table() -> None:
    """No energy price is suggested: any number there would be made up."""
    defaults = _defaults(await _flow("G12sezON").async_step_contract())

    assert defaults["valid_from"] == "2026-01-01"
    assert "energy_recommended_use" not in defaults


async def test_the_three_zones_of_g13active_are_asked_for() -> None:
    result = await _flow("G13active").async_step_contract()

    assert [f for f in _fields(result) if f.startswith("energy_")] == [
        "energy_recommended_use",
        "energy_remaining",
        "energy_recommended_limit",
    ]


async def test_a_tariff_group_is_prefilled_with_invoice_prices() -> None:
    """The tariff's 2026 G12 prices, excise included, as the invoice prints them."""
    defaults = _defaults(await _flow("G12").async_step_contract())

    assert (defaults["energy_day"], defaults["energy_night"]) == (0.5829, 0.3419)
    assert defaults["trade_fee"] == 0.0


async def test_the_contract_is_stored_as_typed() -> None:
    """Prices stay as copied off the invoice; the excise comes off at setup."""
    result = await _flow("G12sezON").async_step_contract(dict(SEZON_INPUT))

    assert result["type"] == "create_entry"
    assert result["data"][CONF_PRICE_CHANGES] == [
        {
            "valid_from": "2026-01-01",
            "energy": {"recommended_use": 0.35, "remaining": 0.59},
            "trade_fee": 9.82,
        }
    ]


class _Registry:
    """The hass surface a new entry's unique ID is checked against."""

    def __init__(self, entries: list[str], flows: list[str]) -> None:
        self.entries = entries
        """Unique IDs of the entries already configured."""
        self.flows = flows
        """Unique IDs of other flows still in progress."""
        self.config_entries = self
        self.flow = self

    def async_progress_by_handler(self, handler: str, **kwargs: Any) -> list[dict[str, Any]]:
        wanted = kwargs["match_context"]["unique_id"]
        return [
            {"flow_id": f"other-{n}", "context": {"source": "user", "unique_id": uid}}
            for n, uid in enumerate(self.flows)
            if uid == wanted
        ]

    def async_entry_for_domain_unique_id(self, domain: str, unique_id: str) -> Any:
        return SimpleNamespace(source="user") if unique_id in self.entries else None


def _registered_flow(tariff: str, *, entries: list[str], flows: list[str]) -> EneaPricesConfigFlow:
    flow = EneaPricesConfigFlow()
    flow.context = {"source": "user"}
    flow.flow_id = "flow"
    flow.handler = DOMAIN
    flow.hass = _Registry(entries, flows)
    flow._tariff_name = tariff
    return flow


async def test_an_abandoned_flow_does_not_block_a_new_one() -> None:
    """A flow left on the prices form lives until restart; starting again must work."""
    flow = _registered_flow("G12sezON", entries=[], flows=["G12sezON"])

    result = await flow.async_step_details({key: str(value) for key, value in DETAILS.items()})

    assert result["type"] == "form"
    assert result["step_id"] == "contract"


async def test_a_group_already_added_is_refused_at_the_details_step() -> None:
    flow = _registered_flow("G12", entries=["G12"], flows=[])

    with pytest.raises(AbortFlow, match="already_configured"):
        await flow.async_step_details({key: str(value) for key, value in DETAILS.items()})


async def test_of_two_parallel_flows_only_the_first_creates_the_entry() -> None:
    """Both got past the details step; the other one has finished since."""
    flow = _registered_flow("G12sezON", entries=[], flows=[])
    await flow.async_step_details({key: str(value) for key, value in DETAILS.items()})
    flow.hass.entries.append("G12sezON")

    with pytest.raises(AbortFlow, match="already_configured"):
        await flow.async_step_contract(dict(SEZON_INPUT))


async def test_a_start_before_the_table_is_refused() -> None:
    result = await _flow("G12sezON").async_step_contract(
        {**SEZON_INPUT, "valid_from": "2025-12-31"}
    )

    assert result["type"] == "form"
    assert result["errors"] == {"valid_from": "before_tariff"}


@pytest.fixture
def reconfigured(monkeypatch: pytest.MonkeyPatch):
    """A reconfigure flow past its details step, capturing the data it would save."""

    async def _make(data: dict[str, Any]) -> tuple[EneaPricesConfigFlow, dict[str, Any], dict]:
        flow = EneaPricesConfigFlow()
        flow.context = {"source": "reconfigure"}
        flow.flow_id = "flow"
        flow.handler = DOMAIN
        entry = FakeConfigEntry(domain=DOMAIN, data=data)
        monkeypatch.setattr(flow, "_get_reconfigure_entry", lambda: entry)
        saved: dict[str, Any] = {}

        def _update(entry: Any, *, data: dict[str, Any]) -> dict[str, Any]:
            saved.update(data)
            return {"type": "abort", "reason": "reconfigure_successful"}

        monkeypatch.setattr(flow, "async_update_reload_and_abort", _update)
        menu = await flow.async_step_reconfigure(
            {key: str(value) for key, value in DETAILS.items()}
        )
        return flow, saved, menu

    return _make


async def test_reconfigure_offers_to_change_prices_from_a_date(reconfigured) -> None:
    _, _, menu = await reconfigured({CONF_TARIFF: "G12", **DETAILS, CONF_PRICE_CHANGES: [G12_OFFER]})

    assert menu["step_id"] == "change_prices"
    assert list(menu["menu_options"]) == ["keep_prices", "contract", "tariff_prices", "clear_prices"]
    assert menu["description_placeholders"]["history"] == (
        "- 2026-03-01: 0.6000 / 0.3000 zł/kWh, 9.82 zł/mies."
    )


async def test_a_contract_group_cannot_go_back_to_a_tariff_it_does_not_have(reconfigured) -> None:
    sezon = {"valid_from": "2026-01-01", "energy": {"recommended_use": 0.35, "remaining": 0.59}, "trade_fee": 9.82}
    _, _, menu = await reconfigured({CONF_TARIFF: "G12sezON", **DETAILS, CONF_PRICE_CHANGES: [sezon]})

    assert list(menu["menu_options"]) == ["keep_prices", "contract"]


async def test_keeping_prices_keeps_the_history(reconfigured) -> None:
    flow, saved, _ = await reconfigured({CONF_TARIFF: "G12", **DETAILS, CONF_PRICE_CHANGES: [G12_OFFER]})

    await flow.async_step_keep_prices()

    assert saved[CONF_PRICE_CHANGES] == [G12_OFFER]


async def test_new_prices_are_added_after_the_old_ones(reconfigured) -> None:
    """A renewed offer is a second change; the first keeps the months it priced."""
    flow, saved, _ = await reconfigured({CONF_TARIFF: "G12", **DETAILS, CONF_PRICE_CHANGES: [G12_OFFER]})

    defaults = _defaults(await flow.async_step_contract())
    assert (defaults["energy_day"], defaults["trade_fee"]) == (0.6, 9.82)
    assert defaults["valid_from"] == datetime.date.today().isoformat()

    await flow.async_step_contract(
        {"energy_day": 0.65, "energy_night": 0.32, "trade_fee": 15.94, "valid_from": "2026-09-01"}
    )

    assert saved[CONF_PRICE_CHANGES] == [
        G12_OFFER,
        {"valid_from": "2026-09-01", "energy": {"day": 0.65, "night": 0.32}, "trade_fee": 15.94},
    ]


async def test_the_same_start_corrects_the_latest_change(reconfigured) -> None:
    """A typo is fixed by entering the prices again from the same day."""
    flow, saved, _ = await reconfigured({CONF_TARIFF: "G12", **DETAILS, CONF_PRICE_CHANGES: [G12_OFFER]})

    await flow.async_step_contract(
        {"energy_day": 0.61, "energy_night": 0.3, "trade_fee": 9.82, "valid_from": "2026-03-01"}
    )

    assert [c["energy"]["day"] for c in saved[CONF_PRICE_CHANGES]] == [0.61]


async def test_a_change_before_the_latest_one_is_refused(reconfigured) -> None:
    flow, saved, _ = await reconfigured({CONF_TARIFF: "G12", **DETAILS, CONF_PRICE_CHANGES: [G12_OFFER]})

    result = await flow.async_step_contract(
        {"energy_day": 0.65, "energy_night": 0.32, "trade_fee": 0.0, "valid_from": "2026-02-01"}
    )

    assert result["errors"] == {"valid_from": "before_last_change"}
    assert saved == {}


async def test_going_back_to_the_tariff_is_a_change_too(reconfigured) -> None:
    flow, saved, _ = await reconfigured({CONF_TARIFF: "G12", **DETAILS, CONF_PRICE_CHANGES: [G12_OFFER]})

    form = await flow.async_step_tariff_prices()
    assert form["step_id"] == "tariff_from"

    await flow.async_step_tariff_from({"valid_from": "2026-09-01"})

    assert saved[CONF_PRICE_CHANGES] == [G12_OFFER, {"valid_from": "2026-09-01"}]


async def test_clearing_the_history_returns_to_the_tariff_everywhere(reconfigured) -> None:
    flow, saved, _ = await reconfigured({CONF_TARIFF: "G12", **DETAILS, CONF_PRICE_CHANGES: [G12_OFFER]})

    await flow.async_step_clear_prices()

    assert CONF_PRICE_CHANGES not in saved
    assert saved[CONF_TARIFF] == "G12"
    assert saved[CONF_BILLING_MONTHS] == 2
