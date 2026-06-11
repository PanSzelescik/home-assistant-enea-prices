# Enea Ceny – integracja Home Assistant

Integracja podająca aktualne ceny energii elektrycznej ENEA w Polsce.
Obsługuje taryfy wielostrefowe (G12 i inne) z uwzględnieniem wszystkich składników rachunku.

## Instalacja

1. Skopiuj katalog `custom_components/enea_prices` do swojego katalogu `custom_components` w Home Assistant
2. Uruchom ponownie Home Assistant
3. Przejdź do **Ustawienia → Urządzenia i usługi → Dodaj integrację** i wyszukaj „Enea Ceny"

## Konfiguracja

Integracja konfigurowana jest w dwóch krokach:

**Krok 1 – Wybór taryfy**
- Wybierz swoją grupę taryfową (np. G12)

**Krok 2 – Szczegóły instalacji** (potrzebne do opłat miesięcznych)
- Typ instalacji: 1-fazowa / 3-fazowa
- Roczne zużycie energii (przedział dla opłaty mocowej)
- Okres rozliczeniowy (dla opłaty abonamentowej)

## Sensory – przykład dla G12 (21 marca 2026)

Aktywny okres taryfowy: **1 lutego – 31 grudnia 2026**
Konfiguracja przykładowa: instalacja 3-fazowa, zużycie 1200–2800 kWh/rok, rozliczenie miesięczne

### Sensory główne

| Sensor | Strefa dzienna | Strefa nocna |
|--------|:--------------:|:------------:|
| Aktualna strefa | `Dzień` lub `Noc` | *(zależnie od godziny)* |
| Aktualna cena energii (netto) | 0.5779 zł/kWh | 0.3369 zł/kWh |
| Aktualna cena energii (brutto) | 0.7170 zł/kWh | 0.4205 zł/kWh |
| Aktualna opłata dystrybucyjna (netto) | 0.3214 zł/kWh | 0.1348 zł/kWh |
| Aktualna opłata dystrybucyjna (brutto) | 0.3953 zł/kWh | 0.1658 zł/kWh |
| Aktualny składnik sieciowy (netto) | 0.2779 zł/kWh | 0.0913 zł/kWh |
| Aktualna cena całkowita (netto) | 0.8993 zł/kWh | 0.4717 zł/kWh |
| Aktualna cena całkowita (brutto) | 1.1123 zł/kWh | 0.5863 zł/kWh |
| Cena energii – dzień (netto/brutto) | 0.5779 / 0.7170 zł/kWh | — |
| Cena energii – noc (netto/brutto) | — | 0.3369 / 0.4205 zł/kWh |
| Cena całkowita – dzień (netto/brutto) | 0.8993 / 1.1123 zł/kWh | — |
| Cena całkowita – noc (netto/brutto) | — | 0.4717 / 0.5863 zł/kWh |
| Opłata stała sieciowa | **14.56 zł/miesiąc** (3-fazowa) | |
| Opłata abonamentowa | **3.84 zł/miesiąc** (rozl. miesięczne) | |
| Opłata mocowa | **17.18 zł/miesiąc** (1200–2800 kWh/rok) | |
| Taryfa obowiązuje od | **2026-02-01** | |
| Taryfa obowiązuje do (włącznie) | **2026-12-31** | |

> Sensory „aktualne" zmieniają wartość automatycznie o: **6:00, 13:00, 15:00, 22:00** (granice stref G12) oraz **0:00** (przejście między okresami taryfowymi).

### Sensory diagnostyczne

Widoczne w zakładce **Diagnostics** urządzenia (ukryte w głównym widoku).

| Sensor | Dzień | Noc |
|--------|:-----:|:---:|
| Opłata dystrybucyjna – dzień/noc (netto) | 0.3214 | 0.1348 |
| Opłata dystrybucyjna – dzień/noc (brutto) | 0.3953 | 0.1658 |
| Składnik sieciowy – dzień/noc | 0.2779 | 0.0913 |
| Stawka jakościowa | 0.0332 | *(taka sama)* |
| Opłata OZE | 0.0073 | *(taka sama)* |
| Opłata kogeneracyjna | 0.0030 | *(taka sama)* |
| Opłata przejściowa | **0.00 zł/miesiąc** *(zniesiona w 2026)* | |

### Jak obliczane są ceny brutto?

```
Energia brutto      = (energia_netto + akcyza) × 1.23
                    = (0.5779 + 0.0050) × 1.23 = 0.7170 zł/kWh

Dystrybucja brutto  = dystrybucja_netto × 1.23
                    = 0.3214 × 1.23 = 0.3953 zł/kWh

Całkowita brutto    = (energia_netto + akcyza + dystrybucja_netto) × 1.23
                    = (0.5779 + 0.0050 + 0.3214) × 1.23 = 1.1123 zł/kWh
```

Akcyza: **0.005 zł/kWh** (podatek akcyzowy na energię elektryczną), VAT: **23%**

## Strefy taryfowe G12

| Strefa | Godziny |
|--------|---------|
| Noc (tańsza) | 00:00–06:00 i 13:00–15:00 |
| Dzień (droższa) | 06:00–13:00 i 15:00–22:00 |

## Koszty w dashboardzie Energia

Integracja jest niezależna od integracji licznika. Aby liczyć koszty w dashboardzie Energia:

1. Dodaj źródło energii (np. z integracji licznika Enea)
2. Jako sensor ceny wybierz odpowiedni sensor z tej integracji, np.:
   - `sensor.enea_ceny_g12_cena_calkowita_dzien_brutto` dla strefy dziennej
   - `sensor.enea_ceny_g12_cena_calkowita_noc_brutto` dla strefy nocnej

> **Uwaga:** HA zaczyna zapisywać statystyki cen od momentu instalacji integracji. Koszty dla dat przed instalacją nie będą dostępne.

## Obsługiwane taryfy

| Taryfa | Opis | Status |
|--------|------|--------|
| G11 | Jednostrefowa (całodobowa) | ✅ Dostępna |
| G12 | Dwustrefowa (dzień/noc) | ✅ Dostępna |
| G12w | Dwustrefowa weekendowa (szczyt/poza szczytem) | ✅ Dostępna |

## Źródła danych (rok 2026)

- Dystrybucja: Decyzja Prezesa URE z 17.12.2025 (ENEA Operator Sp. z o.o.)
- Stawka jakościowa od 1.02.2026: decyzja URE z 16.01.2026
- Sprzedaż energii: Taryfa Enea S.A. dla grup taryfowych G (od 01.01.2026)
- Opłata przejściowa: zniesiona od 01.01.2026
