"""Which zone an hour is billed in, for a tariff whose zones depend on the month.

G12sezON and G13active take their zones from Enea Operator's 2026 tariff
(extract, points 2.2.10 and 2.2.11), which sets them month by month: the cheap
zone follows solar output, so in summer it sits in the middle of the day.
"""
from __future__ import annotations

import datetime

import pytest

from custom_components.enea_prices.tariffs import TARIFFS, Zone

USE, REST, LIMIT = Zone.RECOMMENDED_USE, Zone.REMAINING, Zone.RECOMMENDED_LIMIT

G12SEZON = TARIFFS["G12sezON"].get_period_for_date(datetime.date(2026, 6, 1))
G13ACTIVE = TARIFFS["G13active"].get_period_for_date(datetime.date(2026, 6, 1))


@pytest.mark.parametrize("name", ["G12sezON", "G13active"])
@pytest.mark.parametrize("month", range(1, 13))
def test_every_hour_of_every_month_has_exactly_one_zone(name: str, month: int) -> None:
    """A gap would silently fall back to Zone.DAY, which these groups do not have.

    An overlap would make the zone depend on the order of the entries.
    """
    period = TARIFFS[name].get_period_for_date(datetime.date(2026, 6, 1))

    for hour in range(24):
        matching = [
            entry
            for entry in period.schedule
            if entry.start_hour <= hour < entry.end_hour and month in entry.months
        ]
        assert len(matching) == 1, (month, hour, matching)


@pytest.mark.parametrize(
    ("day", "hour", "expected"),
    [
        # Kwiecień–wrzesień: zalecany pobór 4–6 i 9–17
        (datetime.date(2026, 7, 15), 3, REST),
        (datetime.date(2026, 7, 15), 4, USE),
        (datetime.date(2026, 7, 15), 6, REST),
        (datetime.date(2026, 7, 15), 10, USE),
        (datetime.date(2026, 7, 15), 17, REST),
        (datetime.date(2026, 7, 15), 23, REST),
        # Październik–marzec: zalecany pobór 22–6 i 11–13
        (datetime.date(2026, 1, 15), 3, USE),
        (datetime.date(2026, 1, 15), 10, REST),
        (datetime.date(2026, 1, 15), 12, USE),
        (datetime.date(2026, 1, 15), 22, USE),
        # The season turns on the first of the month, not mid-month
        (datetime.date(2026, 3, 31), 10, REST),
        (datetime.date(2026, 4, 1), 10, USE),
        (datetime.date(2026, 9, 30), 23, REST),
        (datetime.date(2026, 10, 1), 23, USE),
    ],
)
def test_g12sezon_zones(day: datetime.date, hour: int, expected: Zone) -> None:
    assert G12SEZON.get_zone_at_hour(hour, day=day) is expected


@pytest.mark.parametrize(
    ("day", "hour", "expected"),
    [
        (datetime.date(2026, 1, 15), 5, USE),
        (datetime.date(2026, 1, 15), 8, LIMIT),
        (datetime.date(2026, 1, 15), 12, REST),
        (datetime.date(2026, 1, 15), 23, USE),
        (datetime.date(2026, 3, 15), 5, REST),
        (datetime.date(2026, 3, 15), 12, USE),
        (datetime.date(2026, 7, 15), 9, USE),
        (datetime.date(2026, 7, 15), 17, REST),
        (datetime.date(2026, 7, 15), 18, LIMIT),
        # October alone keeps 6:00 in the remaining hours (23–7, not 23–6)
        (datetime.date(2026, 10, 15), 6, REST),
        (datetime.date(2026, 9, 15), 6, LIMIT),
        (datetime.date(2026, 11, 15), 14, LIMIT),
        (datetime.date(2026, 12, 15), 13, LIMIT),
    ],
)
def test_g13active_zones(day: datetime.date, hour: int, expected: Zone) -> None:
    assert G13ACTIVE.get_zone_at_hour(hour, day=day) is expected


def test_a_public_holiday_does_not_change_a_monthly_schedule() -> None:
    """Neither group distinguishes working days, so a holiday is an ordinary day."""
    christmas = datetime.date(2026, 12, 25)
    ordinary = datetime.date(2026, 12, 15)

    assert [G13ACTIVE.get_zone_at_hour(h, day=christmas) for h in range(24)] == [
        G13ACTIVE.get_zone_at_hour(h, day=ordinary) for h in range(24)
    ]
