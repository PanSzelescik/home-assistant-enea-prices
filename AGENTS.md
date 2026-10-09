# Enea Ceny – kontekst dla Claude

## Czym jest ten projekt

Integracja Home Assistant (custom component) podająca ceny energii elektrycznej ENEA w Polsce.
Domena: `enea_prices`. Brak zewnętrznego API — wszystkie dane są hardkodowane z decyzji URE,
z jednym wyjątkiem: cenę energii z umowy (oferta rynkowa) wpisuje użytkownik z faktury.

Powiązany projekt: `C:\Git\home-assistant-enea` (integracja licznika Enea — odczyty zużycia).

## Architektura

```
custom_components/enea_prices/
  __init__.py       # setup/unload, EneaPricesRuntimeData
  config_flow.py    # 3 kroki: taryfa → szczegóły instalacji → ceny (taryfa URE / z umowy); to samo w reconfigure
  meter.py          # podpowiedzi z licznika integracji enea (MeterHint, duck typing)
  const.py          # DOMAIN, PLATFORMS, klucze konfiguracji
  tariffs.py        # model danych: TariffGroup > TariffPeriod > ZonePricing + MonthlyFees
  sensor.py         # ~25 sensory (G12): 6 dynamicznych + 10 per-strefa + 3 diagnostyczne + 4 miesięczne + 2 datowe
                    # (+ „Opłata handlowa”, gdy wpisano ceny z umowy)
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
`total_distribution`, `total` — oraz jedną brutto: `total_brutto`
= `(energy + AKCYZA + total_distribution) × (1 + VAT_RATE)`, w tej kolejności dodawania,
bo `costs.py` w integracji `enea` liczy to samo inline i oba wyniki muszą być identyczne co do bitu.
`AKCYZA` (0.005 zł/kWh) i `VAT_RATE` (0.23) są zdefiniowane w `tariffs.py` i re-eksportowane
z `const.py`, skąd importuje je `enea`.

`ZoneScheduleEntry` ma opcjonalne `weekdays: frozenset[int] | None` (0=Pon, 6=Nd; None=każdy dzień)
i `months: frozenset[int] | None` (1–12; None=każdy miesiąc). Oba filtry działają tylko, gdy
`get_zone_at_hour` dostanie `day`.
`Zone` enum: `DAY`, `NIGHT`, `PEAK`, `OFF_PEAK`, `RECOMMENDED_USE` (zalecany pobór),
`REMAINING` (pozostałe godziny doby), `RECOMMENDED_LIMIT` (zalecane ograniczanie).

`MonthlyFees.trade` — opłata handlowa sprzedawcy; w tabeli zawsze 0.0 (taryfa URE jej nie zna),
ustawia ją dopiero `with_price_changes`.

## Ceny z umowy

Klient przechodzi w czasie między taryfą a ofertami: oferta jest stała przez swój okres
(np. 36 mies.), potem wg OWU Enea Sprzedaż § 7 sprzedawca może przysłać „Nową Ofertę” z nowym
cennikiem (brak sprzeciwu = nowe ceny), a bez niej / po rezygnacji wraca „Taryfa Sprzedawcy”.
Dlatego `entry.data["price_changes"]` to **historia**: lista posortowana po `valid_from`, każda
zmiana obowiązuje do następnej, przed pierwszą — taryfa. Brak klucza = sama taryfa.
- ceny z umowy: `{"valid_from": ISO, "energy": {strefa: cena}, "trade_fee": zł/mies.}`
- powrót do taryfy: `{"valid_from": ISO}`

Ceny są zapisane **tak, jak na fakturze — z akcyzą** („Cena jedn. netto” w sekcji
„Rozliczenie – sprzedaż energii”: 0,5829 = 0,5779 + 0,005). `build_tariff` w `__init__.py` zamienia
je na `PriceChange` (`invoice_price_to_energy`: −`AKCYZA`, round 4) i woła `with_price_changes`,
który tnie okresy tabeli na granicach zmian i w odcinkach z umową podmienia `energy` każdej strefy
oraz `monthly.trade`. Dystrybucja zostaje z tabeli. `runtime_data.tariff` to już grupa po nałożeniu
cen — `enea` (duck typing) widzi ceny z umowy bez zmian.

Rekonfiguracja **dopisuje** zmianę od daty (menu `change_prices`: bez zmian / nowe ceny od… /
powrót do taryfy od… / usuń wszystko); data nie może być wcześniejsza niż ostatnia zmiana, a ta sama
data zastępuje ostatnią zmianę (poprawka literówki). Nadpisywanie jednego zestawu cen byłoby
błędem: przepisywanie statystyk wstecz zamieniłoby historię poprzedniej oferty na taryfę.

`TariffGroup.contract_energy=True` (G12sezON, G13active): grupa nie ma ceny energii w taryfie URE,
`energy` w tabeli to 0.0. Bez żadnej zmiany z cenami setup rzuca `ConfigEntryError`;
`with_price_changes` odrzuca jej dni poza odcinkami z umową, a menu nie oferuje powrotu do taryfy.
Cen ofert nie hardkodujemy — każda oferta ma inne, zamrożone od podpisania umowy.

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

**G12sezON** – sezonowa, strefy z taryfy Enea Operator 2026 (pkt 2.2.10):
- **Zalecany pobór** (Zone.RECOMMENDED_USE): IV–IX 04–06 i 09–17; X–III 22–06 i 11–13
- **Pozostałe godziny** (Zone.REMAINING): reszta doby

**G13active** – trzy strefy, harmonogram inny w każdym miesiącu (pkt 2.2.11, tabela w `tariffs.py`).
Uwaga: październik ma pozostałe godziny 23–07, nie 23–06.

G12sezON i G13active nie rozróżniają dni roboczych — święta nie mają znaczenia.
G11pewna i G12as **celowo nieobsługiwane**: ich stawka sieciowa zależy od zużycia w okresie
(próg 250 kWh / zużycie sprzed roku), czego `enea_prices` nie zna.

Odświeżanie sensorów dynamicznych: godziny z `get_zone_change_hours()` + 0:00 (via `async_track_time_change`).
Zmiana strefy przy Sob/Nd, świętach i zmianie miesiąca obsługiwana przez refresh o 0:00.

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
Statystyki obejmują **każdy** okres w `group.periods` — od `valid_from` najstarszego (1.07.2024)
do wczoraj, więc dopisanie okresu wstecz backfilluje go przy najbliższym starcie.
Rząd wielkości jednorazowego backfillu roku: 8760 h × `len(ZONE_PRICE_ATTRS)` × liczba stref
(dla G12/G12w ≈ 35 tys. wierszy).
Wywołanie następuje automatycznie przy starcie integracji (`sensor.py:async_setup_entry`).
Przy każdym uruchomieniu zapisywane są godziny brakujące w oknie okresu albo zapisane z inną
ceną (`statistics_during_period` z `mean`, porównanie po `round(…, 4)` — rekorder trzyma
zaokrągloną wartość stanu) — dzięki temu ceny z umowy z datą wsteczną, ich zmiana lub usunięcie
poprawiają historię. Zapisywane są wyłącznie godziny sprzed najnowszej zapisanej statystyki
(`get_last_statistics`) — godziny na końcu i za nią należą do rekordera, który sam
kompiluje statystyki tych sensorów; import tej samej godziny ścigałby się z jego
ślepym INSERT-em i wycofywał całą paczkę nadrabianych statystyk.

Energy dashboard — opcja „Użyj encji z bieżącą ceną": wybierz statyczny sensor per strefa
(np. `day_price_total`, `night_price_total`). HA pobierze historyczne mean-statystyki z recordera
i policzy koszty retroaktywnie od `valid_from`.

Sensory brutto są lustrzane do netto: dynamiczny `current_price_total_brutto` (cena płacona za 1 kWh
w bieżącej strefie — dla aplikacji liczących koszt z sensora HA, np. rejestratorów ładowania) oraz
statyczne `{zone}_price_total_brutto`. Wyjątek: wstrzykiwane statystyki pozostają netto
(`ZONE_PRICE_ATTRS` nie zawiera `total_brutto`) — koszty brutto oblicza `costs.py` w integracji `enea`,
a drugi komplet ~35 tys. wierszy na grupę niczego by tam nie dodał.

## Opłaty miesięczne

Personalizowane przez config_flow (fazy instalacji, roczne zużycie, okres rozliczeniowy).
Wpływają na sensory: `monthly_network_fixed`, `monthly_subscription`, `monthly_capacity`, `monthly_transition`.

### Podpowiedzi z licznika (`meter.py`)

Integracja `enea` wylicza z danych licznika te same trzy ustawienia (`coordinator.detected_installation`:
`phases`, `billing_months`, `annual_kwh` + `annual_kwh_until` — szczegóły w `AGENTS.md` repo `enea`).
`meter_hints` czyta je przez duck typing z `entry.runtime_data.coordinator` wpisów `enea` (bez importu,
jak `enea` czyta tę integrację); grupę dopasowuje jak `enea` — `casefold` nazwy z portalu do klucza `TARIFFS`.
Starsza wersja `enea` bez `detected_installation` daje samą grupę.

- Krok `user`: grupa wstępnie wybrana, gdy liczniki zostawiają dokładnie jedną grupę bez wpisu.
- Krok szczegółów: z licznikiem w wybranej grupie formularz ma `step_id="details_from_meter"` — pola
  wypełnione tym, co licznik przesądza (`form_defaults`), opis wylicza wartości z licznika („—” = nieznane).
- Rekonfiguracja (`reconfigure_from_meter`): pola zostają przy obecnych ustawieniach, wartości z licznika
  tylko w opisie — zapis innej zmiany nie może po cichu przejąć wartości licznika. Poprawki rozbieżności
  proponuje `enea` w Naprawach.
- Osobne `step_id` są tylko po to, żeby opis mógł być inny; handlery to aliasy (`async_step_details_from_meter
  = async_step_details`).
- Dwa liczniki w jednej grupie dzielą jeden wpis (unique_id = grupa), a ich wartości mogą się różnić — wtedy
  `meter_hint` nic nie podpowiada.
- `annual_kwh` we wpisie może być zmierzonym zużyciem (np. 3170, ustawionym z Napraw `enea`), nie tylko
  wartością opcji; opłaty liczą się progami, a formularz pokazuje opcję przedziału (`annual_kwh_option`,
  te same granice co `MonthlyFees.get_capacity`).

## Dodawanie nowej taryfy

1. Zdefiniuj `TariffPeriod`(y) z odpowiednimi strefami i `MonthlyFees`
2. Owiń w `TariffGroup` i dodaj do `TARIFFS` dict w `tariffs.py`
3. config_flow automatycznie pokaże nową opcję

## Dodawanie nowego okresu do istniejącej taryfy (np. 2027)

Dopisz `TariffPeriod` do listy `periods` w odpowiednim `TariffGroup`. Sensory dynamiczne
przejdą na nowe ceny automatycznie o północy w dniu `valid_from` nowego okresu.

## Mrożenie cen 2024–2025

Cena maksymalna **0,5000 zł/kWh netto** (bez VAT i akcyzy) obowiązywała **1.07.2024–31.12.2025**,
bez limitów zużycia, wyłącznie dla energii czynnej — dystrybucja naliczana normalnie.
Ceny taryfowe Enea S.A. były wyższe, więc tabela zawiera cenę efektywną (patrz ostrzeżenie
przy modelu danych).

**Dolna granica tabeli to 1.07.2024** i nie da się jej obniżyć bez zmiany modelu: mrożenia
z 2023 i I poł. 2024 opierały się na rocznych limitach zużycia zależnych od oświadczeń odbiorcy
(niepełnosprawność, KDR, rolnik), a cena zmieniała się w momencie przekroczenia limitu.
W 2022 doszłaby jeszcze tarcza antyinflacyjna — obniżony VAT i zerowa akcyza, podczas gdy
`const.py` trzyma `VAT_RATE` i `AKCYZA` jako stałe. Szczegóły: `docs/decyzje-ure/README.md`.

Dla G12 i G12w Enea stosowała cap **dwustopniowo, w skali miesiąca**: (1) gdy średnia cena
taryfowa ważona zużyciem we wszystkich strefach < 0,500 → ceny taryfowe w każdej strefie;
(2) w przeciwnym razie każda strefa dostaje `min(cena_taryfowa, 0,500)`. Tabela koduje tylko
stopień 2, bo nie zna zużycia — jest dokładna powyżej progów udziału droższej strefy:
G12w 19,6 % / 28,4 %, G12 27,4 % / 39,0 % (odpowiednio do 30.09 i od 1.10.2025).
Poniżej progu zaniża koszt. Pełny wywód w komentarzu nad `TARIFF_G12W`.

Opłata mocowa zawieszona 1.01–30.06.2025; opłata przejściowa jeszcze obowiązywała.

## Źródła danych

**2026, G12sezON/G13active** — tylko dystrybucja: wyciąg z taryfy Enea Operator (decyzja
DRE.WRE.4211.52.11.2025.TG z 17.12.2025), strefy pkt 2.2.10–2.2.11, stawki pkt 7.5–7.6
(stawki zmienne w `tariffs.py`, opłata stała 9,59/14,56 jak G12). Taryfa sprzedaży
Enea S.A. (DRE.WRE.4211.51.8.2025.TG) obejmuje wyłącznie G11/G12/G12w/G11p/G12p.

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

**II połowa 2024, G11/G12/G12w**

- **Dystrybucja**: Wyciąg z taryfy ENEA Operator od 1.07.2024 — zmienne 0.2486 (G11),
  0.2817/0.0927 (G12), 0.2736/0.0825 (G12w); **jakościowa 0.0314**
- **Sprzedaż energii**: ta sama zmiana taryfy z 28.06.2024 co w 2025 (ceny taryfowe niezmienne
  do 30.09.2025)
- **OZE 0.0000** i **kogeneracyjna 0.00618** (6,18 zł/MWh) — inaczej niż w 2025 (0.0035 / 0.0030)
- **Opłata mocowa 0.00 zł/mies.** przez cały okres — art. 28 ustawy z 23.05.2024 o bonie
  energetycznym
- **Opłata przejściowa**: 0.02 / 0.10 / 0.33, jak w 2025

**Weryfikacja cen**: dokumenty „Dodatkowa informacja ENEA S.A. o cenach BRUTTO" podają ceny
brutto per grupa/strefa; przeliczenie na `energy` w tabeli to `brutto/1.23 - 0.005`.

## Obsługiwane taryfy

| Taryfa | Strefy | Uwagi |
|--------|--------|-------|
| G11 | 1 (całodobowa) | |
| G12 | 2 (dzień/noc) | |
| G12w | 2 (szczyt/poza szczytem) | Tygodniowy harmonogram; dni ustawowo wolne obsługiwane (pakiet `holidays`) |
| G12sezON | 2 (zalecany pobór/pozostałe) | Od 2026; harmonogram sezonowy; cena energii tylko z umowy |
| G13active | 3 (zalecany pobór/pozostałe/zalecane ograniczanie) | Od 2026; harmonogram co miesiąc; cena energii tylko z umowy |
