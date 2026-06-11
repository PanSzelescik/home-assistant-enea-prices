"""Sensor entities for Enea Ceny integration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from . import EneaPricesConfigEntry
from .const import DOMAIN, UNIT_MONTHLY, UNIT_PRICE
from .statistics import async_inject_price_statistics
from .tariffs import MonthlyFees, TariffGroup, TariffPeriod, Zone


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EneaPricesConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Enea Ceny sensors."""
    group = entry.runtime_data.tariff
    phases = entry.runtime_data.phases
    annual_kwh = entry.runtime_data.annual_kwh
    billing_months = entry.runtime_data.billing_months
    period = group.get_current_period()

    # --- Dynamic sensors (change with zone / period) ---

    dynamic_sensors: list[EneaPricesDynamicSensor] = [
        EneaPricesDynamicSensor(
            group=group,
            key="current_zone",
            translation_key="current_zone",
            unit=None,
            value_fn=lambda p, z: z.value,
        ),
        EneaPricesDynamicSensor(
            group=group,
            key="current_price_energy",
            translation_key="current_price_energy",
            unit=UNIT_PRICE,
            value_fn=lambda p, z: round(p.zones[z].energy, 4),
        ),
        EneaPricesDynamicSensor(
            group=group,
            key="current_price_total",
            translation_key="current_price_total",
            unit=UNIT_PRICE,
            value_fn=lambda p, z: round(p.zones[z].total, 4),
        ),
        EneaPricesDynamicSensor(
            group=group,
            key="current_distribution",
            translation_key="current_distribution",
            unit=UNIT_PRICE,
            value_fn=lambda p, z: round(p.zones[z].total_distribution, 4),
        ),
        EneaPricesDynamicSensor(
            group=group,
            key="current_network_fee",
            translation_key="current_network_fee",
            unit=UNIT_PRICE,
            value_fn=lambda p, z: round(p.zones[z].variable_network, 4),
        ),
    ]

    # --- Static sensors (reflect current period) ---

    def _pv(zone: Zone, attr: str) -> float | None:
        """Get a rounded value from the current period, or None."""
        if period is None or zone not in period.zones:
            return None
        val = getattr(period.zones[zone], attr)
        return round(val, 4) if isinstance(val, float) else val

    def _mv(monthly_attr: str) -> float | None:
        """Get a monthly fee value from the current period, or None."""
        if period is None:
            return None
        return getattr(period.monthly, monthly_attr)

    def _s(key: str, value: float | None, *, category: EntityCategory | None = None, unit: str = UNIT_PRICE) -> EneaPricesStaticSensor:
        """Build a static sensor with the given key, value and optional entity category."""
        return EneaPricesStaticSensor(
            group=group, key=key, translation_key=key,
            unit=unit, value=value, entity_category=category,
        )

    # Per-zone static sensors – data-driven (obsługuje G11/G12/G12w)
    active_zones = list(period.zones.keys()) if period else []
    first_zone = active_zones[0] if active_zones else Zone.DAY

    per_zone: list[EneaPricesStaticSensor] = []
    for zone in active_zones:
        per_zone += [
            _s(f"{zone}_price_energy",   _pv(zone, "energy")),
            _s(f"{zone}_price_total",    _pv(zone, "total")),
            _s(f"{zone}_distribution",   _pv(zone, "total_distribution"),  category=EntityCategory.DIAGNOSTIC),
            _s(f"{zone}_network_fee",    _pv(zone, "variable_network"),    category=EntityCategory.DIAGNOSTIC),
        ]

    static_sensors: list[EneaPricesStaticSensor | EneaPricesDateSensor | EneaPricesMonthlyFeeSensor] = [
        *per_zone,
        # Stawki jednakowe we wszystkich strefach (diagnostic)
        _s("quality_fee",      _pv(first_zone, "quality"),      category=EntityCategory.DIAGNOSTIC),
        _s("oze_fee",          _pv(first_zone, "oze"),          category=EntityCategory.DIAGNOSTIC),
        _s("cogeneration_fee", _pv(first_zone, "cogeneration"), category=EntityCategory.DIAGNOSTIC),
        # Opłaty miesięczne (personalised, in zł/miesiąc)
        EneaPricesMonthlyFeeSensor(group=group, key="monthly_network_fixed", translation_key="monthly_network_fixed",
                                   value_fn=lambda m: m.get_network_fixed(phases)),
        EneaPricesMonthlyFeeSensor(group=group, key="monthly_subscription", translation_key="monthly_subscription",
                                   value_fn=lambda m: m.get_subscription(billing_months)),
        EneaPricesMonthlyFeeSensor(group=group, key="monthly_capacity", translation_key="monthly_capacity",
                                   value_fn=lambda m: m.get_capacity(annual_kwh)),
        EneaPricesMonthlyFeeSensor(group=group, key="monthly_transition", translation_key="monthly_transition",
                                   value_fn=lambda m: m.get_transition(annual_kwh),
                                   entity_category=EntityCategory.DIAGNOSTIC),
        # Daty obowiązywania taryfy
        EneaPricesDateSensor(group=group, key="valid_from",  translation_key="valid_from"),
        EneaPricesDateSensor(group=group, key="valid_until", translation_key="valid_until"),
    ]

    async_add_entities(dynamic_sensors + static_sensors)
    hass.async_create_task(async_inject_price_statistics(hass, group))

    # Refresh dynamic sensors at zone boundaries
    period_for_listeners = period or (group.periods[0] if group.periods else None)
    zone_change_hours = period_for_listeners.get_zone_change_hours() if period_for_listeners else []

    @callback
    def _on_change(_now: object) -> None:
        """Push updated state to all dynamic sensors on zone boundary or period change."""
        for sensor in dynamic_sensors:
            sensor.async_write_ha_state()

    for hour in zone_change_hours:
        unsub = async_track_time_change(hass, _on_change, hour=hour, minute=0, second=0)
        entry.runtime_data.unsub_listeners.append(unsub)

    # Midnight refresh handles period transitions (e.g. Feb 1 quality fee change)
    unsub = async_track_time_change(hass, _on_change, hour=0, minute=0, second=0)
    entry.runtime_data.unsub_listeners.append(unsub)


