"""Price statistics injection for the Enea Ceny integration.

Injects hourly mean statistics for static price sensors so that the Energy Dashboard
can calculate historical costs using "Use an entity with current price".

Price sensors have state_class=MEASUREMENT (required by async_import_statistics with
source="recorder") and statistics are injected manually so HA has historical price data
for cost calculations.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from functools import partial

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN, UNIT_PRICE, ZONE_PRICE_ATTRS
from .tariffs import TariffGroup

_LOGGER = logging.getLogger(__name__)


async def async_inject_price_statistics(hass: HomeAssistant, group: TariffGroup) -> None:
    """Inject hourly mean statistics for all static price sensors of this tariff group.

    Covers every hour from the tariff period's valid_from up to yesterday.
    Hours already stored with the price the table gives them are skipped.
    """
    registry = er.async_get(hass)
    today = dt_util.now().date()
    yesterday = today - timedelta(days=1)

    # Every period of one sensor goes in one import: what the recorder already
    # owns has to be read before anything is written, or the first period's
    # own rows would pass for the recorder's and hide every later period.
    spans: dict[str, list[tuple[float, date, date]]] = {}
    for period in group.periods:
        if period.valid_from > yesterday:
            continue  # future period, nothing to inject yet
        period_end = min(period.valid_until, yesterday)

        for zone, pricing in period.zones.items():
            for key_suffix, attr in ZONE_PRICE_ATTRS:
                unique_id = f"enea_prices-{group.name}-{zone}_{key_suffix}"
                entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
                if entity_id is None:
                    continue
                spans.setdefault(entity_id, []).append(
                    (getattr(pricing, attr), period.valid_from, period_end)
                )

    for entity_id, sensor_spans in spans.items():
        await _inject_sensor_statistics(hass, entity_id, sensor_spans)


async def _inject_sensor_statistics(
    hass: HomeAssistant,
    entity_id: str,
    spans: list[tuple[float, date, date]],
) -> None:
    """Inject hourly mean statistics for one price sensor, backfilling gaps.

    spans are the sensor's (price, first day, last day) in every period it
    has a price in, oldest first.

    Checks which hours are actually missing across the whole period window
    instead of looking only at the newest stored entry, so an older tariff
    period added later is filled in as well.

    An hour stored with a different price is written again too: importing
    over an existing hour replaces its mean.  That is what makes contract
    prices entered with a past start date, a correction to the table, or a
    return from contract to tariff prices reach the history the Energy
    Dashboard prices consumption with.  Prices are compared at the 4 decimal
    places the sensors report, because the hours the recorder compiles itself
    hold the rounded state, not the exact sum the table computes.

    Only hours strictly before the newest stored statistic are written.  The
    price sensors have a state class, so the recorder compiles their hourly
    statistics itself, and after a restart it catches up on the hour the
    shutdown cut short.  Importing those hours here races the recorder's own
    blind insert into the same unique key, and losing that race rolls back
    the recorder's whole catch-up batch, for every entity in the install.
    Hours the sensor was dead for become gaps behind the recorder's newest
    row once it writes again, and the next run fills them then.

    Each span runs from local midnight on its first day to local midnight
    after its last, and the hours inside it are stepped through in UTC, so the
    days the clocks change get the 23 or 25 hours they really have.
    """
    windows = [
        (
            value,
            dt_util.start_of_local_day(first),
            dt_util.start_of_local_day(last + timedelta(days=1)),
        )
        for value, first, last in spans
    ]
    windows = [(value, start, end) for value, start, end in windows if start < end]
    if not windows:
        return

    existing = await get_instance(hass).async_add_executor_job(
        partial(
            statistics_during_period,
            hass,
            windows[0][1],
            windows[-1][2],
            {entity_id},
            "hour",
            None,
            {"mean"},
        )
    )
    stored_mean = {
        int(row["start"]): row.get("mean")
        for row in existing.get(entity_id, [])
        if row.get("start") is not None
    }

    newest = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, entity_id, True, {"mean"}
    )
    rows = newest.get(entity_id)
    recorder_owns_after = (
        rows[0]["start"] if rows and rows[0].get("start") is not None else None
    )

    # One StatisticData entry per missing or mispriced hour before the newest one.
    stats_data: list[StatisticData] = []
    for value, start_dt, end_dt in windows:
        expected = round(value, 4)
        current = start_dt.astimezone(dt_util.UTC)
        limit = end_dt.astimezone(dt_util.UTC)
        while current < limit:
            if recorder_owns_after is not None and current.timestamp() >= recorder_owns_after:
                break
            mean = stored_mean.get(int(current.timestamp()))
            if mean is None or round(mean, 4) != expected:
                stats_data.append(StatisticData(start=current, mean=value))
            current += timedelta(hours=1)

    if not stats_data:
        return

    metadata = StatisticMetaData(
        has_mean=True,
        mean_type=StatisticMeanType.ARITHMETIC,
        has_sum=False,
        name=None,
        source="recorder",
        statistic_id=entity_id,
        unit_of_measurement=UNIT_PRICE,
        unit_class=None,
    )
    async_import_statistics(hass, metadata, stats_data)
    _LOGGER.debug(
        "Injected %d price stats for %s (%s → %s)",
        len(stats_data), entity_id, spans[0][1], spans[-1][2],
    )
