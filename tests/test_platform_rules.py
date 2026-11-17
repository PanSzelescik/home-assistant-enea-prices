"""What Home Assistant and HACS expect of the platform, the manifest and hacs.json."""
from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from homeassistant.const import EVENT_RECORDER_HOURLY_STATISTICS_GENERATED
from homeassistant.helpers import entity_registry as er

from custom_components import enea_prices
from custom_components.enea_prices import sensor
from custom_components.enea_prices.tariffs import AKCYZA, TARIFFS, ZoneScheduleEntry
from ha_instance import (  # noqa: F401 - clock, database, triggers and hass are fixtures
    clock,
    database,
    hass,
    make_entry,
    triggers,
)

ROOT = Path(__file__).parent.parent
INTEGRATION = ROOT / "custom_components" / "enea_prices"


async def _set_up(hass, **data):
    """Add an entry and wait for its setup and statistics import."""
    entry = make_entry(**data)
    await hass.config_entries.async_add(entry)
    await hass.async_block_till_done()
    return entry


def test_platform_declares_parallel_updates():
    """Sensors computed from the table are not throttled: PARALLEL_UPDATES is 0."""
    assert sensor.PARALLEL_UPDATES == 0


async def test_no_sensor_is_polled(hass):
    """Every sensor has its state pushed; Home Assistant arms no polling timer.

    Without should_poll set to False each sensor's state was recomputed and
    written every 30 seconds, although it only changes a few times a day.
    """
    entry = await _set_up(hass)

    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    assert len(entities) > 15
    [platform] = hass.data["entity_platform"]["enea_prices"]
    assert [e.entity_id for e in platform.entities.values() if e.should_poll] == []
    assert platform._async_polling_timer is None


async def test_states_still_follow_the_clock_without_polling(hass, clock, triggers):
    """The zone sensor changes at the boundary because the platform writes it then."""
    from ha_instance import TODAY, at_local, state  # noqa: PLC0415

    await _set_up(hass)
    assert state(hass, "G12", "current_zone") == "day"

    clock.now = at_local(TODAY, 13)
    assert state(hass, "G12", "current_zone") == "day"  # nothing wrote it yet
    triggers.fire(13, clock.now)

    assert state(hass, "G12", "current_zone") == "night"


@pytest.mark.parametrize("name", sorted(n for n, g in TARIFFS.items() if not g.contract_energy))
async def test_boundaries_of_every_period_are_scheduled(platform, name):
    """The zone callbacks cover the boundaries of all the group's periods, and midnight."""
    done = await platform(name)

    expected = {hour for period in TARIFFS[name].periods for hour in period.get_zone_change_hours()}
    assert set(done.at_hour) == expected | {0}


async def test_later_period_with_another_schedule_has_its_boundaries_covered(platform, monkeypatch):
    """A period that starts later with other zone hours is not left without a callback.

    The hours used to come from the period in force at setup alone; nothing
    polls the sensors, so the zone sensor would then miss the new boundaries
    until the entry was reloaded.
    """
    group = TARIFFS["G12"]
    last = group.periods[-1]
    night = next(zone for zone in last.zones if str(zone) != "day")
    moved = replace(
        last,
        schedule=[
            ZoneScheduleEntry(zone=night, start_hour=0, end_hour=7),
            ZoneScheduleEntry(zone=next(iter(last.zones)), start_hour=7, end_hour=23),
            ZoneScheduleEntry(zone=night, start_hour=23, end_hour=24),
        ],
    )
    synthetic = replace(group, periods=[*group.periods[:-1], moved])
    monkeypatch.setattr(enea_prices, "build_tariff", lambda *args: synthetic)

    done = await platform("G12")

    assert {7, 23} <= set(done.at_hour)
    for period in group.periods[:-1]:
        assert set(period.get_zone_change_hours()) <= set(done.at_hour)


async def test_midnight_checks_the_table_issue(platform):
    """The midnight callback is where the tariff table issue is looked at again."""
    done = await platform("G12")
    assert done.issue_checks == []
    for entity in done.entities:  # not added to a Home Assistant here
        entity.async_write_ha_state = lambda: None

    for action in done.at_hour[0]:
        action(None)

    assert done.issue_checks == [done.entry.entry_id]


async def test_statistics_runs_share_what_they_have_checked(hass, database):
    """Both runs after a start, and a reload, use one memory kept in hass.data."""
    entry = await _set_up(hass)
    verified = hass.data[sensor.DATA_VERIFIED_STATISTICS]
    assert verified, "the first run remembers how far it got"
    first = dict(verified)

    hass.bus.async_fire(EVENT_RECORDER_HOURLY_STATISTICS_GENERATED)
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.data[sensor.DATA_VERIFIED_STATISTICS] is verified
    assert set(verified) == set(first)


async def test_runtime_data_carries_the_excise(hass):
    """The enea integration reads the excise off the entry instead of sys.modules."""
    entry = await _set_up(hass)

    assert entry.runtime_data.akcyza == AKCYZA
    assert AKCYZA > 0


def test_manifest_requires_the_recorder_and_says_what_it_is():
    """The statistics are written unconditionally, so the recorder is a dependency."""
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["dependencies"] == ["recorder"]
    assert "after_dependencies" not in manifest
    assert manifest["integration_type"] == "service"
    assert manifest["iot_class"] == "calculated"
    # hassfest wants domain and name first, then the keys in alphabetical order.
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_minimum_is_the_version_the_tests_run_against():
    """hacs.json must not promise a Home Assistant older than the one that is tested.

    It said 2025.3.0 while the code imports names that version does not have
    (StatisticMeanType), so HACS offered the integration to installations it
    could not even be imported on.
    """
    declared = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))["homeassistant"]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    tested = re.search(r'"homeassistant>=([0-9.]+)"', pyproject)

    assert tested is not None
    assert declared == tested.group(1)
