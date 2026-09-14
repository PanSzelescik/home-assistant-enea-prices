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
dla każdego statycznego sensora per strefa, obejmując **wszystkie okresy taryfowe z tabeli — od 1 lipca 2024**.
Dzięki temu koszty są dostępne retroaktywnie — nawet jeśli integracja została zainstalowana później.

> Pierwszy start po aktualizacji rozszerzającej tabelę o kolejny rok wstrzykuje jednorazowo
> kilkadziesiąt tysięcy wierszy statystyk i może chwilę potrwać. Kolejne starty dopisują tylko braki.

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

## Ceny historyczne i rządowe mrożenie

Tabela sięga **1 lipca 2024**, więc dashboard Energia policzy koszty retroaktywnie od tej daty.

Od 1 lipca 2024 do 31 grudnia 2025 obowiązywała ustawowa **cena maksymalna 0,5000 zł/kWh netto**
(bez VAT i akcyzy), **bez limitów zużycia**, dotycząca wyłącznie energii czynnej — opłaty
dystrybucyjne naliczano normalnie, według taryfy Enea Operator. Ceny taryfowe Enea S.A. były
wyższe od capu, więc w kolumnie „cena energii" tabela podaje **cenę efektywną po zastosowaniu
ceny maksymalnej**, a nie cenę z cennika:

| Grupa / strefa | Taryfowa do 30.09 | Taryfowa od 1.10 | W tabeli |
|----------------|------------------:|-----------------:|---------:|
| G11 całodobowa | 0,6265 | 0,5760 | 0,5000 |
| G12 dzień | 0,7506 | 0,6815 | 0,5000 |
| G12 noc | 0,4056 | 0,3840 | bez zmian *(poniżej capu)* |
| G12w szczyt | 0,8404 | 0,7676 | 0,5000 |
| G12w poza szczytem | 0,4171 | 0,3940 | bez zmian *(poniżej capu)* |

Ceny taryfowe były te same w II połowie 2024 i do 30.09.2025 — zmieniła je dopiero decyzja
z 30.09.2025. Różnią się natomiast składniki dystrybucyjne i opłaty doliczane do rachunku:

| | II poł. 2024 | 2025 |
|---|---|---|
| Opłata mocowa | **0 zł** (zawieszona cały okres) | **0 zł** do 30.06, potem 2,86 / 6,86 / 11,44 / 16,01 zł/mies. |
| Opłata OZE | **0,0000** zł/kWh | 0,0035 zł/kWh |
| Opłata kogeneracyjna | 0,00618 zł/kWh | 0,0030 zł/kWh |
| Stawka jakościowa | 0,0314 zł/kWh | 0,0321 zł/kWh |
| Składnik zmienny G11 | 0,2486 zł/kWh | 0,2456 zł/kWh |

Opłata przejściowa (0,02 / 0,10 / 0,33 zł/mies.) obowiązywała w obu okresach — zniesiono ją
dopiero od 2026.

Wcześniej niż 1 lipca 2024 tabela nie sięga: mrożenia z 2023 i I połowy 2024 były oparte na
**rocznych limitach zużycia**, których wysokość zależała od oświadczeń odbiorcy, a cena zmieniała
się w momencie przekroczenia limitu. Model danych integracji (jedna cena na strefę w okresie)
tego nie wyrazi — szczegóły w [`docs/decyzje-ure/README.md`](docs/decyzje-ure/README.md).

> **Ograniczenie dla G12 i G12w.** Enea stosowała cenę maksymalną dwustopniowo, w skali miesiąca:
> jeżeli średnia cena taryfowa ważona zużyciem we wszystkich strefach była niższa od capu,
> obowiązywały ceny taryfowe w **każdej** strefie; w przeciwnym razie każda strefa dostawała
> niższą z dwóch cen. Tabela nie zna miesięcznego zużycia, więc koduje wyłącznie drugi przypadek.
> Jest dokładna, gdy udział droższej strefy w miesiącu wynosi co najmniej **19,6 %** (G12w)
> lub **27,4 %** (G12) do 30.09.2025 oraz **28,4 %** / **39,0 %** od 1.10.2025. Poniżej tych progów
> realnie obowiązywały ceny taryfowe, a wyliczony koszt jest **zaniżony** — dotyczy to zwłaszcza
> gospodarstw grzejących nocą, gdzie udział droższej strefy bywa niski.

## Źródła danych

Pełne teksty decyzji Prezesa URE dla taryf sprzedaży Enea S.A. znajdują się
w katalogu [`docs/decyzje-ure/`](docs/decyzje-ure/).

**Rok 2026**

- Dystrybucja: Decyzja Prezesa URE z 17.12.2025 (ENEA Operator Sp. z o.o.)
- Stawka jakościowa od 1.02.2026: decyzja URE z 16.01.2026
- Sprzedaż energii: Taryfa Enea S.A. dla grup taryfowych G (od 01.01.2026)
- Opłata przejściowa: zniesiona od 01.01.2026

**Rok 2025**

- Dystrybucja: Decyzja Prezesa URE nr DRE.WRE.4211.46.9.2024.MKa4 z 16.12.2024 (ENEA Operator)
- Sprzedaż energii: Taryfa Enea S.A. dla grup G — decyzja DRE.WRE.4211.31.11.2024.JTr z 28.06.2024,
  od 1.10.2025 decyzja DRE.WRE.4211.38.12.2025.MKa4/AKr3 z 30.09.2025
- Cena maksymalna: ustawa z 27 października 2022 r. o środkach nadzwyczajnych mających na celu
  ograniczenie wysokości cen energii elektrycznej; sposób stosowania w taryfach strefowych —
  dodatkowa informacja Enea S.A. z 1.10.2025 o cenach brutto
- Opłata mocowa: Informacja Prezesa URE nr 56/2024 (stawki obowiązywały też od 1.07.2025)

**II połowa 2024**

- Dystrybucja: Wyciąg z taryfy ENEA Operator obowiązującej od 1.07.2024
- Sprzedaż energii: ta sama zmiana taryfy Enea S.A. z 28.06.2024 (obowiązywała do 31.12.2025)
- Cena maksymalna: ustawa z 23 maja 2024 r. o bonie energetycznym — 500 zł/MWh bez względu
  na zużycie, od 1.07.2024
- Opłata mocowa: 0,00 zł/miesiąc od 1.07 do 31.12.2024 (art. 28 tej samej ustawy)
- Opłata OZE 0,00 zł/MWh i kogeneracyjna 6,18 zł/MWh — za wyciągiem z taryfy
