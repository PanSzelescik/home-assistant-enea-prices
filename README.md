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

Wszystkie wartości cenowe są **netto** (bez VAT). Ceny brutto oblicza integracja [Enea Licznik](https://github.com/PanSzelescik/home-assistant-enea) na podstawie danych z tej integracji.

### Sensory główne

| Sensor | Dzień | Noc |
|--------|:-----:|:---:|
| Aktualna strefa | `Dzień` | `Noc` *(zależnie od godziny)* |
| Aktualna cena energii (netto) | 0.5779 zł/kWh | 0.3369 zł/kWh |
| Aktualna opłata dystrybucyjna (netto) | 0.3214 zł/kWh | 0.1348 zł/kWh |
| Aktualny składnik sieciowy (netto) | 0.2779 zł/kWh | 0.0913 zł/kWh |
| Aktualna cena całkowita (netto) | 0.8993 zł/kWh | 0.4717 zł/kWh |
| Cena energii – dzień/noc (netto) | 0.5779 zł/kWh | 0.3369 zł/kWh |
| Cena całkowita – dzień/noc (netto) | 0.8993 zł/kWh | 0.4717 zł/kWh |
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
| Składnik sieciowy – dzień/noc (netto) | 0.2779 | 0.0913 |
| Stawka jakościowa | 0.0332 | *(taka sama)* |
| Opłata OZE | 0.0073 | *(taka sama)* |
| Opłata kogeneracyjna | 0.0030 | *(taka sama)* |
| Opłata przejściowa | **0.00 zł/miesiąc** *(zniesiona w 2026)* | |

## Strefy taryfowe G12

| Strefa | Godziny |
|--------|---------|
| Noc (tańsza) | 00:00–06:00 i 13:00–15:00 |
| Dzień (droższa) | 06:00–13:00 i 15:00–22:00 |

## Koszty w dashboardzie Energia

Integracja automatycznie wstrzykuje do recordera godzinowe statystyki cen (netto, zł/kWh)
dla każdego statycznego sensora per strefa, obejmując **cały aktywny okres taryfowy od `valid_from`**.
Dzięki temu koszty są dostępne retroaktywnie — nawet jeśli integracja została zainstalowana po starcie okresu.

Aby skonfigurować śledzenie kosztów w dashboardzie Energia:

1. Dodaj źródło energii (z dowolnej integracji licznika, np. [Enea Licznik](https://github.com/PanSzelescik/home-assistant-enea))
2. Przy źródle energii wybierz opcję **„Użyj encji z bieżącą ceną"** i wskaż sensor z tej integracji, np.:
   - `sensor.enea_ceny_g12_cena_calkowita_dzien_netto` dla strefy dziennej
   - `sensor.enea_ceny_g12_cena_calkowita_noc_netto` dla strefy nocnej

HA pobierze historyczne statystyki mean z recordera i policzy koszty retroaktywnie (kWh × cena/h).

> **Koszty brutto** (z VAT): integracja [Enea Licznik](https://github.com/PanSzelescik/home-assistant-enea) oferuje zaawansowane śledzenie kosztów brutto — oblicza je we współpracy z danymi z tej integracji i wstrzykuje jako oddzielne statystyki zewnętrzne.

## Powiązana integracja – Enea Licznik

Integracja [**Enea Licznik**](https://github.com/PanSzelescik/home-assistant-enea) pobiera dane o zużyciu energii z liczników zdalnego odczytu (AMI) Enea Operator i ściśle współpracuje z Enea Ceny:

- Enea Licznik automatycznie wykrywa zainstalowane Enea Ceny i oblicza **koszty brutto** (z VAT i akcyzą) dla każdej godziny, wstrzykując je jako statystyki zewnętrzne `enea:{PPE}_koszt_...`
- Koszty są gotowe do użycia w **Energy Dashboard** jako „encja śledząca całkowite koszty"
- Obie integracje są w pełni niezależne — Enea Ceny działa samodzielnie jako źródło cen

| Funkcja | Enea Ceny (ten projekt) | Enea Licznik |
|---------|------------------------|--------------|
| Aktualne ceny netto | ✅ | ❌ |
| Statystyki cen netto | ✅ (automatyczne) | ❌ |
| Odczyty zużycia kWh | ❌ | ✅ |
| Koszty brutto (PLN) | ❌ | ✅ (wymaga Enea Ceny) |
| Szacowanie rachunku | ❌ | ✅ (wymaga Enea Ceny) |

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