def _build_device_info(group: TariffGroup) -> DeviceInfo:
    """Return DeviceInfo for the given tariff group."""
    return DeviceInfo(
        identifiers={(DOMAIN, group.name)},
        name=f"Enea Ceny {group.name}",
        manufacturer="Enea",
    )


class EneaPricesDynamicSensor(SensorEntity):
    """Sensor whose value depends on the current time zone and active tariff period."""

    _attr_has_entity_name = True
    _attr_suggested_display_precision = 4

    def __init__(
        self,
        group: TariffGroup,
        key: str,
        translation_key: str,
        unit: str | None,
        value_fn: Callable[[TariffPeriod, Zone], Any],
    ) -> None:
        self._group = group
        self._value_fn = value_fn
        self._attr_unique_id = f"enea_prices-{group.name}-{key}"
        self._attr_translation_key = translation_key
        self._attr_native_unit_of_measurement = unit
        self._attr_device_info = _build_device_info(group)

        if unit is None:
            self._attr_suggested_display_precision = None

    @property
    def native_value(self) -> Any:
        """Return current price or zone value based on active tariff zone."""
        now = dt_util.now()
        today = now.date()
        period = self._group.get_period_for_date(today)
        if period is None:
            return None
        zone = period.get_zone_at_hour(now.hour, day=today)
        return self._value_fn(period, zone)


class EneaPricesStaticSensor(SensorEntity):
    """Sensor showing a fixed value from the currently active tariff period."""

    _attr_has_entity_name = True
    _attr_suggested_display_precision = 4
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        group: TariffGroup,
        key: str,
        translation_key: str,
        unit: str,
        value: float | None,
        entity_category: EntityCategory | None = None,
    ) -> None:
        self._attr_unique_id = f"enea_prices-{group.name}-{key}"
        self._attr_translation_key = translation_key
        self._attr_native_unit_of_measurement = unit
        self._attr_native_value = value
        self._attr_entity_category = entity_category
        self._attr_device_info = _build_device_info(group)


class EneaPricesMonthlyFeeSensor(SensorEntity):
    """Sensor showing a personalised monthly fee in zł."""

    _attr_has_entity_name = True
    _attr_suggested_display_precision = 2
    _attr_native_unit_of_measurement = UNIT_MONTHLY

    def __init__(
        self,
        group: TariffGroup,
        key: str,
        translation_key: str,
        value_fn: Callable[[MonthlyFees], float],
        entity_category: EntityCategory | None = None,
    ) -> None:
        self._group = group
        self._value_fn = value_fn
        self._attr_unique_id = f"enea_prices-{group.name}-{key}"
        self._attr_translation_key = translation_key
        self._attr_entity_category = entity_category
        self._attr_device_info = _build_device_info(group)

    @property
    def native_value(self) -> float | None:
        """Return the monthly fee in zł rounded to 2 decimal places."""
        period = self._group.get_current_period()
        if period is None:
            return None
        return round(self._value_fn(period.monthly), 2)


class EneaPricesDateSensor(SensorEntity):
    """Sensor showing valid_from or valid_until of the current tariff period."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(
        self,
        group: TariffGroup,
        key: str,
        translation_key: str,
    ) -> None:
        self._group = group
        self._key = key
        self._attr_unique_id = f"enea_prices-{group.name}-{key}"
        self._attr_translation_key = translation_key
        self._attr_device_info = _build_device_info(group)

    @property
    def native_value(self) -> date | None:
        """Return valid_from or valid_until of the currently active tariff period."""
        return getattr(self._group, f"current_{self._key}", None)
