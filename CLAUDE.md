# Enea Ceny – kontekst dla Claude

## Czym jest ten projekt

Integracja Home Assistant (custom component) podająca ceny energii elektrycznej ENEA w Polsce.
Domena: `enea_prices`. Brak zewnętrznego API — wszystkie dane są hardkodowane z decyzji URE.

Powiązany projekt: `C:\Git\home-assistant-enea` (integracja licznika Enea — odczyty zużycia).

## Architektura

```
custom_components/enea_prices/
  __init__.py       # setup/unload, EneaPricesRuntimeData
  config_flow.py    # 2 kroki: wybór taryfy → szczegóły instalacji (fazy, zużycie, rozliczenie)
  const.py          # DOMAIN, PLATFORMS, klucze konfiguracji
  tariffs.py        # model danych: TariffGroup > TariffPeriod > ZonePricing + MonthlyFees
  sensor.py         # ~30 sensorów: dynamiczne (zmieniają się ze strefą) + statyczne + miesięczne
  translations/
    pl.json
    en.json
```

## Model danych (`tariffs.py`)

```
TariffGroup (np. "G12")
  └── periods: list[TariffPeriod]     # posortowane wg valid_from, bez nakładania
        ├── valid_from / valid_until
        ├── schedule: list[ZoneScheduleEntry]   # harmonogram stref (godziny + opcjonalnie dni tygodnia)
        ├── zones: dict[Zone, ZonePricing]      # ceny per strefa (netto, zł/kWh)
        └── monthly: MonthlyFees               # opłaty stałe (zł/miesiąc)
```

`ZonePricing` ma właściwości netto: `energy`, `variable_network`, `quality`, `oze`, `cogeneration`,
`total_distribution`, `total`. Brak wariantów `_brutto` — cenę brutto oblicza `costs.py` inline
jako `round((pricing.energy + AKCYZA + pricing.total_distribution) * (1 + VAT_RATE), 4)`.
`AKCYZA` (0.005 zł/kWh) i `VAT_RATE` (0.23) są zdefiniowane w `const.py`.

`ZoneScheduleEntry` ma opcjonalne `weekdays: frozenset[int] | None` (0=Pon, 6=Nd; None=każdy dzień).
`Zone` enum: `DAY`, `NIGHT`, `PEAK`, `OFF_PEAK`.

## Strefy taryf

**G11** – jedna strefa całodobowa (Zone.DAY 00:00–24:00)

**G12** – dwustrefowa:
- **Noc** (Zone.NIGHT): 00:00–06:00 i 13:00–15:00
- **Dzień** (Zone.DAY): 06:00–13:00 i 15:00–22:00

**G12w** – weekendowa:
- **Szczyt** (Zone.PEAK): Pon–Pt 06:00–21:00, z wyłączeniem dni ustawowo wolnych od pracy
- **Poza szczytem** (Zone.OFF_PEAK): Pon–Pt poza szczytem + cała Sob–Nd + dni ustawowo wolne

Odświeżanie sensorów dynamicznych: godziny z `get_zone_change_hours()` + 0:00 (via `async_track_time_change`).
Zmiana strefy przy Sob/Nd i świętach obsługiwana przez refresh o 0:00.

## Obsługa świąt (G12w)

Pakiet `holidays==0.84` (ten sam co `workday`/`holiday` w HA core).
Ładowany w `sensor.py` przez `hass.async_add_executor_job` przy starcie integracji.
Pokrywa 3 lata od daty uruchomienia: `country_holidays("PL", years=range(current_year, current_year + 3))`.
Dzień świąteczny Pon–Pt traktowany jak sobota przy wyborze strefy (`is_holiday=True` → `effective_weekday=5`).
Dla G11/G12 holidays nie są ładowane — `_load_holiday_dates` zwraca `frozenset()` natychmiast.

## Statystyki

Sensory cenowe **nie mają** `state_class` — unika warningu Energy dashboard o `last_reset`.

Zamiast tego `statistics.py` wstrzykuje statystyki godzinowe (mean = stała wartość ceny) przez
`async_import_statistics` (source=`"recorder"`) dla każdego statycznego sensora cenowego per strefa.
Statystyki obejmują cały okres taryfowy od `valid_from` do wczoraj.

Energy dashboard używa tych statystyk do obliczania kosztów historycznych (kWh × cena/h).
Wywołanie następuje automatycznie przy starcie integracji (`sensor.py:async_setup_entry`).

Konfiguracja Energy dashboard: opcja „Użyj encji z bieżącą ceną" — wybierz statyczny sensor
per strefa (np. `day_price_total`, `night_price_total`). Sensory brutto zostały usunięte;
statystyki kosztów brutto są obliczane przez `costs.py` w integracji `enea`.

## Opłaty miesięczne

Personalizowane przez config_flow (fazy instalacji, roczne zużycie, okres rozliczeniowy).
Wpływają na sensory: `monthly_network_fixed`, `monthly_subscription`, `monthly_capacity`, `monthly_transition`.

## Dodawanie nowej taryfy

1. Zdefiniuj `TariffPeriod`(y) z odpowiednimi strefami i `MonthlyFees`
2. Owiń w `TariffGroup` i dodaj do `TARIFFS` dict w `tariffs.py`
3. config_flow automatycznie pokaże nową opcję

## Dodawanie nowego okresu do istniejącej taryfy (np. 2027)

Dopisz `TariffPeriod` do listy `periods` w odpowiednim `TariffGroup`. Sensory dynamiczne
przejdą na nowe ceny automatycznie o północy w dniu `valid_from` nowego okresu.

## Źródła danych (2026, G11/G12/G12w)

- **Dystrybucja**: Decyzja Prezesa URE z dnia 17.12.2025 (ENEA Operator)
- **Stawka jakościowa od 1.02.2026**: 0.0332 zł/kWh (poprzednio 0.0331)
- **Sprzedaż energii**: Taryfa Enea S.A. dla grup G, od 01.01.2026
- **Opłata przejściowa**: zniesiona od 1.01.2026
- Wszystkie pliki PDF i podsumowania Gemini w katalogu głównym repozytorium

## Obsługiwane taryfy

| Taryfa | Strefy | Uwagi |
|--------|--------|-------|
| G11 | 1 (całodobowa) | |
| G12 | 2 (dzień/noc) | |
| G12w | 2 (szczyt/poza szczytem) | Tygodniowy harmonogram; dni ustawowo wolne obsługiwane (pakiet `holidays`) |
