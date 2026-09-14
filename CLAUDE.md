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

⚠️ **`energy` znaczy co innego w różnych okresach.** W okresach objętych rządowym mrożeniem
(cały 2025) pole zawiera **cenę efektywną po zastosowaniu ceny maksymalnej**, a nie cenę
z cennika Enea S.A.; od 2026 zawiera cenę taryfową. Cena taryfowa danego okresu jest podana
w komentarzu obok wpisu. Szczegóły mechanizmu i progi dokładności — w komentarzu nad `TARIFF_G12W`.

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
Statystyki obejmują **każdy** okres w `group.periods` — od `valid_from` najstarszego (1.01.2025)
do wczoraj, więc dopisanie okresu wstecz backfilluje go przy najbliższym starcie.
Rząd wielkości jednorazowego backfillu roku: 8760 h × `len(ZONE_PRICE_ATTRS)` × liczba stref
(dla G12/G12w ≈ 35 tys. wierszy).
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

## Mrożenie cen 2025

Cena maksymalna **0,5000 zł/kWh netto** (bez VAT i akcyzy) obowiązywała 1.01–31.12.2025,
bez limitów zużycia, wyłącznie dla energii czynnej — dystrybucja naliczana normalnie.
Ceny taryfowe Enea S.A. były wyższe, więc tabela zawiera cenę efektywną (patrz ostrzeżenie
przy modelu danych).

Dla G12 i G12w Enea stosowała cap **dwustopniowo, w skali miesiąca**: (1) gdy średnia cena
taryfowa ważona zużyciem we wszystkich strefach < 0,500 → ceny taryfowe w każdej strefie;
(2) w przeciwnym razie każda strefa dostaje `min(cena_taryfowa, 0,500)`. Tabela koduje tylko
stopień 2, bo nie zna zużycia — jest dokładna powyżej progów udziału droższej strefy:
G12w 19,6 % / 28,4 %, G12 27,4 % / 39,0 % (odpowiednio do 30.09 i od 1.10.2025).
Poniżej progu zaniża koszt. Pełny wywód w komentarzu nad `TARIFF_G12W`.

Opłata mocowa zawieszona 1.01–30.06.2025; opłata przejściowa jeszcze obowiązywała.

## Źródła danych

Decyzje Prezesa URE dla taryf sprzedaży Enea S.A. (PDF) — `docs/decyzje-ure/`, indeks w `README.md`
tego katalogu.

**2026, G11/G12/G12w**

- **Dystrybucja**: Decyzja Prezesa URE z dnia 17.12.2025 (ENEA Operator)
- **Stawka jakościowa od 1.02.2026**: 0.0332 zł/kWh (poprzednio 0.0331)
- **Sprzedaż energii**: Taryfa Enea S.A. dla grup G, od 01.01.2026
- **Opłata przejściowa**: zniesiona od 1.01.2026

**2025, G11/G12/G12w**

- **Dystrybucja**: Decyzja Prezesa URE nr DRE.WRE.4211.46.9.2024.MKa4 z 16.12.2024 (ENEA Operator)
- **Sprzedaż energii**: decyzja DRE.WRE.4211.31.11.2024.JTr z 28.06.2024; od 1.10.2025
  decyzja DRE.WRE.4211.38.12.2025.MKa4/AKr3 z 30.09.2025
- **Stawka jakościowa**: 0.0321 zł/kWh · **OZE**: 0.0035 · **kogeneracyjna**: 0.0030
- **Opłata mocowa od 1.07.2025**: Informacja Prezesa URE nr 56/2024 (2.86 / 6.86 / 11.44 / 16.01)

**Weryfikacja cen**: dokumenty „Dodatkowa informacja ENEA S.A. o cenach BRUTTO" podają ceny
brutto per grupa/strefa; przeliczenie na `energy` w tabeli to `brutto/1.23 - 0.005`.

## Obsługiwane taryfy

| Taryfa | Strefy | Uwagi |
|--------|--------|-------|
| G11 | 1 (całodobowa) | |
| G12 | 2 (dzień/noc) | |
| G12w | 2 (szczyt/poza szczytem) | Tygodniowy harmonogram; dni ustawowo wolne obsługiwane (pakiet `holidays`) |
