"""Test fixtures for the Enea Ceny integration.

The tariff tables are plain data structures and need nothing but the standard
library, so they are exercised directly.  The statistics injection reaches for
recorder helpers, but those are module-level names a test can replace, which
keeps the suite independent of a version-pinned Home Assistant test harness.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from homeassistant.util import dt as dt_util

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TEST_TIME_ZONE = "Europe/Warsaw"
"""The zone a real installation of this integration runs in.

It has to be a zone that observes daylight saving time: the hours written for
a day are derived from the zone, and in plain UTC every day is 24 hours long,
so a bare test process would never exercise the short and long days at all.
"""


@pytest.fixture(autouse=True)
def _local_time_zone() -> Any:
    """Pin the zone the integration treats as local."""
    previous = dt_util.DEFAULT_TIME_ZONE
    dt_util.set_default_time_zone(dt_util.get_time_zone(TEST_TIME_ZONE))
    yield
    dt_util.set_default_time_zone(previous)


@dataclass
class FakeConfigEntry:
    """Stand-in for a Home Assistant config entry."""

    domain: str
    data: dict[str, Any] = field(default_factory=dict)
    runtime_data: Any = None
    entry_id: str = "entry"


class _FakeConfigEntries:
    """Minimal hass.config_entries surface used by the integration."""

    def __init__(self, entries: list[FakeConfigEntry]) -> None:
        self._entries = entries
        self.reloaded: list[str] = []

    def async_entries(self, domain: str) -> list[FakeConfigEntry]:
        """Return the entries registered for a domain."""
        return [e for e in self._entries if e.domain == domain]

    async def async_reload(self, entry_id: str) -> None:
        """Record a reload request instead of performing one."""
        self.reloaded.append(entry_id)


class FakeHass:
    """Minimal hass object: config entries plus a task runner that records."""

    def __init__(self, entries: list[FakeConfigEntry] | None = None) -> None:
        self.config_entries = _FakeConfigEntries(entries or [])
        self.tasks: list[Any] = []

    def async_create_task(self, coro: Any) -> None:
        """Keep the coroutine so the test can await it deliberately."""
        self.tasks.append(coro)


@dataclass
class StatsStore:
    """Captures what the integration writes back to the recorder."""

    injected: list[tuple[Any, list[Any]]] = field(default_factory=list)

    def import_statistics(self, hass: Any, metadata: Any, rows: list[Any]) -> None:
        """Record an async_import_statistics call."""
        self.injected.append((metadata, rows))

    @property
    def starts(self) -> list[Any]:
        """Every injected row start, across all calls."""
        return [row["start"] for _meta, rows in self.injected for row in rows]


@pytest.fixture
def stats_store() -> StatsStore:
    """Return a fresh capture of recorder writes."""
    return StatsStore()
