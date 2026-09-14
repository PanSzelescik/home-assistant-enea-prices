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

from custom_components.enea_prices.tariffs import TARIFFS, TariffGroup, TariffPeriod, Zone

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


def test_every_group_covers_the_same_span() -> None:
    """A year added to one group must be added to all of them.

    costs.py prices a day only when the table of the customer's own group
    covers it, so a group that lags behind the others leaves its users with
    silently missing cost statistics for the whole gap.
    """
    spans = {name: _span(group) for name, group in TARIFFS.items()}

    assert len(set(spans.values())) == 1, spans


@pytest.mark.parametrize("name", sorted(TARIFFS))
def test_every_group_prices_every_day_of_2025(name: str) -> None:
    """2025 is bundled for all three groups, not only the one with invoices."""
    group = TARIFFS[name]
    unpriced = [
        day
        for day in _days(datetime.date(2025, 1, 1), datetime.date(2025, 12, 31))
        if not any(p.valid_from <= day <= p.valid_until for p in group.periods)
    ]

    assert unpriced == []


def _period_on(name: str, day: datetime.date) -> TariffPeriod:
    (period,) = [p for p in TARIFFS[name].periods if p.valid_from <= day <= p.valid_until]
    return period


# Energy price (net, excise excluded) and capacity fee for the top consumption
# band on both sides of the two 2025 boundaries: the capacity fee returning on
# 1 July and the Enea S.A. price change on 1 October.  A shifted date or a
# rate typed into the wrong zone shows up here.
_2025_BOUNDARIES = [
    # name, day, {zone: energy}, capacity_gt2800
    ("G11", datetime.date(2025, 6, 30), {Zone.DAY: 0.5000}, 0.0),
    ("G11", datetime.date(2025, 7, 1), {Zone.DAY: 0.5000}, 16.01),
    ("G11", datetime.date(2025, 9, 30), {Zone.DAY: 0.5000}, 16.01),
    ("G11", datetime.date(2025, 10, 1), {Zone.DAY: 0.5000}, 16.01),
    ("G12", datetime.date(2025, 6, 30), {Zone.DAY: 0.5000, Zone.NIGHT: 0.4056}, 0.0),
    ("G12", datetime.date(2025, 7, 1), {Zone.DAY: 0.5000, Zone.NIGHT: 0.4056}, 16.01),
    ("G12", datetime.date(2025, 9, 30), {Zone.DAY: 0.5000, Zone.NIGHT: 0.4056}, 16.01),
    ("G12", datetime.date(2025, 10, 1), {Zone.DAY: 0.5000, Zone.NIGHT: 0.3840}, 16.01),
    ("G12w", datetime.date(2025, 6, 30), {Zone.PEAK: 0.5000, Zone.OFF_PEAK: 0.4171}, 0.0),
    ("G12w", datetime.date(2025, 7, 1), {Zone.PEAK: 0.5000, Zone.OFF_PEAK: 0.4171}, 16.01),
    ("G12w", datetime.date(2025, 9, 30), {Zone.PEAK: 0.5000, Zone.OFF_PEAK: 0.4171}, 16.01),
    ("G12w", datetime.date(2025, 10, 1), {Zone.PEAK: 0.5000, Zone.OFF_PEAK: 0.3940}, 16.01),
]


@pytest.mark.parametrize(
    ("name", "day", "energy", "capacity"),
    _2025_BOUNDARIES,
    ids=[f"{n}-{d.isoformat()}" for n, d, _, _ in _2025_BOUNDARIES],
)
def test_2025_boundary_rates(
    name: str, day: datetime.date, energy: dict, capacity: float
) -> None:
    period = _period_on(name, day)

    assert {zone: pricing.energy for zone, pricing in period.zones.items()} == energy
    assert period.monthly.capacity_gt2800 == capacity
