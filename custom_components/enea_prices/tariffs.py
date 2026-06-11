"""Tariff definitions for Enea Ceny integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from functools import lru_cache


class Zone(StrEnum):
    """Tariff zone names."""

    DAY = "day"
    NIGHT = "night"
    PEAK = "peak"
    OFF_PEAK = "off_peak"


@dataclass(frozen=True)
class ZonePricing:
    """Per-kWh prices for a single zone (all netto, zł/kWh)."""

    energy: float
    """Cena energii elektrycznej netto (sprzedawca Enea S.A.)."""

    variable_network: float
    """Składnik zmienny stawki sieciowej (Enea Operator)."""

    quality: float
    """Stawka jakościowa (Enea Operator)."""

    oze: float
    """Opłata OZE (Enea Operator), w zł/kWh."""

    cogeneration: float
    """Opłata kogeneracyjna (Enea Operator), w zł/kWh."""

    @property
    def total_distribution(self) -> float:
        """Suma wszystkich zmiennych opłat dystrybucyjnych netto."""
        return self.variable_network + self.quality + self.oze + self.cogeneration

    @property
    def total(self) -> float:
        """Cena energii + wszystkie zmienne opłaty dystrybucyjne (netto)."""
        return self.energy + self.total_distribution



@dataclass(frozen=True)
class MonthlyFees:
    """Fixed monthly fees (netto, zł/miesiąc)."""

    # Składnik stały stawki sieciowej
    network_fixed_1phase: float
    network_fixed_3phase: float

    # Opłata abonamentowa
    subscription_1m: float
    subscription_2m: float
    subscription_6m: float
    subscription_12m: float

    # Opłata mocowa
    capacity_lt500: float
    capacity_500_1200: float
    capacity_1200_2800: float
    capacity_gt2800: float

    # Opłata przejściowa (0.0 jeśli zniesiona)
    transition_lt500: float = 0.0
    transition_500_1200: float = 0.0
    transition_gt1200: float = 0.0

    def get_network_fixed(self, phases: int) -> float:
        """Składnik stały dla instalacji 1- lub 3-fazowej."""
        return self.network_fixed_1phase if phases == 1 else self.network_fixed_3phase

    def get_subscription(self, billing_months: int) -> float:
        """Opłata abonamentowa dla danego okresu rozliczeniowego."""
        return {1: self.subscription_1m, 2: self.subscription_2m,
                6: self.subscription_6m, 12: self.subscription_12m}[billing_months]

    def get_capacity(self, annual_kwh: int) -> float:
        """Opłata mocowa dla danego rocznego zużycia (kWh)."""
        if annual_kwh < 500:
            return self.capacity_lt500
        if annual_kwh <= 1200:
            return self.capacity_500_1200
        if annual_kwh <= 2800:
            return self.capacity_1200_2800
        return self.capacity_gt2800

    def get_transition(self, annual_kwh: int) -> float:
        """Opłata przejściowa dla danego rocznego zużycia (kWh)."""
        if annual_kwh < 500:
            return self.transition_lt500
        if annual_kwh <= 1200:
            return self.transition_500_1200
        return self.transition_gt1200


@dataclass(frozen=True)
class ZoneScheduleEntry:
    """A contiguous time range belonging to a zone."""

    zone: Zone
    start_hour: int
    """Start hour (0-23), inclusive."""
    end_hour: int
    """End hour (1-24), exclusive. 24 means midnight next day."""
    weekdays: frozenset[int] | None = None
    """Days-of-week this entry applies to (0=Mon, 6=Sun). None means every day."""


@lru_cache(maxsize=10)
def _polish_holidays(year: int) -> frozenset[date]:
    """Return Polish public holidays for the given year (cached per year)."""
    from holidays import country_holidays
    return frozenset(country_holidays("PL", years=[year]).keys())


@dataclass(frozen=True)
class TariffPeriod:
    """Prices and schedule valid for a specific date range."""

    valid_from: date
    valid_until: date
    """Inclusive."""

    zones: dict[Zone, ZonePricing]
    schedule: list[ZoneScheduleEntry]
    monthly: MonthlyFees
    has_weekday_schedule: bool = field(init=False, repr=False, compare=False)
    """True when any schedule entry has weekday constraints (e.g. G12w). Precomputed."""

    def __post_init__(self) -> None:
        """Precompute has_weekday_schedule once on construction."""
        object.__setattr__(
            self,
            "has_weekday_schedule",
            any(e.weekdays is not None for e in self.schedule),
        )

    def get_zone_at_hour(self, hour: int, day: date | None = None) -> Zone:
        """Return which zone is active at the given hour (0-23).

        day: when provided, weekday constraints are evaluated and Polish public
             holidays are automatically treated as non-workdays (Saturday).
             When None, weekday constraints are ignored.
        """
        weekday: int | None = None
        if day is not None:
            weekday = day.weekday()
            if (
                weekday < 5
                and self.has_weekday_schedule
                and day in _polish_holidays(day.year)
            ):
                weekday = 5  # treat public holiday as Saturday
        for entry in self.schedule:
            if entry.start_hour <= hour < entry.end_hour:
                if entry.weekdays is None or weekday is None or weekday in entry.weekdays:
                    return entry.zone
        return Zone.DAY

    def get_zone_change_hours(self) -> list[int]:
        """Return sorted list of hours when zone transitions happen."""
        return sorted({entry.start_hour for entry in self.schedule if entry.start_hour > 0})


@dataclass(frozen=True)
class TariffGroup:
    """A named tariff group (e.g. G12) with one or more time-bounded periods."""

    name: str
    periods: list[TariffPeriod]
    """Must be sorted by valid_from ascending, must not overlap."""

    def get_period_for_date(self, d: date) -> TariffPeriod | None:
        """Return the period active on the given date, or None."""
        for period in self.periods:
            if period.valid_from <= d <= period.valid_until:
                return period
        return None

    def get_current_period(self) -> TariffPeriod | None:
        """Return the period active today."""
        return self.get_period_for_date(date.today())

    @property
    def earliest_date(self) -> date:
        """Earliest date covered by any period."""
        return self.periods[0].valid_from

    @property
    def current_valid_from(self) -> date | None:
        """valid_from of the currently active period."""
        p = self.get_current_period()
        return p.valid_from if p else None

    @property
    def current_valid_until(self) -> date | None:
        """valid_until of the currently active period."""
        p = self.get_current_period()
        return p.valid_until if p else None


# ---------------------------------------------------------------------------
# G12 – taryfa dwustrefowa
#
# Godziny stref:
#   Noc:   00:00–06:00 i 13:00–15:00
#   Dzień: 06:00–13:00 i 15:00–22:00
#
# Źródła:
#   Dystrybucja: Decyzja Prezesa URE z dnia 17.12.2025, ENEA Operator
#   Sprzedaż:    Taryfa Enea S.A. dla grup taryfowych G
# ---------------------------------------------------------------------------

_G12_SCHEDULE = [
    ZoneScheduleEntry(Zone.NIGHT, 0, 6),
    ZoneScheduleEntry(Zone.DAY, 6, 13),
    ZoneScheduleEntry(Zone.NIGHT, 13, 15),
    ZoneScheduleEntry(Zone.DAY, 15, 22),
    ZoneScheduleEntry(Zone.NIGHT, 22, 24),
]

_G12_MONTHLY_2026 = MonthlyFees(
    network_fixed_1phase=9.59,
    network_fixed_3phase=14.56,
    subscription_1m=3.84,
    subscription_2m=1.92,
    subscription_6m=0.64,
    subscription_12m=0.32,
    capacity_lt500=4.29,
    capacity_500_1200=10.31,
    capacity_1200_2800=17.18,
    capacity_gt2800=24.05,
    # Opłata przejściowa zniesiona od 1.01.2026
    transition_lt500=0.0,
    transition_500_1200=0.0,
    transition_gt1200=0.0,
)

TARIFF_G12 = TariffGroup(
    name="G12",
    periods=[
        # Styczeń 2026: stawka jakościowa 0.0331
        TariffPeriod(
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 1, 31),
            monthly=_G12_MONTHLY_2026,
            zones={
                Zone.DAY: ZonePricing(
                    energy=0.5779,
                    variable_network=0.2779,
                    quality=0.0331,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
                Zone.NIGHT: ZonePricing(
                    energy=0.3369,
                    variable_network=0.0913,
                    quality=0.0331,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
            },
            schedule=_G12_SCHEDULE,
        ),
        # Luty–Grudzień 2026: stawka jakościowa 0.0332 (zmiana od 1.02.2026)
        TariffPeriod(
            valid_from=date(2026, 2, 1),
            valid_until=date(2026, 12, 31),
            monthly=_G12_MONTHLY_2026,
            zones={
                Zone.DAY: ZonePricing(
                    energy=0.5779,
                    variable_network=0.2779,
                    quality=0.0332,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
                Zone.NIGHT: ZonePricing(
                    energy=0.3369,
                    variable_network=0.0913,
                    quality=0.0332,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
            },
            schedule=_G12_SCHEDULE,
        ),
    ],
)

# ---------------------------------------------------------------------------
# G11 – taryfa jednostrefowa
#
# Jedna strefa całodobowa.
#
# Źródła:
#   Dystrybucja: Decyzja Prezesa URE z dnia 17.12.2025, ENEA Operator
#   Sprzedaż:    Taryfa Enea S.A. dla grup taryfowych G
# ---------------------------------------------------------------------------

_G11_SCHEDULE = [
    ZoneScheduleEntry(Zone.DAY, 0, 24),
]

_G11_MONTHLY_2026 = MonthlyFees(
    network_fixed_1phase=7.45,
    network_fixed_3phase=10.41,
    subscription_1m=3.84,
    subscription_2m=1.92,
    subscription_6m=0.64,
    subscription_12m=0.32,
    capacity_lt500=4.29,
    capacity_500_1200=10.31,
    capacity_1200_2800=17.18,
    capacity_gt2800=24.05,
    transition_lt500=0.0,
    transition_500_1200=0.0,
    transition_gt1200=0.0,
)

TARIFF_G11 = TariffGroup(
    name="G11",
    periods=[
        # Styczeń 2026: stawka jakościowa 0.0331
        TariffPeriod(
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 1, 31),
            monthly=_G11_MONTHLY_2026,
            zones={
                Zone.DAY: ZonePricing(
                    energy=0.4980,
                    variable_network=0.2456,
                    quality=0.0331,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
            },
            schedule=_G11_SCHEDULE,
        ),
        # Luty–Grudzień 2026: stawka jakościowa 0.0332
        TariffPeriod(
            valid_from=date(2026, 2, 1),
            valid_until=date(2026, 12, 31),
            monthly=_G11_MONTHLY_2026,
            zones={
                Zone.DAY: ZonePricing(
                    energy=0.4980,
                    variable_network=0.2456,
                    quality=0.0332,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
            },
            schedule=_G11_SCHEDULE,
        ),
    ],
)


# ---------------------------------------------------------------------------
# G12w – taryfa dwustrefowa weekendowa
#
# Godziny stref:
#   Szczyt (Peak):        Pon–Pt 06:00–21:00
#   Poza szczytem:        Pon–Pt 21:00–06:00 oraz cała sobota, niedziela
#                         i inne dni ustawowo wolne od pracy
#
# Źródła:
#   Dystrybucja: Decyzja Prezesa URE z dnia 17.12.2025, ENEA Operator
#   Sprzedaż:    Taryfa Enea S.A. dla grup taryfowych G
# ---------------------------------------------------------------------------

_WORKDAYS = frozenset({0, 1, 2, 3, 4})   # Pon–Pt
_WEEKEND = frozenset({5, 6})              # Sob–Nd

_G12W_SCHEDULE = [
    ZoneScheduleEntry(Zone.PEAK,     6, 21, _WORKDAYS),
    ZoneScheduleEntry(Zone.OFF_PEAK, 0,  6, _WORKDAYS),
    ZoneScheduleEntry(Zone.OFF_PEAK, 21, 24, _WORKDAYS),
    ZoneScheduleEntry(Zone.OFF_PEAK, 0, 24, _WEEKEND),
]

_G12W_MONTHLY_2026 = MonthlyFees(
    network_fixed_1phase=16.85,
    network_fixed_3phase=26.23,
    subscription_1m=3.84,
    subscription_2m=1.92,
    subscription_6m=0.64,
    subscription_12m=0.32,
    capacity_lt500=4.29,
    capacity_500_1200=10.31,
    capacity_1200_2800=17.18,
    capacity_gt2800=24.05,
    transition_lt500=0.0,
    transition_500_1200=0.0,
    transition_gt1200=0.0,
)

TARIFF_G12W = TariffGroup(
    name="G12w",
    periods=[
        # Styczeń 2026: stawka jakościowa 0.0331
        TariffPeriod(
            valid_from=date(2026, 1, 1),
            valid_until=date(2026, 1, 31),
            monthly=_G12W_MONTHLY_2026,
            zones={
                Zone.PEAK: ZonePricing(
                    energy=0.6518,
                    variable_network=0.2702,
                    quality=0.0331,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
                Zone.OFF_PEAK: ZonePricing(
                    energy=0.3465,
                    variable_network=0.0813,
                    quality=0.0331,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
            },
            schedule=_G12W_SCHEDULE,
        ),
        # Luty–Grudzień 2026: stawka jakościowa 0.0332
        TariffPeriod(
            valid_from=date(2026, 2, 1),
            valid_until=date(2026, 12, 31),
            monthly=_G12W_MONTHLY_2026,
            zones={
                Zone.PEAK: ZonePricing(
                    energy=0.6518,
                    variable_network=0.2702,
                    quality=0.0332,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
                Zone.OFF_PEAK: ZonePricing(
                    energy=0.3465,
                    variable_network=0.0813,
                    quality=0.0332,
                    oze=0.0073,
                    cogeneration=0.0030,
                ),
            },
            schedule=_G12W_SCHEDULE,
        ),
    ],
)


TARIFFS: dict[str, TariffGroup] = {
    "G11": TARIFF_G11,
    "G12": TARIFF_G12,
    "G12w": TARIFF_G12W,
}
