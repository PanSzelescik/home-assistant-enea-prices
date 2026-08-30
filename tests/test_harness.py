"""The suite must be able to import the integration at all."""
from __future__ import annotations

import datetime


def test_modules_import() -> None:
    """Integration modules import without a running Home Assistant."""
    from custom_components.enea_prices import statistics, tariffs

    assert callable(statistics.async_inject_price_statistics)
    assert "G12w" in tariffs.TARIFFS


def test_g12w_zone_schedule() -> None:
    """G12w peak hours are workdays 06:00-21:00; weekends are entirely off-peak."""
    from custom_components.enea_prices.tariffs import TARIFFS, Zone

    period = TARIFFS["G12w"].get_period_for_date(datetime.date(2026, 3, 3))
    workday = datetime.date(2026, 3, 3)  # Tuesday
    saturday = datetime.date(2026, 3, 7)

    peak_hours = [h for h in range(24) if period.get_zone_at_hour(h, day=workday) is Zone.PEAK]
    assert peak_hours == list(range(6, 21))
    assert all(
        period.get_zone_at_hour(h, day=saturday) is Zone.OFF_PEAK for h in range(24)
    )
