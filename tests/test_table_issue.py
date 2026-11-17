"""The tariff table runs out on a fixed date; Repairs says so before and after.

Past the table's last day the sensors report nothing and the costs the Enea
Licznik integration computes stop growing — silently, until now.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.enea_prices.const import (
    ISSUE_TARIFF_TABLE_ENDED,
    ISSUE_TARIFF_TABLE_ENDING,
    RELEASES_URL,
    TARIFF_TABLE_WARNING_DAYS,
)
from custom_components.enea_prices.issues import table_issue
from custom_components.enea_prices.tariffs import TARIFFS
from ha_instance import (  # noqa: F401 - clock, database, triggers and hass are fixtures
    at_local,
    clock,
    database,
    hass,
    make_entry,
    state,
    triggers,
)

G12 = TARIFFS["G12"]
LAST_DAY = max(period.valid_until for period in G12.periods)


@pytest.mark.parametrize("today,expected", [
    pytest.param(G12.periods[0].valid_from, None, id="first-day-of-the-table"),
    pytest.param(LAST_DAY - timedelta(days=TARIFF_TABLE_WARNING_DAYS + 1), None, id="day-before-the-warning"),
    pytest.param(LAST_DAY - timedelta(days=TARIFF_TABLE_WARNING_DAYS), ISSUE_TARIFF_TABLE_ENDING, id="warning-starts"),
    pytest.param(LAST_DAY, ISSUE_TARIFF_TABLE_ENDING, id="last-day"),
    pytest.param(LAST_DAY + timedelta(days=1), ISSUE_TARIFF_TABLE_ENDED, id="day-after"),
    pytest.param(LAST_DAY + timedelta(days=400), ISSUE_TARIFF_TABLE_ENDED, id="a-year-later"),
])
def test_issue_follows_the_distance_to_the_last_day(today, expected):
    """Nothing while the table reaches far, a warning near its end, another one past it."""
    assert table_issue(G12, today) == (expected, LAST_DAY)


def test_last_day_is_the_latest_of_all_periods_whatever_their_order():
    """The end of the table is the latest valid_until, not the last period listed."""
    shuffled = replace(G12, periods=list(reversed(G12.periods)))

    assert table_issue(shuffled, LAST_DAY + timedelta(days=1)) == (ISSUE_TARIFF_TABLE_ENDED, LAST_DAY)


def test_group_without_periods_raises_nothing():
    """A group with an empty table has no last day to speak of."""
    assert table_issue(replace(G12, periods=[]), date(2026, 6, 1)) == (None, None)


@pytest.mark.parametrize("name", sorted(TARIFFS))
def test_every_group_is_far_from_its_end_on_its_first_day(name):
    """The rule works for every group shipped, contract ones included."""
    group = TARIFFS[name]
    last = max(period.valid_until for period in group.periods)

    assert table_issue(group, group.periods[0].valid_from) == (None, last)
    assert table_issue(group, last + timedelta(days=1))[0] == ISSUE_TARIFF_TABLE_ENDED


def _issue(hass, key: str, entry):
    """Return the entry's issue with the given key, or None."""
    return ir.async_get(hass).async_get_issue("enea_prices", f"{key}_{entry.entry_id}")


async def _set_up(hass, **data):
    """Add an entry and wait for its setup."""
    entry = make_entry(**data)
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    return entry


async def test_no_issue_in_the_middle_of_the_table(hass):
    """In March 2026 the table has most of a year left."""
    entry = await _set_up(hass)

    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry) is None
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDED, entry) is None


async def test_setup_near_the_end_warns(hass, clock):
    """Set up two weeks before the last day: a warning naming the group and the day."""
    clock.now = at_local(LAST_DAY - timedelta(days=TARIFF_TABLE_WARNING_DAYS), 10)

    entry = await _set_up(hass)

    issue = _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert issue.is_fixable is False
    assert issue.is_persistent is False
    assert issue.learn_more_url == RELEASES_URL
    assert issue.translation_placeholders == {"tariff": "G12", "valid_until": LAST_DAY.isoformat()}
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDED, entry) is None


