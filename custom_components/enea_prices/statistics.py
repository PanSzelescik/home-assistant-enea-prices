"""Price statistics injection for the Enea Ceny integration.

Injects hourly mean statistics for static price sensors so that the Energy Dashboard
can calculate historical costs using "Use an entity with current price".

Price sensors have state_class=MEASUREMENT (required by async_import_statistics with
source="recorder") and statistics are injected manually so HA has historical price data
for cost calculations.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import async_import_statistics, get_last_statistics
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import DOMAIN, UNIT_PRICE, ZONE_PRICE_ATTRS
from .tariffs import TariffGroup

_LOGGER = logging.getLogger(__name__)


async def async_inject_price_statistics(hass: HomeAssistant, group: TariffGroup) -> None:
    """Inject hourly mean statistics for all static price sensors of this tariff group.

    Covers every hour from the tariff period's valid_from up to yesterday.
    Uses get_last_statistics to avoid re-injecting already-present data.
    """
    registry = er.async_get(hass)
    today = dt_util.now().date()
    yesterday = today - timedelta(days=1)

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

                price_value: float = getattr(pricing, attr)
                await _inject_sensor_statistics(
                    hass, entity_id, price_value, period.valid_from, period_end
                )


async def _inject_sensor_statistics(
    hass: HomeAssistant,
    entity_id: str,
    value: float,
    valid_from: date,
    end_date: date,
) -> None:
    """Inject hourly mean statistics for a single price sensor with a constant value."""
    # Find the last already-injected statistic to avoid duplicates.
    last_stats = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, entity_id, True, {"mean"}
    )

    if last_stats.get(entity_id):
        last_ts = last_stats[entity_id][0].get("start")
        if last_ts is not None:
            last_date = (
                dt_util.utc_from_timestamp(last_ts)
                .astimezone(dt_util.DEFAULT_TIME_ZONE)
                .date()
            )
            if last_date >= end_date:
                return  # Already up to date
            start_date = last_date + timedelta(days=1)
        else:
            start_date = valid_from
    else:
        start_date = valid_from

    if start_date > end_date:
        return

    # Generate one StatisticData entry per hour for the missing range.
    stats_data: list[StatisticData] = []
    current = datetime.combine(start_date, time(0, 0), tzinfo=dt_util.DEFAULT_TIME_ZONE)
    end_dt = datetime.combine(end_date, time(23, 0), tzinfo=dt_util.DEFAULT_TIME_ZONE)
    while current <= end_dt:
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
        "Injected %d price stats for %s (%.4f %s, %s → %s)",
        len(stats_data), entity_id, value, UNIT_PRICE, start_date, end_date,
    )
