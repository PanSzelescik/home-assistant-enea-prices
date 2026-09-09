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
  sensor.py         # ~22 sensory (G12): 5 dynamicznych + 8 per-strefa + 3 diagnostyczne + 4 miesięczne + 2 datowe
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

Pakiet `holidays` w wersji z `manifest.json`. Święta pobiera `_polish_holidays(year)`
w `tariffs.py` — `country_holidays("PL", years=[year])` pod `@lru_cache`, wołane
synchronicznie z `get_zone_at_hour` przy pierwszym zapytaniu o dany rok.
Dzień świąteczny Pon–Pt jest traktowany jak sobota przy wyborze strefy (`weekday = 5`).
Dla taryf bez harmonogramu tygodniowego (G11, G12) sprawdzenie świąt jest pomijane —
parametr `day` nie wpływa na wynik.

## Statystyki

Statyczne sensory cenowe mają `state_class=MEASUREMENT` — wymagane przez `async_import_statistics`
z `source="recorder"` (bez tego HA odrzuca import statystyk).

`statistics.py` wstrzykuje statystyki godzinowe (mean = stała wartość ceny) przez
`async_import_statistics` (source=`"recorder"`) dla każdego statycznego sensora cenowego per strefa.
Statystyki obejmują cały okres taryfowy od `valid_from` do wczoraj.
Wywołanie następuje automatycznie przy starcie integracji (`sensor.py:async_setup_entry`).
Przy każdym uruchomieniu zapisywane są tylko godziny brakujące w oknie okresu
(`statistics_during_period`), i wyłącznie te sprzed najnowszej zapisanej statystyki
(`get_last_statistics`) — godziny na końcu i za nią należą do rekordera, który sam
kompiluje statystyki tych sensorów; import tej samej godziny ścigałby się z jego
ślepym INSERT-em i wycofywał całą paczkę nadrabianych statystyk.

Energy dashboard — opcja „Użyj encji z bieżącą ceną": wybierz statyczny sensor per strefa
(np. `day_price_total`, `night_price_total`). HA pobierze historyczne mean-statystyki z recordera
i policzy koszty retroaktywnie od `valid_from`.

Sensory brutto nie istnieją w tej integracji; koszty brutto oblicza `costs.py` w integracji `enea`.

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
