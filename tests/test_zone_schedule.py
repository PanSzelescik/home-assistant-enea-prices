"""Which zone an hour is billed in, for a tariff whose zones depend on the day.

G12w is the only bundled tariff with a weekday schedule, and it is where the
subtle rule lives: peak hours exist on working days only, so a Tuesday that
happens to be a public holiday has to be billed like a Sunday.
"""
from __future__ import annotations

import datetime

import pytest

from custom_components.enea_prices.tariffs import TARIFFS, Zone

G12W = TARIFFS["G12w"].get_period_for_date(datetime.date(2026, 6, 1))

WEDNESDAY = datetime.date(2026, 6, 3)
SATURDAY = datetime.date(2026, 6, 6)

HOLIDAYS_2026 = {
    "New Year's Day": datetime.date(2026, 1, 1),
    "Corpus Christi, a movable feast": datetime.date(2026, 6, 4),
    "Independence Day": datetime.date(2026, 11, 11),
    "Christmas Eve, statutory only since 2025": datetime.date(2026, 12, 24),
}


@pytest.mark.parametrize(
    "hour,expected",
    [(5, Zone.OFF_PEAK), (6, Zone.PEAK), (20, Zone.PEAK), (21, Zone.OFF_PEAK)],
)
def test_peak_hours_on_a_working_day(hour: int, expected: Zone) -> None:
    """On a working day the peak zone runs from 06:00 up to but not including 21:00."""
    assert G12W.get_zone_at_hour(hour, day=WEDNESDAY) is expected


def test_a_weekend_day_has_no_peak_hours() -> None:
    """The whole of Saturday and Sunday is off-peak, midday included."""
    assert G12W.get_zone_at_hour(12, day=SATURDAY) is Zone.OFF_PEAK


@pytest.mark.parametrize("day", HOLIDAYS_2026.values(), ids=list(HOLIDAYS_2026))
def test_a_public_holiday_is_billed_like_a_weekend(day: datetime.date) -> None:
    """A statutory holiday falling Monday to Friday must have no peak hours.

    Enea prices the whole of such a day at the off-peak rate.  Getting it wrong
    costs the difference between the two rates for fifteen hours, on a dozen
    days a year.

    Christmas Eve is the case that pins the lower bound on the holidays
    package: it only became a statutory holiday in 2025, and releases before
    0.64 still report twelve Polish holidays for December without it.
    """
    assert day.weekday() < 5, "the point of the case is a holiday on a working day"

    assert G12W.get_zone_at_hour(12, day=day) is Zone.OFF_PEAK


@pytest.mark.parametrize("name", ["G11", "G12"])
def test_a_tariff_without_a_weekday_schedule_ignores_the_day(name: str) -> None:
    """G11 and G12 price by the hour alone, so holidays make no difference."""
    period = TARIFFS[name].get_period_for_date(datetime.date(2026, 6, 1))

    assert period.get_zone_at_hour(12, day=HOLIDAYS_2026["New Year's Day"]) is (
        period.get_zone_at_hour(12, day=WEDNESDAY)
    )
