"""Test fixtures for the Enea Ceny integration.

The tariff tables are plain data structures and need nothing but the standard
library, so they are exercised directly.  The statistics injection reaches for
recorder helpers, but those are module-level names a test can replace, which
keeps the suite independent of a version-pinned Home Assistant test harness.
"""
from __future__ import annotations

import datetime
import sys
from collections.abc import Callable
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
        self.unloaded: list[str] = []

    def async_entries(self, domain: str) -> list[FakeConfigEntry]:
        """Return the entries registered for a domain."""
        return [e for e in self._entries if e.domain == domain]

    async def async_reload(self, entry_id: str) -> None:
        """Record a reload request instead of performing one."""
        self.reloaded.append(entry_id)

    async def async_unload_platforms(
        self, entry: FakeConfigEntry, platforms: list[Any]
    ) -> bool:
        """Record an unload request instead of performing one."""
        self.unloaded.append(entry.entry_id)
        return True


class FakeBus:
    """Minimal hass.bus surface: one-shot listeners a test can fire.

    Home Assistant only logs an exception when asked to remove a listener that
    is no longer registered, which a test would not notice.  This raises
    instead, so removing a listener twice fails the test that does it.
    """

    def __init__(self) -> None:
        self.listeners: dict[str, list[Any]] = {}

    def async_listen_once(self, event_type: str, listener: Any) -> Callable[[], None]:
        """Register a listener that is dropped as soon as it is fired."""
        self.listeners.setdefault(event_type, []).append(listener)

        def _remove() -> None:
            registered = self.listeners.get(event_type, [])
            if listener not in registered:
                raise LookupError(f"no listener registered for {event_type}")
            registered.remove(listener)

        return _remove

    def async_fire(self, event_type: str) -> None:
        """Fire the event, dropping every one-shot listener it reaches."""
        for listener in self.listeners.pop(event_type, []):
            listener(object())


class FakeHass:
    """Minimal hass object: config entries, an event bus and a task recorder."""

    def __init__(self, entries: list[FakeConfigEntry] | None = None) -> None:
        self.config_entries = _FakeConfigEntries(entries or [])
        self.bus = FakeBus()
        self.tasks: list[Any] = []

    def async_create_task(self, coro: Any) -> None:
        """Keep the coroutine so the test can await it deliberately."""
        self.tasks.append(coro)

    async def async_settle(self) -> None:
        """Await everything scheduled so far, as the event loop would."""
        pending, self.tasks = self.tasks, []
        for coro in pending:
            await coro


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


class _Recorder:
    """Answers recorder queries from a set of stored hour starts.

    late, when given, is a row committed between the two queries the code
    makes: the window read does not see it, the newest-entry read does.
    """

    def __init__(
        self,
        stored: list[datetime.datetime],
        late: datetime.datetime | None = None,
    ) -> None:
        self.stored = sorted(stored)
        self.late = late

    async def async_add_executor_job(self, target: Any, *args: Any) -> Any:
        """Run the query inline."""
        return target(*args)

    def last(self, hass: Any, count: int, sid: str, convert: bool, types: set) -> dict:
        """Newest entry first, mirroring get_last_statistics."""
        newest = self.late or (self.stored[-1] if self.stored else None)
        if newest is None:
            return {}
        return {sid: [{"start": newest.timestamp()}]}

    def during(self, hass: Any, start: Any, end: Any, ids: set, *rest: Any) -> dict:
        """Ascending entries inside [start, end)."""
        sid = next(iter(ids))
        rows = [{"start": dt.timestamp()} for dt in self.stored if start <= dt < end]
        return {sid: rows} if rows else {}


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, stats_store: StatsStore):
    """Wire the statistics module to an in-memory recorder and capture writes."""
    # Imported here so it is resolved after the path above has been set up.
    from custom_components.enea_prices import statistics as price_stats  # noqa: PLC0415

    def _wire(
        stored: list[datetime.datetime],
        late: datetime.datetime | None = None,
    ) -> StatsStore:
        rec = _Recorder(stored, late)
        monkeypatch.setattr(price_stats, "get_instance", lambda hass: rec)
        monkeypatch.setattr(price_stats, "statistics_during_period", rec.during, raising=False)
        # Kept wired so the pre-fix code path runs too and the regression test
        # fails for the defect itself, not for a missing stub.
        monkeypatch.setattr(price_stats, "get_last_statistics", rec.last, raising=False)
        monkeypatch.setattr(
            price_stats, "async_import_statistics", stats_store.import_statistics
        )
        return stats_store

    return _wire