async def test_setup_past_the_end_says_the_table_ended(hass, clock):
    """Started on an old release after the table ran out: the sensors are empty, and it says why."""
    clock.now = at_local(LAST_DAY + timedelta(days=10), 10)

    entry = await _set_up(hass)

    assert state(hass, "G12", "current_price_total") == "unknown"
    issue = _issue(hass, ISSUE_TARIFF_TABLE_ENDED, entry)
    assert issue is not None
    assert issue.translation_placeholders == {"tariff": "G12", "valid_until": LAST_DAY.isoformat()}
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry) is None


async def test_midnight_raises_the_warning_and_then_replaces_it(hass, clock, triggers):
    """Running through the end of the table: nothing, then the warning, then "ended"."""
    clock.now = at_local(LAST_DAY - timedelta(days=TARIFF_TABLE_WARNING_DAYS + 1), 23, 59)
    entry = await _set_up(hass)
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry) is None

    clock.now = at_local(LAST_DAY - timedelta(days=TARIFF_TABLE_WARNING_DAYS))
    triggers.fire(0, clock.now)
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry) is not None
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDED, entry) is None

    clock.now = at_local(LAST_DAY + timedelta(days=1))
    triggers.fire(0, clock.now)
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry) is None
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDED, entry) is not None


async def test_zone_boundary_does_not_touch_the_issue(hass, clock, triggers):
    """Only midnight checks the table; a zone change during the day does not."""
    clock.now = at_local(LAST_DAY - timedelta(days=TARIFF_TABLE_WARNING_DAYS + 1), 12)
    entry = await _set_up(hass)

    clock.now = at_local(LAST_DAY + timedelta(days=1), 13)
    triggers.fire(13, clock.now)

    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDED, entry) is None


async def test_unloading_drops_the_issue(hass, clock):
    """An entry that is unloaded no longer prices anything, so it warns about nothing."""
    clock.now = at_local(LAST_DAY, 10)
    entry = await _set_up(hass)
    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)

    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry) is None


async def test_each_group_has_its_own_issue(hass, clock):
    """Two groups set up: one issue each, named after its group."""
    clock.now = at_local(LAST_DAY, 10)
    g12 = await _set_up(hass)
    g11 = await _set_up(hass, tariff="G11")

    placeholders = {
        _issue(hass, ISSUE_TARIFF_TABLE_ENDING, entry).translation_placeholders["tariff"]
        for entry in (g12, g11)
    }

    assert placeholders == {"G12", "G11"}


async def test_contract_prices_do_not_extend_the_table(hass, clock):
    """An entry with contract prices still takes distribution from the table, which ends."""
    clock.now = at_local(LAST_DAY + timedelta(days=1), 10)

    entry = await _set_up(hass, price_changes=[
        {"valid_from": "2026-01-01", "energy": {"day": 0.62, "night": 0.41}, "trade_fee": 9.9},
    ])

    assert _issue(hass, ISSUE_TARIFF_TABLE_ENDED, entry) is not None


@pytest.mark.parametrize("language", ["en", "pl"])
def test_issue_texts_exist_and_name_the_group_and_the_day(language):
    """Both issues have a title and a description using both placeholders."""
    import json  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    path = (
        Path(__file__).parent.parent
        / "custom_components" / "enea_prices" / "translations" / f"{language}.json"
    )
    issues = json.loads(path.read_text(encoding="utf-8"))["issues"]

    assert set(issues) == {ISSUE_TARIFF_TABLE_ENDING, ISSUE_TARIFF_TABLE_ENDED}
    for texts in issues.values():
        assert "{tariff}" in texts["title"] and "{valid_until}" in texts["title"]
        assert "{tariff}" in texts["description"] and "{valid_until}" in texts["description"]
