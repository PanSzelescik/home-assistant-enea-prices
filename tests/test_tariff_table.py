"""Structural invariants every bundled tariff table has to satisfy.

These say nothing about what the prices are — that is what the URE decisions
are for — only that the table is shaped the way the rest of the integration
assumes.  A gap or an overlap here does not raise anything: costs.py in the
enea integration skips a day it cannot price, so a malformed table shows up as
missing statistics rather than an error.
"""
from __future__ import annotations

import datetime

import pytest

from custom_components.enea_prices.tariffs import TARIFFS, TariffGroup

ONE_DAY = datetime.timedelta(days=1)


def _days(start: datetime.date, end: datetime.date):
    """Yield every date from start to end inclusive."""
    day = start
    while day <= end:
        yield day
        day += ONE_DAY


def _span(group: TariffGroup) -> tuple[datetime.date, datetime.date]:
    """Return the first and last date the group's periods cover."""
    return group.periods[0].valid_from, group.periods[-1].valid_until


@pytest.mark.parametrize("name", sorted(TARIFFS))
def test_periods_ascend_by_start_date(name: str) -> None:
    """TariffGroup documents that its periods are sorted by valid_from.

    Nothing enforces it at construction, and the lookup below relies on it.
    """
    starts = [period.valid_from for period in TARIFFS[name].periods]

    assert starts == sorted(starts)


@pytest.mark.parametrize("name", sorted(TARIFFS))
def test_every_covered_day_belongs_to_exactly_one_period(name: str) -> None:
    """Inside its own span a table must have neither gaps nor overlaps.

    A gap leaves those days unpriced, which is silent.  An overlap makes the
    price depend on the order the periods happen to be listed in.
    """
    group = TARIFFS[name]
    first, last = _span(group)

    matches = {
        day: [p for p in group.periods if p.valid_from <= day <= p.valid_until]
        for day in _days(first, last)
    }

    assert [day for day, found in matches.items() if not found] == [], "gap"
    assert [day for day, found in matches.items() if len(found) > 1] == [], "overlap"


@pytest.mark.parametrize("name", sorted(TARIFFS))
def test_the_table_stops_at_its_own_edges(name: str) -> None:
    """Dates beyond the span must report no period rather than the nearest one.

    Prices outside the range the tariff decisions cover would be invented.
    """
    group = TARIFFS[name]
    first, last = _span(group)

    assert group.get_period_for_date(first - ONE_DAY) is None
    assert group.get_period_for_date(last + ONE_DAY) is None
    assert group.get_period_for_date(first) is not None
    assert group.get_period_for_date(last) is not None
