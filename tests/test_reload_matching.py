"""Reloading enea meter entries once prices become available."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from conftest import FakeConfigEntry, FakeHass

from custom_components.enea_prices import _async_reload_matching_enea_entries


@dataclass
class FakeCoordinator:
    """Carries the tariff name the meter integration read from the portal."""

    _tariff_name: str | None


@dataclass
class FakeRuntime:
    """enea runtime data, reached by duck typing."""

    coordinator: Any


async def _reload_ids(hass: FakeHass, tariff_name: str) -> list[str]:
    """Run the helper and settle the tasks it scheduled."""
    _async_reload_matching_enea_entries(hass, tariff_name)
    for coro in hass.tasks:
        await coro
    return hass.config_entries.reloaded


def _hass(reported: str | None) -> FakeHass:
    return FakeHass(
        [
            FakeConfigEntry(
                domain="enea",
                entry_id="meter",
                runtime_data=FakeRuntime(coordinator=FakeCoordinator(reported)),
            )
        ]
    )


# The portal reports "G12W"; this entry stores the TARIFFS key "G12w".
@pytest.mark.parametrize("reported", ["G12W", "G12w"])
async def test_entry_reloaded_regardless_of_case(reported: str) -> None:
    """A meter on the same tariff is reloaded even if the case differs."""
    assert await _reload_ids(_hass(reported), "G12w") == ["meter"]


@pytest.mark.parametrize("reported", ["G11", "G12", "G12as", None])
async def test_other_tariffs_are_left_alone(reported: str | None) -> None:
    """Meters on a different tariff must not be reloaded."""
    assert await _reload_ids(_hass(reported), "G12w") == []


async def test_entry_without_runtime_data_is_skipped() -> None:
    """An entry that has not finished setting up yet is ignored."""
    hass = FakeHass([FakeConfigEntry(domain="enea", entry_id="meter")])

    assert await _reload_ids(hass, "G12w") == []
